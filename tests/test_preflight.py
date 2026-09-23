import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.check_cluster import (
    _check_installed_templates,
    _render_template,
    assert_manifest_matches,
    load_settings,
)


def test_installed_template_may_have_server_metadata_but_not_different_limits():
    expected = {
        "metadata": {"name": "smoke"},
        "resources": {"limits": [{"name": "cpu", "quantity": "1"}]},
    }
    installed = {
        "metadata": {"name": "smoke", "uid": "generated"},
        "resources": {"limits": [{"name": "cpu", "quantity": "1"}]},
        "status": {},
    }
    assert_manifest_matches(installed, expected)
    installed["resources"]["limits"][0]["quantity"] = "2"
    with pytest.raises(ValueError, match="resources"):
        assert_manifest_matches(installed, expected)


def test_preflight_unwraps_cli_actor_templates_response(monkeypatch):
    settings = load_settings(
        Path(__file__).resolve().parents[1] / "provider.example.toml"
    )

    def fake_run(command, **kwargs):
        role = "agent" if "harbor-smoke-agent-v1" in command else "verifier"
        installed = _render_template(role, settings)
        installed["metadata"]["uid"] = "server-generated"
        return SimpleNamespace(stdout=json.dumps({"actorTemplates": [installed]}))

    monkeypatch.setattr("scripts.check_cluster.subprocess.run", fake_run)
    _check_installed_templates(settings)


@pytest.mark.parametrize(
    "role,field,value", [("agent", "cpus", 2), ("verifier", "memory_mb", 1024)]
)
def test_mapping_resource_mismatch_rejected_before_render(role, field, value):
    settings = load_settings(
        Path(__file__).resolve().parents[1] / "provider.example.toml"
    )
    settings["templates"]["poc/actor-smoke@1.0.0"][role][field] = value
    with pytest.raises(ValueError, match=field):
        _render_template(role, settings)
