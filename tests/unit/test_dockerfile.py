"""Cheap, always-run guards on the Dockerfile's contract -- the full
container tests (tests/integration/test_container.py) are opt-in and slow,
so the drift most likely to break the image silently is caught here instead.
"""

import fnmatch
import re
from pathlib import Path

from fixit_mcp.catalog.manifest import DEFAULT_MANIFEST_PATH
from fixit_mcp.config import DEFAULT_SQLITE_PATH, REPO_ROOT, Settings
from fixit_mcp.retrieval.codes import DEFAULT_INDEX_PATH

DOCKERFILE = (REPO_ROOT / "Dockerfile").read_text()
DOCKERIGNORE = [
    line.strip()
    for line in (REPO_ROOT / ".dockerignore").read_text().splitlines()
    if line.strip() and not line.startswith("#")
]


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def _is_dockerignored(relative_path: str) -> bool:
    for pattern in DOCKERIGNORE:
        if pattern.startswith("!"):
            continue
        prefix = pattern.rstrip("/")
        if relative_path == prefix or relative_path.startswith(prefix + "/"):
            return True
        if fnmatch.fnmatch(relative_path, pattern):
            return True
    return False


def test_every_data_file_loaded_at_startup_is_copied_into_the_image() -> None:
    """load_manual_catalog() silently returns an empty catalog if its file is
    missing, so a new startup data file that isn't COPYed in would not fail
    loudly inside the container -- keep this list in sync with create_server()."""
    for path in (DEFAULT_INDEX_PATH, DEFAULT_MANIFEST_PATH):
        relative = _relative(path)
        assert f"COPY --chown=fixit:fixit {relative} ./{relative}" in DOCKERFILE, relative
        assert not _is_dockerignored(relative), f"{relative} is excluded by .dockerignore"


def test_local_state_and_derived_data_are_kept_out_of_the_build_context() -> None:
    for relative in (
        _relative(DEFAULT_SQLITE_PATH),
        "data/manuals/pdf/example.pdf",
        "data/manuals/parsed/example.json",
        "data/index/.extract_cache/abc.json",
        ".env",
    ):
        assert _is_dockerignored(relative), relative


def test_project_install_stays_editable() -> None:
    """Data paths are resolved via Path(__file__).parents[N], which only
    points at /app/data when the package runs from /app/src. A non-editable
    install into site-packages would break every one of them."""
    assert "--no-editable" not in DOCKERFILE
    assert "COPY --from=builder --chown=fixit:fixit /app/src ./src" in DOCKERFILE


def test_image_matches_agentcore_mcp_container_contract() -> None:
    """AgentCore's MCP contract is 0.0.0.0:8000/mcp -- the Dockerfile must
    not override the Settings defaults that already satisfy it."""
    settings = Settings(_env_file=None)
    assert (settings.host, settings.port, settings.streamable_http_path) == ("0.0.0.0", 8000, "/mcp")
    assert re.search(r"^EXPOSE 8000$", DOCKERFILE, re.M)
    assert "FIXIT_HOST" not in DOCKERFILE and "FIXIT_PORT" not in DOCKERFILE


def test_runs_as_non_root_without_dev_dependencies() -> None:
    assert re.search(r"^USER fixit$", DOCKERFILE, re.M)
    assert "--uid 1000" in DOCKERFILE
    sync_commands = re.findall(r"uv sync[^\n]*", DOCKERFILE)
    assert sync_commands, "expected at least one `uv sync` in the Dockerfile"
    assert all("--no-dev" in command for command in sync_commands), sync_commands
