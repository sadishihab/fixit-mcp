"""Create, update, or tear down FixIt's CloudWatch observability (step 23c).

    uv run python scripts/observability.py --dry-run    # print the plan, touch no AWS
    FIXIT_ALERT_EMAIL=you@example.com uv run python scripts/observability.py
    uv run python scripts/observability.py --teardown

Creates exactly the step 23a plan, and nothing else:
  - four metric filters on the runtime's log group, publishing to namespace
    FixIt from our own structured log lines: ToolLatency (dimension Tool),
    ToolLatencyAll, ToolCallFailed, MemoryCallFailed
  - 90-day retention on that log group (it never expired before)
  - SNS topic fixit-alerts, with an email subscription to FIXIT_ALERT_EMAIL
  - alarms fixit-errors and fixit-tool-latency, both emailing that topic
  - dashboard FixIt

Every name starts with fixit/FixIt, which is what deploy/iam's
FixItObservability policy is scoped to. AgentCore's own metric names and
dimensions (Resource, Operation, Name) are the ones list-metrics returned
for our runtime and memory (step 23c), not guessed.

Idempotent: each resource is read first and written only if missing or
different, so a re-run reports "unchanged". The runtime is found by name,
and the account and memory ids come from STS and FIXIT_AGENTCORE_MEMORY_ID
at run time, so no id is ever written to a tracked file. --dry-run makes no
AWS call at all: ids it isn't given (--account-id, --runtime-id, the env
var) are shown as <placeholders>.

Teardown deletes the alarms, dashboard, metric filters and topic (which
removes its subscription). It leaves the log group's 90-day retention in
place: the policy doesn't grant DeleteRetentionPolicy, and "never expire" was
never a setting worth restoring.

Known gap: a 504 from AgentCore's front door for a request that never
reached the container produces no log line of ours, and isn't documented as
counting in the runtime's SystemErrors. This dashboard may not show it
(FRICTION_LOG.md, step 23c).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deploy_runtime import DEFAULT_REGION, RUNTIME_NAME, find_runtime  # noqa: E402
from smoke_test import EXPECTED_TOOLS  # noqa: E402

NAMESPACE = "FixIt"
AGENTCORE_NAMESPACE = "AWS/Bedrock-AgentCore"
DASHBOARD_NAME = "FixIt"
TOPIC_NAME = "fixit-alerts"
ERRORS_ALARM = "fixit-errors"
LATENCY_ALARM = "fixit-tool-latency"
RETENTION_DAYS = 90
ENDPOINT_NAME = "DEFAULT"
TOOLS = sorted(EXPECTED_TOOLS)
MEMORY_OPERATIONS = ["CreateEvent", "ListEvents", "DeleteEvent"]
PERIOD_S = 300
# Handler time only (our own log line), not round trip: a cold session's
# ~2s of platform time would otherwise trip it for every new conversation.
LATENCY_THRESHOLD_MS = 300


@dataclass(frozen=True)
class Context:
    region: str
    account_id: str
    runtime_id: str
    memory_id: str
    email: str

    @property
    def log_group(self) -> str:
        return f"/aws/bedrock-agentcore/runtimes/{self.runtime_id}-{ENDPOINT_NAME}"

    @property
    def runtime_arn(self) -> str:
        return f"arn:aws:bedrock-agentcore:{self.region}:{self.account_id}:runtime/{self.runtime_id}"

    @property
    def memory_arn(self) -> str:
        return f"arn:aws:bedrock-agentcore:{self.region}:{self.account_id}:memory/{self.memory_id}"

    @property
    def topic_arn(self) -> str:
        return f"arn:aws:sns:{self.region}:{self.account_id}:{TOPIC_NAME}"


@dataclass
class Plan:
    log_group: str
    retention_days: int
    metric_filters: list[dict[str, Any]]
    topic_name: str
    topic_arn: str
    email: str
    alarms: list[dict[str, Any]]
    dashboard_name: str
    dashboard_body: dict[str, Any]
    notes: list[str] = field(default_factory=list)


def _filter(name: str, event: str, metric: str, value: str, unit: str, **extra: Any) -> dict[str, Any]:
    transformation = {"metricName": metric, "metricNamespace": NAMESPACE, "metricValue": value, "unit": unit}
    transformation.update(extra)
    return {
        "filterName": name,
        "filterPattern": f'{{ $.event = "{event}" }}',
        "metricTransformations": [transformation],
    }


def metric_filters() -> list[dict[str, Any]]:
    return [
        _filter(
            "fixit-tool-latency",
            "tool_call_completed",
            "ToolLatency",
            "$.latency_ms",
            "Milliseconds",
            dimensions={"Tool": "$.tool"},
        ),
        _filter(
            "fixit-tool-latency-all", "tool_call_completed", "ToolLatencyAll", "$.latency_ms", "Milliseconds"
        ),
        # defaultValue 0 gives a continuous series while logs flow (only allowed without dimensions).
        _filter(
            "fixit-tool-call-failed", "tool_call_failed", "ToolCallFailed", "1", "Count", defaultValue=0.0
        ),
        _filter(
            "fixit-memory-call-failed",
            "agentcore_memory_call_failed",
            "MemoryCallFailed",
            "1",
            "Count",
            defaultValue=0.0,
        ),
    ]


def runtime_dimensions(ctx: Context) -> list[dict[str, str]]:
    """The runtime's metric dimensions exactly as list-metrics returned them."""
    return [
        {"Name": "Resource", "Value": ctx.runtime_arn},
        {"Name": "Operation", "Value": "InvokeAgentRuntime"},
        {"Name": "Name", "Value": f"{RUNTIME_NAME}::{ENDPOINT_NAME}"},
    ]


