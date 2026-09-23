from mcp.server.fastmcp import FastMCP

from fixit_mcp.config import Settings
from fixit_mcp.logging import configure_logging
from fixit_mcp.repository.base import ApplianceRepository
from fixit_mcp.repository.in_memory import InMemoryApplianceRepository
from fixit_mcp.tools.appliances import register_appliance_tools

SERVER_INSTRUCTIONS = (
    "FixIt helps customers diagnose appliance error codes, remembers which "
    "appliances a household owns, guides repairs, orders replacement parts, "
    "and schedules maintenance. All tools are fast, pre-indexed lookups -- "
    "they never call an LLM themselves; you (the assistant) handle language "
    "generation from the structured data they return."
)


def create_server(
    settings: Settings | None = None,
    repository: ApplianceRepository | None = None,
) -> FastMCP:
    """Build the FixIt FastMCP server: Streamable HTTP, stateless, with tools registered."""
    settings = settings or Settings()
    configure_logging(settings.log_level)

    mcp = FastMCP(
        name="fixit-mcp",
        instructions=SERVER_INSTRUCTIONS,
        host=settings.host,
        port=settings.port,
        streamable_http_path=settings.streamable_http_path,
        stateless_http=True,
        json_response=settings.json_response,
    )

    register_appliance_tools(mcp, repository or InMemoryApplianceRepository())

    return mcp


def main() -> None:
    server = create_server()
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
