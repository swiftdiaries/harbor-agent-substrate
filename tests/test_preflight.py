import pytest

from scripts.check_cluster import assert_manifest_matches


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