def _stat(namespace: str, metric: str, dims: list[dict[str, str]], stat: str) -> dict[str, Any]:
    return {
        "Metric": {"Namespace": namespace, "MetricName": metric, "Dimensions": dims},
        "Period": PERIOD_S,
        "Stat": stat,
    }


def alarms(ctx: Context) -> list[dict[str, Any]]:
    errors = {
        "AlarmName": ERRORS_ALARM,
        "AlarmDescription": (
            "FixIt: runtime SystemErrors, failed tool calls, or failed AgentCore Memory calls in "
            "the last 5 minutes. A front-door 504 that never reached the container may not count."
        ),
        "Metrics": [
            {
                "Id": "total",
                "Expression": "FILL(sys, 0) + FILL(tool, 0) + FILL(mem, 0)",
                "Label": "errors",
                "ReturnData": True,
            },
            {
                "Id": "sys",
                "MetricStat": _stat(AGENTCORE_NAMESPACE, "SystemErrors", runtime_dimensions(ctx), "Sum"),
                "ReturnData": False,
            },
            {"Id": "tool", "MetricStat": _stat(NAMESPACE, "ToolCallFailed", [], "Sum"), "ReturnData": False},
            {"Id": "mem", "MetricStat": _stat(NAMESPACE, "MemoryCallFailed", [], "Sum"), "ReturnData": False},
        ],
        "ComparisonOperator": "GreaterThanOrEqualToThreshold",
        "Threshold": 1.0,
        "EvaluationPeriods": 1,
        "DatapointsToAlarm": 1,
        "TreatMissingData": "notBreaching",
        "AlarmActions": [ctx.topic_arn],
    }
    latency = {
        "AlarmName": LATENCY_ALARM,
        "AlarmDescription": (
            f"FixIt: tool handler p95 above {LATENCY_THRESHOLD_MS} ms in 2 of 3 five-minute periods "
            "(handler time from our own log lines, not round trip)."
        ),
        "Namespace": NAMESPACE,
        "MetricName": "ToolLatencyAll",
        "ExtendedStatistic": "p95",
        "Period": PERIOD_S,
        "Unit": "Milliseconds",
        "ComparisonOperator": "GreaterThanThreshold",
        "Threshold": float(LATENCY_THRESHOLD_MS),
        "EvaluationPeriods": 3,
        "DatapointsToAlarm": 2,
        "TreatMissingData": "notBreaching",
        "AlarmActions": [ctx.topic_arn],
    }
    return [errors, latency]


