import asyncio
import io
import os
import stat
import subprocess
import tarfile
from pathlib import Path
from typing import Any, cast

import pytest
from harbor.environments.base import ExecResult

from harbor_agent_substrate.environment import SubstrateEnvironment


class LocalActor:
    async def write_file(self, path, chunks, *, mode):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"".join(chunks))
        target.chmod(mode)

    async def read_file(self, path):
        with Path(path).open("rb") as stream:  # noqa: ASYNC230 - local fake
            while chunk := stream.read(65536):
                yield chunk


def environment():
    instance = object.__new__(SubstrateEnvironment)
    cast(Any, instance).actor = LocalActor()

    async def shell(command, **kwargs):
        result = await asyncio.to_thread(
            subprocess.run,
            command,
            shell=True,
            text=True,
            capture_output=True,
            check=False,
        )
        return ExecResult(
            stdout=result.stdout, stderr=result.stderr, return_code=result.returncode
        )

    cast(Any, instance).exec = shell
    return instance


@pytest.mark.asyncio
async def test_binary_file_and_mode_round_trip(tmp_path):
    source = tmp_path / "source.sh"
    source.write_bytes(b"\x00\xff\n")
    source.chmod(0o755)
    remote = tmp_path / "remote.sh"
    target = tmp_path / "download.sh"
    instance = environment()
    await instance.upload_file(source, str(remote))
    await instance.download_file(str(remote), target)
    assert target.read_bytes() == b"\x00\xff\n"
    assert stat.S_IMODE(remote.stat().st_mode) == 0o755


@pytest.mark.asyncio
async def test_nested_and_empty_directory_round_trip(tmp_path):
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "empty").mkdir()
    (source / "nested/test.sh").write_text("#!/bin/sh\nexit 0\n")
    (source / "nested/test.sh").chmod(0o755)
    remote = tmp_path / "remote"
    target = tmp_path / "target"
    instance = environment()
    await instance.upload_dir(source, str(remote))
    await instance.download_dir(str(remote), target)
    assert (target / "empty").is_dir()
    assert (target / "nested/test.sh").read_text() == "#!/bin/sh\nexit 0\n"
    assert os.access(target / "nested/test.sh", os.X_OK)


@pytest.mark.parametrize("name,linkname", [("../escape", None), ("safe", "../escape")])
@pytest.mark.asyncio
async def test_unsafe_archive_never_extracts(name, linkname, tmp_path):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        info = tarfile.TarInfo(name)
        if linkname is None:
            data = b"bad"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        else:
            info.type = tarfile.SYMTYPE
            info.linkname = linkname
            tar.addfile(info)
    remote = tmp_path / "unsafe.tar.gz"
    remote.write_bytes(archive.getvalue())
    instance = environment()

    async def shell(command, **kwargs):
        if command.startswith("tar -czf"):
            import shlex

            Path(shlex.split(command)[2]).write_bytes(archive.getvalue())
            return ExecResult(return_code=0)
        result = await asyncio.to_thread(
            subprocess.run,
            command,
            shell=True,
            text=True,
            capture_output=True,
            check=False,
        )
        return ExecResult(
            stdout=result.stdout, stderr=result.stderr, return_code=result.returncode
        )

    cast(Any, instance).exec = shell
    target = tmp_path / "target"
    with pytest.raises(ValueError):
        await instance.download_dir(str(remote), target)
    assert not (tmp_path / "escape").exists()


@pytest.mark.asyncio
async def test_remote_extraction_failure_removes_archive(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    instance = environment()
    commands = []

    async def shell(command, **kwargs):
        commands.append(command)
        if "tar -xzf" in command:
            return ExecResult(stderr="unpack failed", return_code=2)
        return ExecResult(return_code=0)

    cast(Any, instance).exec = shell
    with pytest.raises(RuntimeError, match="unpack failed"):
        await instance.upload_dir(source, str(tmp_path / "remote"))
    assert any(command.startswith("rm -f /tmp/hb-transfer-") for command in commands)
