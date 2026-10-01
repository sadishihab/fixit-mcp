"""The Converse tool-use loop: turns one user message plus conversation
history into a spoken-style reply, a record of every tool call made along
the way, and (when applicable) an MCP Apps card.

Request/response shapes here follow Amazon Bedrock's Converse API tool-use
contract exactly as AWS's own docs show it (toolConfig.tools[].toolSpec,
toolUse/toolResult content blocks, stopReason == "tool_use" driving the
loop) -- verified against docs.aws.amazon.com/bedrock/latest/userguide/
tool-use-client-side.md before writing this, not guessed.
"""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog
from mcp import ClientSession, McpError

from demo.mcp_session import ToolDef

# Reopens a fresh MCP session for the same conversation -- called only when
# a "session terminated" failure proves the current one is permanently stale
# (see _call_tool_with_retry). Provided by whoever owns the SessionManager
# (demo/app.py); orchestrator.py has no session-storage knowledge of its own.
RefreshSession = Callable[[], Awaitable[ClientSession]]

# A tool result is worth fetching a card for when its structuredContent's
# status is one of these -- generalized rather than hardcoded to
# diagnose_error by name, so any future tool with a ui card and the same
# found/not_found/ambiguous_appliance convention gets the same behavior for
# free. Any other status (or a tool with no resourceUri at all) gets no
# card -- see demo/README.md.
_CARD_STATUSES = frozenset({"found", "not_found", "ambiguous_appliance"})

MAX_REPLY_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.3

# Tools whose repeated invocation with the same arguments can't create a
# duplicate side effect -- safe to retry after an ambiguous "did the server
# even see this" failure. add_appliance is deliberately excluded: retrying it
# after a lost response risks registering the same appliance twice.
_IDEMPOTENT_TOOLS = frozenset(
    {"list_my_appliances", "diagnose_error", "diagnose_symptom", "check_warranty", "remove_appliance"}
)

# mcp.client.streamable_http._handle_post_request's own 404 branch: a stale
# or misrouted Mcp-Session-Id short-circuits *before* any tool code runs and
# is turned into this specific McpError (never a real tool-level error), so
# retrying it can never duplicate a side effect -- the request is known not
# to have reached the tool handler at all.
_SESSION_TERMINATED_ERROR_CODE = 32600


def _session_terminated_before_reaching_handler(exc: BaseException) -> bool:
    return isinstance(exc, McpError) and exc.error.code == _SESSION_TERMINATED_ERROR_CODE


def is_transient_transport_error(exc: BaseException) -> bool:
    """A failure that looks like a runtime/transport/session communication
    problem rather than a deterministic application or tool error: the MCP
    transport's own "session terminated" signal (see
    _session_terminated_before_reaching_handler), a real httpx transport-level
    failure (connection reset, timeout, protocol error), or a 502/503/504 from
    an intermediary. This is a *hypothesis* about a failure's likely cause,
    not a proven diagnosis -- used to label a /chat error response as
    retryable, and (narrowed further by tool idempotency, see
    _is_retryable_tool_call) to decide whether to automatically retry a tool
    call once."""
    if _session_terminated_before_reaching_handler(exc):
        return True
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (502, 503, 504)
    return False


def _is_retryable_tool_call(exc: BaseException, tool_name: str) -> bool:
    """Safe to automatically retry this tool call exactly once. The "session
    terminated" signal is always safe (the request is known never to have
    reached the tool handler); any other transient transport error is only
    retried for a tool in _IDEMPOTENT_TOOLS, so a lost response never risks a
    duplicate side effect. A deterministic McpError (a real tool/application
    error) is never retried."""
    if _session_terminated_before_reaching_handler(exc):
        return True
    return tool_name in _IDEMPOTENT_TOOLS and is_transient_transport_error(exc)


