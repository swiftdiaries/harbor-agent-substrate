import asyncio
from types import SimpleNamespace

import pytest
from ate_env.types import OutputSource
from harbor.models.task.config import EnvironmentConfig

from harbor_agent_substrate.environment import SubstrateEnvironment


class FakeActor:
    def __init__(self, *, wait_forever=False):
        self.cwd = None
        self.env = None
        self.started = 0
        self.killed = []
        self.wait_forever = wait_forever

    async def start_process(self, command, *, cwd, env):
        self.started += 1
        self.cwd = cwd
        self.env = env
        return "pid-1"

    async def stream_outputs(self, pid, *, follow):
        yield SimpleNamespace(source=OutputSource.STDOUT, data=b"ok\n")
        yield SimpleNamespace(source=OutputSource.STDERR, data=b"warning\n")
        if self.wait_forever:
            await asyncio.sleep(3600)

    async def wait(self, pid):
        return SimpleNamespace(exit_code=7)

    async def kill_process(self, pid):
        self.killed.append(pid)


def environment(actor):
    instance = object.__new__(SubstrateEnvironment)
    instance.actor = actor
    instance.default_user = None
    instance._persistent_env = {}
    instance.task_env_config = EnvironmentConfig()
    return instance


@pytest.mark.asyncio
async def test_exec_preserves_output_exit_code_cwd_and_env():
    actor = FakeActor()
    result = await environment(actor).exec(
        "exit 7", cwd="/tmp", env={"X": "1"}, user="root"
    )
    assert (result.stdout, result.stderr, result.return_code) == (
        "ok\n",
        "warning\n",
        7,
    )
    assert actor.cwd == "/tmp"
    assert actor.env is not None and actor.env["X"] == "1"


@pytest.mark.asyncio
async def test_nonroot_user_fails_before_start():
    actor = FakeActor()
    instance = environment(actor)
    with pytest.raises(ValueError, match="user"):
        await instance.exec("true", user="nobody")
    instance.default_user = "nobody"
    with pytest.raises(ValueError, match="user"):
        await instance.exec("true")
    assert actor.started == 0


@pytest.mark.asyncio
async def test_timeout_kills_started_process():
    actor = FakeActor(wait_forever=True)
    with pytest.raises(TimeoutError):
        await environment(actor).exec("sleep 10", timeout_sec=0.01)
    assert actor.killed == ["pid-1"]


@pytest.mark.asyncio
async def test_cancellation_waits_for_kill():
    actor = FakeActor(wait_forever=True)
    task = asyncio.create_task(environment(actor).exec("sleep 10"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert actor.killed == ["pid-1"]
