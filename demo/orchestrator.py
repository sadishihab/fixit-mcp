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
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession

from demo.mcp_session import ToolDef

# A tool result is worth fetching a card for when its structuredContent's
# status is one of these -- generalized rather than hardcoded to
# diagnose_error by name, so any future tool with a ui card and the same
# found/not_found/ambiguous_appliance convention gets the same behavior for
# free. Any other status (or a tool with no resourceUri at all) gets no
# card -- see demo/README.md.
_CARD_STATUSES = frozenset({"found", "not_found", "ambiguous_appliance"})

MAX_REPLY_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.3

SYSTEM_PROMPT_TEMPLATE = (
    "You are a voice assistant helping a customer with home appliances, in the "
    "style of Alexa+: short, spoken-style sentences, plain prose -- no markdown, "
    "no headers, no bullet points, nothing that only makes sense written down. "
    "You are serving household_id={household_id!r}; pass this household_id to "
    "any tool that accepts one, so it looks up the right household's appliances. "
    "Call a tool whenever you need real information about an error code or the "
    "household's appliances -- never invent a code's meaning, a cause, a repair "
    "step, a part, or a safety warning; only say what a tool actually returned. "
    "Never add your own explanation, consequence, or reasoning that a tool result "
    "didn't state -- if you want to say why something matters, only say what the "
    "tool itself said. "
    "If asked whether something is safe or dangerous, answer only from the tool "
    "result's safety_warnings: if it has none, say the manual doesn't list a "
    "specific safety warning for this code, and stop there -- an empty list means "
    "no warning was found, not that it's confirmed safe, so never say 'it's safe' "
    "or otherwise assert a safety judgment the tool didn't make. "
    "If a tool's result says the appliance is ambiguous, ask the customer which "
    "appliance they mean before guessing. If a tool finds nothing, say so "
    "plainly instead of making something up."
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


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None
    latency_ms: float


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


async def _dispatch_tool_call(
    session: ClientSession, name: str, arguments: dict[str, Any]
) -> tuple[ToolCallRecord, dict[str, Any], bool]:
    """Calls the tool, returning (record for the API response, the Bedrock
    toolResult content block, whether the result was an error)."""
    start = time.perf_counter()
    result = await session.call_tool(name, arguments)
    latency_ms = (time.perf_counter() - start) * 1000
    structured = result.structuredContent

    record = ToolCallRecord(name=name, arguments=arguments, result=structured, latency_ms=latency_ms)

    if result.isError:
        return record, {"content": [{"text": _text_of(result.content)}], "status": "error"}, True
    if structured is not None:
        return record, {"content": [{"json": structured}]}, False
    return record, {"content": [{"text": _text_of(result.content)}]}, False


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
) -> TurnResult:
    """Runs one user turn to completion: possibly several rounds of
    tool_use, ending either with a plain text reply or (if max_rounds is
    exhausted) a fallback apology rather than hanging forever. `messages`
    is the session's Converse history, mutated in place so the next turn
    sees this one."""
    tool_config = build_tool_config(tool_defs)
    resource_uri_by_name = {tool.name: tool.resource_uri for tool in tool_defs if tool.resource_uri}

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

        response = await asyncio.to_thread(converse, **kwargs)
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

            record, result_block, is_error = await _dispatch_tool_call(session, name, arguments)
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
                read = await session.read_resource(resource_uri)
                html = read.contents[0].text if read.contents else ""
                card = CardResult(resource_uri=resource_uri, html=html)

        messages.append({"role": "user", "content": [{"toolResult": b} for b in result_blocks]})

    return TurnResult(
        reply_text="Sorry, I'm having trouble with that one -- could you try asking again?",
        tool_calls=tool_calls,
        card=card,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
