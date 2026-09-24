from mcp.server.fastmcp import FastMCP

from fixit_mcp.catalog.manifest import ManualCatalog, load_manual_catalog
from fixit_mcp.config import Settings
from fixit_mcp.logging import configure_logging
from fixit_mcp.repository.agentcore_memory import (
    AgentCoreMemoryApplianceRepository,
    make_agentcore_memory_client,
)
from fixit_mcp.repository.base import ApplianceRepository
from fixit_mcp.repository.in_memory import InMemoryApplianceRepository
from fixit_mcp.repository.sqlite import SqliteApplianceRepository
from fixit_mcp.retrieval.codes import ErrorCodeIndex, load_index
from fixit_mcp.tools.appliances import register_appliance_tools
from fixit_mcp.tools.diagnose import register_diagnose_tool

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
    error_code_index: ErrorCodeIndex | None = None,
    manual_catalog: ManualCatalog | None = None,
) -> FastMCP:
    """Build the FixIt FastMCP server: Streamable HTTP, stateless, with tools registered.

    error_code_index is loaded from data/index/error_codes.json exactly once,
    here at startup -- not per-request (rule 4, the <500ms budget). Callers
    (tests) can inject a smaller index built from a fixture instead. Likewise
    repository defaults to settings.repository_backend ("sqlite" persists
    across restarts at settings.sqlite_path; "memory" is a fresh
    InMemoryApplianceRepository each time; "agentcore" is AgentCore Memory,
    warmed up with one read here so the first tool call doesn't pay for it)
    and manual_catalog is loaded from data/manuals/manifest.yaml exactly
    once, unless a caller injects either.
    """
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

    if repository is None:
        repository = _make_repository(settings)
    error_code_index = error_code_index or load_index()
    manual_catalog = manual_catalog or load_manual_catalog()

    register_appliance_tools(mcp, repository, manual_catalog)
    register_diagnose_tool(mcp, repository, error_code_index)

    return mcp


def _make_repository(settings: Settings) -> ApplianceRepository:
    if settings.repository_backend == "sqlite":
        return SqliteApplianceRepository(settings.sqlite_path)
    if settings.repository_backend == "agentcore":
        repository = AgentCoreMemoryApplianceRepository(
            memory_id=settings.agentcore_memory_id,
            client=make_agentcore_memory_client(settings.agentcore_region),
            registry_session_id=settings.agentcore_registry_session_id,
        )
        repository.warm_up()
        return repository
    return InMemoryApplianceRepository()


def main() -> None:
    server = create_server()
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
