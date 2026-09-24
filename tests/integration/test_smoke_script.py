"""scripts/smoke_test.py is what confirms the Docker image (and, in step 4b,
the AgentCore deployment) behaves like the dev server -- so it has to stay
correct against the dev server itself. Runs every check, latency included,
against the same real in-process server the rest of the integration suite
uses."""

import importlib.util
from pathlib import Path

SMOKE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke_test.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("fixit_smoke_test", SMOKE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_every_smoke_check_passes_against_the_dev_server(server_url: str) -> None:
    smoke = _load_smoke_module()

    results = await smoke.run_smoke_checks(server_url)

    assert len(results) == len(smoke.CHECKS)


async def test_skip_latency_drops_only_the_latency_check(server_url: str) -> None:
    smoke = _load_smoke_module()

    checks = smoke.selected_checks(skip_latency=True)

    assert smoke.check_latency not in checks
    assert len(checks) == len(smoke.CHECKS) - 1
