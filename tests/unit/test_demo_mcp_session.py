"""demo.mcp_session: tool discovery from a fake MCP session -- no network,
no real server."""

from __future__ import annotations

from mcp import types

from demo.mcp_session import ToolDef, list_tool_defs


class FakeListToolsResult:
    def __init__(self, tools: list[types.Tool]) -> None:
        self.tools = tools


class FakeSession:
    """Stands in for mcp.ClientSession -- only list_tools is exercised here."""

    def __init__(self, tools: list[types.Tool]) -> None:
        self._tools = tools

    async def list_tools(self) -> FakeListToolsResult:
        return FakeListToolsResult(self._tools)


async def test_list_tool_defs_builds_from_what_the_server_advertises() -> None:
    tools = [
        types.Tool(
            name="diagnose_error",
            description="Look up an error code.",
            inputSchema={"type": "object", "properties": {"error_code": {"type": "string"}}},
            _meta={"ui": {"resourceUri": "ui://fixit-mcp/diagnose-error-card"}},
        ),
        types.Tool(
            name="list_my_appliances",
            description="List a household's appliances.",
            inputSchema={"type": "object"},
        ),
    ]

    defs = await list_tool_defs(FakeSession(tools))

    assert defs == [
        ToolDef(
            name="diagnose_error",
            description="Look up an error code.",
            input_schema={"type": "object", "properties": {"error_code": {"type": "string"}}},
            resource_uri="ui://fixit-mcp/diagnose-error-card",
        ),
        ToolDef(
            name="list_my_appliances",
            description="List a household's appliances.",
            input_schema={"type": "object"},
            resource_uri=None,
        ),
    ]


async def test_list_tool_defs_handles_no_description() -> None:
    tools = [types.Tool(name="add_appliance", description=None, inputSchema={"type": "object"})]

    defs = await list_tool_defs(FakeSession(tools))

    assert defs[0].description == ""
