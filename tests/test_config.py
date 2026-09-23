import pytest
from harbor.models.task.config import EnvironmentConfig, NetworkPolicy, TaskConfig
from harbor.models.trial.paths import TrialPaths

from harbor_agent_substrate.config import (
    TaskKey,
    load_task,
    select_pair,
    validate_scope,
)
from harbor_agent_substrate.environment import SubstrateEnvironment

TASK = """
[task]
name = "poc/actor-smoke"
version = "1.0.0"
[environment]
cpus = 1
memory_mb = 512
[verifier]
environment_mode = "separate"
[verifier.environment]
cpus = 1
memory_mb = 512
"""

TEMPLATES = {
    "poc/actor-smoke@1.0.0": {
        "agent": {
            "name": "agent",
            "atespace": "poc",
            "image": "agent@sha256:abc",
            "cpus": 1,
            "memory_mb": 512,
        },
        "verifier": {
            "name": "verifier",
            "atespace": "poc",
            "image": "verifier@sha256:def",
            "cpus": 1,
            "memory_mb": 512,
        },
    }
}


def test_adjacent_contexts_share_identity_and_select_distinct_templates(tmp_path):
    root = tmp_path / "smoke"
    root.mkdir()
    (root / "task.toml").write_text(TASK)
    for child in ("environment", "tests"):
        (root / child).mkdir()
    key_a, _, role_a = load_task(root / "environment")
    key_v, _, role_v = load_task(root / "tests")
    assert key_a == key_v == TaskKey("poc/actor-smoke", "1.0.0")
    assert (role_a, role_v) == ("agent", "verifier")
    pair = select_pair(TEMPLATES, key_a)
    assert pair.agent.name == "agent"
    assert pair.verifier.name == "verifier"
    with pytest.raises(ValueError, match="context"):
        load_task(root / "other")


def test_missing_task_or_version_is_rejected(tmp_path):
    context = tmp_path / "environment"
    context.mkdir()
    with pytest.raises(ValueError, match="task.toml"):
        load_task(context)
    (tmp_path / "task.toml").write_text(TASK.replace('version = "1.0.0"', ""))
    with pytest.raises(ValueError, match="version"):
        load_task(context)


def test_mapping_requires_both_valid_templates():
    key = TaskKey("poc/actor-smoke", "1.0.0")
    with pytest.raises(ValueError, match="mapping"):
        select_pair({}, key)
    with pytest.raises(ValueError, match="verifier"):
        select_pair(
            {
                "poc/actor-smoke@1.0.0": {
                    "agent": TEMPLATES["poc/actor-smoke@1.0.0"]["agent"]
                }
            },
            key,
        )


@pytest.fixture
def valid_args(tmp_path):
    paths = TrialPaths(tmp_path)
    pair = select_pair(TEMPLATES, TaskKey("poc/actor-smoke", "1.0.0"))
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
            "source": str(paths.artifacts_dir.resolve() / "logs/artifacts"),
            "target": "/logs/artifacts",
        },
    ]
    return {
        "task": TaskConfig.model_validate(__import__("tomllib").loads(TASK)),
        "role": "agent",
        "effective": EnvironmentConfig(cpus=1, memory_mb=512),
        "template": pair.agent,
        "mounts": mounts,
        "trial_paths": paths,
        "network_policy": NetworkPolicy(),
        "phase_network_policies": [NetworkPolicy()],
        "stream": False,
        "force_build": False,
    }


def test_standard_mounts_and_verifier_resources_pass(valid_args):
    validate_scope(**valid_args)
    valid_args["role"] = "verifier"
    valid_args["template"] = select_pair(
        TEMPLATES, TaskKey("poc/actor-smoke", "1.0.0")
    ).verifier
    valid_args["mounts"] = [valid_args["mounts"][0]]
    validate_scope(**valid_args)


@pytest.mark.parametrize(
    "field,value", [("cpus", 2), ("memory_mb", 1024), ("storage_mb", 1)]
)
def test_request_mismatch(field, value, valid_args):
    valid_args["effective"] = valid_args["effective"].model_copy(update={field: value})
    with pytest.raises(ValueError, match=field):
        validate_scope(**valid_args)


def test_custom_mount(valid_args):
    valid_args["mounts"].append(
        {"type": "bind", "source": "/tmp/extra", "target": "/workspace"}
    )
    with pytest.raises(ValueError, match="mount"):
        validate_scope(**valid_args)


@pytest.mark.parametrize(
    "change",
    [
        {"os": "windows"},
        {"gpus": 1},
        {"tpu": {"type": "v5", "topology": "1x1"}},
    ],
)
def test_unsupported_environment_features(change, valid_args):
    valid_args["effective"] = valid_args["effective"].model_copy(update=change)
    with pytest.raises(ValueError):
        validate_scope(**valid_args)


@pytest.mark.parametrize("field", ["stream", "force_build"])
def test_unsupported_runtime_flags(field, valid_args):
    valid_args[field] = True
    with pytest.raises(ValueError):
        validate_scope(**valid_args)


@pytest.mark.asyncio
async def test_start_rejects_job_override_before_actor_creation(tmp_path, valid_args):
    root = tmp_path / "smoke"
    (root / "environment").mkdir(parents=True)
    (root / "task.toml").write_text(TASK)
    environment = SubstrateEnvironment(
        endpoint="localhost:7777",
        atespace="poc",
        templates=TEMPLATES,
        environment_dir=root / "environment",
        environment_name="smoke",
        session_id="smoke-env",
        trial_paths=valid_args["trial_paths"],
        task_env_config=EnvironmentConfig(cpus=1, memory_mb=512),
        mounts=valid_args["mounts"],
        override_cpus=2,
    )
    with pytest.raises(ValueError, match="cpus"):
        await environment.start(False)
