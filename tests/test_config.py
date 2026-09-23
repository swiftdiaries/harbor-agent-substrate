import pytest

from harbor_agent_substrate.config import TaskKey, load_task, select_pair


TASK = '''
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
'''

TEMPLATES = {
    "poc/actor-smoke@1.0.0": {
        "agent": {"name": "agent", "atespace": "poc", "image": "agent@sha256:abc", "cpus": 1, "memory_mb": 512},
        "verifier": {"name": "verifier", "atespace": "poc", "image": "verifier@sha256:def", "cpus": 1, "memory_mb": 512},
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
        select_pair({"poc/actor-smoke@1.0.0": {"agent": TEMPLATES["poc/actor-smoke@1.0.0"]["agent"]}}, key)
