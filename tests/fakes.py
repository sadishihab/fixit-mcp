"""Shared test doubles."""

from __future__ import annotations

import copy
import itertools
from typing import Any


class FakeClientError(Exception):
    """Stands in for botocore's ClientError in fakes -- the repository must
    let AWS errors propagate, not swallow them, and tests assert that."""


class FakeAgentCoreMemoryClient:
    """Stands in for a boto3 `bedrock-agentcore` data-plane client -- no
    network, no AWS. Models only the behavior the repository relies on:

    - events are stored per (memoryId, actorId, sessionId);
    - ListEvents pages with nextToken (page_size is small-able, to exercise
      pagination with a handful of events);
    - a repeated clientToken is ignored without error, as AWS documents --
      so a repository that derived tokens from appliance_id would visibly
      fail the re-add-after-remove test.

    Every call is recorded in `calls` as (operation, kwargs).
    """

    def __init__(self, page_size: int = 100) -> None:
        self.page_size = page_size
        self.events: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_next: dict[str, Exception] = {}
        self._seen_tokens: set[str] = set()
        self._ids = itertools.count(1)

    def _maybe_fail(self, operation: str) -> None:
        if operation in self.fail_next:
            raise self.fail_next.pop(operation)

    def create_event(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("CreateEvent", kwargs))
        self._maybe_fail("CreateEvent")
        token = kwargs.get("clientToken")
        key = (kwargs["memoryId"], kwargs["actorId"], kwargs["sessionId"])
        if token is not None and token in self._seen_tokens:
            return {"event": {}}
        if token is not None:
            self._seen_tokens.add(token)
        event = {
            "memoryId": kwargs["memoryId"],
            "actorId": kwargs["actorId"],
            "sessionId": kwargs["sessionId"],
            "eventId": f"evt-{next(self._ids):06d}",
            "eventTimestamp": kwargs["eventTimestamp"],
            "payload": copy.deepcopy(kwargs["payload"]),
            "metadata": copy.deepcopy(kwargs.get("metadata", {})),
        }
        self.events.setdefault(key, []).append(event)
        return {"event": copy.deepcopy(event)}

    def list_events(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("ListEvents", kwargs))
        self._maybe_fail("ListEvents")
        key = (kwargs["memoryId"], kwargs["actorId"], kwargs["sessionId"])
        events = self.events.get(key, [])
        start = int(kwargs.get("nextToken", 0))
        page_size = min(kwargs.get("maxResults", 20), self.page_size)
        page = events[start : start + page_size]
        response: dict[str, Any] = {"events": copy.deepcopy(page)}
        if start + page_size < len(events):
            response["nextToken"] = str(start + page_size)
        return response

    def delete_event(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("DeleteEvent", kwargs))
        self._maybe_fail("DeleteEvent")
        key = (kwargs["memoryId"], kwargs["actorId"], kwargs["sessionId"])
        events = self.events.get(key, [])
        remaining = [e for e in events if e["eventId"] != kwargs["eventId"]]
        if len(remaining) == len(events):
            raise FakeClientError("ResourceNotFoundException")
        self.events[key] = remaining
        return {"eventId": kwargs["eventId"]}

    def operations(self) -> list[str]:
        return [operation for operation, _ in self.calls]
