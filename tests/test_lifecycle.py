import logging
from types import SimpleNamespace
from typing import ClassVar

import pytest
from ate_env.types import EnvironmentStatus
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths
from test_config import TASK, TEMPLATES

from harbor_agent_substrate.environment import SubstrateEnvironment


class FakeActor:
    def __init__(self, client, actor_id):
        self.client = client
        self.id = actor_id
        self.status = EnvironmentStatus.RUNNING

    async def info(self):
        return SimpleNamespace(status=self.status)

    async def start_process(self, command):
        if self.client.fail_readiness:
            raise RuntimeError("guest down")
        return "pid"

    async def wait(self, pid):
        return SimpleNamespace(exit_code=0)

    async def delete(self):
        self.client.deleted.append(self.id)

    async def suspend(self):
        self.client.suspended.append(self.id)
        self.status = EnvironmentStatus.SUSPENDED


class FakeClient:
    instances: ClassVar[list] = []
    fail_readiness = False

    def __init__(self, endpoint):
        self.created = []
        self.deleted = []
        self.suspended = []
        self.closed = False
        self.instances.append(self)

    async def create(self, actor_id, *, atespace, template_name, template_atespace):
        self.created.append(SimpleNamespace(id=actor_id, template_name=template_name))
        return FakeActor(self, actor_id)

    async def close(self):
        self.closed = True


def make_environment(tmp_path, role, session_id="smoke"):
    root = tmp_path / "smoke"
    root.mkdir(exist_ok=True)
    (root / "task.toml").write_text(TASK)
    context = root / ("environment" if role == "agent" else "tests")
    context.mkdir(exist_ok=True)
    paths = TrialPaths(tmp_path / "trial")
    mounts = [
        {
            "type": "bind",
            "source": str(paths.verifier_dir.resolve()),
            "target": "/logs/verifier",
        }
    ]
    if role == "agent":
        mounts.extend(
            [
                {
                    "type": "bind",
                    "source": str(paths.agent_dir.resolve()),
                    "target": "/logs/agent",
                },
                {
                    "type": "bind",
                    "source": str((paths.artifacts_dir / "logs/artifacts").resolve()),
                    "target": "/logs/artifacts",
                },
            ]
        )
    return SubstrateEnvironment(
        endpoint="localhost:7777",
        atespace="poc",
        templates=TEMPLATES,
        environment_dir=context,
        environment_name="smoke",
        session_id=session_id,
        trial_paths=paths,
        task_env_config=EnvironmentConfig(cpus=1, memory_mb=512),
        mounts=mounts,
    )


@pytest.mark.asyncio
async def test_distinct_actor_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "harbor_agent_substrate.environment.Client", FakeClient, raising=False
    )
    agent = make_environment(tmp_path, "agent")
    verifier = make_environment(tmp_path, "verifier")
    await agent.start(False)
    await verifier.start(False)
    assert agent.actor_id != verifier.actor_id
    assert FakeClient.instances[-2].created[0].template_name == "agent"
    assert FakeClient.instances[-1].created[0].template_name == "verifier"
    await agent.stop(delete=True)
    await verifier.stop(delete=False)
    await agent.stop(delete=True)
    assert FakeClient.instances[-2].deleted == [agent.actor_id]
    assert FakeClient.instances[-1].suspended == [verifier.actor_id]


@pytest.mark.asyncio
async def test_failed_readiness_deletes_recorded_actor(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "harbor_agent_substrate.environment.Client", FakeClient, raising=False
    )
    FakeClient.fail_readiness = True
    environment = make_environment(tmp_path, "agent")
    try:
        with pytest.raises(RuntimeError, match="guest down"):
            await environment.start(False)
        assert FakeClient.instances[-1].deleted == [environment.actor_id]
        assert FakeClient.instances[-1].closed
    finally:
        FakeClient.fail_readiness = False


@pytest.mark.asyncio
async def test_stop_logs_exact_actor_cleanup(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(
        "harbor_agent_substrate.environment.Client", FakeClient, raising=False
    )
    environment = make_environment(tmp_path, "agent")
    with caplog.at_level(logging.DEBUG):
        await environment.start(False)
        await environment.stop(delete=True)
    assert f"Substrate actor {environment.actor_id} deleted role=agent" in caplog.text
