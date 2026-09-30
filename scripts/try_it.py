"""A readable walkthrough of FixIt's tools against a running local server.
Needs no AWS account: the local server uses the SQLite backend and the
committed error-code index.

    make run      # terminal 1
    make try-it   # terminal 2  (= uv run python scripts/try_it.py)

Starts nothing itself. It connects over MCP (the same client code as
scripts/smoke_test.py), lists the tools, and makes four read-only calls for
the seeded demo household house-002 (a GE washer and an LG dryer): a code the
household's dryer documents, the dryer's warranty, a code documented for an
appliance the household doesn't own, and a code no manual documents.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import textwrap
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession

sys.path.insert(0, str(Path(__file__).resolve().parent))

from smoke_test import DEFAULT_URL, _wait_until_up, _with_session  # noqa: E402

HOUSEHOLD_ID = "house-002"
WIDTH = 78

# (heading, tool name, arguments). All read-only, so running this against a
# server with real data changes nothing.
STEPS: list[tuple[str, str, dict[str, str]]] = [
    (
        "Diagnose tE1 on house-002's LG dryer",
        "diagnose_error",
        {"error_code": "tE1", "household_id": HOUSEHOLD_ID},
    ),
    (
        "Is house-002's dryer still under warranty?",
        "check_warranty",
        {"household_id": HOUSEHOLD_ID, "appliance_type": "dryer"},
    ),
    (
        "Diagnose IE: documented for an LG washer house-002 hasn't registered",
        "diagnose_error",
        {"error_code": "IE", "household_id": HOUSEHOLD_ID},
    ),
    (
        "Diagnose ZZ99: a code no manual documents",
        "diagnose_error",
        {"error_code": "ZZ99", "household_id": HOUSEHOLD_ID},
    ),
]


def _wrap(text: str, indent: str = "    ") -> str:
    return textwrap.fill(text, WIDTH, initial_indent=indent, subsequent_indent=indent)


def _bullets(label: str, items: list[str], numbered: bool = False) -> list[str]:
    if not items:
        return []
    lines = [f"  {label}:"]
    for i, item in enumerate(items, 1):
        marker = f"{i}." if numbered else "-"
        lines.append(
            textwrap.fill(
                item, WIDTH, initial_indent=f"    {marker} ", subsequent_indent=" " * (len(marker) + 5)
            )
        )
    return lines


def _appliance(appliance: dict[str, Any] | None) -> str:
    if not appliance:
        return "(none)"
    return f"{appliance['brand']} {appliance['model']} ({appliance['appliance_type']})"


def format_heading(number: int, title: str, call: str) -> str:
    return f"\n{number}. {title}\n   > {call}"


def format_call(tool: str, arguments: dict[str, str]) -> str:
    args = ", ".join(f'{k}="{v}"' for k, v in arguments.items())
    return f"{tool}({args})"


def format_tools(tools: list[tuple[str, str]]) -> str:
    """One line per tool: its name and the first sentence of its description."""
    lines = []
    for name, description in tools:
        first = " ".join((description or "").split()).split(". ")[0].rstrip(".")
        prefix = f"  {name:<20} "
        lines.append(prefix + textwrap.shorten(first, WIDTH - len(prefix), placeholder="..."))
    return "\n".join(lines)


def format_diagnosis(result: dict[str, Any]) -> str:
    status = result.get("status")
    lines = [f"  status: {status}"]
    if status == "found":
        registered = result.get("appliance_registered")
        owner = {True: "registered to this household", False: "NOT registered to this household"}.get(
            registered, "no household given"
        )
        lines.append(f"  appliance: {_appliance(result.get('appliance'))}, {owner}")
        lines.append(f"  meaning: {result.get('meaning') or '(the manual does not say)'}")
        lines += _bullets("likely causes", result.get("likely_causes", []))
        lines += _bullets("repair steps", result.get("repair_steps", []), numbered=True)
        lines += _bullets("parts", result.get("parts_needed", []))
        lines += _bullets("safety warnings", result.get("safety_warnings", []))
        citation = result.get("citation")
        if citation:
            section = f', section "{citation["section"]}"' if citation.get("section") else ""
            lines.append(
                f"  source: {citation['brand']} {citation['model']} manual, page {citation['page']}{section}"
            )
        if result.get("suggest_add_appliance"):
            lines.append("  suggest_add_appliance: true (the assistant should offer to register it)")
    elif status == "ambiguous_appliance":
        lines.append(_wrap(result.get("message", ""), "  message: "))
        lines += _bullets("candidates", [_appliance(a) for a in result.get("candidate_appliances", [])])
    else:
        lines.append(
            textwrap.fill(
                result.get("message", ""), WIDTH, initial_indent="  message: ", subsequent_indent="    "
            )
        )
        nearest = result.get("nearest_matches", [])
        lines.append(f"  nearest codes: {', '.join(nearest) if nearest else '(none close enough)'}")
        if result.get("family_note"):
            lines.append(_wrap(result["family_note"], "  family note: "))
        if result.get("suggest_add_appliance"):
            lines.append("  suggest_add_appliance: true")
        lines.append("  Nothing is made up: an unknown code gets no meaning, causes or steps.")
    return "\n".join(lines)


def format_warranty(result: dict[str, Any]) -> str:
    status = result.get("status")
    lines = [f"  status: {status}"]
    if result.get("appliance"):
        lines.append(f"  appliance: {_appliance(result['appliance'])}")
    for field in ("purchase_date", "warranty_end_date", "days_remaining", "days_since_expiry"):
        if result.get(field) is not None:
            lines.append(f"  {field}: {result[field]}")
    lines += _bullets("candidates", [_appliance(a) for a in result.get("candidate_appliances", [])])
    lines.append(
        textwrap.fill(
            result.get("message", ""), WIDTH, initial_indent="  message: ", subsequent_indent="    "
        )
    )
    lines.append("  (A date comparison against what the customer registered; never a coverage claim.)")
    return "\n".join(lines)


def format_result(tool: str, result: dict[str, Any]) -> str:
    return format_warranty(result) if tool == "check_warranty" else format_diagnosis(result)


async def walkthrough(session: ClientSession) -> list[str]:
    """Run every step on an open session; return the printable sections."""
    init = await session.initialize()
    sections = [
        f"Connected: {init.serverInfo.name}, MCP protocol {init.protocolVersion}",
        "\nTools the server offers:",
        format_tools([(t.name, t.description or "") for t in (await session.list_tools()).tools]),
    ]
    for number, (title, tool, arguments) in enumerate(STEPS, 1):
        sections.append(format_heading(number, title, format_call(tool, arguments)))
        result = await session.call_tool(tool, arguments)
        if result.isError:
            text = " ".join(getattr(c, "text", "") for c in result.content)
            sections.append(f"  tool error: {text}")
            continue
        sections.append(format_result(tool, result.structuredContent or {}))
    return sections


async def _main(url: str, wait_s: float) -> int:
    try:
        await _wait_until_up(url, wait_s)
    except httpx.TransportError:
        print(f"No FixIt server at {url}. Start one first with `make run` in another terminal.")
        return 1
    sections: list[str] = []

    async def body(session: ClientSession) -> None:
        sections.extend(await walkthrough(session))

    await _with_session(url, body)
    print("\n".join(sections))
    print("\nThat's FixIt: structured, cited answers for an assistant to speak, and no guessing.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--wait", type=float, default=5, help="seconds to wait for the server to answer")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.url, args.wait)))
