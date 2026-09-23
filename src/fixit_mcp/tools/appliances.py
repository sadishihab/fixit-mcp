from mcp.server.fastmcp import FastMCP

from fixit_mcp.domain.models import ApplianceList
from fixit_mcp.logging import log_tool_latency
from fixit_mcp.repository.base import ApplianceRepository

LIST_MY_APPLIANCES_DESCRIPTION = (
    "List the appliances a household owns, including brand, model, appliance "
    "type, purchase date, and warranty end date. Call this whenever the "
    "customer asks what appliances they have, refers to an appliance by brand "
    "or type without more detail, or before diagnosing an error code so you "
    "know exactly which appliance it applies to. Requires the household_id "
    "for the customer's account; returns an empty list if the household has "
    "no registered appliances."
)


def register_appliance_tools(mcp: FastMCP, repository: ApplianceRepository) -> None:
    """Register appliance-related tools on the given FastMCP server."""

    @mcp.tool(name="list_my_appliances", description=LIST_MY_APPLIANCES_DESCRIPTION)
    @log_tool_latency("list_my_appliances")
    def list_my_appliances(household_id: str) -> ApplianceList:
        appliances = repository.list_by_household(household_id)
        return ApplianceList(household_id=household_id, appliances=appliances)