SYSTEM_PROMPT_TEMPLATE = (
    "You are a voice assistant helping a customer with home appliances, in the "
    "style of Alexa+: short, spoken-style sentences, plain prose -- no markdown, "
    "no headers, no bullet points, nothing that only makes sense written down. "
    "Keep replies to at most two sentences, unless the customer asks for the full "
    "repair steps. "
    "You are serving household_id={household_id!r}; pass this household_id to "
    "any tool that accepts one, so it looks up the right household's appliances. "
    "Call a tool whenever you need real information about an error code or the "
    "household's appliances -- never invent a code's meaning, a cause, a repair "
    "step, a part, or a safety warning; only say what a tool actually returned. "
    "Never add your own explanation, consequence, or reasoning that a tool result "
    "didn't state -- if you want to say why something matters, only say what the "
    "tool itself said. "
    "Never add a judgment of your own -- no 'good news', 'nothing's wrong', 'nothing to "
    "worry about', 'it's not serious' or 'it's an easy fix' -- no prediction of what will "
    "happen, how long anything takes or what it costs, and no next step the tool result "
    "didn't state. That includes saying which part or component a technician would check, "
    "diagnose or replace: if the result only says to call for service, say only that. "
    "State a code's meaning and its repair steps exactly as the result gives them -- never "
    "gloss, expand, or explain a code with a mechanism, cause, or condition the result "
    "didn't give, even one that sounds obvious or harmless. For example if meaning is "
    "'INLET ERROR', say only 'INLET ERROR' (or a plain restatement of those exact words) -- "
    "never add a clause like 'which happens when water isn't filling the washer properly' "
    "unless the result itself says that. "
    "Don't repeat the same fact twice in one reply -- if a result's meaning and "
    "its likely_causes say the same thing, state it once, not both. "
    "If asked whether something is safe or dangerous, answer only from the tool "
    "result's safety_warnings: if it has none, say the manual doesn't list a "
    "specific safety warning for this code, and stop there -- an empty list means "
    "no warning was found, not that it's confirmed safe, so never say 'it's safe' "
    "or otherwise assert a safety judgment the tool didn't make. "
    "If a tool's result says the appliance is ambiguous, ask the customer which "
    "appliance they mean before guessing. "
    "If diagnose_error's result has appliance_registered set to false, the code is real "
    "and documented, but only for an appliance this household hasn't registered -- say so "
    "plainly (name the brand and model the result gives, and that it isn't registered to "
    "this household) before or alongside the diagnosis, and never assume or imply it's the "
    "customer's own appliance; you may mention that they can add it with add_appliance. "
    "When a tool result's status is not_found, the search covered the whole "
    "index, not any one appliance -- say only that this code isn't in the "
    "manuals we have, and never name a brand or appliance for it. Nearest_matches "
    "and a suggestion to add the appliance are the only things a not_found result "
    "supports: if nearest_matches is non-empty, offer those as possible codes to "
    "check; if the result suggests adding the appliance to the household, say so; "
    "never suggest contacting support or anyone else, and never add any other "
    "advice the tool result didn't provide. "
    "If the customer describes a problem and gives no error code -- 'it won't drain', 'it keeps "
    "beeping' -- call diagnose_symptom with their short description. State only what its matching "
    "entries say: the problem, the possible causes, and what the manual says to do, in the manual's "
    "own words -- never add a cause, a step, a part, a safety judgment, a time, a cost, or "
    "reassurance of your own, and never finish a sentence an entry leaves unfinished. If an entry "
    "carries a footnote, say it limits which models the entry applies to. An entry whose "
    "response_label is 'Reason' explains normal behavior; don't phrase it as an instruction. If "
    "asked whether the problem is dangerous or whether to call someone, answer only from the entry: "
    "it carries no safety rating, so say the manual doesn't state one beyond what it lists, repeat a "
    "call-for-service instruction only if the entry itself gives it, and never say it is safe or "
    "that no one needs to be called. If its status is not_found, say only that the manuals don't "
    "list that problem, offer nearest_phrases as possible matches if there are any, and name no "
    "cause. If its appliance_registered is false, say the entry is for a brand and model that isn't "
    "registered to this household, as for diagnose_error. "
    "If the customer asks about warranty status -- whether an appliance is still covered, "
    "how much longer, or when it expired -- call check_warranty. State only the date fact "
    "the result gives (active, expired, or unknown, plus the date and day count), and always "
    "call it the recorded warranty date -- for example 'the recorded warranty ended on ...' -- "
    "since it's what the customer registered, not something verified with the manufacturer; "
    "never say whether a repair would be covered, never characterize what the warranty "
    "covers, and never suggest contacting anyone the tool result didn't mention."
)


def build_system_prompt(household_id: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(household_id=household_id)


def build_tool_config(tool_defs: list[ToolDef]) -> dict[str, Any] | None:
    """Bedrock Converse's toolConfig, built from what tools/list actually
    returned -- never a hardcoded tool list."""
    if not tool_defs:
        return None
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": {"json": tool.input_schema},
                }
            }
            for tool in tool_defs
        ]
    }


DEFAULT_TOOL_TIMEOUT_S = 15.0
DEFAULT_CONVERSE_TIMEOUT_S = 30.0


