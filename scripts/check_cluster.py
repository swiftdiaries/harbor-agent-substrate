"""Operator preflight for an existing private Agent Substrate cluster."""

import argparse
import asyncio
import json
import os
import subprocess
import tomllib
from pathlib import Path
from uuid import uuid4

import yaml
from ate_env import Client
from ate_env.types import EnvironmentStatus
from harbor.models.trial.config import (
    AgentConfig,
    EnvironmentConfig,
    TaskConfig,
    TrialConfig,
)
from harbor.trial.trial import Trial

from harbor_agent_substrate.config import TaskKey, select_pair

ROOT = Path(__file__).resolve().parents[1]
TASK_KEY = TaskKey("poc/actor-smoke", "1.0.0")


def load_settings(path: Path) -> dict:
    data = tomllib.loads(path.read_text())
    if not data.get("atespace") or not data.get("snapshots_bucket"):
        raise ValueError("atespace and snapshots_bucket are required")
    if not data.get("worker_label_key") or not data.get("worker_label_value"):
        raise ValueError("worker label key/value are required")
    select_pair(data.get("templates", {}), TASK_KEY)
    return data


def _render_template(role: str, settings: dict) -> dict:
    template = (ROOT / "templates" / f"{role}.yaml.tmpl").read_text()
    pair = select_pair(settings["templates"], TASK_KEY)
    spec = getattr(pair, role)
    replacements = {
        "ATESPACE": settings["atespace"],
        "WORKER_LABEL_KEY": settings["worker_label_key"],
        "WORKER_LABEL_VALUE": settings["worker_label_value"],
        "SNAPSHOTS_BUCKET": settings["snapshots_bucket"],
        f"{role.upper()}_IMAGE_DIGEST": spec.image,
    }
    for key, value in replacements.items():
        template = template.replace("{{" + key + "}}", value)
    return yaml.safe_load(template)


def render_templates(settings: dict, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for role in ("agent", "verifier"):
        (directory / f"{role}.yaml").write_text(
            yaml.safe_dump(_render_template(role, settings), sort_keys=False)
        )


def assert_manifest_matches(installed, expected, path: str = "template") -> None:
    if isinstance(expected, dict):
        if not isinstance(installed, dict):
            raise TypeError(f"{path} differs from rendered manifest")
        for key, value in expected.items():
            if key not in installed:
                raise ValueError(f"{path}.{key} missing from installed template")
            assert_manifest_matches(installed[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        if not isinstance(installed, list) or len(installed) != len(expected):
            raise ValueError(f"{path} differs from rendered manifest")
        if all(isinstance(item, dict) and "name" in item for item in expected):
            actual_by_name = {item["name"]: item for item in installed}
            for item in expected:
                if item["name"] not in actual_by_name:
                    raise ValueError(
                        f"{path}.{item['name']} missing from installed template"
                    )
                assert_manifest_matches(
                    actual_by_name[item["name"]], item, f"{path}.{item['name']}"
                )
        else:
            for index, item in enumerate(expected):
                assert_manifest_matches(installed[index], item, f"{path}[{index}]")
    elif installed != expected:
        raise ValueError(f"{path} differs from rendered manifest")


def _check_installed_templates(settings: dict) -> None:
    pair = select_pair(settings["templates"], TASK_KEY)
    for role in ("agent", "verifier"):
        spec = getattr(pair, role)
        expected = _render_template(role, settings)
        output = subprocess.run(
            [
                "kubectl",
                "ate",
                "get",
                "actor-template",
                spec.name,
                "-a",
                spec.atespace,
                "-o",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        installed = json.loads(output)
        assert_manifest_matches(installed, expected, f"installed {role} template")


async def _probe_guest(endpoint: str, settings: dict) -> None:
    pair = select_pair(settings["templates"], TASK_KEY)
    actor_id = f"harbor-preflight-{uuid4().hex}"
    client = Client(endpoint)
    actor = None
    try:
        actor = await client.create(
            actor_id,
            atespace=settings["atespace"],
            template_name=pair.agent.name,
            template_atespace=pair.agent.atespace,
        )
        async with asyncio.timeout(120):
            while (await actor.info()).status != EnvironmentStatus.RUNNING:
                await asyncio.sleep(0.2)
            result = await actor.shell("printf ready")
            if result.stdout != "ready" or result.exit_code != 0:
                raise RuntimeError("guest process routing failed")
            await actor.write_file("/tmp/harbor-preflight.bin", b"\x00\xff")
            if await actor.read_file_bytes("/tmp/harbor-preflight.bin") != b"\x00\xff":
                raise RuntimeError("guest file routing failed")
    finally:
        try:
            if actor is not None:
                await actor.delete()
        finally:
            await client.close()


async def check_cluster(endpoint: str, settings: dict) -> None:
    if not endpoint.startswith(("localhost:", "127.0.0.1:", "[::1]:")):
        raise ValueError("ATE_ENV_ENDPOINT must be a private local port forward")
    _check_installed_templates(settings)
    await _probe_guest(endpoint, settings)


async def run_smoke(name: str, endpoint: str, settings: dict, trials_dir: Path):
    config = TrialConfig(
        task=TaskConfig(path=ROOT / "smoke"),
        trial_name=name,
        trials_dir=trials_dir,
        agent=AgentConfig(name="oracle"),
        environment=EnvironmentConfig(
            import_path="harbor_agent_substrate.environment:SubstrateEnvironment",
            kwargs={
                "endpoint": endpoint,
                "atespace": settings["atespace"],
                "templates": settings["templates"],
            },
        ),
    )
    trial = await Trial.create(config)
    return await trial.run(), trial.paths.trial_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--render-dir", type=Path)
    args = parser.parse_args()
    settings = load_settings(args.config)
    if args.render_dir is not None:
        render_templates(settings, args.render_dir)
        return
    endpoint = os.getenv("ATE_ENV_ENDPOINT")
    if not endpoint:
        parser.error("UNVERIFIED SETUP: ATE_ENV_ENDPOINT missing")
    asyncio.run(check_cluster(endpoint, settings))


if __name__ == "__main__":
    main()
