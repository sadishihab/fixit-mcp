"""Create, update, or delete the FixIt AgentCore Runtime -- the direct,
no-CDK deploy path chosen in step 4c (see FRICTION_LOG.md).

    uv run python scripts/deploy_runtime.py            # create or update (idempotent)
    uv run python scripts/deploy_runtime.py --delete   # teardown: stops all Runtime charges

Deploy resolves the pushed image (`make docker-push`) to its immutable
**digest** in ECR and points the runtime at `repo@sha256:...`, never at a
mutable tag -- the runtime runs exactly the bytes that were pushed.

Idempotent: finds the runtime by name; creates it if absent, updates it
only if the image, role, env vars, protocol, network, lifecycle, or auth
differ from what's wanted, and otherwise does nothing (an update would mint
a new runtime version for no reason). Waits until the runtime is READY.

Configuration is fixed on purpose -- this is the deployed configuration,
not a menu:
  - protocol MCP, network PUBLIC, inbound auth AWS_IAM (no
    authorizerConfiguration => SigV4; OAuth/JWT is a later step)
  - FIXIT_REPOSITORY_BACKEND=agentcore + FIXIT_AGENTCORE_MEMORY_ID, since
    SQLite doesn't survive AgentCore's per-session microVMs (step 4a)
Only the memory id is taken from the environment (FIXIT_AGENTCORE_MEMORY_ID).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

RUNTIME_NAME = "fixit_mcp"
REPOSITORY_NAME = "fixit-mcp"
EXECUTION_ROLE_NAME = "FixItAgentCoreRuntimeRole"
DEFAULT_REGION = "us-east-1"
DEFAULT_IMAGE_TAG = "latest"
# 5 minutes idle before a session's microVM is stopped (the default is 15).
# Household state lives in AgentCore Memory, so a stopped session loses
# nothing -- the next call just pays a cold start.
IDLE_TIMEOUT_S = 300
MAX_LIFETIME_S = 28800
POLL_INTERVAL_S = 5
WAIT_TIMEOUT_S = 900


class DeployError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeployTarget:
    account_id: str
    region: str
    memory_id: str
    image_tag: str = DEFAULT_IMAGE_TAG

    @property
    def repository_uri(self) -> str:
        return f"{self.account_id}.dkr.ecr.{self.region}.amazonaws.com/{REPOSITORY_NAME}"

    @property
    def role_arn(self) -> str:
        return f"arn:aws:iam::{self.account_id}:role/{EXECUTION_ROLE_NAME}"


def resolve_image_digest_uri(ecr: Any, target: DeployTarget) -> str:
    """`<repo>@sha256:...` for the pushed tag. Fails loudly if it isn't pushed."""
    try:
        response = ecr.describe_images(
            repositoryName=REPOSITORY_NAME, imageIds=[{"imageTag": target.image_tag}]
        )
    except Exception as exc:
        raise DeployError(
            f"image {REPOSITORY_NAME}:{target.image_tag} not found in ECR -- "
            f"run `make docker-push` first ({exc})"
        ) from exc
    digest = response["imageDetails"][0]["imageDigest"]
    return f"{target.repository_uri}@{digest}"


def desired_config(target: DeployTarget, container_uri: str) -> dict[str, Any]:
    return {
        "agentRuntimeArtifact": {"containerConfiguration": {"containerUri": container_uri}},
        "roleArn": target.role_arn,
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "protocolConfiguration": {"serverProtocol": "MCP"},
        "lifecycleConfiguration": {
            "idleRuntimeSessionTimeout": IDLE_TIMEOUT_S,
            "maxLifetime": MAX_LIFETIME_S,
        },
        "environmentVariables": {
            "FIXIT_REPOSITORY_BACKEND": "agentcore",
            "FIXIT_AGENTCORE_MEMORY_ID": target.memory_id,
            "FIXIT_AGENTCORE_REGION": target.region,
            "FIXIT_LOG_LEVEL": "INFO",
        },
        "description": "FixIt MCP server (Alexa+ appliance help), deployed by scripts/deploy_runtime.py",
    }


def config_matches(current: dict[str, Any], desired: dict[str, Any]) -> bool:
    """True if a GetAgentRuntime response already has every setting we manage.
    Any authorizerConfiguration on the current runtime counts as a mismatch:
    the deployed runtime must be IAM-auth (no authorizer) until OAuth ships."""
    if current.get("authorizerConfiguration"):
        return False
    return all(current.get(key) == value for key, value in desired.items())


def find_runtime(control: Any, name: str = RUNTIME_NAME) -> dict[str, Any] | None:
    kwargs: dict[str, Any] = {"maxResults": 100}
    while True:
        response = control.list_agent_runtimes(**kwargs)
        for runtime in response.get("agentRuntimes", []):
            if runtime["agentRuntimeName"] == name:
                return runtime
        if not response.get("nextToken"):
            return None
        kwargs["nextToken"] = response["nextToken"]


