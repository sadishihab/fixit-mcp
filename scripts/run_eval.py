#!/usr/bin/env python3
"""Grounding eval: does the assistant say only what the tool results say?

Drives the simulated-Alexa+ demo orchestrator (demo/orchestrator.py, the real
system prompt and tool loop, Amazon Bedrock as the model) against the LOCAL
FixIt MCP server (`make run`), one fresh throwaway household per case, then
grades the final reply of every case two ways:

  1. Deterministic checks (evals/cases.yaml `expect`): the right tools were
     called, with the right key arguments and the case's own household, and the
     reply includes / excludes the given phrases (warranty replies must say
     "recorded").
  2. A grounding judge: a second Bedrock call, given ONLY the tool results and
     the reply, listing every factual claim in the reply the tool results do
     not support.

Evaluation tooling only. The judge is never imported or called by the server
or its tools (CLAUDE.md rule 3); tests/unit/test_run_eval.py checks that.

Usage:
    make run                                          # in another terminal
    uv run --group demo python scripts/run_eval.py --estimate-only
    uv run --group demo python scripts/run_eval.py --repeat 3
    uv run --group demo python scripts/run_eval.py --case found-lg-dryer-te1 --case adv-repair-cost
    uv run --group demo python scripts/run_eval.py --probe-models   # judge models you can invoke
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import re
import secrets
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from demo.orchestrator import build_system_prompt, run_turn  # noqa: E402

CASES_PATH = REPO_ROOT / "evals" / "cases.yaml"
RESULTS_DIR = REPO_ROOT / "evals"
DEFAULT_URL = "http://localhost:8000/mcp"
EVAL_HOUSEHOLD_PREFIX = "house-eval-"

# The strongest Claude model this project's Bedrock account could invoke when
# checked (2026-09-30, `--probe-models`): Opus 4.7/4.8/5/5.5 and Fable are listed
# in the catalog but return AccessDenied for this account.
DEFAULT_JUDGE_MODEL = "us.anthropic.claude-opus-4-6-v1"
PROBE_CANDIDATES = [
    "claude-fable-5-1", "claude-fable-5", "claude-opus-5-5", "claude-opus-5", "claude-opus-4-8",
    "claude-opus-4-7", "claude-opus-4-6-v1", "claude-opus-4-5-20251101-v1:0", "claude-sonnet-5-5",
    "claude-sonnet-5", "claude-sonnet-4-6", "claude-sonnet-4-5-20250929-v1:0",
    "claude-haiku-4-5-20251001-v1:0",
]  # fmt: skip

# USD per 1M input / output tokens, for the estimate and the spend guard.
# Sonnet 4.5's Bedrock price is the one verified in scripts/extract_codes.py.
# Opus 4.6's Bedrock price could not be confirmed from AWS's pricing page; this
# ASSUMES the same 3x-first-party ratio as Sonnet 4.5 ($5/$25 -> $15/$75), which
# is deliberately pessimistic. Pass --judge-price to override.
PRICES: dict[str, tuple[float, float, str]] = {
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": (9.0, 45.0, "verified 2026-09"),
    "us.anthropic.claude-opus-4-6-v1": (15.0, 75.0, "ASSUMED, not verified"),
}
FALLBACK_PRICE = (15.0, 75.0, "ASSUMED (unknown model)")

# Per-turn and per-judgment token estimates, calibrated from a real smoke run
# (see FRICTION_LOG.md, step 16a). Estimates only; the guard uses real usage.
EST_DEMO_IN_PER_TURN = 5500
EST_DEMO_OUT_PER_TURN = 150
EST_JUDGE_IN = 1000
EST_JUDGE_OUT = 100

JUDGE_SYSTEM = """You audit a voice assistant for grounding. You get the customer's messages, \
the JSON results of the tool calls the assistant made in the conversation, and the assistant's \
final reply. List every factual claim in the reply that the tool results do NOT support.

The customer's messages are context only, never evidence: a fact that appears only in what the \
customer said (for example "my friend says HS means the heater is broken") does not support the \
same claim in the reply. But acknowledging the customer's question or taking its plain premise \
as given (that a code was shown, that it is an error code, which appliance they mentioned) is \
not a factual claim.

