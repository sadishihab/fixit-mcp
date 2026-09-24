"""Push the already-built, already-tested local image to ECR -- no rebuild.

    uv run python scripts/push_image.py [--local-image fixit-mcp:latest]

Step 4c's rule is "deploy exactly what was tested": this script only tags
and pushes the image `make docker-build` produced (and the container tests
ran against). Before pushing it checks that the image is linux/arm64
(AgentCore Runtime rejects anything else), and reports whether the source
baked into it matches the working tree -- a mismatch means the image
predates later commits, which is worth knowing even when harmless
(e.g. docstring-only changes).

Pushes two tags: `latest` (what deploy_runtime.py resolves) and
`img-<local image id prefix>` (a stable name for exactly this build).
deploy_runtime.py then pins the runtime to the pushed **digest**.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_NAME = "fixit-mcp"
DEFAULT_LOCAL_IMAGE = "fixit-mcp:latest"
DEFAULT_REGION = "us-east-1"
_SOURCE_GLOBS = ("*.py", "*.html")


def _docker(*args: str, input_text: str | None = None) -> str:
    result = subprocess.run(["docker", *args], input=input_text, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"docker {' '.join(args[:2])} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def local_source_hashes(root: Path = REPO_ROOT) -> dict[str, str]:
    hashes = {}
    for pattern in _SOURCE_GLOBS:
        for path in (root / "src").rglob(pattern):
            if "__pycache__" not in path.parts:
                hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def parse_sha256sum_output(output: str) -> dict[str, str]:
    hashes = {}
    for line in output.splitlines():
        digest, _, path = line.partition("  ")
        if path:
            hashes[path.strip()] = digest
    return hashes


def source_drift(image_hashes: dict[str, str], local_hashes: dict[str, str]) -> list[str]:
    """Files that differ, or exist on only one side, between image and working tree."""
    return sorted(
        path
        for path in image_hashes.keys() | local_hashes.keys()
        if image_hashes.get(path) != local_hashes.get(path)
    )


def ecr_login_password(authorization_token: str) -> str:
    user, _, password = base64.b64decode(authorization_token).decode().partition(":")
    if user != "AWS" or not password:
        raise SystemExit("unexpected ECR authorization token format")
    return password


def main() -> int:
    import boto3

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--local-image", default=DEFAULT_LOCAL_IMAGE)
    parser.add_argument("--region", default=DEFAULT_REGION)
    args = parser.parse_args()

    architecture = _docker("image", "inspect", args.local_image, "--format", "{{.Architecture}}")
    if architecture != "arm64":
        raise SystemExit(
            f"{args.local_image} is {architecture}; AgentCore Runtime needs arm64 (make docker-build)"
        )
    image_id = _docker("image", "inspect", args.local_image, "--format", "{{.Id}}").removeprefix("sha256:")

    image_hashes = parse_sha256sum_output(
        _docker(
            "run", "--rm", "--platform", "linux/arm64", "--entrypoint", "sh", args.local_image, "-c",
            "cd /app && find src -type f \\( -name '*.py' -o -name '*.html' \\) ! -path '*/__pycache__/*' "
            "| sort | xargs sha256sum",
        )
    )  # fmt: skip
    drift = source_drift(image_hashes, local_source_hashes())
    if drift:
        print(f"NOTE: image source differs from the working tree in {len(drift)} file(s): {', '.join(drift)}")
    else:
        print("image source matches the working tree exactly")

    session = boto3.Session(region_name=args.region)
    ecr = session.client("ecr")
    account_id = session.client("sts").get_caller_identity()["Account"]
    registry = f"{account_id}.dkr.ecr.{args.region}.amazonaws.com"
    repository_uri = f"{registry}/{REPOSITORY_NAME}"

    try:
        ecr.describe_repositories(repositoryNames=[REPOSITORY_NAME])
    except ecr.exceptions.RepositoryNotFoundException:
        ecr.create_repository(
            repositoryName=REPOSITORY_NAME,
            imageScanningConfiguration={"scanOnPush": True},
            imageTagMutability="MUTABLE",  # `latest` moves; the digest the runtime pins never does
        )
        print(f"created ECR repository {repository_uri}")

    token = ecr.get_authorization_token()["authorizationData"][0]["authorizationToken"]
    _docker("login", "--username", "AWS", "--password-stdin", registry, input_text=ecr_login_password(token))

    for tag in ("latest", f"img-{image_id[:12]}"):
        _docker("tag", args.local_image, f"{repository_uri}:{tag}")
        _docker("push", f"{repository_uri}:{tag}")
        print(f"pushed {repository_uri}:{tag}")

    digest = ecr.describe_images(repositoryName=REPOSITORY_NAME, imageIds=[{"imageTag": "latest"}])[
        "imageDetails"
    ][0]["imageDigest"]
    print(f"digest: {repository_uri}@{digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
