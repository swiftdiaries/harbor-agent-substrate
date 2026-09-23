import os
from pathlib import Path

import pytest

from scripts.check_cluster import check_cluster, load_settings, run_smoke

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_one_harbor_trial_on_existing_cluster(tmp_path):
    endpoint = os.getenv("ATE_ENV_ENDPOINT")
    if not endpoint:
        pytest.skip("UNVERIFIED SETUP: ATE_ENV_ENDPOINT missing")
    settings = load_settings(Path(os.environ["ATE_ENV_PROVIDER_CONFIG"]))
    await check_cluster(endpoint, settings)
    result, trial_dir = await run_smoke(
        "substrate-smoke-1", endpoint, settings, tmp_path
    )
    assert result.exception_info is None
    assert result.verifier_result is not None
    assert result.verifier_result.rewards == {"reward": 1.0}
    assert (
        trial_dir / "artifacts/logs/artifacts/answer.txt"
    ).read_text() == "substrate-ok\n"
    assert (trial_dir / "agent").exists()
    assert (trial_dir / "verifier/reward.txt").is_file()
