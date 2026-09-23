import tomllib
from dataclasses import dataclass
from pathlib import Path

from harbor.models.task.config import (
    EnvironmentConfig,
    NetworkMode,
    NetworkPolicy,
    TaskConfig,
    TaskOS,
)
from harbor.models.trial.config import ServiceVolumeConfig
from harbor.models.trial.paths import TrialPaths


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
    if entry is None:
        raise ValueError(f"missing template mapping for {key.name}@{key.version}")
    if not isinstance(entry, dict):
        raise TypeError("template mapping must be a dict")
    specs = {}
    for role in ("agent", "verifier"):
        if role not in entry:
            raise ValueError(f"missing {role} template")
        if not isinstance(entry[role], dict):
            raise TypeError(f"{role} template must be a dict")
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


def validate_scope(
    task: TaskConfig,
    role: str,
    effective: EnvironmentConfig,
    template: TemplateSpec,
    mounts: list[ServiceVolumeConfig],
    network_policy: NetworkPolicy,
    phase_network_policies: list[NetworkPolicy],
    *,
    trial_paths: TrialPaths,
    stream: bool,
    force_build: bool,
) -> None:
    for field, limit in (("cpus", template.cpus), ("memory_mb", template.memory_mb)):
        if getattr(effective, field) != limit:
            raise ValueError(f"{field} does not match template limit {limit}")
    if effective.storage_mb is not None:
        raise ValueError("storage_mb is unsupported")
    if effective.gpus is not None or effective.tpu is not None or effective.gpu_types:
        raise ValueError("accelerators are unsupported")
    if effective.os != TaskOS.LINUX:
        raise ValueError("Windows is unsupported")
    if stream or force_build:
        raise ValueError("stream/force_build are unsupported")
    if task.agent.user not in (None, "root", 0, "0") or task.verifier.user not in (
        None,
        "root",
        0,
        "0",
    ):
        raise ValueError("custom user is unsupported")
    if network_policy.network_mode != NetworkMode.PUBLIC or any(
        policy != network_policy for policy in phase_network_policies
    ):
        raise ValueError("network policy is unsupported")
    allowed = {
        "/logs/verifier": trial_paths.verifier_dir.resolve(),
    }
    if role == "agent":
        allowed.update(
            {
                "/logs/agent": trial_paths.agent_dir.resolve(),
                "/logs/artifacts": (
                    trial_paths.artifacts_dir / "logs/artifacts"
                ).resolve(),
                "/logs/user-agent": trial_paths.user_agent_dir.resolve(),
            }
        )
    seen = set()
    for mount in mounts:
        target = mount.get("target")
        if (
            target in seen
            or mount.get("type") != "bind"
            or target not in allowed
            or mount.get("source") != str(allowed[target])
        ):
            raise ValueError(f"unsupported mount: {mount}")
        seen.add(target)
    required = (
        {"/logs/verifier"}
        if role == "verifier"
        else {"/logs/verifier", "/logs/agent", "/logs/artifacts"}
    )
    if not required <= seen:
        raise ValueError("missing standard mount")