def _widget(
    title: str, metrics: list[list[Any]], ctx: Context, x: int, y: int, **props: Any
) -> dict[str, Any]:
    properties = {
        "title": title,
        "region": ctx.region,
        "view": "timeSeries",
        "period": PERIOD_S,
        "metrics": metrics,
    }
    properties.update(props)
    return {"type": "metric", "x": x, "y": y, "width": 12, "height": 6, "properties": properties}


def dashboard_body(ctx: Context) -> dict[str, Any]:
    rt = [
        "Resource",
        ctx.runtime_arn,
        "Operation",
        "InvokeAgentRuntime",
        "Name",
        f"{RUNTIME_NAME}::{ENDPOINT_NAME}",
    ]
    ns = AGENTCORE_NAMESPACE
    memory_errors = (
        f'SEARCH(\'{{{ns},Operation,Resource}} Resource="{ctx.memory_arn}" '
        'MetricName=("SystemErrors" OR "UserErrors" OR "Throttles" OR "Errors")\', \'Sum\', 300)'
    )
    return {
        "widgets": [
            {
                "type": "text",
                "x": 0,
                "y": 0,
                "width": 24,
                "height": 2,
                "properties": {
                    "markdown": (
                        "## FixIt MCP on AgentCore Runtime\n"
                        "Server-side view only. A **504 from AgentCore's front door for a request that never "
                        "reached the container** leaves no log line of ours and isn't documented as a "
                        "SystemError, so it may not appear here. "
                        "Tool latency is handler time, not round trip."
                    )
                },
            },
            _widget(
                "Runtime invocations and new sessions",
                [[ns, "Invocations", *rt, {"stat": "Sum"}], [ns, "Sessions", *rt, {"stat": "Sum"}]],
                ctx,
                0,
                2,
            ),
            _widget(
                "Runtime errors (SystemErrors = 500, UserErrors = 4xx, Throttles = 429/402)",
                [
                    [ns, m, *rt, {"stat": "Sum"}]
                    for m in ("SystemErrors", "UserErrors", "Throttles", "Errors")
                ],
                ctx,
                12,
                2,
            ),
            _widget(
                "Runtime invocation latency (platform-measured)",
                [[ns, "Latency", *rt, {"stat": "p50"}], [ns, "Latency", *rt, {"stat": "p95"}]],
                ctx,
                0,
                8,
            ),
            _widget(
                "Tool handler latency p95, per tool",
                [[NAMESPACE, "ToolLatency", "Tool", tool, {"stat": "p95"}] for tool in TOOLS],
                ctx,
                12,
                8,
                annotations={"horizontal": [{"label": "alarm threshold", "value": LATENCY_THRESHOLD_MS}]},
            ),
            _widget(
                "Failed tool calls and failed AgentCore Memory calls (our logs)",
                [
                    [NAMESPACE, "ToolCallFailed", {"stat": "Sum"}],
                    [NAMESPACE, "MemoryCallFailed", {"stat": "Sum"}],
                ],
                ctx,
                0,
                14,
            ),
            _widget(
                "AgentCore Memory latency p95, per operation",
                [
                    [ns, "Latency", "Resource", ctx.memory_arn, "Operation", op, {"stat": "p95"}]
                    for op in MEMORY_OPERATIONS
                ],
                ctx,
                12,
                14,
            ),
            _widget(
                "AgentCore Memory errors and throttles (appear only once AWS has published one)",
                [[{"expression": memory_errors, "id": "memerr"}]],
                ctx,
                0,
                20,
            ),
        ]
    }


def build_plan(ctx: Context) -> Plan:
    return Plan(
        log_group=ctx.log_group,
        retention_days=RETENTION_DAYS,
        metric_filters=metric_filters(),
        topic_name=TOPIC_NAME,
        topic_arn=ctx.topic_arn,
        email=ctx.email,
        alarms=alarms(ctx),
        dashboard_name=DASHBOARD_NAME,
        dashboard_body=dashboard_body(ctx),
    )


