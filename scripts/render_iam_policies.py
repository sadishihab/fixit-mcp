"""Render deploy/iam/*.json templates with this account's values into
build/iam/ (gitignored), ready to paste into the IAM console.

    FIXIT_AGENTCORE_MEMORY_ID=<id> uv run python scripts/render_iam_policies.py [--account-id <id>]

The account id comes from `sts get-caller-identity` unless passed in. The
templates stay placeholder-only so no account id is ever committed.
"""

from __future__ import annotations

import argparse
import json
import os
import string
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "deploy" / "iam"
OUTPUT_DIR = REPO_ROOT / "build" / "iam"


def render(template_text: str, values: dict[str, str]) -> str:
    """Substitute every ${NAME}; raise if any placeholder is left unfilled."""
    rendered = string.Template(template_text).substitute(values)
    json.loads(rendered)  # never hand out a policy the console would reject
    return rendered


def render_all(
    values: dict[str, str], template_dir: Path = TEMPLATE_DIR, output_dir: Path = OUTPUT_DIR
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for template in sorted(template_dir.glob("*.json")):
        target = output_dir / template.name
        target.write_text(render(template.read_text(), values))
        written.append(target)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--account-id")
    parser.add_argument("--region", default=os.environ.get("FIXIT_AGENTCORE_REGION", "us-east-1"))
    args = parser.parse_args()
    memory_id = os.environ.get("FIXIT_AGENTCORE_MEMORY_ID", "")
    if not memory_id:
        print("FIXIT_AGENTCORE_MEMORY_ID is not set.", file=sys.stderr)
        return 2
    account_id = args.account_id
    if not account_id:
        import boto3

        account_id = boto3.client("sts").get_caller_identity()["Account"]
    values = {"AWS_ACCOUNT_ID": account_id, "AWS_REGION": args.region, "FIXIT_AGENTCORE_MEMORY_ID": memory_id}
    for path in render_all(values):
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