class OperationTimeout(Exception):
    """One awaited step of a turn (a tool call, a resource read, a Converse
    call, or the whole turn) exceeded its time budget. Carries which step and
    how long the budget was, so /chat's failure log can name both, instead of
    the turn hanging with no signal at all (FRICTION_LOG.md, step 13)."""

    def __init__(self, operation: str, timeout_s: float) -> None:
        super().__init__(f"{operation} timed out after {timeout_s:g}s")
        self.operation = operation
        self.timeout_s = timeout_s
        self.fixit_operation = operation


async def within(timeout_s: float | None, operation: str, awaitable: Awaitable[Any]) -> Any:
    """Await `awaitable`, raising OperationTimeout if it takes longer than
    `timeout_s` (None disables the limit)."""
    if timeout_s is None:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout_s)
    except TimeoutError:
        raise OperationTimeout(operation, timeout_s) from None


def _tool_use_ids(message: dict[str, Any]) -> list[str]:
    return [b["toolUse"]["toolUseId"] for b in message.get("content", []) if "toolUse" in b]


def _tool_result_ids(message: dict[str, Any]) -> list[str]:
    return [b["toolResult"]["toolUseId"] for b in message.get("content", []) if "toolResult" in b]


def repair_history(messages: list[dict[str, Any]]) -> int:
    """Repairs, in place, a Converse history a failed turn left half-written:
    an assistant toolUse that is not answered by a toolResult for every one of
    its ids in the very next message (Bedrock rejects the whole conversation
    with "tool_use ids were found without tool_result blocks immediately
    after"). The dangling assistant message is dropped, as is any toolResult
    block that no longer has its toolUse; then adjacent same-role messages are
    merged (the API wants strictly alternating roles) and empty messages
    removed. Returns how many dangling toolUse messages were dropped, so the
    caller can log that it happened."""
    dropped = 0
    i = 0
    while i < len(messages):
        message = messages[i]
        if message.get("role") == "assistant":
            ids = _tool_use_ids(message)
            if ids:
                following = messages[i + 1] if i + 1 < len(messages) else None
                answered = (
                    following is not None
                    and following.get("role") == "user"
                    and set(ids) <= set(_tool_result_ids(following))
                )
                if not answered:
                    del messages[i]
                    dropped += 1
                    continue
        i += 1

    if dropped:
        live_ids = {tid for m in messages if m.get("role") == "assistant" for tid in _tool_use_ids(m)}
        for message in messages:
            if message.get("role") == "user":
                message["content"] = [
                    b
                    for b in message["content"]
                    if "toolResult" not in b or b["toolResult"]["toolUseId"] in live_ids
                ]
        messages[:] = [m for m in messages if m.get("content")]
        merged: list[dict[str, Any]] = []
        for message in messages:
            if merged and merged[-1]["role"] == message["role"]:
                merged[-1]["content"] = merged[-1]["content"] + message["content"]
            else:
                merged.append(message)
        messages[:] = merged
    return dropped


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None
    latency_ms: float
    # True if a transient transport/session failure on the first attempt was
    # retried once (see _is_retryable_tool_call) -- for observability, not
    # behavior; a successful retried call looks the same to Bedrock either way.
    retried: bool = False


@dataclass(frozen=True)
class CardResult:
    resource_uri: str
    html: str


@dataclass
class TurnResult:
    reply_text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    card: CardResult | None = None
    # Summed across every Converse call this turn made (usually 1-2: the
    # round that decides to call a tool, plus the round that answers using
    # its result) -- for cost/usage reporting, not returned in the API
    # response.
    input_tokens: int = 0
    output_tokens: int = 0


class ConversationStore:
    """Per-session_id Converse message history, kept in memory only --
    process-lifetime, never persisted. Fine for a local demo (CLAUDE.md's
    persistence conventions are about the real server's household data,
    not this)."""

    def __init__(self) -> None:
        self._messages: dict[str, list[dict[str, Any]]] = {}

    def get(self, session_id: str) -> list[dict[str, Any]]:
        return self._messages.setdefault(session_id, [])


def _text_of(content: list[Any]) -> str:
    return "".join(getattr(block, "text", "") for block in content)


