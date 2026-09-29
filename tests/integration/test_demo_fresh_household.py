"""Step 14 end to end: with FIXIT_DEMO_FRESH_HOUSEHOLD on, a new conversation
gets its own seeded house-demo-* household through the real FixIt MCP server
(only Bedrock faked), the system prompt names it, and cleanup removes it.
With the setting off (the default) nothing changes."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from demo.app import create_app
from demo.config import DemoSettings
from demo.households import HouseholdLedger, remove_households
from demo.mcp_session import MCPTarget


def _bedrock(prompts: list[str]) -> MagicMock:
    def converse(**kwargs: Any) -> dict[str, Any]:
        prompts.append(kwargs["system"][0]["text"])
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
            "usage": {},
        }

    client = MagicMock()
    client.converse.side_effect = converse
    return client


async def _appliances(server_url: str, household_id: str) -> list[dict[str, Any]]:
    async with (
        create_mcp_http_client() as http,
        streamable_http_client(server_url, http_client=http) as (r, w, _),
    ):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool("list_my_appliances", {"household_id": household_id})
            return result.structuredContent["appliances"]


async def test_fresh_mode_seeds_a_new_household_per_conversation_names_it_in_the_prompt_and_cleans_up(
    server_url: str, tmp_path
) -> None:
    prompts: list[str] = []
    settings = DemoSettings(fresh_household=True, households_file=str(tmp_path / "hh.txt"))
    with patch("demo.app.boto3.client", return_value=_bedrock(prompts)):
        app = create_app(MCPTarget(url=server_url, auth=None), settings)
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://demo.local") as client:
                for sid in ("convo-1", "convo-1", "convo-2"):
                    response = await client.post("/chat", json={"message": "hi", "session_id": sid})
                    assert response.status_code == 200

    ledger = HouseholdLedger(tmp_path / "hh.txt")
    first, second = ledger.read()
    assert first != second and first.startswith("house-demo-") and second.startswith("house-demo-")
    assert f"household_id='{first}'" in prompts[0] and f"household_id='{first}'" in prompts[1]
    assert f"household_id='{second}'" in prompts[2]
    assert "house-002" not in "".join(prompts)

    for household in (first, second):
        seeded = await _appliances(server_url, household)
        assert sorted((a["brand"], a["model"]) for a in seeded) == [
            ("GE", "GTW680BSJWS"),
            ("LG", "DLEX8000W"),
        ]
        assert all(a["manual_id"] for a in seeded)  # linked to their manuals, like house-002's

    # The second turn of convo-1 did not seed again.
    assert len(await _appliances(server_url, first)) == 2

    async with (
        create_mcp_http_client() as http,
        streamable_http_client(server_url, http_client=http) as (r, w, _),
    ):
        async with ClientSession(r, w) as session:
            await session.initialize()
            removed, remaining = await remove_households(session, ledger, say=lambda _: None)
    assert (removed, remaining) == (4, [])
    assert await _appliances(server_url, first) == [] and await _appliances(server_url, second) == []
    assert ledger.read() == []


async def test_default_mode_still_serves_house_002_and_creates_nothing(server_url: str, tmp_path) -> None:
    prompts: list[str] = []
    ledger_file = tmp_path / "hh.txt"
    settings = DemoSettings(households_file=str(ledger_file))
    assert settings.fresh_household is False
    with patch("demo.app.boto3.client", return_value=_bedrock(prompts)):
        app = create_app(MCPTarget(url=server_url, auth=None), settings)
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://demo.local") as client:
                response = await client.post("/chat", json={"message": "hi", "session_id": "x"})

    assert response.status_code == 200
    assert "household_id='house-002'" in prompts[0]
    assert not ledger_file.exists()
