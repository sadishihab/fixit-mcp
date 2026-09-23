from typing import Protocol

from fixit_mcp.domain.models import Appliance


class ApplianceRepository(Protocol):
    """Storage-agnostic interface for looking up a household's appliances.

    The hackathon build backs this with an in-memory seed store; a later
    step can swap in a database-backed implementation without touching
    callers, since they only depend on this protocol.
    """

    def list_by_household(self, household_id: str) -> list[Appliance]:
        """Return the appliances owned by the given household, or an empty list."""
        ...
