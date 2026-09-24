"""scripts/deploy_runtime.py, push_image.py, render_iam_policies.py and
measure_runtime_latency.py -- against fakes, no AWS."""

import base64
import copy
import importlib.util
import itertools
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
REPO_ROOT = SCRIPTS.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"fixit_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve annotations via sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


deploy_runtime = _load("deploy_runtime")
push_image = _load("push_image")
render_iam = _load("render_iam_policies")
latency = _load("measure_runtime_latency")

TARGET = deploy_runtime.DeployTarget(
    account_id="111122223333", region="us-east-1", memory_id="FixItH-abcdefghij"
)
IMAGE = f"{TARGET.repository_uri}@sha256:{'a' * 64}"


class FakeControl:
    """bedrock-agentcore-control stand-in: asynchronous status transitions
    (CREATING/UPDATING -> READY after `settle` polls, DELETING -> gone)."""

    def __init__(self, settle: int = 2, fail_with: str | None = None) -> None:
        self.settle = settle
        self.fail_with = fail_with
        self.runtimes: dict[str, dict] = {}
        self.pending: dict[str, int] = {}
        self.calls: list[str] = []
        self._ids = itertools.count(1)

    def list_agent_runtimes(self, **kwargs):
        self.calls.append("list")
        for runtime_id in [i for i, r in self.runtimes.items() if r["status"] == "DELETING"]:
            if self._tick(runtime_id):
                del self.runtimes[runtime_id]
        return {
            "agentRuntimes": [
                {k: r[k] for k in ("agentRuntimeName", "agentRuntimeId", "agentRuntimeArn", "status")}
                for r in self.runtimes.values()
            ]
        }

    def create_agent_runtime(self, agentRuntimeName, **config):
        self.calls.append("create")
        runtime_id = f"{agentRuntimeName}-{next(self._ids):010d}"
        self.runtimes[runtime_id] = {
            "agentRuntimeName": agentRuntimeName,
            "agentRuntimeId": runtime_id,
            "agentRuntimeArn": f"arn:aws:bedrock-agentcore:us-east-1:111122223333:runtime/{runtime_id}",
            "agentRuntimeVersion": "1",
            "status": "CREATING",
            **copy.deepcopy(config),
        }
        self.pending[runtime_id] = self.settle
        return {"agentRuntimeId": runtime_id, "status": "CREATING"}

    def update_agent_runtime(self, agentRuntimeId, **config):
        self.calls.append("update")
        runtime = self.runtimes[agentRuntimeId]
        runtime.update(copy.deepcopy(config))
        runtime["agentRuntimeVersion"] = str(int(runtime["agentRuntimeVersion"]) + 1)
        runtime["status"] = "UPDATING"
        self.pending[agentRuntimeId] = self.settle
        return {"agentRuntimeId": agentRuntimeId, "status": "UPDATING"}

    def get_agent_runtime(self, agentRuntimeId):
        self.calls.append("get")
        runtime = self.runtimes[agentRuntimeId]
        if runtime["status"] in ("CREATING", "UPDATING") and self._tick(agentRuntimeId):
            runtime["status"] = self.fail_with or "READY"
            if self.fail_with:
                runtime["failureReason"] = "image pull failed"
        return copy.deepcopy(runtime)

    def delete_agent_runtime(self, agentRuntimeId):
        self.calls.append("delete")
        self.runtimes[agentRuntimeId]["status"] = "DELETING"
        self.pending[agentRuntimeId] = self.settle
        return {"status": "DELETING"}

    def _tick(self, runtime_id: str) -> bool:
        self.pending[runtime_id] -= 1
        return self.pending[runtime_id] <= 0


def no_sleep(_seconds: float) -> None:
    pass


def desired(image: str = IMAGE) -> dict:
    return deploy_runtime.desired_config(TARGET, image)


# --- deploy_runtime: configuration -------------------------------------------------