def wait_for_status(
    control: Any,
    runtime_id: str,
    ready: frozenset[str] = frozenset({"READY"}),
    sleep: Callable[[float], None] = time.sleep,
    timeout_s: float = WAIT_TIMEOUT_S,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while True:
        runtime = control.get_agent_runtime(agentRuntimeId=runtime_id)
        status = runtime["status"]
        if status in ready:
            return runtime
        if status.endswith("_FAILED"):
            raise DeployError(
                f"runtime {runtime_id} is {status}: {runtime.get('failureReason', 'no reason given')}"
            )
        if time.monotonic() > deadline:
            raise DeployError(f"runtime {runtime_id} still {status} after {timeout_s}s")
        sleep(POLL_INTERVAL_S)


def deploy(
    control: Any, desired: dict[str, Any], sleep: Callable[[float], None] = time.sleep
) -> tuple[str, dict[str, Any]]:
    """Returns (action, runtime) where action is created | updated | unchanged."""
    existing = find_runtime(control)
    if existing is None:
        created = control.create_agent_runtime(agentRuntimeName=RUNTIME_NAME, **desired)
        return "created", wait_for_status(control, created["agentRuntimeId"], sleep=sleep)

    runtime_id = existing["agentRuntimeId"]
    current = wait_for_status(control, runtime_id, sleep=sleep)
    if config_matches(current, desired):
        return "unchanged", current
    control.update_agent_runtime(agentRuntimeId=runtime_id, **desired)
    return "updated", wait_for_status(control, runtime_id, sleep=sleep)


def delete(
    control: Any, sleep: Callable[[float], None] = time.sleep, timeout_s: float = WAIT_TIMEOUT_S
) -> str:
    """Delete the runtime (and with it its DEFAULT endpoint and all sessions).
    Returns deleted | absent. Waits until it's actually gone."""
    existing = find_runtime(control)
    if existing is None:
        return "absent"
    control.delete_agent_runtime(agentRuntimeId=existing["agentRuntimeId"])
    deadline = time.monotonic() + timeout_s
    while find_runtime(control) is not None:
        if time.monotonic() > deadline:
            raise DeployError(f"runtime {existing['agentRuntimeId']} still present after {timeout_s}s")
        sleep(POLL_INTERVAL_S)
    return "deleted"


def delete_image_repository(ecr: Any) -> str:
    try:
        ecr.delete_repository(repositoryName=REPOSITORY_NAME, force=True)
    except ecr.exceptions.RepositoryNotFoundException:
        return "absent"
    return "deleted"


def invocation_url(agent_runtime_arn: str, qualifier: str = "DEFAULT") -> str:
    region = agent_runtime_arn.split(":")[3]
    escaped = urllib.parse.quote(agent_runtime_arn, safe="")
    return f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{escaped}/invocations?qualifier={qualifier}"


def main() -> int:
    import boto3

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--region", default=os.environ.get("FIXIT_AGENTCORE_REGION", DEFAULT_REGION))
    parser.add_argument("--image-tag", default=DEFAULT_IMAGE_TAG)
    parser.add_argument(
        "--delete", action="store_true", help="delete the runtime (stops all Runtime charges)"
    )
    parser.add_argument(
        "--delete-image-repo",
        action="store_true",
        help="with --delete: also delete the fixit-mcp ECR repository and every image in it",
    )
    args = parser.parse_args()

    session = boto3.Session(region_name=args.region)
    control = session.client("bedrock-agentcore-control")
    ecr = session.client("ecr")

    if args.delete:
        print(f"runtime {RUNTIME_NAME}: {delete(control)}")
        if args.delete_image_repo:
            print(f"ECR repository {REPOSITORY_NAME}: {delete_image_repository(ecr)}")
        return 0

    memory_id = os.environ.get("FIXIT_AGENTCORE_MEMORY_ID", "")
    if not memory_id:
        print("FIXIT_AGENTCORE_MEMORY_ID is not set.", file=sys.stderr)
        return 2
    account_id = session.client("sts").get_caller_identity()["Account"]
    target = DeployTarget(
        account_id=account_id, region=args.region, memory_id=memory_id, image_tag=args.image_tag
    )

    container_uri = resolve_image_digest_uri(ecr, target)
    action, runtime = deploy(control, desired_config(target, container_uri))
    arn = runtime["agentRuntimeArn"]
    print(f"runtime {RUNTIME_NAME}: {action} (version {runtime['agentRuntimeVersion']}, {runtime['status']})")
    print(f"image:          {container_uri}")
    print(f"ARN:            {arn}")
    print(f"invocation URL: {invocation_url(arn)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
