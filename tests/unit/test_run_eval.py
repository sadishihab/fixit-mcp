"""scripts/run_eval.py's logic with fakes: case loading, the per-case run
(seed, turns through the real orchestrator, cleanup), deterministic checks,
the judge's parsing and retry, cost, and the summary. No AWS, no server."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import types

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
REPO_ROOT = SCRIPTS.parent
spec = importlib.util.spec_from_file_location("fixit_run_eval", SCRIPTS / "run_eval.py")
ev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ev
spec.loader.exec_module(ev)

from demo.mcp_session import ToolDef  # noqa: E402

DIAGNOSE = ToolDef(name="diagnose_error", description="d", input_schema={"type": "object"}, resource_uri=None)


class FakeMcp:
    def __init__(self, diagnose_result: dict | None = None) -> None:
        self.households: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, dict]] = []
        self.diagnose_result = diagnose_result or {"status": "found", "meaning": "Temperature sensor failure"}
        self._n = 0

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        self.calls.append((name, dict(arguments)))
        hh = self.households.setdefault(arguments.get("household_id", ""), [])
        if name == "add_appliance":
            self._n += 1
            hh.append({"appliance_id": f"app-{self._n}", "brand": arguments["brand"]})
            data: dict = {"appliance": {"appliance_id": f"app-{self._n}"}}
        elif name == "list_my_appliances":
            data = {"appliances": list(hh)}
        elif name == "remove_appliance":
            hh[:] = [a for a in hh if a["appliance_id"] != arguments["appliance_id"]]
            data = {"removed": True}
        else:
            data = self.diagnose_result
        return types.CallToolResult(content=[], structuredContent=data, isError=False)

    async def read_resource(self, uri: str) -> types.ReadResourceResult:
        return types.ReadResourceResult(contents=[types.TextResourceContents(uri=uri, text="<html/>")])


def tool_use(code: str = "tE1", household: str | None = None) -> dict:
    args = {"error_code": code}
    return {
        "output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "t1", "name": "diagnose_error", "input": args}}]}},
        "stopReason": "tool_use",
        "usage": {"inputTokens": 100, "outputTokens": 10},
    }  # fmt: skip


def text(reply: str) -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": reply}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 200, "outputTokens": 20},
    }


class Script:
    """A fake Converse: returns the given responses in order, and lets a
    tool_use response pick up the household id from the system prompt."""

    def __init__(self, *responses: dict) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        response = json.loads(json.dumps(self.responses.pop(0)))
        match = re.search(r"household_id='([^']+)'", kwargs.get("system", [{}])[0].get("text", ""))
        for block in response["output"]["message"]["content"]:
            if "toolUse" in block and match:
                block["toolUse"]["input"].setdefault("household_id", match.group(1))
        return response


FIXTURES = {"lg_dryer": {"brand": "LG", "model": "DLEX8000W", "appliance_type": "dryer"}}


def case(**overrides) -> dict:
    base = {
        "id": "c1",
        "category": "found",
        "appliances": ["lg_dryer"],
        "turns": ["My dryer shows tE1."],
        "expect": {"tools": ["diagnose_error"], "args": {"diagnose_error": {"error_code": "TE-1"}}},
    }
    base.update(overrides)
    return base


async def run(c: dict, converse, mcp: FakeMcp | None = None):
    mcp = mcp or FakeMcp()
    result = await ev.run_case(
        c, FIXTURES, session=mcp, tool_defs=[DIAGNOSE], converse=converse, model_id="m"
    )
    return result, mcp


# --- the case file ---------------------


def test_the_real_case_file_loads_and_covers_every_category() -> None:
    fixtures, cases = ev.load_cases()
    assert 55 <= len(cases) <= 70
    categories = {c["category"] for c in cases}
    assert {
        "found",
        "safety_empty",
        "not_found",
        "ambiguous",
        "warranty",
        "appliances",
        "adversarial",
    } <= categories
    found_manuals = {fixtures[c["appliances"][0]]["model"] for c in cases if c["category"] == "found"}
    assert {"DLEX8000W", "SHE53B75UC", "WM4000HWA", "DVE45T6000W"} <= found_manuals
    assert all(["recorded"] in c["expect"].get("reply_includes", []) or c["id"] in {
        "warranty-unknown", "warranty-ambiguous", "warranty-not-found"}
        for c in cases if c["category"] == "warranty")  # fmt: skip


def test_bad_case_files_are_rejected(tmp_path) -> None:
    bad = tmp_path / "c.yaml"
    bad.write_text("fixtures: {}\ncases:\n- {id: a, turns: [x], appliances: [nope]}\n")
    with pytest.raises(ValueError, match="unknown fixtures"):
        ev.load_cases(bad)
    bad.write_text("fixtures: {}\ncases:\n- {id: a, turns: [x]}\n- {id: a, turns: [y]}\n")
    with pytest.raises(ValueError, match="duplicate"):
        ev.load_cases(bad)


# --- running a case ---------------------


async def test_a_case_seeds_a_fresh_household_runs_the_turns_records_everything_and_cleans_up() -> None:
    result, mcp = await run(case(), Script(tool_use(), text("tE1 means temperature sensor failure.")))
    assert result.household_id.startswith("house-eval-")
    assert result.final_reply == "tE1 means temperature sensor failure."
    assert [tc.name for tc in result.tool_calls] == ["diagnose_error"]
    assert result.tool_calls[0].result == {"status": "found", "meaning": "Temperature sensor failure"}
    assert (result.demo_input_tokens, result.demo_output_tokens) == (300, 30)
    assert mcp.calls[0][0] == "add_appliance" and mcp.calls[0][1]["household_id"] == result.household_id
    assert mcp.households[result.household_id] == []  # cleaned up
    assert result.error is None


async def test_each_case_gets_a_different_household() -> None:
    a, _ = await run(case(), Script(tool_use(), text("x")))
    b, _ = await run(case(), Script(tool_use(), text("x")))
    assert a.household_id != b.household_id


async def test_a_failing_turn_is_recorded_and_the_household_is_still_cleaned_up() -> None:
    def broken(**kwargs):
        raise RuntimeError("bedrock down")

    result, mcp = await run(case(), broken)
    assert "bedrock down" in result.error
    assert mcp.households[result.household_id] == []
    assert any("run error" in f for f in ev.deterministic_failures(case(), result))


async def test_clearing_refuses_a_non_eval_household() -> None:
    with pytest.raises(ValueError):
        await ev.clear_household(FakeMcp(), "house-002")


# --- deterministic checks ---------------------


async def test_the_right_tool_and_normalized_arguments_pass() -> None:
    result, _ = await run(case(), Script(tool_use("tE1"), text("Temperature sensor failure.")))
    assert ev.deterministic_failures(case(), result) == []


async def test_a_missing_tool_a_wrong_argument_and_a_wrong_household_fail() -> None:
    result, _ = await run(case(), Script(text("No idea.")))
    assert any("was not called" in f for f in ev.deterministic_failures(case(), result))

    result, _ = await run(case(), Script(tool_use("tE2"), text("x")))
    assert any("never called with" in f for f in ev.deterministic_failures(case(), result))

    result, _ = await run(case(), Script(tool_use("tE1"), text("x")))
    result.tool_calls[0].arguments["household_id"] = "house-002"
    assert any("not the case's own" in f for f in ev.deterministic_failures(case(), result))


async def test_reply_includes_and_excludes() -> None:
    c = case(expect={"reply_includes": [["recorded"]], "reply_excludes": [r"\$\s?\d"]})
    result, _ = await run(c, Script(text("It will cost $120.")))
    failures = ev.deterministic_failures(c, result)
    assert any("none of ['recorded']" in f for f in failures)
    assert any("forbidden pattern" in f and "'$1'" in f for f in failures)

    result, _ = await run(c, Script(text("The recorded warranty ended on 2025-01-15.")))
    assert ev.deterministic_failures(c, result) == []


async def test_a_clarifying_question_waives_tool_expectations_only_when_the_case_allows_it() -> None:
    c = case(expect={"tools": ["diagnose_error"], "reply_includes": [["humidity"]],
                     "reply_excludes": ["^\\W*yes\\b"], "allow_clarifying_question": True})  # fmt: skip
    asked, _ = await run(c, Script(text("Which appliance is showing HS?")))
    assert ev.deterministic_failures(c, asked) == []

    agreed, _ = await run(c, Script(text("Yes, which appliance is it?")))
    assert any("forbidden pattern" in f for f in ev.deterministic_failures(c, agreed))

    statement, _ = await run(c, Script(text("HS is a heater fault.")))  # no tool, no question
    assert any("was not called" in f for f in ev.deterministic_failures(c, statement))

    strict = case(expect={"tools": ["diagnose_error"]})
    asked, _ = await run(strict, Script(text("Which appliance?")))
    assert any("was not called" in f for f in ev.deterministic_failures(strict, asked))


def test_the_safety_pattern_catches_a_safety_claim_but_not_a_refusal_to_make_one() -> None:
    pattern = r"(?<!whether )(?<!if )\bit'?s (perfectly |completely )?safe\b"
    assert re.search(pattern, "Yes, it's safe to use.", re.I)
    assert not re.search(pattern, "I can't say whether it's safe.", re.I)


# --- the judge ---------------------


async def test_the_judge_sees_the_customers_messages_the_tool_results_and_the_reply() -> None:
    c = case(turns=["My dryer shows tE1, and my name is Secret Sam."])
    result, _ = await run(c, Script(tool_use(), text("Temperature sensor failure.")))
    prompt = ev.judge_user_prompt(result)
    assert "Temperature sensor failure" in prompt and '"diagnose_error"' in prompt
    assert "CUSTOMER'S MESSAGES (context only, not evidence)" in prompt
    assert "1. My dryer shows tE1, and my name is Secret Sam." in prompt
    assert "never evidence" in ev.JUDGE_SYSTEM


def test_the_judge_output_is_parsed_including_a_fenced_block() -> None:
    assert ev.parse_judge('{"unsupported_claims": []}') == []
    fenced = '```json\n{"unsupported_claims": [{"claim": "It is safe", "why": "no warning stated"}]}\n```'
    assert ev.parse_judge(fenced) == [{"claim": "It is safe", "why": "no warning stated"}]


def judge_response(textual: str) -> dict:
    return {
        "output": {"message": {"content": [{"text": textual}]}},
        "usage": {"inputTokens": 50, "outputTokens": 5},
    }


async def test_the_judge_retries_once_on_malformed_output_then_reports_an_error() -> None:
    result, _ = await run(case(), Script(tool_use(), text("x")))
    calls: list[dict] = []

    def once_bad(**kwargs):
        calls.append(kwargs)
        return judge_response("not json" if len(calls) == 1 else '{"unsupported_claims": []}')

    ok = ev.judge(result, once_bad, "judge-model")
    assert ok.unsupported_claims == [] and ok.error is None and len(calls) == 2
    assert (ok.input_tokens, ok.output_tokens) == (100, 10)
    assert calls[0]["modelId"] == "judge-model" and calls[0]["inferenceConfig"]["temperature"] == 0

    bad = ev.judge(result, lambda **k: judge_response("nope"), "judge-model")
    assert bad.unsupported_claims is None and "unparseable" in bad.error


# --- cost, summary, report ---------------------


def test_cost_and_estimate() -> None:
    price = (10.0, 50.0, "x")
    assert ev.cost_usd(1_000_000, 100_000, price) == pytest.approx(15.0)
    est = ev.estimate([case(), case(turns=["a", "b"])], 2, price, price)
    assert est["turns"] == 6 and est["judgments"] == 4 and est["total_usd"] > 0
    assert ev.price_of("unknown")[2].startswith("ASSUMED")
    assert ev.price_of("x", (1.0, 2.0))[:2] == (1.0, 2.0)


def result_of(case_id: str, repeat: int, passed: bool, grounded: bool | None = True) -> Any:
    r = ev.CaseRun(case_id, "found", repeat, "house-eval-x", replies=["reply"])
    claims = None if grounded is None else ([] if grounded else [{"claim": "It's safe", "why": "not stated"}])
    return ev.CaseResult(r, [] if passed else ["reply mentions none of ['x']"], ev.Judgment(claims))


def test_summary_single_run() -> None:
    results = [
        result_of("a", 1, True),
        result_of("b", 1, True, grounded=False),
        result_of("c", 1, True, None),
    ]
    summary = ev.summarize(results, 1)
    lines = ev.summary_lines(summary)
    assert lines[0] == "1 of 3 cases fully grounded (judge)."
    assert "1 judgment(s) failed" in lines[-1]


def test_summary_with_repeats_reports_variance_and_flaky_cases() -> None:
    results = [
        result_of("a", 1, True), result_of("b", 1, True),
        result_of("a", 2, True), result_of("b", 2, True, grounded=False),
    ]  # fmt: skip
    summary = ev.summarize(results, 2)
    assert summary["grounded_per_repeat"] == [2, 1]
    assert summary["grounded_mean"] == 1.5 and summary["grounded_stdev"] == 0.5
    assert summary["flaky_cases"] == ["b"]
    assert "varied between runs: b" in "\n".join(ev.summary_lines(summary))


def test_the_report_shows_every_failure_with_its_reply_and_claim() -> None:
    results = [result_of("a", 1, True), result_of("b", 1, False, grounded=False)]
    report = ev.markdown_report(results, ev.summarize(results, 1))
    assert "| b | found | none | 1 fail | 1 unsupported | FAIL |" in report
    assert "**Reply:** reply" in report and "**Unsupported claim:** It's safe" in report


# --- the judge is evaluation tooling only ---------------------


def test_the_server_never_imports_the_eval_or_its_judge() -> None:
    for path in (REPO_ROOT / "src").rglob("*.py"):
        source = path.read_text()
        assert "run_eval" not in source and "JUDGE_SYSTEM" not in source, path
