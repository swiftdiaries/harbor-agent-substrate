import tomllib
from dataclasses import dataclass
from pathlib import Path

from harbor.models.task.config import TaskConfig


@dataclass(frozen=True)
class TaskKey:
    name: str
    version: str


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    atespace: str
    image: str
    cpus: int
    memory_mb: int


@dataclass(frozen=True)
class TemplatePair:
    agent: TemplateSpec
    verifier: TemplateSpec


def load_task(context: Path) -> tuple[TaskKey, TaskConfig, str]:
    role = {"environment": "agent", "tests": "verifier"}.get(context.name)
    if role is None:
        raise ValueError(f"unsupported context: {context}")
    task_file = context.parent / "task.toml"
    if not task_file.is_file():
        raise ValueError(f"missing task.toml: {task_file}")
    data = tomllib.loads(task_file.read_text())
    identity = data.get("task") or {}
    if not identity.get("name") or not identity.get("version"):
        raise ValueError("task name and version are required")
    task = TaskConfig.model_validate(data)
    if task.steps is not None:
        raise ValueError("steps are unsupported")
    return TaskKey(identity["name"], identity["version"]), task, role


def select_pair(mapping: dict, key: TaskKey) -> TemplatePair:
    entry = mapping.get(f"{key.name}@{key.version}")
    if not isinstance(entry, dict):
        raise ValueError(f"missing template mapping for {key.name}@{key.version}")
    specs = {}
    for role in ("agent", "verifier"):
        if not isinstance(entry.get(role), dict):
            raise ValueError(f"missing {role} template")
        try:
            spec = TemplateSpec(**entry[role])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {role} template") from exc
        if not spec.name or not spec.atespace or "@sha256:" not in spec.image:
            raise ValueError(f"invalid {role} template identity or image")
        if spec.cpus <= 0 or spec.memory_mb <= 0:
            raise ValueError(f"invalid {role} template resources")
        specs[role] = spec
    return TemplatePair(**specs)
