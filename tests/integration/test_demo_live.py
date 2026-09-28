"""Opt-in: one real conversation through the demo backend against a real
deployed AgentCore Runtime and real Amazon Bedrock. Needs AWS credentials,
FIXIT_DEMO_TESTS=1, and FIXIT_DEMO_LIVE_AGENT_ARN set to a deployed
runtime's ARN.

    FIXIT_DEMO_TESTS=1 FIXIT_DEMO_LIVE_AGENT_ARN=arn:aws:... uv run pytest \
        tests/integration/test_demo_live.py --group demo
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from demo.app import create_app
from demo.config import DemoSettings
from demo.mcp_target import build_target

pytestmark = pytest.mark.skipif(
    os.environ.get("FIXIT_DEMO_TESTS") != "1", reason="opt-in: set FIXIT_DEMO_TESTS=1 (needs real AWS)"
)


async def test_one_real_conversation_diagnoses_the_lg_dryer_code() -> None:
    settings = DemoSettings()
    assert settings.live_agent_arn, "set FIXIT_DEMO_LIVE_AGENT_ARN to a deployed runtime ARN"
    target = build_target(url=None, agent_arn=settings.live_agent_arn)
    app = create_app(target, settings)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://demo.local") as client:
            response = await client.post(
                "/chat", json={"message": "my dryer shows tE1", "session_id": "live-test-1"}
            )

    assert response.status_code == 200
    body = response.json()
    assert body["simulated_alexa_plus"] is True
    assert body["reply_text"]

    diagnose_calls = [tc for tc in body["tool_calls"] if tc["name"] == "diagnose_error"]
    assert diagnose_calls, f"model never called diagnose_error: {body['tool_calls']}"
    result = diagnose_calls[0]["result"]
    assert result["status"] == "found"
    assert result["appliance"]["brand"] == "LG"

    assert body["card"] is not None
    assert body["card"]["resource_uri"] == "ui://fixit-mcp/diagnose-error-card"
    assert "<html" in body["card"]["html"].lower() or "<!doctype" in body["card"]["html"].lower()
