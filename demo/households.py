"""Throwaway demo households (step 14): one fresh, seeded household per demo
conversation, so nothing carries over between recordings, plus the local
ledger `make demo-cleanup` uses to remove them again.

Everything goes through the MCP server's own tools (add_appliance,
list_my_appliances, remove_appliance) -- never straight into AgentCore Memory
or SQLite -- so it works identically against the local dev server and the
deployed runtime, and exercises the same path a real customer would.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from mcp import ClientSession

from demo.orchestrator import DEFAULT_TOOL_TIMEOUT_S, within

# Only ids with this prefix are ever created or removed by the demo tooling.
DEMO_HOUSEHOLD_PREFIX = "house-demo-"


@dataclass(frozen=True)
class SeedAppliance:
    brand: str
    model: str
    appliance_type: str
    purchase_date: str
    warranty_end_date: str


# The same appliances, with the same dates, as house-002 in the real seed data
# (fixit_mcp.repository.in_memory.DEFAULT_SEED; tests/unit/test_demo_households.py
# checks they still match). The demo never imports fixit_mcp, hence the copy.
HOUSE_002_LIKE_SEED: tuple[SeedAppliance, ...] = (
    SeedAppliance("LG", "DLEX8000W", "dryer", "2023-01-15", "2025-01-15"),
    SeedAppliance("GE", "GTW680BSJWS", "washing_machine", "2023-01-15", "2025-01-15"),
)


def new_demo_household_id() -> str:
    return f"{DEMO_HOUSEHOLD_PREFIX}{secrets.token_hex(4)}"


class HouseholdLedger:
    """A local file (gitignored, under data/state/) listing every demo
    household this machine created, one id per line. Written *before* a
    household is seeded, so a crash mid-seed still leaves it cleanable."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, household_id: str) -> None:
        if not household_id.startswith(DEMO_HOUSEHOLD_PREFIX):
            raise ValueError(f"refusing to track {household_id!r}: not a {DEMO_HOUSEHOLD_PREFIX}* id")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if household_id not in self.read():
            with self.path.open("a") as f:
                f.write(household_id + "\n")

    def read(self) -> list[str]:
        if not self.path.exists():
            return []
        seen: list[str] = []
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if line and line not in seen:
                seen.append(line)
        return seen

    def write(self, household_ids: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(h + "\n" for h in household_ids))


class HouseholdProvisioner:
    """Decides which household each demo conversation serves.

    Default (fresh=False): every session serves `fixed_household_id`, exactly as
    before this step, and nothing is ever seeded. Fresh mode: each new
    session_id gets its own `house-demo-<random>` household, recorded in the
    ledger and seeded on that session's first turn."""

    def __init__(self, *, fixed_household_id: str, fresh: bool, ledger: HouseholdLedger) -> None:
        self.fixed_household_id = fixed_household_id
        self.fresh = fresh
        self.ledger = ledger
        self._by_session: dict[str, str] = {}
        self._seeded: set[str] = set()

    def household_for(self, session_id: str) -> str:
        if not self.fresh:
            return self.fixed_household_id
        household_id = self._by_session.get(session_id)
        if household_id is None:
            household_id = self._by_session[session_id] = new_demo_household_id()
            self.ledger.record(household_id)
        return household_id

    def needs_seeding(self, session_id: str) -> bool:
        return self.fresh and self._by_session.get(session_id) not in self._seeded

    async def ensure_seeded(
        self, session_id: str, session: ClientSession, tool_timeout_s: float | None = DEFAULT_TOOL_TIMEOUT_S
    ) -> bool:
        """Seed this session's fresh household through the MCP server if it has
        not been yet. Idempotent (lists first and adds only what is missing), so
        a retry after a half-finished seed never duplicates an appliance.
        Returns True if it seeded anything. Raises if a call fails; the household
        then stays unseeded and the next turn tries again."""
        if not self.needs_seeding(session_id):
            return False
        household_id = self._by_session[session_id]
        listed = await within(
            tool_timeout_s,
            "tool_call:list_my_appliances",
            session.call_tool("list_my_appliances", {"household_id": household_id}),
        )
        have = {
            (a["brand"].lower(), a["model"].lower())
            for a in ((listed.structuredContent or {}).get("appliances") or [])
        }
        added: list[str] = []
        for appliance in HOUSE_002_LIKE_SEED:
            if (appliance.brand.lower(), appliance.model.lower()) in have:
                continue
            result = await within(
                tool_timeout_s,
                "tool_call:add_appliance",
                session.call_tool(
                    "add_appliance",
                    {
                        "household_id": household_id,
                        "brand": appliance.brand,
                        "model": appliance.model,
                        "appliance_type": appliance.appliance_type,
                        "purchase_date": appliance.purchase_date,
                        "warranty_end_date": appliance.warranty_end_date,
                    },
                ),
            )
            if result.isError:
                raise RuntimeError(f"seeding {appliance.brand} {appliance.model} failed: {result.content}")
            added.append(f"{appliance.brand} {appliance.model}")
        self._seeded.add(household_id)
        structlog.get_logger().info(
            "demo_household_seeded", session_id=session_id, household_id=household_id, added=added
        )
        return bool(added)


async def remove_households(
    session: ClientSession, ledger: HouseholdLedger, say: Any = print
) -> tuple[int, list[str]]:
    """Remove every appliance of every ledger household (only ids starting with
    `house-demo-`), through remove_appliance, then drop the household from the
    ledger once it lists empty. Households that fail stay in the ledger for the
    next run. Returns (appliances removed, households left)."""
    removed = 0
    remaining: list[str] = []
    for household_id in ledger.read():
        if not household_id.startswith(DEMO_HOUSEHOLD_PREFIX):
            say(f"skipping {household_id!r}: not a {DEMO_HOUSEHOLD_PREFIX}* id")
            continue
        try:
            listed = await session.call_tool("list_my_appliances", {"household_id": household_id})
            for appliance in (listed.structuredContent or {}).get("appliances") or []:
                result = await session.call_tool(
                    "remove_appliance",
                    {"household_id": household_id, "appliance_id": appliance["appliance_id"]},
                )
                if result.isError or not (result.structuredContent or {}).get("removed"):
                    raise RuntimeError(f"remove_appliance failed for {appliance['appliance_id']}")
                removed += 1
            after = await session.call_tool("list_my_appliances", {"household_id": household_id})
            if (after.structuredContent or {}).get("appliances"):
                raise RuntimeError("household still lists appliances after removal")
            say(f"{household_id}: clean")
        except Exception as exc:  # noqa: BLE001 -- keep going, report, keep it in the ledger
            say(f"{household_id}: FAILED ({type(exc).__name__}: {exc}); kept in the ledger")
            remaining.append(household_id)
    ledger.write(remaining)
    return removed, remaining