def test_desired_config_is_the_agreed_deployed_configuration() -> None:
    config = desired()

    assert config["agentRuntimeArtifact"] == {"containerConfiguration": {"containerUri": IMAGE}}
    assert config["roleArn"] == "arn:aws:iam::111122223333:role/FixItAgentCoreRuntimeRole"
    assert config["protocolConfiguration"] == {"serverProtocol": "MCP"}
    assert config["networkConfiguration"] == {"networkMode": "PUBLIC"}
    assert config["environmentVariables"]["FIXIT_REPOSITORY_BACKEND"] == "agentcore"
    assert config["environmentVariables"]["FIXIT_AGENTCORE_MEMORY_ID"] == "FixItH-abcdefghij"
    # IAM (SigV4) inbound auth == no authorizerConfiguration at all.
    assert "authorizerConfiguration" not in config


def test_image_is_pinned_by_digest_not_tag() -> None:
    class FakeEcr:
        def describe_images(self, repositoryName, imageIds):
            assert imageIds == [{"imageTag": "latest"}]
            return {"imageDetails": [{"imageDigest": "sha256:" + "b" * 64}]}

    uri = deploy_runtime.resolve_image_digest_uri(FakeEcr(), TARGET)

    assert uri == f"111122223333.dkr.ecr.us-east-1.amazonaws.com/fixit-mcp@sha256:{'b' * 64}"


def test_missing_image_fails_with_a_pointer_to_docker_push() -> None:
    class FakeEcr:
        def describe_images(self, **kwargs):
            raise RuntimeError("ImageNotFoundException")

    with pytest.raises(deploy_runtime.DeployError, match="make docker-push"):
        deploy_runtime.resolve_image_digest_uri(FakeEcr(), TARGET)


def test_config_with_any_authorizer_never_matches() -> None:
    current = {**desired(), "authorizerConfiguration": {"customJWTAuthorizer": {"discoveryUrl": "x"}}}

    assert deploy_runtime.config_matches(current, desired()) is False


# --- deploy_runtime: idempotent deploy -------------------------------------------------


def test_first_deploy_creates_and_waits_until_ready() -> None:
    control = FakeControl()

    action, runtime = deploy_runtime.deploy(control, desired(), sleep=no_sleep)

    assert action == "created"
    assert runtime["status"] == "READY"
    assert runtime["agentRuntimeName"] == "fixit_mcp"


def test_redeploying_the_same_config_is_a_no_op() -> None:
    control = FakeControl()
    deploy_runtime.deploy(control, desired(), sleep=no_sleep)
    control.calls.clear()

    action, runtime = deploy_runtime.deploy(control, desired(), sleep=no_sleep)

    assert action == "unchanged"
    assert "update" not in control.calls and "create" not in control.calls
    assert runtime["agentRuntimeVersion"] == "1"


def test_a_new_image_digest_updates_the_existing_runtime() -> None:
    control = FakeControl()
    deploy_runtime.deploy(control, desired(), sleep=no_sleep)
    new_image = f"{TARGET.repository_uri}@sha256:{'c' * 64}"

    action, runtime = deploy_runtime.deploy(control, desired(new_image), sleep=no_sleep)

    assert action == "updated"
    assert runtime["agentRuntimeVersion"] == "2"
    assert runtime["agentRuntimeArtifact"]["containerConfiguration"]["containerUri"] == new_image
    assert len(control.runtimes) == 1


def test_failed_create_raises_with_the_failure_reason() -> None:
    control = FakeControl(fail_with="CREATE_FAILED")

    with pytest.raises(deploy_runtime.DeployError, match="image pull failed"):
        deploy_runtime.deploy(control, desired(), sleep=no_sleep)


def test_wait_times_out_instead_of_hanging() -> None:
    control = FakeControl(settle=10**9)
    control.create_agent_runtime(agentRuntimeName="fixit_mcp", **desired())
    (runtime_id,) = control.runtimes

    with pytest.raises(deploy_runtime.DeployError, match="still CREATING"):
        deploy_runtime.wait_for_status(control, runtime_id, sleep=no_sleep, timeout_s=0)


