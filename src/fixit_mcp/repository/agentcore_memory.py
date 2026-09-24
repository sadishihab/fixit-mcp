"""ApplianceRepository backed by Amazon Bedrock AgentCore Memory -- the
production backend once the server runs on AgentCore Runtime, where local
disk is per-session scratch space (see FRICTION_LOG.md, step 4a).

Storage model: AgentCore Memory **short-term events**, used as a small
keyed record store rather than as conversation history:

- actorId   = household_id
- sessionId = one fixed "registry" session per household (settings)
- one event per appliance, with a structured `json` payload and
  `extractionMode="SKIP"`, so nothing is ever sent to long-term (LLM-driven)
  extraction. That keeps CLAUDE.md rule 3 true of the backing store too,
  not just our own handlers.
- appliance_id is duplicated into event metadata so a remove can find the
  event without parsing every payload.

Why events and not long-term memory records (BatchCreateMemoryRecords):
events are read by exact (actor, session) key via ListEvents, 200 TPS
account quota; long-term records are built for semantic retrieval,
`ListMemoryRecords` namespaces are *prefix* matches, the account quota is
30 TPS, and freshness after a write isn't documented. The cost of events:
**they expire** after the memory's eventExpiryDuration, 365 days at most.
See FRICTION_LOG.md (step 4b).

Latency: list_by_household and add are one AgentCore call each; remove is
two (ListEvents, then DeleteEvent). Every call's latency is logged
(`agentcore_memory_call`) the same way tool calls are, so the 500ms budget
is monitored rather than assumed.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import ValidationError

from fixit_mcp.domain.models import Appliance

PAYLOAD_SCHEMA = "fixit.appliance.v1"
DEFAULT_REGISTRY_SESSION_ID = "appliance-registry"
_LIST_PAGE_SIZE = 100  # ListEvents' maximum -- one page for any real household.

# AgentCore's actorId pattern (CreateEvent/ListEvents API reference). A
# household_id outside it can never have been stored, so it's rejected
# locally rather than sent to AWS just to get a ValidationException back.
_ACTOR_ID_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9\-_/]*(?::[a-zA-Z0-9\-_/]+)*[a-zA-Z0-9\-_/]*")
_MAX_ACTOR_ID_LEN = 255


def is_valid_household_id(household_id: str) -> bool:
    return len(household_id) <= _MAX_ACTOR_ID_LEN and _ACTOR_ID_RE.fullmatch(household_id) is not None


class AgentCoreMemoryApplianceRepository:
    """ApplianceRepository over AgentCore Memory short-term events.

    `client` is a boto3 `bedrock-agentcore` (data plane) client, injectable
    so unit tests can pass a fake -- same pattern as BedrockExtractor.
    Never seeds anything itself: see scripts/seed_agentcore_memory.py and
    FRICTION_LOG.md (step 4b) for why seeding is an explicit offline step
    for this backend rather than a runtime side effect.
    """

    def __init__(
        self,
        memory_id: str,
        client: Any,
        registry_session_id: str = DEFAULT_REGISTRY_SESSION_ID,
    ) -> None:
        if not memory_id:
            raise ValueError(
                "AgentCore Memory backend needs a memory id -- set FIXIT_AGENTCORE_MEMORY_ID "
                "(see README's AgentCore Memory section)."
            )
        self._memory_id = memory_id
        self._client = client
        self._session_id = registry_session_id
        self._log = structlog.get_logger()

    def list_by_household(self, household_id: str) -> list[Appliance]:
        if not is_valid_household_id(household_id):
            return []
        by_id: dict[str, Appliance] = {}
        for event in self._list_events(household_id):
            appliance = self._appliance_from_event(event)
            # A retried CreateEvent could in principle leave two events for
            # one appliance; the list must still show it once.
            if appliance is not None:
                by_id[appliance.appliance_id] = appliance
        return sorted(by_id.values(), key=lambda a: a.appliance_id)

    def add(self, household_id: str, appliance: Appliance) -> None:
        if not is_valid_household_id(household_id):
            raise ValueError(f"household_id {household_id!r} is not a valid AgentCore Memory actor id")
        self._call(
            "CreateEvent",
            memoryId=self._memory_id,
            actorId=household_id,
            sessionId=self._session_id,
            eventTimestamp=datetime.now(UTC),
            payload=[
                {
                    "json": {
                        "content": {
                            "schema": PAYLOAD_SCHEMA,
                            "appliance": appliance.model_dump(mode="json"),
                        }
                    }
                }
            ],
            metadata={"appliance_id": {"stringValue": appliance.appliance_id}},
            extractionMode="SKIP",
            # Fresh per add() call, not derived from appliance_id: boto3
            # resends these same kwargs on a retry, so retries stay
            # idempotent, while a legitimate re-add of the same appliance_id
            # after a remove (e.g. re-seeding a demo household) isn't
            # silently swallowed as a duplicate. See FRICTION_LOG.md (4b).
            clientToken=uuid.uuid4().hex,
        )

    def remove(self, household_id: str, appliance_id: str) -> bool:
        if not is_valid_household_id(household_id):
            return False
        matching = [
            event["eventId"]
            for event in self._list_events(household_id)
            if _metadata_appliance_id(event) == appliance_id
        ]
        for event_id in matching:
            self._call(
                "DeleteEvent",
                memoryId=self._memory_id,
                actorId=household_id,
                sessionId=self._session_id,
                eventId=event_id,
            )
        return bool(matching)

    def warm_up(self) -> None:
        """One cheap read at startup, so the first real tool call in a fresh
        microVM doesn't also pay for credential resolution and the TLS
        handshake. Logs rather than raises: a transient failure here
        shouldn't stop the server from starting."""
        try:
            self._list_events("fixit-warmup")
        except Exception as exc:  # noqa: BLE001 -- best-effort by design
            self._log.warning("agentcore_memory_warmup_failed", error=str(exc))

    def _list_events(self, household_id: str) -> list[dict]:
        events: list[dict] = []
        kwargs: dict[str, Any] = {
            "memoryId": self._memory_id,
            "actorId": household_id,
            "sessionId": self._session_id,
            "includePayloads": True,
            "maxResults": _LIST_PAGE_SIZE,
        }
        while True:
            response = self._call("ListEvents", **kwargs)
            events.extend(response.get("events", []))
            next_token = response.get("nextToken")
            if not next_token:
                return events
            kwargs["nextToken"] = next_token

    def _call(self, operation: str, **kwargs: Any) -> dict:
        method = getattr(self._client, _SNAKE_CASE[operation])
        start = time.perf_counter()
        try:
            response = method(**kwargs)
        except Exception:
            self._log.error(
                "agentcore_memory_call_failed",
                operation=operation,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            raise
        self._log.info(
            "agentcore_memory_call",
            operation=operation,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return response

    def _appliance_from_event(self, event: dict) -> Appliance | None:
        for item in event.get("payload", []):
            content = item.get("json", {}).get("content")
            if not isinstance(content, dict) or content.get("schema") != PAYLOAD_SCHEMA:
                continue
            try:
                return Appliance.model_validate(content["appliance"])
            except (KeyError, ValidationError):
                break
        # Skip, don't crash: one unreadable event must not hide a household's
        # other appliances. Logged so it's visible, never silently dropped.
        self._log.warning("agentcore_memory_unreadable_event", event_id=event.get("eventId"))
        return None


_SNAKE_CASE = {"CreateEvent": "create_event", "ListEvents": "list_events", "DeleteEvent": "delete_event"}


def _metadata_appliance_id(event: dict) -> str | None:
    return event.get("metadata", {}).get("appliance_id", {}).get("stringValue")


def make_agentcore_memory_client(region: str) -> Any:
    """boto3 `bedrock-agentcore` data-plane client with timeouts sized to
    the 500ms tool budget: fail fast rather than hang a tool call, and at
    most one retry (a second retry could never land inside the budget anyway).
    Credentials come from the standard chain -- the AgentCore Runtime
    execution role once deployed, the local AWS profile until then."""
    import boto3
    from botocore.config import Config

    config = Config(
        connect_timeout=1,
        read_timeout=2,
        retries={"mode": "standard", "total_max_attempts": 2},
        tcp_keepalive=True,
    )
    return boto3.client("bedrock-agentcore", region_name=region, config=config)
