"""The repo is public: no real AWS account id may be committed (CLAUDE.md,
step 4c). IAM templates use ${AWS_ACCOUNT_ID}; docs use <account>. This
scans every tracked text file for account ids embedded in ARNs and ECR
URIs, allowing only AWS's own documentation examples and test dummies."""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {
    "111122223333",  # AWS documentation example
    "123456789012",  # AWS documentation example
    "999999999999",  # our test dummy (same length as a real id)
    "424242424242",  # this file's own scanner-catches-a-leak sample, below
}
# AgentCore resource ids: the memory id (FixItHouseholds-<10 alnum>) and the
# runtime id (fixit_mcp-<10 alnum>). Docs use the placeholders <memory-id> and
# <runtime-id>, which never match (no 10 alphanumerics after the dash). Only
# these obviously fake examples, already used in tests and docs, are allowed.
ALLOWED_RESOURCE_IDS = {
    "a1B2c3D4e5",  # fake memory id example
    "AbCdEf1234",  # fake runtime id example
    "Zz9Yy8Xx7W",  # this file's own scanner-catches-a-leak sample, below
}
RESOURCE_ID_PATTERNS = [
    re.compile(r"\bFixItHouseholds-([A-Za-z0-9]{10})\b"),
    re.compile(r"\bfixit_mcp-([A-Za-z0-9]{10})\b"),
]
# The public-facing places that must always be covered by the scan.
MUST_SCAN = ("FRICTION_LOG.md", "README.md", "docs/", "demo/")
PATTERNS = [
    re.compile(r"arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:(\d{12}):"),
    re.compile(r"(\d{12})\.dkr\.ecr\."),
    re.compile(r"\"(?:AWS_ACCOUNT_ID|aws:SourceAccount)\"\s*:\s*\"(\d{12})\""),
]


def _tracked_text_files() -> list[Path]:
    names = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [REPO_ROOT / n for n in names if not n.endswith((".pdf", ".png", ".jpg", ".db"))]


def test_no_real_account_id_in_any_tracked_file() -> None:
    leaks = []
    for path in _tracked_text_files():
        try:
            text = path.read_text()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for pattern in PATTERNS:
            for match in pattern.finditer(text):
                if match.group(1) not in ALLOWED:
                    leaks.append(f"{path.relative_to(REPO_ROOT)}: ...{match.group(0)[-40:]}")
    assert not leaks, "real-looking AWS account id committed:\n" + "\n".join(leaks)


def test_the_scanner_catches_a_leak() -> None:
    sample = 'arn:aws:bedrock-agentcore:us-east-1:424242424242:runtime/x "AWS_ACCOUNT_ID": "424242424242"'
    found = {m.group(1) for p in PATTERNS for m in p.finditer(sample)}

    assert found == {"424242424242"}


def test_no_real_agentcore_resource_id_in_any_tracked_file() -> None:
    leaks = []
    for path in _tracked_text_files():
        try:
            text = path.read_text()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for pattern in RESOURCE_ID_PATTERNS:
            for match in pattern.finditer(text):
                if match.group(1) not in ALLOWED_RESOURCE_IDS:
                    leaks.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")
    assert not leaks, "real-looking AgentCore memory/runtime id committed:\n" + "\n".join(leaks)


def test_the_resource_id_scanner_catches_a_leak_and_allows_placeholders() -> None:
    def found(text: str) -> set[str]:
        return {m.group(1) for p in RESOURCE_ID_PATTERNS for m in p.finditer(text)}

    assert found("FixItHouseholds-Zz9Yy8Xx7W and runtime/fixit_mcp-Zz9Yy8Xx7W") == {"Zz9Yy8Xx7W"}
    assert found("FixItHouseholds-<memory-id> and fixit_mcp-<runtime-id>") == set()
    assert found("fixit_mcp-server and fixit_mcp-tools") == set()


def test_the_scan_covers_the_public_facing_files() -> None:
    scanned = {str(p.relative_to(REPO_ROOT)) for p in _tracked_text_files()}
    for required in MUST_SCAN:
        assert any(n == required or n.startswith(required) for n in scanned), f"{required} is not scanned"
