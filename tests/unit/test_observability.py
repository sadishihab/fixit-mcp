"""scripts/observability.py against fakes: the plan it builds (names,
scoping, dimensions, thresholds), idempotent apply, teardown, and a dry run
that makes no AWS call. No AWS."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
REPO_ROOT = SCRIPTS.parent
spec = importlib.util.spec_from_file_location("fixit_observability", SCRIPTS / "observability.py")
obs = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = obs
spec.loader.exec_module(obs)

CTX = obs.Context(
    region="us-east-1",
    account_id="111122223333",
    runtime_id="fixit_mcp-TESTID",
    memory_id="FixItH-abc",
    email="alerts@example.com",
)
RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-east-1:111122223333:runtime/fixit_mcp-TESTID"
MEMORY_ARN = "arn:aws:bedrock-agentcore:us-east-1:111122223333:memory/FixItH-abc"


class AwsError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeLogs:
    def __init__(self, retention: int | None = None, group_exists: bool = True) -> None:
        self.groups = {CTX.log_group: {"logGroupName": CTX.log_group}} if group_exists else {}
        if retention is not None and group_exists:
            self.groups[CTX.log_group]["retentionInDays"] = retention
        self.filters: dict[str, dict] = {}
        self.writes: list[str] = []

    def describe_log_groups(self, logGroupNamePrefix: str) -> dict:
        return {
            "logGroups": [
                copy.deepcopy(g) for n, g in self.groups.items() if n.startswith(logGroupNamePrefix)
            ]
        }

    def put_retention_policy(self, logGroupName: str, retentionInDays: int) -> None:
        self.writes.append("put_retention_policy")
        self.groups[logGroupName]["retentionInDays"] = retentionInDays

    def describe_metric_filters(self, logGroupName: str, filterNamePrefix: str) -> dict:
        return {
            "metricFilters": [
                copy.deepcopy(f) for n, f in self.filters.items() if n.startswith(filterNamePrefix)
            ]
        }

    def put_metric_filter(self, logGroupName: str, **kwargs: Any) -> None:
        self.writes.append(f"put_metric_filter:{kwargs['filterName']}")
        self.filters[kwargs["filterName"]] = {**copy.deepcopy(kwargs), "logGroupName": logGroupName}

    def delete_metric_filter(self, logGroupName: str, filterName: str) -> None:
        self.writes.append(f"delete_metric_filter:{filterName}")
        del self.filters[filterName]


class FakeSns:
    def __init__(self) -> None:
        self.topics: dict[str, list[dict]] = {}
        self.writes: list[str] = []

    def create_topic(self, Name: str) -> dict:
        arn = f"arn:aws:sns:us-east-1:111122223333:{Name}"
        if arn not in self.topics:
            self.writes.append("create_topic")
            self.topics[arn] = []
        return {"TopicArn": arn}

    def list_subscriptions_by_topic(self, TopicArn: str) -> dict:
        return {"Subscriptions": copy.deepcopy(self.topics[TopicArn])}

    def subscribe(self, TopicArn: str, Protocol: str, Endpoint: str) -> dict:
        self.writes.append("subscribe")
        self.topics[TopicArn].append(
            {"Protocol": Protocol, "Endpoint": Endpoint, "SubscriptionArn": "PendingConfirmation"}
        )
        return {"SubscriptionArn": "pending confirmation"}

    def delete_topic(self, TopicArn: str) -> None:
        self.writes.append("delete_topic")
        self.topics.pop(TopicArn, None)


class FakeCloudWatch:
    def __init__(self) -> None:
        self.alarms: dict[str, dict] = {}
        self.dashboards: dict[str, str] = {}
        self.writes: list[str] = []

    def describe_alarms(self, AlarmNames: list[str]) -> dict:
        # The real API adds fields of its own; idempotence must ignore them.
        return {
            "MetricAlarms": [
                {**copy.deepcopy(self.alarms[n]), "StateValue": "OK", "AlarmArn": f"arn:{n}"}
                for n in AlarmNames
                if n in self.alarms
            ]
        }

    def put_metric_alarm(self, **kwargs: Any) -> None:
        self.writes.append(f"put_metric_alarm:{kwargs['AlarmName']}")
        self.alarms[kwargs["AlarmName"]] = copy.deepcopy(kwargs)

    def delete_alarms(self, AlarmNames: list[str]) -> None:
        self.writes.append("delete_alarms")
        for n in AlarmNames:
            self.alarms.pop(n)

    def get_dashboard(self, DashboardName: str) -> dict:
        if DashboardName not in self.dashboards:
            raise AwsError("ResourceNotFound")
        return {"DashboardBody": self.dashboards[DashboardName]}

    def put_dashboard(self, DashboardName: str, DashboardBody: str) -> None:
        self.writes.append("put_dashboard")
        json.loads(DashboardBody)
        self.dashboards[DashboardName] = DashboardBody

    def delete_dashboards(self, DashboardNames: list[str]) -> None:
        for n in DashboardNames:
            if n not in self.dashboards:
                raise AwsError("ResourceNotFound")
            self.writes.append("delete_dashboards")
            del self.dashboards[n]


def _clients(**logs_kwargs: Any) -> tuple[FakeLogs, FakeSns, FakeCloudWatch]:
    return FakeLogs(**logs_kwargs), FakeSns(), FakeCloudWatch()


# --- the plan -----------------------------------------------------------------


def test_every_resource_name_is_covered_by_the_observability_policy_scoping() -> None:
    plan = obs.build_plan(CTX)

    assert plan.dashboard_name.startswith("FixIt")
    assert plan.topic_name.startswith("fixit-")
    assert all(a["AlarmName"].startswith("fixit-") for a in plan.alarms)
    assert all(f["filterName"].startswith("fixit-") for f in plan.metric_filters)
    assert plan.log_group == "/aws/bedrock-agentcore/runtimes/fixit_mcp-TESTID-DEFAULT"
    assert plan.log_group.startswith("/aws/bedrock-agentcore/runtimes/fixit_mcp-")
    assert plan.topic_arn == "arn:aws:sns:us-east-1:111122223333:fixit-alerts"


def test_the_policy_template_scopes_match_the_plan() -> None:
    policy = json.loads((REPO_ROOT / "deploy" / "iam" / "observability-policy.json").read_text())
    resources = {s["Sid"]: s["Resource"] for s in policy["Statement"]}

    assert resources["Dashboard"].endswith(":dashboard/FixIt*")
    assert resources["Alarms"].endswith(":alarm:fixit-*")
    assert resources["AlertTopic"].endswith(f":{obs.TOPIC_NAME}")
    assert resources["MetricFilters"].endswith("/aws/bedrock-agentcore/runtimes/fixit_mcp-*")


def test_exactly_the_four_planned_metric_filters() -> None:
    filters = {f["filterName"]: f for f in obs.build_plan(CTX).metric_filters}

    metrics = {n: f["metricTransformations"][0] for n, f in filters.items()}
    assert {t["metricName"] for t in metrics.values()} == {
        "ToolLatency",
        "ToolLatencyAll",
        "ToolCallFailed",
        "MemoryCallFailed",
    }
    assert all(t["metricNamespace"] == "FixIt" for t in metrics.values())
    assert metrics["fixit-tool-latency"]["dimensions"] == {"Tool": "$.tool"}
    assert metrics["fixit-tool-latency"]["metricValue"] == "$.latency_ms"
    assert "defaultValue" not in metrics["fixit-tool-latency"]  # not allowed with dimensions
    assert "dimensions" not in metrics["fixit-tool-latency-all"]
    assert filters["fixit-tool-call-failed"]["filterPattern"] == '{ $.event = "tool_call_failed" }'
    assert (
        filters["fixit-memory-call-failed"]["filterPattern"] == '{ $.event = "agentcore_memory_call_failed" }'
    )


def test_filter_patterns_match_the_event_names_the_server_actually_logs() -> None:
    src = (REPO_ROOT / "src" / "fixit_mcp").rglob("*.py")
    logged = "".join(p.read_text() for p in src)
    for f in obs.build_plan(CTX).metric_filters:
        event = f["filterPattern"].split('"')[1]
        assert f'"{event}"' in logged, f"no log line emits {event!r}"


def test_the_tool_dimension_values_are_the_servers_tools() -> None:
    from fixit_mcp.repository.in_memory import InMemoryApplianceRepository
    from fixit_mcp.server import create_server

    server = create_server(repository=InMemoryApplianceRepository())
    registered = {t.name for t in server._tool_manager.list_tools()}

    assert set(obs.TOOLS) == registered


def test_runtime_metrics_use_the_dimensions_list_metrics_returned() -> None:
    dims = obs.runtime_dimensions(CTX)

    assert dims == [
        {"Name": "Resource", "Value": RUNTIME_ARN},
        {"Name": "Operation", "Value": "InvokeAgentRuntime"},
        {"Name": "Name", "Value": "fixit_mcp::DEFAULT"},
    ]


def test_errors_alarm_sums_runtime_system_errors_and_our_failure_counts() -> None:
    errors = next(a for a in obs.build_plan(CTX).alarms if a["AlarmName"] == "fixit-errors")
    by_id = {m["Id"]: m for m in errors["Metrics"]}

    assert [m["Id"] for m in errors["Metrics"] if m["ReturnData"]] == ["total"]
    assert by_id["sys"]["MetricStat"]["Metric"]["MetricName"] == "SystemErrors"
    assert by_id["sys"]["MetricStat"]["Metric"]["Namespace"] == "AWS/Bedrock-AgentCore"
    assert by_id["tool"]["MetricStat"]["Metric"]["MetricName"] == "ToolCallFailed"
    assert by_id["mem"]["MetricStat"]["Metric"]["MetricName"] == "MemoryCallFailed"
    assert errors["Threshold"] == 1.0
    assert errors["TreatMissingData"] == "notBreaching"
    assert errors["AlarmActions"] == [CTX.topic_arn]


def test_latency_alarm_is_handler_p95_2_of_3() -> None:
    latency = next(a for a in obs.build_plan(CTX).alarms if a["AlarmName"] == "fixit-tool-latency")

    assert (latency["Namespace"], latency["MetricName"]) == ("FixIt", "ToolLatencyAll")
    assert latency["ExtendedStatistic"] == "p95"
    assert latency["Threshold"] == 300.0
    assert (latency["DatapointsToAlarm"], latency["EvaluationPeriods"]) == (2, 3)
    assert latency["AlarmActions"] == [CTX.topic_arn]


def test_dashboard_covers_the_planned_panels_and_states_the_504_gap() -> None:
    body = obs.build_plan(CTX).dashboard_body
    text = json.dumps(body)
    titles = [w["properties"].get("title", "") for w in body["widgets"]]

    assert "504" in body["widgets"][0]["properties"]["markdown"]
    assert any("Runtime errors" in t for t in titles)
    assert any("Tool handler latency" in t for t in titles)
    assert any("AgentCore Memory errors" in t for t in titles)
    for tool in obs.TOOLS:
        assert f'"Tool", "{tool}"' in text
    assert MEMORY_ARN in text and RUNTIME_ARN in text
    metric_count = sum(len(w["properties"].get("metrics", [])) for w in body["widgets"])
    assert metric_count <= 50  # the free tier's per-dashboard metric allowance


def test_retention_is_90_days() -> None:
    assert obs.build_plan(CTX).retention_days == 90


# --- apply / idempotence ------------------------------------------------------


def test_first_apply_creates_everything() -> None:
    logs, sns, cw = _clients()

    report = obs.apply(obs.build_plan(CTX), logs, sns, cw)

    assert logs.groups[CTX.log_group]["retentionInDays"] == 90
    assert set(logs.filters) == {f["filterName"] for f in obs.metric_filters()}
    assert sns.topics[CTX.topic_arn][0]["Endpoint"] == "alerts@example.com"
    assert set(cw.alarms) == {"fixit-errors", "fixit-tool-latency"}
    assert "FixIt" in cw.dashboards
    assert not any(line.startswith("unchanged") for line in report)


def test_second_apply_writes_nothing() -> None:
    logs, sns, cw = _clients()
    obs.apply(obs.build_plan(CTX), logs, sns, cw)
    logs.writes.clear(), sns.writes.clear(), cw.writes.clear()

    report = obs.apply(obs.build_plan(CTX), logs, sns, cw)

    assert logs.writes == [] and sns.writes == [] and cw.writes == []
    assert all(line.split()[0] in ("unchanged", "ensured") for line in report)


def test_apply_updates_only_what_drifted() -> None:
    logs, sns, cw = _clients()
    obs.apply(obs.build_plan(CTX), logs, sns, cw)
    logs.filters["fixit-tool-latency-all"]["filterPattern"] = "old"
    cw.alarms["fixit-tool-latency"]["Threshold"] = 999.0
    logs.writes.clear(), cw.writes.clear()

    report = obs.apply(obs.build_plan(CTX), logs, sns, cw)

    assert logs.writes == ["put_metric_filter:fixit-tool-latency-all"]
    assert cw.writes == ["put_metric_alarm:fixit-tool-latency"]
    assert "updated    metric filter fixit-tool-latency-all" in report
    assert "updated    alarm fixit-tool-latency" in report


def test_existing_retention_other_than_90_is_changed() -> None:
    logs, sns, cw = _clients(retention=30)

    report = obs.apply(obs.build_plan(CTX), logs, sns, cw)

    assert logs.groups[CTX.log_group]["retentionInDays"] == 90
    assert "set        retention 30 -> 90 days" in report


def test_missing_log_group_stops_before_creating_anything() -> None:
    logs, sns, cw = _clients(group_exists=False)

    with pytest.raises(SystemExit, match="not found"):
        obs.apply(obs.build_plan(CTX), logs, sns, cw)
    assert sns.writes == [] and cw.writes == []


def test_a_new_email_address_is_subscribed_alongside_the_old_one() -> None:
    logs, sns, cw = _clients()
    obs.apply(obs.build_plan(CTX), logs, sns, cw)

    obs.apply(obs.build_plan(obs.Context(**{**CTX.__dict__, "email": "new@example.com"})), logs, sns, cw)

    assert [s["Endpoint"] for s in sns.topics[CTX.topic_arn]] == ["alerts@example.com", "new@example.com"]


# --- teardown -----------------------------------------------------------------


def test_teardown_removes_everything_but_retention_and_is_idempotent() -> None:
    logs, sns, cw = _clients()
    obs.apply(obs.build_plan(CTX), logs, sns, cw)

    first = obs.teardown(obs.build_plan(CTX), logs, sns, cw)
    second = obs.teardown(obs.build_plan(CTX), logs, sns, cw)

    assert logs.filters == {} and sns.topics == {} and cw.alarms == {} and cw.dashboards == {}
    assert logs.groups[CTX.log_group]["retentionInDays"] == 90
    assert "deleted    dashboard FixIt" in first
    assert "absent     dashboard FixIt" in second
    assert all("deleted    alarm" not in line for line in second)


def test_an_unexpected_dashboard_error_is_not_swallowed() -> None:
    logs, sns, cw = _clients()

    def boom(DashboardName: str) -> dict:
        raise AwsError("AccessDenied")

    cw.get_dashboard = boom
    with pytest.raises(AwsError):
        obs.apply(obs.build_plan(CTX), logs, sns, cw)


# --- dry run ------------------------------------------------------------------


def test_dry_run_makes_no_aws_call_and_prints_placeholders(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import boto3

    def no_aws(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("dry run touched AWS")

    monkeypatch.setattr(boto3, "Session", no_aws)
    monkeypatch.setattr(boto3, "client", no_aws)
    monkeypatch.setenv("FIXIT_AGENTCORE_MEMORY_ID", "FixItH-secret")
    monkeypatch.setenv("FIXIT_ALERT_EMAIL", "alerts@example.com")
    monkeypatch.setattr(sys, "argv", ["observability.py", "--dry-run"])

    assert obs.main() == 0
    out = capsys.readouterr().out
    assert out.startswith("DRY RUN: no AWS calls.")
    assert "<runtime-id>" in out and "<account-id>" in out
    assert "FixItH-secret" not in out
    assert "alarm fixit-errors" in out and "dashboard FixIt" in out


def test_real_run_refuses_without_an_alert_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIXIT_AGENTCORE_MEMORY_ID", "FixItH-abc")
    monkeypatch.delenv("FIXIT_ALERT_EMAIL", raising=False)
    monkeypatch.setattr(sys, "argv", ["observability.py"])

    assert obs.main() == 2
