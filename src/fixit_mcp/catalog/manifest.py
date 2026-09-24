"""Read-only, in-memory view of data/manuals/manifest.yaml for the running
server -- lets add_appliance link a newly-registered appliance to a manual
by brand+model, without re-reading the file per call (CLAUDE.md rule 3/4:
no file I/O in the request path).

This is deliberately independent of `fixit_mcp.ingestion.*` (offline tooling
only, see CLAUDE.md) even though `scripts/fetch_manuals.py` and
`scripts/parse_manuals.py` also read this same file -- this module reads
static catalog metadata the manifest already publishes, not anything the
ingestion pipeline computes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parents[3] / "data" / "manuals" / "manifest.yaml"


@dataclass(frozen=True)
class ManualCatalogEntry:
    manual_id: str
    brand: str
    model: str
    appliance_type: str


@dataclass
class ManualCatalog:
    entries: list[ManualCatalogEntry]

    def find(self, brand: str, model: str) -> ManualCatalogEntry | None:
        """Case-insensitive exact brand+model match, or None if no manual is on file."""
        brand_key, model_key = brand.strip().lower(), model.strip().lower()
        for entry in self.entries:
            if entry.brand.lower() == brand_key and entry.model.lower() == model_key:
                return entry
        return None


def load_manual_catalog(path: Path | None = None) -> ManualCatalog:
    path = path or DEFAULT_MANIFEST_PATH
    if not path.exists():
        return ManualCatalog(entries=[])
    raw = yaml.safe_load(path.read_text()) or []
    entries = [
        ManualCatalogEntry(
            manual_id=item["id"],
            brand=item["brand"],
            model=item["model"],
            appliance_type=item["appliance_type"],
        )
        for item in raw
    ]
    return ManualCatalog(entries=entries)
