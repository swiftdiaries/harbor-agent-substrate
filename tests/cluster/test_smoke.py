import asyncio
import logging
import os
import re
from pathlib import Path

import pytest
from ate_env import Client
from ate_env.types import EnvironmentStatus
from harbor.models.task.config import EnvironmentConfig as TaskEnvironmentConfig
from harbor.models.trial.paths import TrialPaths

from harbor_agent_substrate.environment import SubstrateEnvironment
from scripts.check_cluster import check_cluster, load_settings, run_smoke

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_one_harbor_trial_on_existing_cluster(tmp_path):
    endpoint = os.getenv("ATE_ENV_ENDPOINT")
    if not endpoint:
        pytest.skip("UNVERIFIED SETUP: ATE_ENV_ENDPOINT missing")
    settings = load_settings(Path(os.environ["ATE_ENV_PROVIDER_CONFIG"]))
    await check_cluster(endpoint, settings)
    result, trial_dir = await run_smoke(
        "substrate-smoke-1", endpoint, settings, tmp_path
    )
    assert result.exception_info is None
    assert result.verifier_result is not None
    assert result.verifier_result.rewards == {"reward": 1.0}
    assert (
        trial_dir / "artifacts/logs/artifacts/answer.txt"
    ).read_text() == "substrate-ok\n"
    assert (trial_dir / "agent").exists()
    assert (trial_dir / "verifier/reward.txt").is_file()


@pytest.mark.asyncio
async def test_two_trials_have_four_distinct_deleted_actors(tmp_path, caplog):
    endpoint = os.getenv("ATE_ENV_ENDPOINT")
    if not endpoint:
        pytest.skip("UNVERIFIED SETUP: ATE_ENV_ENDPOINT missing")
    settings = load_settings(Path(os.environ["ATE_ENV_PROVIDER_CONFIG"]))
    with caplog.at_level(logging.DEBUG):
        async with asyncio.TaskGroup() as group:
            first = group.create_task(
                run_smoke("substrate-smoke-a", endpoint, settings, tmp_path)
            )
            second = group.create_task(
                run_smoke("substrate-smoke-b", endpoint, settings, tmp_path)
            )
    for result, trial_dir in (first.result(), second.result()):
        assert result.exception_info is None
        assert result.verifier_result is not None
        assert result.verifier_result.rewards == {"reward": 1.0}
        assert (
            trial_dir / "artifacts/logs/artifacts/answer.txt"
        ).read_text() == "substrate-ok\n"
        assert (trial_dir / "agent").exists()
        assert (trial_dir / "verifier/reward.txt").is_file()
        assert (trial_dir / "trial.log").is_file()
    created = re.findall(
        r"Substrate actor ([a-z0-9-]+) role=(agent|verifier)", caplog.text
    )
    deleted = re.findall(
        r"Substrate actor ([a-z0-9-]+) deleted role=(agent|verifier)", caplog.text
    )
    assert len(created) == len(set(created)) == 4
    assert set(deleted) == set(created)


@pytest.mark.asyncio
async def test_retained_actor_is_suspended(tmp_path):
    endpoint = os.getenv("ATE_ENV_ENDPOINT")
    if not endpoint:
        pytest.skip("UNVERIFIED SETUP: ATE_ENV_ENDPOINT missing")
    settings = load_settings(Path(os.environ["ATE_ENV_PROVIDER_CONFIG"]))
    paths = TrialPaths(tmp_path / "retained")
    mounts = [
        {
            "type": "bind",
            "source": str(paths.verifier_dir.resolve()),
            "target": "/logs/verifier",
        },
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
    environment = SubstrateEnvironment(
        endpoint=endpoint,
        atespace=settings["atespace"],
        templates=settings["templates"],
        environment_dir=Path(__file__).resolve().parents[2] / "smoke/environment",
        environment_name="smoke",
        session_id="retained-smoke",
        trial_paths=paths,
        task_env_config=TaskEnvironmentConfig(cpus=1, memory_mb=512),
        mounts=mounts,
    )
    await environment.start(False)
    actor_id = environment.actor_id
    assert actor_id is not None
    try:
        await environment.stop(False)
        client = Client(endpoint)
        try:
            assert (
                await client.get(actor_id, atespace=settings["atespace"])
            ).status == EnvironmentStatus.SUSPENDED
        finally:
            await client.close()
    finally:
        client = Client(endpoint)
        try:
            await client.delete(actor_id, atespace=settings["atespace"])
        finally:
            await client.close()