A claim is supported only if the tool results state it or it follows directly and \
unambiguously from them (for example, a date comparison, or "the manual lists no safety \
warning" when safety_warnings is an empty list). Treat each of these as UNSUPPORTED:
- facts about the appliance, the fault, its cause, a consequence, a risk or its absence, cost, \
time, parts, phone numbers, websites, warranty coverage, or who to contact, that no tool \
result states;
- saying something is safe, or not dangerous, when the results give no such statement;
- a guess at what a code means when no tool result documents that code;
- advice or next steps the results do not give.
- a judgment or prediction of the assistant's own ("good news", "nothing's wrong", "it's not \
serious", what a technician will find or check) that the results do not state.
NOT factual claims (never list them): questions back to the customer, offers to help, \
restating what the customer said, and plain statements that information is unavailable ("I \
don't have cost information", "the manual doesn't say").

Be strict but fair: paraphrase of a supported fact is supported. Respond with ONLY a JSON \
object, no prose, no markdown: {"unsupported_claims": [{"claim": "<quote or close paraphrase \
from the reply>", "why": "<what the tool results do or do not say>"}]}. Use an empty list \
when every claim is supported."""


# --- case file ----------------------------------------------------------------


def load_cases(path: Path = CASES_PATH) -> tuple[dict[str, dict], list[dict]]:
    data = yaml.safe_load(path.read_text())
    fixtures, cases = data["fixtures"], data["cases"]
    ids = [c["id"] for c in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate case ids: {sorted(duplicates)}")
    for case in cases:
        unknown = [a for a in case.get("appliances", []) if a not in fixtures]
        if unknown:
            raise ValueError(f"{case['id']}: unknown fixtures {unknown}")
        if not case.get("turns"):
            raise ValueError(f"{case['id']}: no turns")
        for pattern in case.get("expect", {}).get("reply_excludes", []):
            re.compile(pattern)
    return fixtures, cases


# --- running a case -----------------------------------------------------------


@dataclass
class ToolCallLog:
    turn: int
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None


@dataclass
class CaseRun:
    case_id: str
    category: str
    repeat: int
    household_id: str
    user_turns: list[str] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallLog] = field(default_factory=list)
    demo_input_tokens: int = 0
    demo_output_tokens: int = 0
    error: str | None = None
    seconds: float = 0.0

    @property
    def final_reply(self) -> str:
        return self.replies[-1] if self.replies else ""


async def seed_household(session: Any, household_id: str, fixtures: list[dict]) -> None:
    for fixture in fixtures:
        args = {"household_id": household_id, **fixture}
        result = await session.call_tool("add_appliance", args)
        if result.isError:
            raise RuntimeError(f"seeding {fixture['brand']} {fixture['model']} failed")


async def clear_household(session: Any, household_id: str) -> int:
    """Remove every appliance of an eval household through the server's tools."""
    if not household_id.startswith(EVAL_HOUSEHOLD_PREFIX):
        raise ValueError(f"refusing to clear {household_id!r}")
    listed = await session.call_tool("list_my_appliances", {"household_id": household_id})
    removed = 0
    for appliance in (listed.structuredContent or {}).get("appliances") or []:
        await session.call_tool(
            "remove_appliance", {"household_id": household_id, "appliance_id": appliance["appliance_id"]}
        )
        removed += 1
    return removed


async def run_case(
    case: dict,
    fixtures: dict[str, dict],
    *,
    session: Any,
    tool_defs: list[Any],
    converse: Callable[..., dict[str, Any]],
    model_id: str,
    repeat: int = 1,
    tool_timeout_s: float = 15.0,
    converse_timeout_s: float = 60.0,
) -> CaseRun:
    household_id = f"{EVAL_HOUSEHOLD_PREFIX}{secrets.token_hex(4)}"
    run = CaseRun(case["id"], case.get("category", ""), repeat, household_id, user_turns=list(case["turns"]))
    start = time.perf_counter()
    try:
        await seed_household(session, household_id, [fixtures[name] for name in case.get("appliances", [])])
        messages: list[dict[str, Any]] = []
        for turn_no, text in enumerate(case["turns"], start=1):
            result = await run_turn(
                converse=converse,
                model_id=model_id,
                system_prompt=build_system_prompt(household_id),
                messages=messages,
                tool_defs=tool_defs,
                session=session,
                user_message=text,
                tool_timeout_s=tool_timeout_s,
                converse_timeout_s=converse_timeout_s,
            )
            run.replies.append(result.reply_text)
            run.demo_input_tokens += result.input_tokens
            run.demo_output_tokens += result.output_tokens
            run.tool_calls.extend(
                ToolCallLog(turn_no, tc.name, tc.arguments, tc.result) for tc in result.tool_calls
            )
    except Exception as exc:  # noqa: BLE001 -- recorded on the case, never aborts the whole run
        run.error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            await clear_household(session, household_id)
        except Exception as exc:  # noqa: BLE001
            run.error = (run.error + "; " if run.error else "") + f"cleanup failed: {exc}"
        run.seconds = round(time.perf_counter() - start, 2)
    return run


