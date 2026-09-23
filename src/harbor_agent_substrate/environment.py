from harbor.environments.base import BaseEnvironment
from harbor.environments.capabilities import (
    EnvironmentCapabilities,
    EnvironmentResourceCapabilities,
)

from harbor_agent_substrate.config import load_task, select_pair, validate_scope


class SubstrateEnvironment(BaseEnvironment):
    def __init__(
        self, *, endpoint: str, atespace: str, templates: dict, **harbor_kwargs
    ):
        self.endpoint = endpoint
        self.atespace = atespace
        self.templates = templates
        super().__init__(**harbor_kwargs)

    @staticmethod
    def type() -> str:
        return "agent-substrate"

    @property
    def capabilities(self) -> EnvironmentCapabilities:
        return EnvironmentCapabilities(mounted=False)

    @classmethod
    def resource_capabilities(cls) -> EnvironmentResourceCapabilities:
        return EnvironmentResourceCapabilities(cpu_limit=True, memory_limit=True)

    def _validate_definition(self):
        self.task_key, self.task, self.role = load_task(self.environment_dir)
        self.template_pair = select_pair(self.templates, self.task_key)

    async def start(self, force_build: bool):
        template = getattr(self.template_pair, self.role)
        validate_scope(
            self.task,
            self.role,
            self.task_env_config,
            template,
            self._mounts,
            self.network_policy,
            self._phase_network_policies,
            trial_paths=self.trial_paths,
            stream=self._stream,
            force_build=force_build,
        )
        if any(
            (self.environment_dir / name).exists()
            for name in (
                "docker-compose.yml",
                "docker-compose.yaml",
                "compose.yml",
                "compose.yaml",
            )
        ):
            raise ValueError("Compose and sidecars are unsupported")
        raise NotImplementedError

    async def stop(self, delete: bool):
        raise NotImplementedError

    async def upload_file(self, source_path, target_path):
        raise NotImplementedError

    async def upload_dir(self, source_dir, target_dir):
        raise NotImplementedError

    async def download_file(self, source_path, target_path):
        raise NotImplementedError

    async def download_dir(self, source_dir, target_dir):
        raise NotImplementedError

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        raise NotImplementedError
