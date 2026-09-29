"""Step 14: throwaway demo households -- provisioning, seeding through the
MCP tools, the ledger, and cleanup. Fake MCP session, no server, no AWS."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp import types

from demo.households import (
    DEMO_HOUSEHOLD_PREFIX,
    HOUSE_002_LIKE_SEED,
    HouseholdLedger,
    HouseholdProvisioner,
    new_demo_household_id,
    remove_households,
)
from demo.orchestrator import OperationTimeout
from fixit_mcp.repository.in_memory import DEFAULT_SEED


class FakeMcp:
    """In-memory stand-in for the three tools the demo uses."""

    def __init__(self, fail_add_on: int | None = None, hang: bool = False) -> None:
        self.households: dict[str, list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_add_on = fail_add_on
        self.hang = hang
        self._n = 0

    def _ok(self, data: dict[str, Any]) -> types.CallToolResult:
        return types.CallToolResult(content=[], structuredContent=data, isError=False)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        self.calls.append((name, dict(arguments)))
        if self.hang:
            await asyncio.sleep(3600)
        household = self.households.setdefault(arguments["household_id"], [])
        if name == "list_my_appliances":
            return self._ok({"household_id": arguments["household_id"], "appliances": list(household)})
        if name == "add_appliance":
            self._n += 1
            if self.fail_add_on == self._n:
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text="boom")], isError=True
                )
            household.append(
                {"appliance_id": f"app-{self._n}", **{k: arguments[k] for k in ("brand", "model")}}
            )
            return self._ok({"appliance": {"appliance_id": f"app-{self._n}"}})
        if name == "remove_appliance":
            before = len(household)
            household[:] = [a for a in household if a["appliance_id"] != arguments["appliance_id"]]
            return self._ok({"removed": len(household) < before})
        raise AssertionError(name)


@pytest.fixture
def ledger(tmp_path) -> HouseholdLedger:
    return HouseholdLedger(tmp_path / "state" / "demo_households.txt")


def provisioner(ledger: HouseholdLedger, fresh: bool = True) -> HouseholdProvisioner:
    return HouseholdProvisioner(fixed_household_id="house-002", fresh=fresh, ledger=ledger)


# --- the seed ------------------------------------------------------------------------------------


def test_the_seed_is_house_002s_appliances_with_its_dates() -> None:
    real = {(a.brand, a.model, a.appliance_type, str(a.purchase_date), str(a.warranty_end_date))
            for a in DEFAULT_SEED["house-002"]}  # fmt: skip
    ours = {
        (s.brand, s.model, s.appliance_type, s.purchase_date, s.warranty_end_date)
        for s in HOUSE_002_LIKE_SEED
    }
    assert ours == real


# --- default mode is unchanged -----------------------------------------------------------------------


async def test_default_mode_serves_the_fixed_household_and_never_seeds_or_records(ledger) -> None:
    p = provisioner(ledger, fresh=False)
    mcp = FakeMcp()
    assert p.household_for("a") == p.household_for("b") == "house-002"
    assert p.needs_seeding("a") is False
    assert await p.ensure_seeded("a", mcp) is False  # type: ignore[arg-type]
    assert mcp.calls == [] and not ledger.path.exists()


# --- fresh mode ---------------------------------------------------------------------------------------


def test_each_session_gets_its_own_stable_demo_household_recorded_in_the_ledger(ledger) -> None:
    p = provisioner(ledger)
    a, b = p.household_for("s1"), p.household_for("s2")
    assert a != b and a.startswith(DEMO_HOUSEHOLD_PREFIX) and b.startswith(DEMO_HOUSEHOLD_PREFIX)
    assert p.household_for("s1") == a
    assert ledger.read() == [a, b]


def test_generated_ids_have_the_demo_prefix_and_are_random() -> None:
    ids = {new_demo_household_id() for _ in range(20)}
    assert len(ids) == 20 and all(i.startswith("house-demo-") for i in ids)


async def test_the_first_turn_seeds_the_dryer_and_the_washer_through_add_appliance(ledger) -> None:
    p, mcp = provisioner(ledger), FakeMcp()
    household = p.household_for("s1")
    assert p.needs_seeding("s1") is True
    assert await p.ensure_seeded("s1", mcp) is True  # type: ignore[arg-type]

    adds = [args for name, args in mcp.calls if name == "add_appliance"]
    assert [(a["brand"], a["model"], a["appliance_type"]) for a in adds] == [
        ("LG", "DLEX8000W", "dryer"),
        ("GE", "GTW680BSJWS", "washing_machine"),
    ]
    assert all(a["household_id"] == household for a in adds)
    assert adds[0]["purchase_date"] == "2023-01-15" and adds[0]["warranty_end_date"] == "2025-01-15"
    assert p.needs_seeding("s1") is False


async def test_seeding_happens_once_per_household(ledger) -> None:
    p, mcp = provisioner(ledger), FakeMcp()
    p.household_for("s1")
    await p.ensure_seeded("s1", mcp)  # type: ignore[arg-type]
    calls_after_first = len(mcp.calls)
    assert await p.ensure_seeded("s1", mcp) is False  # type: ignore[arg-type]
    assert len(mcp.calls) == calls_after_first


async def test_a_failed_seed_is_retried_and_never_duplicates_what_already_went_in(ledger) -> None:
    p, mcp = provisioner(ledger), FakeMcp(fail_add_on=2)  # dryer added, washer fails
    household = p.household_for("s1")
    with pytest.raises(RuntimeError):
        await p.ensure_seeded("s1", mcp)  # type: ignore[arg-type]
    assert p.needs_seeding("s1") is True
    assert [a["model"] for a in mcp.households[household]] == ["DLEX8000W"]

    assert await p.ensure_seeded("s1", mcp) is True  # type: ignore[arg-type]
    assert sorted(a["model"] for a in mcp.households[household]) == ["DLEX8000W", "GTW680BSJWS"]


async def test_a_hung_seed_call_times_out_naming_the_tool(ledger) -> None:
    p = provisioner(ledger)
    p.household_for("s1")
    with pytest.raises(OperationTimeout) as info:
        await p.ensure_seeded("s1", FakeMcp(hang=True), tool_timeout_s=0.05)  # type: ignore[arg-type]
    assert info.value.operation == "tool_call:list_my_appliances"


# --- the ledger -----------------------------------------------------------------------------------------


def test_the_ledger_refuses_ids_without_the_demo_prefix_and_dedupes(ledger) -> None:
    with pytest.raises(ValueError):
        ledger.record("house-002")
    ledger.record("house-demo-aa")
    ledger.record("house-demo-aa")
    assert ledger.read() == ["house-demo-aa"]


# --- cleanup ---------------------------------------------------------------------------------------------


async def test_cleanup_removes_every_appliance_of_every_demo_household_and_empties_the_ledger(ledger) -> None:
    p, mcp = provisioner(ledger), FakeMcp()
    for sid in ("s1", "s2"):
        p.household_for(sid)
        await p.ensure_seeded(sid, mcp)  # type: ignore[arg-type]
    mcp.households["house-002"] = [{"appliance_id": "app-003", "brand": "GE", "model": "GTW680BSJWS"}]

    removed, remaining = await remove_households(mcp, ledger, say=lambda _: None)  # type: ignore[arg-type]

    assert (removed, remaining) == (4, [])
    assert ledger.read() == []
    assert all(not a for h, a in mcp.households.items() if h.startswith("house-demo-"))
    assert mcp.households["house-002"] == [{"appliance_id": "app-003", "brand": "GE", "model": "GTW680BSJWS"}]


async def test_cleanup_never_touches_a_household_without_the_demo_prefix(ledger) -> None:
    ledger.write(["house-002", "house-demo-ok"])
    mcp = FakeMcp()
    mcp.households["house-002"] = [{"appliance_id": "app-003", "brand": "GE", "model": "X"}]
    await remove_households(mcp, ledger, say=lambda _: None)  # type: ignore[arg-type]
    assert mcp.households["house-002"] and not any(
        args["household_id"] == "house-002" for _, args in mcp.calls
    )


async def test_a_household_that_fails_to_clean_stays_in_the_ledger(ledger) -> None:
    class Flaky(FakeMcp):
        async def call_tool(self, name, arguments):  # type: ignore[no-untyped-def]
            if name == "remove_appliance":
                return types.CallToolResult(content=[], structuredContent={"removed": False}, isError=False)
            return await super().call_tool(name, arguments)

    ledger.write(["house-demo-bad"])
    mcp = Flaky()
    mcp.households["house-demo-bad"] = [{"appliance_id": "app-1", "brand": "LG", "model": "X"}]
    removed, remaining = await remove_households(mcp, ledger, say=lambda _: None)  # type: ignore[arg-type]
    assert remaining == ["house-demo-bad"] and ledger.read() == ["house-demo-bad"] and removed == 0


async def test_the_cleanup_command_with_an_empty_ledger_does_nothing_and_never_connects(
    tmp_path, capsys
) -> None:
    from demo import cleanup

    assert await cleanup.run("http://localhost:1/mcp", None, tmp_path / "none.txt") == 0
    assert "Nothing to clean up" in capsys.readouterr().out
