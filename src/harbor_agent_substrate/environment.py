import asyncio
import re
from uuid import uuid4

from ate_env import Client
from ate_env.types import EnvironmentStatus
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
        self.actor = None
        self.client = None
        self.actor_id = None
        self._stopped = False
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
        safe_session = re.sub(r"[^a-z0-9-]", "-", self.session_id.lower()).strip("-")[
            :40
        ]
        self.actor_id = f"{safe_session or 'harbor'}-{uuid4().hex}"
        self.client = Client(self.endpoint)
        self.logger.debug("Substrate actor %s role=%s", self.actor_id, self.role)
        try:
            self.actor = await self.client.create(
                self.actor_id,
                atespace=self.atespace,
                template_name=template.name,
                template_atespace=template.atespace,
            )
            async with asyncio.timeout(120):
                while (await self.actor.info()).status != EnvironmentStatus.RUNNING:
                    await asyncio.sleep(0.2)
                pid = await self.actor.start_process(["sh", "-c", "true"])
                if (await self.actor.wait(pid)).exit_code != 0:
                    raise RuntimeError("guest readiness failed")
        except BaseException:
            try:
                if self.actor is not None:
                    await self.actor.delete()
                else:
                    await self.client.delete(self.actor_id, atespace=self.atespace)
            finally:
                await self.client.close()
                self._stopped = True
            raise

    async def stop(self, delete: bool):
        if self._stopped or self.actor is None:
            return
        self._stopped = True
        try:
            if delete:
                await self.actor.delete()
            else:
                await self.actor.suspend()
                async with asyncio.timeout(120):
                    while (
                        await self.actor.info()
                    ).status != EnvironmentStatus.SUSPENDED:
                        await asyncio.sleep(0.2)
        finally:
            if self.client is not None:
                await self.client.close()

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
