"""scripts/smoke_test.py is what confirms the Docker image (and, in step 4b,
the AgentCore deployment) behaves like the dev server -- so it has to stay
correct against the dev server itself. Runs every check, latency included,
against the same real in-process server the rest of the integration suite
uses."""

import importlib.util
from pathlib import Path

import httpx
import pytest

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


class _RecordingAuth(httpx.Auth):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def auth_flow(self, request: httpx.Request):
        self.requests.append(request)
        yield request


async def test_every_check_sends_every_request_through_the_auth_handler(server_url: str) -> None:
    """Against a real AgentCore Runtime every request must be SigV4-signed;
    a check that built its own unauthenticated client would 403 there."""
    smoke = _load_smoke_module()
    auth = _RecordingAuth()

    await smoke.run_smoke_checks(server_url, skip_latency=True, auth=auth)

    # One initialize + at least one follow-up request per check, all via auth.
    assert len(auth.requests) >= 2 * len(smoke.selected_checks(skip_latency=True))
    assert {request.url.path for request in auth.requests} == {"/mcp"}


def test_runtime_invocation_url_is_built_from_the_arn() -> None:
    smoke = _load_smoke_module()
    arn = "arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/fixit_mcp-AbCdEf1234"

    url = smoke.runtime_invocation_url(arn)

    assert url == (
        "https://bedrock-agentcore.us-west-2.amazonaws.com/runtimes/"
        "arn%3Aaws%3Abedrock-agentcore%3Aus-west-2%3A111122223333%3Aruntime%2Ffixit_mcp-AbCdEf1234"
        "/invocations?qualifier=DEFAULT"
    )


def test_sigv4_auth_signs_for_bedrock_agentcore(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    smoke = _load_smoke_module()
    request = httpx.Request(
        "POST",
        "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/x/invocations?qualifier=DEFAULT",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Accept": "application/json, text/event-stream"},
    )

    signed = next(smoke.SigV4Auth("us-east-1").auth_flow(request))

    authorization = signed.headers["Authorization"]
    assert authorization.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "/us-east-1/bedrock-agentcore/aws4_request" in authorization
    assert "host" in authorization.split("SignedHeaders=")[1].split(",")[0].split(";")
    assert "X-Amz-Date" in signed.headers
