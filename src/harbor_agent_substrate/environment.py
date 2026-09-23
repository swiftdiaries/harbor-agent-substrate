import asyncio
import logging
import posixpath
import re
import shlex
import stat
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

from ate_env import Client
from ate_env.types import EnvironmentStatus, OutputSource
from harbor.environments.base import BaseEnvironment, ExecResult
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
                await self.stop(True)
            except BaseException as cleanup_error:  # noqa: BLE001 - preserve original failure
                self.logger.debug(
                    "Substrate actor %s startup cleanup failed: %s",
                    self.actor_id,
                    cleanup_error,
                )
            raise

    async def stop(self, delete: bool):
        if self._stopped or self.actor_id is None:
            return
        client = self.client or Client(self.endpoint)
        actor = self.actor or client.env(self.actor_id, atespace=self.atespace)
        try:
            if delete:
                await actor.delete()
                self.logger.debug(
                    "Substrate actor %s deleted role=%s", self.actor_id, self.role
                )
            else:
                await actor.suspend()
                async with asyncio.timeout(120):
                    while (await actor.info()).status != EnvironmentStatus.SUSPENDED:
                        await asyncio.sleep(0.2)
                self.logger.debug(
                    "Substrate actor %s suspended role=%s", self.actor_id, self.role
                )
            self._stopped = True
        finally:
            await client.close()
            self.client = None
            self.actor = None

    async def upload_file(self, source_path, target_path):
        if self.actor is None:
            raise RuntimeError("actor has not started")
        source = Path(source_path)

        def chunks():
            with source.open("rb") as stream:
                while chunk := stream.read(65536):
                    yield chunk

        await self.actor.write_file(
            str(target_path), chunks(), mode=stat.S_IMODE(source.stat().st_mode)
        )

    async def upload_dir(self, source_dir, target_dir):
        remote_archive = f"/tmp/hb-transfer-{uuid4().hex}.tar.gz"
        with tempfile.TemporaryDirectory() as temporary:
            local_archive = Path(temporary) / "upload.tar.gz"
            with tarfile.open(local_archive, "w:gz") as archive:
                archive.add(source_dir, arcname=".")
            try:
                await self.upload_file(local_archive, remote_archive)
                result = await self.exec(
                    f"mkdir -p {shlex.quote(str(target_dir))} && "
                    f"tar -xzf {shlex.quote(remote_archive)} -C {shlex.quote(str(target_dir))}"
                )
                if result.return_code != 0:
                    raise RuntimeError(result.stderr or "remote extraction failed")
            finally:
                await self._remove_remote_archive(remote_archive)

    async def download_file(self, source_path, target_path):
        if self.actor is None:
            raise RuntimeError("actor has not started")
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as stream:  # noqa: ASYNC230 - stream remote chunks to disk
            async for chunk in self.actor.read_file(str(source_path)):
                stream.write(chunk)

    async def download_dir(self, source_dir, target_dir):
        remote_archive = f"/tmp/hb-transfer-{uuid4().hex}.tar.gz"
        with tempfile.TemporaryDirectory() as temporary:
            local_archive = Path(temporary) / "download.tar.gz"
            try:
                result = await self.exec(
                    f"tar -czf {shlex.quote(remote_archive)} -C {shlex.quote(str(source_dir))} ."
                )
                if result.return_code != 0:
                    raise RuntimeError(result.stderr or "remote archive failed")
                await self.download_file(remote_archive, local_archive)
                with tarfile.open(local_archive, "r:gz") as archive:
                    for member in archive.getmembers():
                        name = PurePosixPath(member.name)
                        if (
                            name.is_absolute()
                            or ".." in name.parts
                            or member.isdev()
                            or member.isfifo()
                        ):
                            raise ValueError(f"unsafe archive member: {member.name}")
                        if member.issym() or member.islnk():
                            link = member.linkname
                            resolved = posixpath.normpath(
                                posixpath.join(posixpath.dirname(member.name), link)
                            )
                            if (
                                link.startswith("/")
                                or resolved == ".."
                                or resolved.startswith("../")
                            ):
                                raise ValueError(f"unsafe archive link: {member.name}")
                    archive.extractall(target_dir, filter="data")
            finally:
                await self._remove_remote_archive(remote_archive)

    async def _remove_remote_archive(self, path: str) -> None:
        original_error = sys.exc_info()[0] is not None
        try:
            result = await self.exec(f"rm -f {shlex.quote(path)}")
            if result.return_code != 0:
                raise RuntimeError(result.stderr or "remote archive cleanup failed")
        except Exception:
            if not original_error:
                raise

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        effective_user = self.default_user if user is None else user
        if effective_user not in (None, "root", 0, "0"):
            raise ValueError("only root user is supported")
        if self.actor is None:
            raise RuntimeError("actor has not started")
        pid = None
        launch = None
        completed = False
        stdout = bytearray()
        stderr = bytearray()
        try:
            async with asyncio.timeout(timeout_sec):
                launch = asyncio.create_task(
                    self.actor.start_process(
                        ["sh", "-c", command],
                        cwd=cwd or "",
                        env={**self._startup_env(), **(env or {})},
                    )
                )
                pid = await asyncio.shield(launch)
                async for chunk in self.actor.stream_outputs(pid, follow=True):
                    if chunk.source == OutputSource.STDOUT:
                        stdout.extend(chunk.data)
                    elif chunk.source == OutputSource.STDERR:
                        stderr.extend(chunk.data)
                result = await self.actor.wait(pid)
                completed = True
                return ExecResult(
                    stdout=stdout.decode(errors="replace"),
                    stderr=stderr.decode(errors="replace"),
                    return_code=result.exit_code,
                )
        finally:
            if pid is None and launch is not None:
                try:
                    pid = await asyncio.wait_for(asyncio.shield(launch), 30)
                except TimeoutError:
                    await self.actor.delete()
                    launch.cancel()
                    raise RuntimeError(
                        "guest launch outcome unknown; actor deleted"
                    ) from None
                except Exception as launch_error:  # noqa: BLE001 - original failure is active
                    logging.getLogger(__name__).debug(
                        "Guest launch failed: %s", launch_error
                    )
            if pid is not None and not completed:
                cleanup = asyncio.create_task(self.actor.kill_process(pid))
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    await cleanup
