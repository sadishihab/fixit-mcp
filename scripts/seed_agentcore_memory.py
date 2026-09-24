"""Seed (or reset) the demo households in AgentCore Memory.

The "agentcore" repository backend never seeds anything at runtime -- see
FRICTION_LOG.md (step 4b) for why. This is the explicit, offline way to put
the demo households (house-001, house-002 from
fixit_mcp.repository.in_memory.DEFAULT_SEED) into a real memory resource:

    FIXIT_AGENTCORE_MEMORY_ID=<id> uv run python scripts/seed_agentcore_memory.py [--reset]

Idempotent: an appliance already present (by appliance_id) is left alone, so
running it twice never duplicates anything. --reset first removes *every*
appliance in the demo households (e.g. ones added while rehearsing a demo),
then seeds -- it never touches any other household.
"""

from __future__ import annotations

import argparse
import sys

from fixit_mcp.config import Settings
from fixit_mcp.domain.models import Appliance
from fixit_mcp.repository.agentcore_memory import (
    AgentCoreMemoryApplianceRepository,
    make_agentcore_memory_client,
)
from fixit_mcp.repository.base import ApplianceRepository
from fixit_mcp.repository.in_memory import DEFAULT_SEED


def seed_demo_households(
    repository: ApplianceRepository,
    seed: dict[str, list[Appliance]] = DEFAULT_SEED,
    reset: bool = False,
) -> dict[str, dict[str, int]]:
    """Returns per-household counts of what was removed/added/already present."""
    summary: dict[str, dict[str, int]] = {}
    for household_id, appliances in seed.items():
        removed = 0
        if reset:
            for existing in repository.list_by_household(household_id):
                removed += repository.remove(household_id, existing.appliance_id)
        present = {a.appliance_id for a in repository.list_by_household(household_id)}
        added = 0
        for appliance in appliances:
            if appliance.appliance_id not in present:
                repository.add(household_id, appliance)
                added += 1
        summary[household_id] = {"removed": removed, "added": added, "already_present": len(present)}
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="remove all demo-household appliances first")
    args = parser.parse_args()

    settings = Settings()
    if not settings.agentcore_memory_id:
        print("FIXIT_AGENTCORE_MEMORY_ID is not set.", file=sys.stderr)
        return 2
    repository = AgentCoreMemoryApplianceRepository(
        memory_id=settings.agentcore_memory_id,
        client=make_agentcore_memory_client(settings.agentcore_region),
        registry_session_id=settings.agentcore_registry_session_id,
    )
    for household_id, counts in seed_demo_households(repository, reset=args.reset).items():
        print(f"{household_id}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
