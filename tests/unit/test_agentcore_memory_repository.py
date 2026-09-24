import importlib.util
from datetime import date
from pathlib import Path

import pytest

from fixit_mcp.config import Settings
from fixit_mcp.domain.models import Appliance
from fixit_mcp.repository import agentcore_memory
from fixit_mcp.repository.agentcore_memory import (
    PAYLOAD_SCHEMA,
    AgentCoreMemoryApplianceRepository,
    is_valid_household_id,
)
from fixit_mcp.repository.in_memory import DEFAULT_SEED
from fixit_mcp.server import _make_repository
from tests.fakes import FakeAgentCoreMemoryClient, FakeClientError

MEMORY_ID = "FixItHouseholds-a1B2c3D4e5"
SEED_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_agentcore_memory.py"


def make_appliance(appliance_id: str = "app-x", **overrides) -> Appliance:
    defaults = dict(
        appliance_id=appliance_id,
        brand="Samsung",
        model="RF28",
        appliance_type="refrigerator",
        purchase_date=date(2020, 1, 1),
        warranty_end_date=date(2022, 1, 1),
        manual_id="samsung-rf28-refrigerator",
    )
    defaults.update(overrides)
    return Appliance(**defaults)


def make_repo(client: FakeAgentCoreMemoryClient | None = None) -> AgentCoreMemoryApplianceRepository:
    return AgentCoreMemoryApplianceRepository(MEMORY_ID, client or FakeAgentCoreMemoryClient())


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("fixit_seed_agentcore", SEED_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- round trip -------------------------------------------------


def test_add_then_list_round_trips_every_field() -> None:
    repo = make_repo()
    appliance = make_appliance()

    repo.add("house-x", appliance)

    assert repo.list_by_household("house-x") == [appliance]


def test_optional_fields_round_trip_as_none_and_empty() -> None:
    repo = make_repo()
    appliance = make_appliance(purchase_date=None, warranty_end_date=None, manual_id="")

    repo.add("house-x", appliance)

    assert repo.list_by_household("house-x") == [appliance]


def test_unknown_household_lists_empty() -> None:
    assert make_repo().list_by_household("house-nobody") == []


def test_list_is_sorted_by_appliance_id_like_sqlite() -> None:
    repo = make_repo()
    for appliance_id in ("app-c", "app-a", "app-b"):
        repo.add("house-x", make_appliance(appliance_id))

    assert [a.appliance_id for a in repo.list_by_household("house-x")] == ["app-a", "app-b", "app-c"]


def test_households_are_isolated_by_actor_id() -> None:
    repo = make_repo()
    repo.add("house-a", make_appliance("app-1"))
    repo.add("house-b", make_appliance("app-2"))

    assert [a.appliance_id for a in repo.list_by_household("house-a")] == ["app-1"]
    assert [a.appliance_id for a in repo.list_by_household("house-b")] == ["app-2"]


def test_list_follows_next_token_across_pages() -> None:
    client = FakeAgentCoreMemoryClient(page_size=2)
    repo = make_repo(client)
    for i in range(5):
        repo.add("house-x", make_appliance(f"app-{i}"))
    client.calls.clear()

    assert len(repo.list_by_household("house-x")) == 5
    assert client.operations() == ["ListEvents"] * 3


# --- wire format -------------------------------------------------


def test_add_writes_one_json_event_that_skips_long_term_extraction() -> None:
    client = FakeAgentCoreMemoryClient()
    repo = make_repo(client)

    repo.add("house-x", make_appliance("app-1"))

    assert client.operations() == ["CreateEvent"]
    _, kwargs = client.calls[0]
    assert kwargs["memoryId"] == MEMORY_ID
    assert kwargs["actorId"] == "house-x"
    assert kwargs["sessionId"] == "appliance-registry"
    assert kwargs["extractionMode"] == "SKIP"
    assert kwargs["metadata"] == {"appliance_id": {"stringValue": "app-1"}}
    (payload,) = kwargs["payload"]
    assert payload["json"]["content"]["schema"] == PAYLOAD_SCHEMA
    assert payload["json"]["content"]["appliance"]["purchase_date"] == "2020-01-01"


def test_list_is_a_single_call_for_a_normal_household() -> None:
    """The 500ms budget assumes one AgentCore round trip per list."""
    client = FakeAgentCoreMemoryClient()
    repo = make_repo(client)
    repo.add("house-x", make_appliance())
    client.calls.clear()

    repo.list_by_household("house-x")

    assert client.operations() == ["ListEvents"]
    assert client.calls[0][1]["includePayloads"] is True


def test_registry_session_id_is_configurable() -> None:
    client = FakeAgentCoreMemoryClient()
    repo = AgentCoreMemoryApplianceRepository(MEMORY_ID, client, registry_session_id="registry-v2")

    repo.add("house-x", make_appliance())

    assert client.calls[0][1]["sessionId"] == "registry-v2"


# --- remove -------------------------------------------------


def test_remove_existing_appliance_deletes_its_event() -> None:
    client = FakeAgentCoreMemoryClient()
    repo = make_repo(client)
    repo.add("house-x", make_appliance("app-1"))
    repo.add("house-x", make_appliance("app-2"))
    client.calls.clear()

    assert repo.remove("house-x", "app-1") is True
    assert client.operations() == ["ListEvents", "DeleteEvent"]
    assert [a.appliance_id for a in repo.list_by_household("house-x")] == ["app-2"]


def test_remove_missing_appliance_returns_false_without_deleting() -> None:
    client = FakeAgentCoreMemoryClient()
    repo = make_repo(client)
    repo.add("house-x", make_appliance("app-1"))
    client.calls.clear()

    assert repo.remove("house-x", "app-nope") is False
    assert client.operations() == ["ListEvents"]


def test_remove_never_touches_another_household() -> None:
    repo = make_repo()
    repo.add("house-a", make_appliance("app-1"))

    assert repo.remove("house-b", "app-1") is False
    assert len(repo.list_by_household("house-a")) == 1


def test_duplicate_events_for_one_appliance_list_once_and_remove_together() -> None:
    client = FakeAgentCoreMemoryClient()
    repo = make_repo(client)
    appliance = make_appliance("app-1")
    repo.add("house-x", appliance)
    repo.add("house-x", appliance)  # e.g. a retry that landed twice

    assert repo.list_by_household("house-x") == [appliance]
    assert repo.remove("house-x", "app-1") is True
    assert repo.list_by_household("house-x") == []


def test_re_adding_an_appliance_after_removing_it_is_not_swallowed() -> None:
    """AWS silently ignores a repeated clientToken. A token derived from
    appliance_id would make this re-add (exactly what a demo reset does)
    vanish without an error -- see FRICTION_LOG.md, step 4b."""
    repo = make_repo()
    appliance = make_appliance("app-1")
    repo.add("house-x", appliance)
    repo.remove("house-x", "app-1")

    repo.add("house-x", appliance)

    assert repo.list_by_household("house-x") == [appliance]


def test_each_add_uses_a_distinct_client_token() -> None:
    client = FakeAgentCoreMemoryClient()
    repo = make_repo(client)

    repo.add("house-x", make_appliance("app-1"))
    repo.add("house-x", make_appliance("app-1"))

    tokens = [kwargs["clientToken"] for _, kwargs in client.calls]
    assert len(set(tokens)) == 2


# --- robustness -------------------------------------------------


def test_unreadable_event_is_skipped_not_fatal() -> None:
    client = FakeAgentCoreMemoryClient()
    repo = make_repo(client)
    repo.add("house-x", make_appliance("app-good"))
    client.events[(MEMORY_ID, "house-x", "appliance-registry")].append(
        {"eventId": "evt-bad", "payload": [{"json": {"content": {"schema": PAYLOAD_SCHEMA}}}], "metadata": {}}
    )
    client.events[(MEMORY_ID, "house-x", "appliance-registry")].append(
        {"eventId": "evt-foreign", "payload": [{"blob": "not ours"}], "metadata": {}}
    )

    assert [a.appliance_id for a in repo.list_by_household("house-x")] == ["app-good"]


@pytest.mark.parametrize("household_id", ["", "-leading-dash", "has space", "semi;colon", "x" * 256])
def test_invalid_household_ids_never_reach_aws(household_id: str) -> None:
    client = FakeAgentCoreMemoryClient()
    repo = make_repo(client)

    assert repo.list_by_household(household_id) == []
    assert repo.remove(household_id, "app-1") is False
    with pytest.raises(ValueError, match="not a valid AgentCore Memory actor id"):
        repo.add(household_id, make_appliance())
    assert client.calls == []


@pytest.mark.parametrize("household_id", ["house-001", "smoke-abc123", "house_1", "org/house-1", "a:b"])
def test_valid_household_ids(household_id: str) -> None:
    assert is_valid_household_id(household_id)


def test_aws_errors_propagate_rather_than_look_like_an_empty_household() -> None:
    """An empty list would tell Alexa+ "you own nothing" -- wrong and worse
    than an error when the real problem is throttling or permissions."""
    client = FakeAgentCoreMemoryClient()
    client.fail_next["ListEvents"] = FakeClientError("ThrottledException")
    repo = make_repo(client)

    with pytest.raises(FakeClientError):
        repo.list_by_household("house-x")


def test_empty_memory_id_fails_loudly_at_construction() -> None:
    with pytest.raises(ValueError, match="FIXIT_AGENTCORE_MEMORY_ID"):
        AgentCoreMemoryApplianceRepository("", FakeAgentCoreMemoryClient())


def test_warm_up_makes_one_read_and_swallows_failures() -> None:
    client = FakeAgentCoreMemoryClient()
    client.fail_next["ListEvents"] = FakeClientError("network blip")
    repo = make_repo(client)

    repo.warm_up()  # must not raise

    assert client.operations() == ["ListEvents"]


def test_never_seeds_on_its_own() -> None:
    client = FakeAgentCoreMemoryClient()
    repo = make_repo(client)

    assert repo.list_by_household("house-001") == []
    assert "CreateEvent" not in client.operations()


# --- server wiring -------------------------------------------------


def test_agentcore_backend_is_built_from_settings_and_warmed_up(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeAgentCoreMemoryClient()
    regions: list[str] = []

    def fake_make_client(region: str) -> FakeAgentCoreMemoryClient:
        regions.append(region)
        return client

    monkeypatch.setattr("fixit_mcp.server.make_agentcore_memory_client", fake_make_client)
    settings = Settings(
        _env_file=None,
        repository_backend="agentcore",
        agentcore_memory_id=MEMORY_ID,
        agentcore_region="us-west-2",
    )

    repository = _make_repository(settings)

    assert isinstance(repository, AgentCoreMemoryApplianceRepository)
    assert regions == ["us-west-2"]
    assert client.operations() == ["ListEvents"]  # the warm-up read


def test_agentcore_backend_without_memory_id_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fixit_mcp.server.make_agentcore_memory_client", lambda region: object())
    settings = Settings(_env_file=None, repository_backend="agentcore", agentcore_memory_id="")

    with pytest.raises(ValueError, match="FIXIT_AGENTCORE_MEMORY_ID"):
        _make_repository(settings)


def test_real_client_factory_uses_tight_timeouts() -> None:
    client = agentcore_memory.make_agentcore_memory_client("us-east-1")

    assert client.meta.service_model.service_name == "bedrock-agentcore"
    assert client.meta.config.read_timeout == 2
    assert client.meta.config.connect_timeout == 1
    assert client.meta.config.retries["total_max_attempts"] == 2


# --- seed script -------------------------------------------------


def test_seed_script_seeds_demo_households_once() -> None:
    seed = _load_seed_module()
    repo = make_repo()

    first = seed.seed_demo_households(repo)
    second = seed.seed_demo_households(repo)

    for household_id, appliances in DEFAULT_SEED.items():
        assert repo.list_by_household(household_id) == sorted(appliances, key=lambda a: a.appliance_id)
        assert first[household_id]["added"] == len(appliances)
        assert second[household_id] == {"removed": 0, "added": 0, "already_present": len(appliances)}


def test_seed_script_fills_in_only_missing_demo_appliances() -> None:
    seed = _load_seed_module()
    repo = make_repo()
    seed.seed_demo_households(repo)
    repo.remove("house-001", "app-001")

    summary = seed.seed_demo_households(repo)

    assert summary["house-001"]["added"] == 1
    assert len(repo.list_by_household("house-001")) == len(DEFAULT_SEED["house-001"])


def test_seed_script_reset_clears_rehearsal_data_but_only_in_demo_households() -> None:
    seed = _load_seed_module()
    repo = make_repo()
    seed.seed_demo_households(repo)
    repo.add("house-001", make_appliance("app-rehearsal"))
    repo.add("house-customer", make_appliance("app-real"))

    seed.seed_demo_households(repo, reset=True)

    assert "app-rehearsal" not in {a.appliance_id for a in repo.list_by_household("house-001")}
    assert len(repo.list_by_household("house-001")) == len(DEFAULT_SEED["house-001"])
    assert [a.appliance_id for a in repo.list_by_household("house-customer")] == ["app-real"]
