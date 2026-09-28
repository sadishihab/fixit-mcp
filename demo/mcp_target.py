"""Builds the demo's MCPTarget: the local dev FixIt server, or a deployed
AgentCore Runtime.

Reuses scripts/smoke_test.py's SigV4Auth and runtime_invocation_url rather
than duplicating AWS SigV4 signing. scripts/ has no __init__.py (see
tests/unit/test_deploy_scripts.py), so it isn't a normal importable
package; this loads it by file path the same way that test suite already
does.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from demo.mcp_session import MCPTarget

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
_DEFAULT_LOCAL_URL = "http://localhost:8000/mcp"


def _load_smoke_test() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fixit_demo_smoke_test", _SCRIPTS_DIR / "smoke_test.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def build_target(url: str | None, agent_arn: str | None) -> MCPTarget:
    """--agent-arn (deployed, SigV4-signed) takes precedence over --url
    (local dev server, unauthenticated) -- the same precedence
    scripts/smoke_test.py's own CLI uses."""
    if agent_arn:
        smoke = _load_smoke_test()
        region = agent_arn.split(":")[3]
        return MCPTarget(url=smoke.runtime_invocation_url(agent_arn), auth=smoke.SigV4Auth(region))
    return MCPTarget(url=url or _DEFAULT_LOCAL_URL, auth=None)