async def _call_tool_with_retry(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
    refresh_session: RefreshSession | None,
) -> tuple[Any, bool, ClientSession]:
    """Calls a tool, retrying exactly once when the failure is classified as
    a transient transport/session communication problem for this tool (see
    _is_retryable_tool_call) -- a deterministic tool/application error is
    never retried. Returns (result, whether a retry was attempted, the
    session subsequent calls this turn should use).

    The "session terminated" signal is special: mcp.client.streamable_http
    never clears its stored Mcp-Session-Id after that error (confirmed by
    reading the SDK and by tests/unit/test_demo_session_recovery.py's fake-
    transport test), so retrying on the *same* session would resend the
    identical stale id and get the identical 404 forever -- retrying it is
    only attempted if `refresh_session` is given, and the retry runs against
    the *fresh* session it returns, not the old one. An ordinary transient
    transport error (a one-off timeout, a dropped connection) doesn't have
    this problem and is retried on the same session as before.

    Logs the first failure before retrying, and the retry's own outcome, so
    a demo operator can see this happened without it silently masking a
    real problem."""
    logger = structlog.get_logger()
    try:
        return await session.call_tool(name, arguments), False, session
    except Exception as exc:
        if not _is_retryable_tool_call(exc, name):
            exc.fixit_operation = f"tool_call:{name}"  # type: ignore[attr-defined]
            raise

        session_terminated = _session_terminated_before_reaching_handler(exc)
        logger.warning(
            "tool_call_transient_failure",
            tool=name,
            attempt=1,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            session_terminated=session_terminated,
        )

        retry_session = session
        if session_terminated:
            if refresh_session is None:
                # No way to open a fresh session -- retrying this one is
                # known to be futile (see the docstring above), so don't.
                exc.fixit_operation = f"tool_call:{name}"  # type: ignore[attr-defined]
                raise
            retry_session = await refresh_session()

        retry_start = time.perf_counter()
        try:
            result = await retry_session.call_tool(name, arguments)
        except Exception as retry_exc:
            retry_exc.fixit_operation = f"tool_call:{name}"  # type: ignore[attr-defined]
            logger.warning(
                "tool_call_retry_failed",
                tool=name,
                attempt=2,
                exception_type=type(retry_exc).__name__,
                exception_message=str(retry_exc),
                session_refreshed=session_terminated,
                elapsed_ms=round((time.perf_counter() - retry_start) * 1000, 1),
            )
            raise
        logger.info(
            "tool_call_retry_succeeded",
            tool=name,
            attempt=2,
            session_refreshed=session_terminated,
            elapsed_ms=round((time.perf_counter() - retry_start) * 1000, 1),
        )
        return result, True, retry_session


async def _dispatch_tool_call(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
    refresh_session: RefreshSession | None,
) -> tuple[ToolCallRecord, dict[str, Any], bool, ClientSession]:
    """Calls the tool, returning (record for the API response, the Bedrock
    toolResult content block, whether the result was an error, the session
    subsequent calls this turn should use -- see _call_tool_with_retry)."""
    start = time.perf_counter()
    result, retried, session = await _call_tool_with_retry(session, name, arguments, refresh_session)
    latency_ms = (time.perf_counter() - start) * 1000
    structured = result.structuredContent

    record = ToolCallRecord(
        name=name, arguments=arguments, result=structured, latency_ms=latency_ms, retried=retried
    )

    if result.isError:
        return record, {"content": [{"text": _text_of(result.content)}], "status": "error"}, True, session
    if structured is not None:
        return record, {"content": [{"json": structured}]}, False, session
    return record, {"content": [{"text": _text_of(result.content)}]}, False, session


async def run_turn(
    *,
    converse: Callable[..., dict[str, Any]],
    model_id: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tool_defs: list[ToolDef],
    session: ClientSession,
    user_message: str,
    max_rounds: int = 4,
    refresh_session: RefreshSession | None = None,
    tool_timeout_s: float | None = DEFAULT_TOOL_TIMEOUT_S,
    converse_timeout_s: float | None = DEFAULT_CONVERSE_TIMEOUT_S,
) -> TurnResult:
    """Runs one user turn to completion: possibly several rounds of
    tool_use, ending either with a plain text reply or (if max_rounds is
    exhausted) a fallback apology rather than hanging forever. `messages`
    is the session's Converse history, mutated in place so the next turn
    sees this one.

    `session` is a local variable, not just a parameter: a tool call that
    hits the "session terminated" failure (see _call_tool_with_retry) swaps
    it for a freshly-opened one via `refresh_session`, and every later
    round's tool calls -- and any read_resource card fetch -- in *this*
    turn use that new session too, never the stale reference.

    History integrity: a turn either completes and leaves its messages in
    `messages`, or leaves `messages` exactly as it found it (after repairing
    any corruption an earlier failure left, see repair_history). Every
    failure path restores it -- an exception, a timeout, asyncio.
    CancelledError (a client disconnect), and the max_rounds fallback -- so a
    turn that dies after the model's toolUse message can never leave an
    unanswered toolUse for every later turn on this session to trip over.

    Each Converse call and each tool call / resource read has its own time
    budget (`converse_timeout_s`, `tool_timeout_s`); exceeding one raises
    OperationTimeout naming the step."""
    repaired = repair_history(messages)
    if repaired:
        structlog.get_logger().warning("demo_history_repaired", dropped_tool_use_messages=repaired)
    # The snapshot is a deep copy: after a repair the new user message may be
    # merged into the history's last (user) message, which an in-place
    # truncation could not undo.
    snapshot = copy.deepcopy(messages)
    try:
        return await _run_turn_body(
            snapshot=snapshot,
            converse=converse,
            model_id=model_id,
            system_prompt=system_prompt,
            messages=messages,
            tool_defs=tool_defs,
            session=session,
            user_message=user_message,
            max_rounds=max_rounds,
            refresh_session=refresh_session,
            tool_timeout_s=tool_timeout_s,
            converse_timeout_s=converse_timeout_s,
        )
    except BaseException:
        messages[:] = snapshot
        raise


