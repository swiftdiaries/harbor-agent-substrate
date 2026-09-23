import tomllib
from pathlib import Path

from harbor.models.task.config import TaskConfig

ROOT = Path(__file__).resolve().parents[1] / "smoke"


def test_smoke_task_is_versioned_single_step_with_declared_artifact():
    data = tomllib.loads((ROOT / "task.toml").read_text())
    task = TaskConfig.model_validate(data)
    assert task.task is not None
    assert task.verifier.environment is not None
    assert (task.task.name, task.task.version) == ("poc/actor-smoke", "1.0.0")
    assert task.steps is None
    assert task.environment.storage_mb is None
    assert task.verifier.environment_mode == "separate"
    assert (task.environment.cpus, task.environment.memory_mb) == (1, 512)
    assert (task.verifier.environment.cpus, task.verifier.environment.memory_mb) == (
        1,
        512,
    )
    assert task.artifacts == ["/logs/artifacts/answer.txt"]
    assert (ROOT / "solution/solve.sh").is_file()
    assert "/logs/artifacts/answer.txt" in (ROOT / "tests/test.sh").read_text()