def test_find_runtime_follows_pagination() -> None:
    pages = iter(
        [
            {"agentRuntimes": [{"agentRuntimeName": "other"}], "nextToken": "t1"},
            {"agentRuntimes": [{"agentRuntimeName": "fixit_mcp", "agentRuntimeId": "fixit_mcp-1"}]},
        ]
    )

    class Paged:
        def list_agent_runtimes(self, **kwargs):
            return next(pages)

    assert deploy_runtime.find_runtime(Paged())["agentRuntimeId"] == "fixit_mcp-1"


# --- deploy_runtime: teardown -------------------------------------------------


def test_delete_removes_the_runtime_and_waits_until_gone() -> None:
    control = FakeControl()
    deploy_runtime.deploy(control, desired(), sleep=no_sleep)

    assert deploy_runtime.delete(control, sleep=no_sleep) == "deleted"
    assert control.runtimes == {}


def test_delete_when_nothing_is_deployed_is_harmless() -> None:
    assert deploy_runtime.delete(FakeControl(), sleep=no_sleep) == "absent"


def test_invocation_url_matches_smoke_test_url_builder() -> None:
    smoke = _load("smoke_test")
    arn = "arn:aws:bedrock-agentcore:us-east-1:111122223333:runtime/fixit_mcp-AbCdEf1234"

    assert deploy_runtime.invocation_url(arn) == smoke.runtime_invocation_url(arn)


# --- push_image -------------------------------------------------


def test_source_drift_reports_changed_added_and_missing_files() -> None:
    image = {"src/a.py": "1", "src/b.py": "2", "src/gone.py": "3"}
    local = {"src/a.py": "1", "src/b.py": "CHANGED", "src/new.py": "4"}

    assert push_image.source_drift(image, local) == ["src/b.py", "src/gone.py", "src/new.py"]


def test_sha256sum_output_parsing() -> None:
    output = f"{'a' * 64}  src/fixit_mcp/server.py\n{'b' * 64}  src/fixit_mcp/apps/diagnose_card.html\n"

    assert push_image.parse_sha256sum_output(output) == {
        "src/fixit_mcp/server.py": "a" * 64,
        "src/fixit_mcp/apps/diagnose_card.html": "b" * 64,
    }


def test_local_source_hashes_cover_python_and_the_card_html() -> None:
    hashes = push_image.local_source_hashes()

    assert "src/fixit_mcp/server.py" in hashes
    assert "src/fixit_mcp/apps/diagnose_card.html" in hashes
    assert not any("__pycache__" in path for path in hashes)


def test_ecr_login_password_decodes_the_authorization_token() -> None:
    token = base64.b64encode(b"AWS:s3cret-password").decode()

    assert push_image.ecr_login_password(token) == "s3cret-password"


# --- render_iam_policies -------------------------------------------------

VALUES = {
    "AWS_ACCOUNT_ID": "111122223333",
    "AWS_REGION": "us-east-1",
    "FIXIT_AGENTCORE_MEMORY_ID": "FixItH-abc",
}


def test_every_committed_template_renders_to_valid_json_with_no_placeholders(tmp_path: Path) -> None:
    written = render_iam.render_all(VALUES, output_dir=tmp_path)

    assert {p.name for p in written} == {
        "deployer-policy.json",
        "runtime-execution-policy.json",
        "runtime-execution-trust.json",
    }
    for path in written:
        text = path.read_text()
        assert "${" not in text
        json.loads(text)


def test_committed_templates_contain_no_real_account_id() -> None:
    for template in (REPO_ROOT / "deploy" / "iam").glob("*.json"):
        text = template.read_text()
        assert "${AWS_ACCOUNT_ID}" in text or "aws-service-role" in text
        assert not any(len(token) == 12 and token.isdigit() for token in text.replace(":", " ").split())


def test_missing_value_fails_rather_than_emitting_a_placeholder() -> None:
    with pytest.raises(KeyError):
        render_iam.render('{"Resource": "${AWS_ACCOUNT_ID}"}', {})