async def _run_turn_body(
    *,
    snapshot: list[dict[str, Any]],
    converse: Callable[..., dict[str, Any]],
    model_id: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tool_defs: list[ToolDef],
    session: ClientSession,
    user_message: str,
    max_rounds: int,
    refresh_session: RefreshSession | None,
    tool_timeout_s: float | None,
    converse_timeout_s: float | None,
) -> TurnResult:
    tool_config = build_tool_config(tool_defs)
    resource_uri_by_name = {tool.name: tool.resource_uri for tool in tool_defs if tool.resource_uri}

    if messages and messages[-1]["role"] == "user":
        # Only possible after repair_history dropped a dangling toolUse: the
        # API wants alternating roles, so this message joins the last one.
        messages[-1]["content"] = messages[-1]["content"] + [{"text": user_message}]
    else:
        messages.append({"role": "user", "content": [{"text": user_message}]})

    tool_calls: list[ToolCallRecord] = []
    card: CardResult | None = None
    input_tokens = 0
    output_tokens = 0

    for _ in range(max_rounds):
        kwargs: dict[str, Any] = {
            "modelId": model_id,
            "system": [{"text": system_prompt}],
            "messages": messages,
            "inferenceConfig": {"maxTokens": MAX_REPLY_TOKENS, "temperature": DEFAULT_TEMPERATURE},
        }
        if tool_config:
            kwargs["toolConfig"] = tool_config

        response = await within(converse_timeout_s, "bedrock_converse", asyncio.to_thread(converse, **kwargs))
        usage = response.get("usage", {})
        input_tokens += usage.get("inputTokens", 0)
        output_tokens += usage.get("outputTokens", 0)
        output_message = response["output"]["message"]
        messages.append(output_message)

        if response.get("stopReason") != "tool_use":
            reply_text = "".join(block["text"] for block in output_message["content"] if "text" in block)
            return TurnResult(
                reply_text=reply_text,
                tool_calls=tool_calls,
                card=card,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        result_blocks: list[dict[str, Any]] = []
        for block in output_message["content"]:
            if "toolUse" not in block:
                continue
            tool_use = block["toolUse"]
            name = tool_use["name"]
            arguments = tool_use.get("input", {})

            record, result_block, is_error, session = await within(
                tool_timeout_s,
                f"tool_call:{name}",
                _dispatch_tool_call(session, name, arguments, refresh_session),
            )
            tool_calls.append(record)
            result_blocks.append({"toolUseId": tool_use["toolUseId"], **result_block})

            if (
                card is None
                and not is_error
                and record.result is not None
                and record.result.get("status") in _CARD_STATUSES
                and resource_uri_by_name.get(name)
            ):
                resource_uri = resource_uri_by_name[name]
                read = await within(
                    tool_timeout_s, f"read_resource:{resource_uri}", session.read_resource(resource_uri)
                )
                html = read.contents[0].text if read.contents else ""
                card = CardResult(resource_uri=resource_uri, html=html)

        messages.append({"role": "user", "content": [{"toolResult": b} for b in result_blocks]})

    # The last message is the tool results, never an assistant reply: leaving
    # them would end the history on a user turn, so the next user message
    # would be a second consecutive one. Treat the exhausted turn as not
    # having happened.
    messages[:] = snapshot
    return TurnResult(
        reply_text="Sorry, I'm having trouble with that one -- could you try asking again?",
        tool_calls=tool_calls,
        card=card,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