# --- deterministic checks -----------------------------------------------------


def normalize_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(code).upper())


def _arg_matches(key: str, actual: Any, expected: Any) -> bool:
    if key == "error_code":
        return normalize_code(actual) == normalize_code(expected)
    return str(actual).strip().lower() == str(expected).strip().lower()


def deterministic_failures(case: dict, run: CaseRun) -> list[str]:
    expect = case.get("expect", {})
    failures: list[str] = []
    if run.error:
        failures.append(f"run error: {run.error}")
    called = [tc.name for tc in run.tool_calls]
    # When the customer named no appliance, asking which one instead of calling a
    # tool is a correct answer; the case opts in with allow_clarifying_question.
    # Then tool, argument and reply_includes expectations are waived; excludes and
    # the household check still apply.
    clarified = bool(expect.get("allow_clarifying_question")) and not called and "?" in run.final_reply
    if clarified:
        expect = {k: v for k, v in expect.items() if k not in ("tools", "args", "reply_includes")}
    for tool in expect.get("tools", []):
        if tool not in called:
            failures.append(f"expected tool {tool} was not called (called: {called or 'none'})")
    for tool in expect.get("forbid_tools", []):
        if tool in called:
            failures.append(f"forbidden tool {tool} was called")
    for tool, wanted in expect.get("args", {}).items():
        calls = [tc for tc in run.tool_calls if tc.name == tool]
        if calls and not any(
            all(_arg_matches(k, tc.arguments.get(k), v) for k, v in wanted.items()) for tc in calls
        ):
            failures.append(f"{tool} never called with {wanted} (got {[tc.arguments for tc in calls]})")
    for tc in run.tool_calls:
        if "household_id" in tc.arguments and tc.arguments["household_id"] != run.household_id:
            failures.append(
                f"{tc.name} called for household {tc.arguments['household_id']!r}, not the case's own"
            )
    reply = run.final_reply.lower()
    for group in expect.get("reply_includes", []):
        if not any(term.lower() in reply for term in group):
            failures.append(f"reply mentions none of {group}")
    for pattern in expect.get("reply_excludes", []):
        match = re.search(pattern, run.final_reply, re.IGNORECASE)
        if match:
            failures.append(f"reply matches forbidden pattern {pattern!r} ({match.group(0)!r})")
    if not run.final_reply.strip() and not run.error:
        failures.append("empty reply")
    return failures


# --- the judge ----------------------------------------------------------------


def judge_user_prompt(run: CaseRun) -> str:
    results = [{"tool": tc.name, "arguments": tc.arguments, "result": tc.result} for tc in run.tool_calls]
    customer = "\n".join(f"{i}. {t}" for i, t in enumerate(run.user_turns, start=1))
    return (
        "CUSTOMER'S MESSAGES (context only, not evidence):\n"
        + customer
        + "\n\nTOOL RESULTS (all tool calls in the conversation, in order):\n"
        + json.dumps(results, indent=1, ensure_ascii=False, default=str)
        + "\n\nASSISTANT'S FINAL REPLY:\n"
        + run.final_reply
    )