def describe_plan(plan: Plan) -> list[str]:
    lines = [f"log group {plan.log_group}", f"  retention: {plan.retention_days} days"]
    for f in plan.metric_filters:
        t = f["metricTransformations"][0]
        dims = f" dimensions {t['dimensions']}" if t.get("dimensions") else ""
        lines.append(
            f"  metric filter {f['filterName']}: {f['filterPattern']} -> "
            f"{t['metricNamespace']}/{t['metricName']} = {t['metricValue']} ({t['unit']}){dims}"
        )
    lines.append(f"sns topic {plan.topic_name} ({plan.topic_arn})")
    lines.append(f"  email subscription: {plan.email}")
    for a in plan.alarms:
        lines.append(f"alarm {a['AlarmName']}: {a['AlarmDescription']}")
    widgets = plan.dashboard_body["widgets"]
    lines.append(f"dashboard {plan.dashboard_name}: {len(widgets)} widgets")
    for w in widgets:
        if w["type"] == "metric":
            lines.append(f"  - {w['properties']['title']}")
    return lines


# --- apply / teardown ---------------------------------------------------------


def _error_code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def _same_filter(current: dict[str, Any], desired: dict[str, Any]) -> bool:
    if current.get("filterPattern") != desired["filterPattern"]:
        return False
    have, want = current["metricTransformations"][0], desired["metricTransformations"][0]
    return all(have.get(k) == v for k, v in want.items())


def _same_alarm(current: dict[str, Any], desired: dict[str, Any]) -> bool:
    return all(current.get(k) == v for k, v in desired.items())


def apply(plan: Plan, logs: Any, sns: Any, cloudwatch: Any) -> list[str]:
    """Create or update every resource in the plan; return one status line each."""
    report = []

    groups = logs.describe_log_groups(logGroupNamePrefix=plan.log_group)["logGroups"]
    group = next((g for g in groups if g["logGroupName"] == plan.log_group), None)
    if group is None:
        raise SystemExit(f"log group {plan.log_group} not found -- is the runtime deployed?")
    if group.get("retentionInDays") == plan.retention_days:
        report.append(f"unchanged  retention {plan.retention_days} days")
    else:
        logs.put_retention_policy(logGroupName=plan.log_group, retentionInDays=plan.retention_days)
        report.append(
            f"set        retention {group.get('retentionInDays') or 'never expire'} -> "
            f"{plan.retention_days} days"
        )

    existing = {
        f["filterName"]: f
        for f in logs.describe_metric_filters(logGroupName=plan.log_group, filterNamePrefix="fixit-")[
            "metricFilters"
        ]
    }
    for desired in plan.metric_filters:
        name = desired["filterName"]
        if name in existing and _same_filter(existing[name], desired):
            report.append(f"unchanged  metric filter {name}")
            continue
        logs.put_metric_filter(logGroupName=plan.log_group, **desired)
        report.append(f"{'updated' if name in existing else 'created':<10} metric filter {name}")

    topic_arn = sns.create_topic(Name=plan.topic_name)["TopicArn"]  # idempotent by name
    report.append(f"ensured    sns topic {plan.topic_name}")
    subscriptions = sns.list_subscriptions_by_topic(TopicArn=topic_arn)["Subscriptions"]
    if any(s["Protocol"] == "email" and s["Endpoint"] == plan.email for s in subscriptions):
        report.append(f"unchanged  email subscription {plan.email}")
    else:
        sns.subscribe(TopicArn=topic_arn, Protocol="email", Endpoint=plan.email)
        report.append(f"created    email subscription {plan.email} (confirm it from the email AWS sends)")

    names = [a["AlarmName"] for a in plan.alarms]
    current_alarms = {a["AlarmName"]: a for a in cloudwatch.describe_alarms(AlarmNames=names)["MetricAlarms"]}
    for desired in plan.alarms:
        name = desired["AlarmName"]
        if name in current_alarms and _same_alarm(current_alarms[name], desired):
            report.append(f"unchanged  alarm {name}")
            continue
        cloudwatch.put_metric_alarm(**desired)
        report.append(f"{'updated' if name in current_alarms else 'created':<10} alarm {name}")

    body = json.dumps(plan.dashboard_body, sort_keys=True)
    try:
        current_body = cloudwatch.get_dashboard(DashboardName=plan.dashboard_name)["DashboardBody"]
    except Exception as exc:
        if _error_code(exc) not in (
            "ResourceNotFound",
            "ResourceNotFoundException",
            "DashboardNotFoundError",
        ):
            raise
        current_body = None
    if current_body is not None and json.loads(current_body) == plan.dashboard_body:
        report.append(f"unchanged  dashboard {plan.dashboard_name}")
    else:
        cloudwatch.put_dashboard(DashboardName=plan.dashboard_name, DashboardBody=body)
        report.append(f"{'updated' if current_body else 'created':<10} dashboard {plan.dashboard_name}")
    return report


