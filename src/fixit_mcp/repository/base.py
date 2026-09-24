from typing import Protocol

from fixit_mcp.domain.models import Appliance


class ApplianceRepository(Protocol):
    """Storage-agnostic interface for a household's appliances.

    Three implementations exist: `InMemoryApplianceRepository` (tests, and
    the "memory" backend for local runs), `SqliteApplianceRepository` (the
    default local backend), and `AgentCoreMemoryApplianceRepository` (the
    "agentcore" backend, for AgentCore Runtime, where local disk is
    per-session) -- see CLAUDE.md. Callers only depend on this protocol, so
    swapping backends never touches them.
    """

    def list_by_household(self, household_id: str) -> list[Appliance]:
        """Return the appliances owned by the given household, or an empty list."""
        ...

    def add(self, household_id: str, appliance: Appliance) -> None:
        """Persist a new appliance under the given household."""
        ...

    def remove(self, household_id: str, appliance_id: str) -> bool:
        """Remove an appliance from a household. Returns True if it existed."""
        ...
