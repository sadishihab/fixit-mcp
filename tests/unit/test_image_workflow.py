"""Guards on .github/workflows/image.yml (step 28b).

The workflow publishes a public container image, so the properties that matter are asserted here:
only a version tag publishes, the only credential is the built-in GITHUB_TOKEN, the smoke job gates the
publish, and the job that can write packages is the only one that can.
"""

import re
from pathlib import Path

import yaml

from fixit_mcp.config import REPO_ROOT

WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "image.yml"
TEXT = WORKFLOW_PATH.read_text()
WF = yaml.safe_load(TEXT)
TRIGGERS = WF.get("on", WF.get(True))  # YAML 1.1 reads a bare `on` key as the boolean True
DOCKERFILE = (REPO_ROOT / "Dockerfile").read_text()


def _steps(job: str) -> list[dict]:
    return WF["jobs"][job]["steps"]


def _step_using(job: str, action: str) -> dict:
    return next(s for s in _steps(job) if str(s.get("uses", "")).startswith(action))


def test_only_a_version_tag_or_a_manual_run_triggers_it() -> None:
    assert set(TRIGGERS) == {"push", "workflow_dispatch"}, "no pull_request, no schedule"
    assert TRIGGERS["push"] == {"tags": ["v*"]}, "a normal push to a branch must never run this"


def test_permissions_are_minimal_and_only_the_publish_job_can_write_packages() -> None:
    assert WF["permissions"] == {"contents": "read"}
    assert WF["jobs"]["publish"]["permissions"] == {"contents": "read", "packages": "write"}
    assert "permissions" not in WF["jobs"]["smoke"], "the smoke job inherits read-only"
    assert not re.search(r"id-token|attestations|actions:\s*write|contents:\s*write", TEXT)


def test_the_only_secret_is_the_built_in_github_token() -> None:
    assert set(re.findall(r"secrets\.(\w+)", TEXT)) == {"GITHUB_TOKEN"}
    assert "aws-actions" not in TEXT and "AWS_ACCESS_KEY" not in TEXT and "role-to-assume" not in TEXT


def test_every_action_is_pinned_to_a_major_version() -> None:
    uses = re.findall(r"uses:\s*(\S+)", TEXT)

    assert uses and all(re.fullmatch(r"[\w./-]+@v\d+", u) for u in uses), uses
    assert {u.split("@")[0] for u in uses} >= {
        "docker/login-action",
        "docker/metadata-action",
        "docker/build-push-action",
        "docker/setup-qemu-action",
        "docker/setup-buildx-action",
    }


def test_the_publish_job_waits_for_the_smoke_job() -> None:
    assert WF["jobs"]["publish"]["needs"] == "smoke"


def test_the_smoke_job_runs_the_smoke_script_against_the_amd64_image_without_the_latency_check() -> None:
    build = _step_using("smoke", "docker/build-push-action")["with"]
    smoke = next(s["run"] for s in _steps("smoke") if "smoke_test.py" in s.get("run", ""))

    assert build["platforms"] == "linux/amd64" and build["load"] is True and build["push"] is False
    assert "--skip-latency" in smoke and "http://localhost:8000/mcp" in smoke


def test_the_smoke_job_checks_non_root_and_no_aws_or_backend_variables() -> None:
    check = next(s["run"] for s in _steps("smoke") if "--entrypoint id" in s.get("run", ""))

    assert '= "1000"' in check
    assert "AWS_" in check and "FIXIT_REPOSITORY_BACKEND" in check and "FIXIT_AGENTCORE" in check


def test_the_image_itself_sets_none_of_what_the_smoke_job_forbids() -> None:
    """The workflow's own guard, checked statically against the Dockerfile that ships."""
    env_lines = " ".join(re.findall(r"^ENV .*(?:\\\n.*)*", DOCKERFILE, re.M))

    assert "AWS_" not in env_lines and "FIXIT_REPOSITORY_BACKEND" not in env_lines
    assert "FIXIT_AGENTCORE" not in env_lines and "FIXIT_HOST" not in env_lines
    assert re.search(r"^USER fixit$", DOCKERFILE, re.M) and "--uid 1000" in DOCKERFILE


def test_publishing_is_gated_on_a_version_tag_and_both_architectures_are_built() -> None:
    build = _step_using("publish", "docker/build-push-action")["with"]
    login = _step_using("publish", "docker/login-action")

    assert build["platforms"] == "linux/amd64,linux/arm64"
    assert build["push"] == "${{ startsWith(github.ref, 'refs/tags/v') }}"
    assert login["if"] == "startsWith(github.ref, 'refs/tags/v')"
    assert login["with"]["registry"] == "ghcr.io"
    assert login["with"]["password"] == "${{ secrets.GITHUB_TOKEN }}"
    assert _step_using("publish", "docker/setup-qemu-action")


def test_the_image_name_tags_and_labels() -> None:
    meta = _step_using("publish", "docker/metadata-action")["with"]

    assert WF["env"]["IMAGE"] == "ghcr.io/sadishihab/fixit-mcp"
    assert (
        "type=semver,pattern={{version}}" in meta["tags"]
        and "type=semver,pattern={{major}}.{{minor}}" in meta["tags"]
    )
    assert "org.opencontainers.image.licenses=MIT" in meta["labels"]
    assert "org.opencontainers.image.source=https://github.com/sadishihab/fixit-mcp" in meta["labels"]
    assert "org.opencontainers.image.description=" in meta["labels"]
    assert "latest" not in meta["tags"], (
        "latest comes from metadata-action's default, which skips pre-releases"
    )


def test_the_license_the_label_names_is_the_repositorys_license() -> None:
    assert (Path(REPO_ROOT) / "LICENSE").read_text().startswith("MIT License")