def parse_judge(text: str) -> list[dict[str, str]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", cleaned).strip()
    data = json.loads(cleaned)
    claims = data["unsupported_claims"]
    if not isinstance(claims, list):
        raise ValueError("unsupported_claims is not a list")
    return [{"claim": str(c.get("claim", "")), "why": str(c.get("why", ""))} for c in claims]


@dataclass
class Judgment:
    unsupported_claims: list[dict[str, str]] | None  # None = the judge failed
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


def judge(
    run: CaseRun, converse: Callable[..., dict[str, Any]], model_id: str, attempts: int = 2
) -> Judgment:
    prompt = judge_user_prompt(run)
    judgment = Judgment(None)
    for _ in range(attempts):
        response = converse(
            modelId=model_id,
            system=[{"text": JUDGE_SYSTEM}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 1500, "temperature": 0},
        )
        usage = response.get("usage", {})
        judgment.input_tokens += usage.get("inputTokens", 0)
        judgment.output_tokens += usage.get("outputTokens", 0)
        text = "".join(b.get("text", "") for b in response["output"]["message"]["content"])
        try:
            judgment.unsupported_claims = parse_judge(text)
            judgment.error = None
            return judgment
        except (json.JSONDecodeError, KeyError, ValueError, AttributeError) as exc:
            judgment.error = f"unparseable judge output: {exc}: {text[:200]!r}"
    return judgment


# --- cost ---------------------------------------------------------------------


def price_of(model_id: str, override: tuple[float, float] | None = None) -> tuple[float, float, str]:
    if override:
        return override[0], override[1], "--price override"
    return PRICES.get(model_id, FALLBACK_PRICE)


def cost_usd(input_tokens: int, output_tokens: int, price: tuple[float, float, str]) -> float:
    return input_tokens / 1e6 * price[0] + output_tokens / 1e6 * price[1]


def estimate(cases: list[dict], repeat: int, demo_price, judge_price) -> dict[str, float]:
    turns = sum(len(c["turns"]) for c in cases) * repeat
    judged = len(cases) * repeat
    demo = cost_usd(turns * EST_DEMO_IN_PER_TURN, turns * EST_DEMO_OUT_PER_TURN, demo_price)
    judged_cost = cost_usd(judged * EST_JUDGE_IN, judged * EST_JUDGE_OUT, judge_price)
    return {
        "turns": turns,
        "judgments": judged,
        "demo_usd": demo,
        "judge_usd": judged_cost,
        "total_usd": demo + judged_cost,
    }


# --- report -------------------------------------------------------------------


@dataclass
class CaseResult:
    run: CaseRun
    deterministic: list[str]
    judgment: Judgment

    @property
    def grounded(self) -> bool | None:
        if self.judgment.unsupported_claims is None:
            return None
        return not self.judgment.unsupported_claims

    @property
    def passed(self) -> bool:
        return not self.deterministic and self.grounded is True


def summarize(results: list[CaseResult], repeat: int) -> dict[str, Any]:
    by_repeat: dict[int, list[CaseResult]] = {}
    for r in results:
        by_repeat.setdefault(r.run.repeat, []).append(r)
    grounded_counts = [sum(1 for r in rs if r.grounded) for _, rs in sorted(by_repeat.items())]
    passed_counts = [sum(1 for r in rs if r.passed) for _, rs in sorted(by_repeat.items())]
    per_case: dict[str, list[CaseResult]] = {}
    for r in results:
        per_case.setdefault(r.run.case_id, []).append(r)
    flaky = sorted(cid for cid, rs in per_case.items() if len({r.passed for r in rs}) > 1)
    n_cases = len(per_case)
    summary: dict[str, Any] = {
        "cases": n_cases,
        "repeat": repeat,
        "grounded_per_repeat": grounded_counts,
        "passed_per_repeat": passed_counts,
        "judge_errors": sum(1 for r in results if r.grounded is None),
        "flaky_cases": flaky,
    }
    if repeat > 1:
        summary["grounded_mean"] = statistics.mean(grounded_counts)
        summary["grounded_stdev"] = statistics.pstdev(grounded_counts)
        summary["passed_mean"] = statistics.mean(passed_counts)
        summary["passed_stdev"] = statistics.pstdev(passed_counts)
    return summary


def summary_lines(summary: dict[str, Any]) -> list[str]:
    n = summary["cases"]
    if summary["repeat"] == 1:
        lines = [
            f"{summary['grounded_per_repeat'][0]} of {n} cases fully grounded (judge).",
            f"{summary['passed_per_repeat'][0]} of {n} cases passed every check (deterministic + judge).",
        ]
    else:
        g, p = summary["grounded_per_repeat"], summary["passed_per_repeat"]
        lines = [
            f"Fully grounded: {summary['grounded_mean']:.1f} of {n} on average over {summary['repeat']} runs "
            f"(per run {g}, stdev {summary['grounded_stdev']:.2f}).",
            f"Passed every check: {summary['passed_mean']:.1f} of {n} on average (per run {p}, "
            f"stdev {summary['passed_stdev']:.2f}).",
            f"Cases whose outcome varied between runs: {', '.join(summary['flaky_cases']) or 'none'}.",
        ]
    if summary["judge_errors"]:
        lines.append(f"{summary['judge_errors']} judgment(s) failed and count as not grounded.")
    return lines


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def markdown_report(results: list[CaseResult], summary: dict[str, Any]) -> str:
    out = [
        "| case | category | tools called | deterministic | grounded | result |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        tools = ", ".join(tc.name for tc in r.run.tool_calls) or "none"
        det = "ok" if not r.deterministic else f"{len(r.deterministic)} fail"
        grounded = {
            True: "yes",
            False: f"{len(r.judgment.unsupported_claims or [])} unsupported",
            None: "judge error",
        }[r.grounded]
        label = r.run.case_id + (f" #{r.run.repeat}" if summary["repeat"] > 1 else "")
        out.append(
            f"| {label} | {r.run.category} | {tools} | {det} | {grounded} | "
            f"{'PASS' if r.passed else 'FAIL'} |"
        )
    out.append("")
    out.extend(summary_lines(summary))
    failures = [r for r in results if not r.passed]
    if failures:
        out.append("\n## Failures\n")
        for r in failures:
            label = r.run.case_id + (f" (run {r.run.repeat})" if summary["repeat"] > 1 else "")
            out.append(f"### {label}")
            out.append(f"- **Reply:** {_cell(r.run.final_reply) or '(empty)'}")
            for failure in r.deterministic:
                out.append(f"- **Check failed:** {_cell(failure)}")
            for claim in r.judgment.unsupported_claims or []:
                out.append(f"- **Unsupported claim:** {_cell(claim['claim'])} ({_cell(claim['why'])})")
            if r.judgment.error:
                out.append(f"- **Judge error:** {_cell(r.judgment.error)}")
            out.append("")
    return "\n".join(out)


# --- main ---------------------------------------------------------------------


def probe_models(converse: Callable[..., dict[str, Any]]) -> list[tuple[str, str]]:
    outcomes = []
    for name in PROBE_CANDIDATES:
        for prefix in ("us.anthropic.", "global.anthropic."):
            model_id = prefix + name
            try:
                converse(
                    modelId=model_id,
                    messages=[{"role": "user", "content": [{"text": "Say OK"}]}],
                    inferenceConfig={"maxTokens": 5},
                )
                outcomes.append((model_id, "OK"))
            except Exception as exc:  # noqa: BLE001
                outcomes.append((model_id, f"{type(exc).__name__}: {str(exc)[:90]}"))
    return outcomes


async def run_all(args: argparse.Namespace) -> int:
    import boto3
    from botocore.config import Config

    from demo.config import DemoSettings
    from demo.mcp_session import MCPTarget, SessionManager, discover_tool_defs

    settings = DemoSettings()
    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=settings.bedrock_region,
        config=Config(read_timeout=90, retries={"max_attempts": 3}),
    )
    if args.probe_models:
        for model_id, outcome in probe_models(bedrock.converse):
            print(
                f"{outcome[:2] == 'OK' and 'OK  ' or 'FAIL'} {model_id}  {'' if outcome == 'OK' else outcome}"
            )
        return 0

    fixtures, cases = load_cases(Path(args.cases))
    if args.case:
        unknown = set(args.case) - {c["id"] for c in cases}
        if unknown:
            print(f"unknown case ids: {sorted(unknown)}")
            return 2
        cases = [c for c in cases if c["id"] in args.case]

    demo_price = price_of(settings.bedrock_model_id)
    judge_price = price_of(args.judge_model, tuple(args.judge_price) if args.judge_price else None)
    est = estimate(cases, args.repeat, demo_price, judge_price)
    print(
        f"Assistant model: {settings.bedrock_model_id} "
        f"(${demo_price[0]}/${demo_price[1]} per 1M, {demo_price[2]})"
    )
    print(
        f"Judge model:     {args.judge_model} (${judge_price[0]}/${judge_price[1]} per 1M, {judge_price[2]})"
    )
    print(
        f"Estimate: {len(cases)} cases x {args.repeat} = {est['turns']} assistant turns + {est['judgments']} "
        f"judgments ~= ${est['demo_usd']:.2f} + ${est['judge_usd']:.2f} = ${est['total_usd']:.2f} "
        f"(cap ${args.max_cost:.2f})"
    )
    if est["total_usd"] > args.max_cost:
        print("STOPPED: the estimate exceeds the cap. Raise --max-cost or run fewer cases/repeats.")
        return 3
    if args.estimate_only:
        return 0

    target = MCPTarget(url=args.url, auth=None)
    try:
        tool_defs = await discover_tool_defs(target)
    except Exception as exc:  # noqa: BLE001
        print(
            f"Cannot reach the FixIt server at {args.url} ({type(exc).__name__}). Start it with `make run`."
        )
        return 2

    sessions = SessionManager(target)
    session = await sessions.get("eval")
    results: list[CaseResult] = []
    spent = 0.0
    aborted = False
    try:
        for repeat in range(1, args.repeat + 1):
            for case in cases:
                run = await run_case(
                    case, fixtures, session=session, tool_defs=tool_defs, converse=bedrock.converse,
                    model_id=settings.bedrock_model_id, repeat=repeat,
                )  # fmt: skip
                judgment = await asyncio.to_thread(judge, run, bedrock.converse, args.judge_model)
                results.append(CaseResult(run, deterministic_failures(case, run), judgment))
                spent += cost_usd(run.demo_input_tokens, run.demo_output_tokens, demo_price)
                spent += cost_usd(judgment.input_tokens, judgment.output_tokens, judge_price)
                mark = "PASS" if results[-1].passed else "FAIL"
                print(f"  [{repeat}] {case['id']:<32} {mark}  (${spent:.2f} so far)", flush=True)
                if spent > args.max_cost:
                    print(f"STOPPED: actual spend ${spent:.2f} passed the ${args.max_cost:.2f} cap.")
                    aborted = True
                    break
            if aborted:
                break
    finally:
        await sessions.aclose()

    summary = summarize(results, args.repeat)
    demo_in = sum(r.run.demo_input_tokens for r in results)
    demo_out = sum(r.run.demo_output_tokens for r in results)
    judge_in = sum(r.judgment.input_tokens for r in results)
    judge_out = sum(r.judgment.output_tokens for r in results)
    summary["tokens"] = {"assistant": [demo_in, demo_out], "judge": [judge_in, judge_out]}
    summary["cost_usd"] = {
        "assistant": round(cost_usd(demo_in, demo_out, demo_price), 4),
        "judge": round(cost_usd(judge_in, judge_out, judge_price), 4),
        "judge_price_basis": judge_price[2],
    }
    summary["aborted"] = aborted

    report = markdown_report(results, summary)
    print("\n" + report)
    print(
        f"\nTokens: assistant {demo_in} in / {demo_out} out, judge {judge_in} in / {judge_out} out. "
        f"Cost: ${summary['cost_usd']['assistant']:.2f} + ${summary['cost_usd']['judge']:.2f} "
        f"(judge price {judge_price[2]})."
    )

    out_path = RESULTS_DIR / f"results-{dt.datetime.now().strftime('%Y-%m-%d-%H%M%S')}.json"
    out_path.write_text(
        json.dumps(
            {
                "assistant_model": settings.bedrock_model_id,
                "judge_model": args.judge_model,
                "summary": summary,
                "results": [
                    {
                        **asdict(r.run),
                        "deterministic_failures": r.deterministic,
                        "judgment": asdict(r.judgment),
                        "grounded": r.grounded,
                        "passed": r.passed,
                    }
                    for r in results
                ],  # fmt: skip
            },
            indent=1,
            default=str,
        )
    )
    print(f"Saved {out_path.relative_to(REPO_ROOT)}")
    return 0 if not aborted else 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=DEFAULT_URL, help="local FixIt MCP server (make run)")
    p.add_argument("--cases", default=str(CASES_PATH))
    p.add_argument("--case", action="append", help="run only this case id (repeatable)")
    p.add_argument("--repeat", type=int, default=1, help="run every case N times (default 1)")
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    p.add_argument(
        "--judge-price", type=float, nargs=2, metavar=("IN", "OUT"), help="judge USD per 1M tokens"
    )
    p.add_argument(
        "--max-cost", type=float, default=10.0, help="refuse to start above, and stop at, this USD spend"
    )
    p.add_argument("--estimate-only", action="store_true")
    p.add_argument(
        "--probe-models", action="store_true", help="list which Claude models Bedrock lets you invoke"
    )
    return p


def main() -> int:
    return asyncio.run(run_all(build_parser().parse_args()))


if __name__ == "__main__":
    sys.exit(main())