def test_execution_role_keeps_the_deliberate_omissions(tmp_path: Path) -> None:
    render_iam.render_all(VALUES, output_dir=tmp_path)
    policy = json.loads((tmp_path / "runtime-execution-policy.json").read_text())
    actions = {
        a
        for s in policy["Statement"]
        for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])
    }

    assert not any(a.startswith("bedrock:InvokeModel") for a in actions)
    assert not any(a.startswith("bedrock-agentcore:GetWorkloadAccessToken") for a in actions)
    memory = next(s for s in policy["Statement"] if s["Sid"] == "HouseholdAppliancesMemory")
    assert set(memory["Action"]) == {
        "bedrock-agentcore:CreateEvent",
        "bedrock-agentcore:ListEvents",
        "bedrock-agentcore:DeleteEvent",
    }
    assert memory["Resource"] == "arn:aws:bedrock-agentcore:us-east-1:111122223333:memory/FixItH-abc"


def test_pass_role_is_limited_to_agentcore(tmp_path: Path) -> None:
    render_iam.render_all(VALUES, output_dir=tmp_path)
    policy = json.loads((tmp_path / "deployer-policy.json").read_text())
    pass_role = next(s for s in policy["Statement"] if s["Action"] == "iam:PassRole")

    assert pass_role["Resource"].endswith(":role/FixItAgentCoreRuntimeRole")
    assert pass_role["Condition"] == {
        "StringEquals": {"iam:PassedToService": "bedrock-agentcore.amazonaws.com"}
    }


# --- measure_runtime_latency -------------------------------------------------


def test_handler_latencies_are_parsed_from_our_own_log_lines_only() -> None:
    messages = [
        json.dumps({"event": "tool_call_completed", "tool": "diagnose_error", "latency_ms": 91.2}),
        json.dumps({"event": "tool_call_completed", "tool": "list_my_appliances", "latency_ms": 80.0}),
        json.dumps({"event": "agentcore_memory_call", "operation": "ListEvents", "latency_ms": 88.0}),
        "INFO:     169.254.0.1 - POST /mcp 200",
    ]

    assert latency.parse_handler_latencies(messages) == [91.2]


def test_percentile() -> None:
    samples = [float(i) for i in range(1, 101)]

    assert latency.percentile(samples, 50) == 50.0
    assert latency.percentile(samples, 95) == 95.0
    assert latency.percentile([7.0], 95) == 7.0


# IAM counts non-whitespace characters against these limits.
IAM_SIZE_LIMITS = {
    "deployer-policy.json": 6144,  # customer managed policy (too big for a 2,048-char user inline policy)
    "runtime-execution-policy.json": 10240,  # role inline policy
    "runtime-execution-trust.json": 2048,  # role trust policy (default quota)
}


@pytest.mark.parametrize("name,limit", IAM_SIZE_LIMITS.items())
def test_rendered_policies_fit_the_iam_size_limit_where_they_are_attached(
    tmp_path: Path, name: str, limit: int
) -> None:
    render_iam.render_all(VALUES | {"AWS_ACCOUNT_ID": "999999999999"}, output_dir=tmp_path)
    size = len("".join((tmp_path / name).read_text().split()))

    assert size <= limit, f"{name} is {size} chars, over IAM's {limit} for where it's attached"


def test_deployer_can_create_the_implicit_default_endpoint(tmp_path: Path) -> None:
    """CreateAgentRuntime also creates the DEFAULT endpoint, authorized as
    CreateAgentRuntimeEndpoint on the literal `runtime/*` -- a name-scoped
    `runtime/fixit_mcp-*` grant doesn't match it (first real deploy, 4c)."""
    render_iam.render_all(VALUES, output_dir=tmp_path)
    policy = json.loads((tmp_path / "deployer-policy.json").read_text())

    wildcard = next(s for s in policy["Statement"] if s["Sid"] == "AgentCoreRuntimeCreateAndList")
    assert "bedrock-agentcore:CreateAgentRuntimeEndpoint" in wildcard["Action"]
    assert wildcard["Resource"] == "*"
    scoped = next(s for s in policy["Statement"] if s["Sid"] == "AgentCoreRuntimeManagement")
    assert {
        "bedrock-agentcore:UpdateAgentRuntimeEndpoint",
        "bedrock-agentcore:DeleteAgentRuntimeEndpoint",
    } <= set(scoped["Action"])