def teardown(plan: Plan, logs: Any, sns: Any, cloudwatch: Any) -> list[str]:
    report = []
    names = [a["AlarmName"] for a in plan.alarms]
    present = [a["AlarmName"] for a in cloudwatch.describe_alarms(AlarmNames=names)["MetricAlarms"]]
    if present:
        cloudwatch.delete_alarms(AlarmNames=present)
    report += [f"{'deleted' if n in present else 'absent':<10} alarm {n}" for n in names]
    try:
        cloudwatch.delete_dashboards(DashboardNames=[plan.dashboard_name])
        report.append(f"deleted    dashboard {plan.dashboard_name}")
    except Exception as exc:
        if _error_code(exc) not in (
            "ResourceNotFound",
            "ResourceNotFoundException",
            "DashboardNotFoundError",
        ):
            raise
        report.append(f"absent     dashboard {plan.dashboard_name}")
    existing = {
        f["filterName"]
        for f in logs.describe_metric_filters(logGroupName=plan.log_group, filterNamePrefix="fixit-")[
            "metricFilters"
        ]
    }
    for f in plan.metric_filters:
        name = f["filterName"]
        if name in existing:
            logs.delete_metric_filter(logGroupName=plan.log_group, filterName=name)
        report.append(f"{'deleted' if name in existing else 'absent':<10} metric filter {name}")
    sns.delete_topic(TopicArn=plan.topic_arn)  # idempotent; removes its subscriptions
    report.append(f"deleted    sns topic {plan.topic_name} (and its subscriptions)")
    report.append(f"kept       {plan.retention_days}-day retention on the runtime log group")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print the plan; make no AWS call")
    parser.add_argument("--teardown", action="store_true", help="delete everything this script creates")
    parser.add_argument("--region", default=os.environ.get("FIXIT_AGENTCORE_REGION", DEFAULT_REGION))
    parser.add_argument("--account-id")
    parser.add_argument("--runtime-id")
    args = parser.parse_args()
    memory_id = os.environ.get("FIXIT_AGENTCORE_MEMORY_ID", "")
    email = os.environ.get("FIXIT_ALERT_EMAIL", "")

    if args.dry_run:
        ctx = Context(
            region=args.region,
            account_id=args.account_id or "<account-id>",
            runtime_id=args.runtime_id or "<runtime-id>",
            memory_id="<memory-id>" if memory_id else "<FIXIT_AGENTCORE_MEMORY_ID unset>",
            email=email or "<FIXIT_ALERT_EMAIL unset>",
        )
        verb = "delete" if args.teardown else "create or update"
        print(f"DRY RUN: no AWS calls. Would {verb}:")
        print("\n".join(describe_plan(build_plan(ctx))))
        return 0

    if not args.teardown and not memory_id:
        print("FIXIT_AGENTCORE_MEMORY_ID is not set.", file=sys.stderr)
        return 2
    if not args.teardown and not email:
        print("FIXIT_ALERT_EMAIL is not set (the address alarms email).", file=sys.stderr)
        return 2

    import boto3

    session = boto3.Session(region_name=args.region)
    account_id = args.account_id or session.client("sts").get_caller_identity()["Account"]
    runtime_id = args.runtime_id
    if not runtime_id:
        runtime = find_runtime(session.client("bedrock-agentcore-control"))
        if runtime is None:
            print(f"No runtime named {RUNTIME_NAME}; deploy it first (make deploy-runtime).", file=sys.stderr)
            return 1
        runtime_id = runtime["agentRuntimeId"]
    ctx = Context(args.region, account_id, runtime_id, memory_id, email)
    plan = build_plan(ctx)
    clients = (session.client("logs"), session.client("sns"), session.client("cloudwatch"))
    report = teardown(plan, *clients) if args.teardown else apply(plan, *clients)
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
