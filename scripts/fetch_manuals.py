#!/usr/bin/env python3
"""Download appliance manual PDFs listed in data/manuals/manifest.yaml.

Manuals are downloaded to data/manuals/pdf/<id>.pdf. Files already present are
skipped unless --force is given. Each download is verified to actually be a
PDF (magic bytes + parseable page count) before being kept. One manual
failing to download does not stop the others.

Usage:
    uv run python scripts/fetch_manuals.py [--force]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml
from pypdf import PdfReader
from pypdf.errors import PdfReadError

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "manuals" / "manifest.yaml"
PDF_DIR = REPO_ROOT / "data" / "manuals" / "pdf"

TIMEOUT_SECONDS = 60.0
USER_AGENT = "fixit-mcp-manual-fetcher/0.1 (hackathon project; manual PDF ingestion)"


@dataclass
class FetchResult:
    manual_id: str
    ok: bool
    detail: str
    size_bytes: int = 0
    pages: int = 0


def load_manifest() -> list[dict]:
    with MANIFEST_PATH.open() as f:
        return yaml.safe_load(f)


def _page_count(path: Path) -> int:
    return len(PdfReader(path).pages)


def fetch_one(entry: dict, force: bool) -> FetchResult:
    manual_id = entry["id"]
    url = entry["source_url"]
    dest = PDF_DIR / f"{manual_id}.pdf"

    if dest.exists() and not force:
        try:
            return FetchResult(
                manual_id, True, "already downloaded (skipped)", dest.stat().st_size, _page_count(dest)
            )
        except PdfReadError:
            pass  # cached file is corrupt; fall through and re-download

    try:
        with httpx.Client(
            follow_redirects=True, timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
        ) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        return FetchResult(manual_id, False, f"download failed: {exc}")

    body = response.content
    if not body.startswith(b"%PDF-"):
        content_type = response.headers.get("content-type", "unknown")
        return FetchResult(manual_id, False, f"not a PDF (content-type={content_type!r})")

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)

    try:
        pages = _page_count(dest)
    except PdfReadError as exc:
        dest.unlink(missing_ok=True)
        return FetchResult(manual_id, False, f"downloaded but failed to parse as PDF: {exc}")

    return FetchResult(manual_id, True, "downloaded", len(body), pages)


def print_results(results: list[FetchResult]) -> None:
    print(f"{'ID':<32} {'STATUS':<6} {'SIZE':>10} {'PAGES':>6}  DETAIL")
    for r in results:
        status = "OK" if r.ok else "FAIL"
        size_str = f"{r.size_bytes / 1024:.0f} KB" if r.size_bytes else "-"
        pages_str = str(r.pages) if r.pages else "-"
        print(f"{r.manual_id:<32} {status:<6} {size_str:>10} {pages_str:>6}  {r.detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-download even if the file already exists.")
    args = parser.parse_args()

    manifest = load_manifest()
    results = [fetch_one(entry, args.force) for entry in manifest]
    print_results(results)

    failures = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failures)}/{len(results)} succeeded.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
