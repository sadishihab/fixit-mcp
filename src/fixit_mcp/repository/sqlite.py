"""SQLite-backed ApplianceRepository -- the dev/demo persistence layer.

Chosen over a flat JSON file for three reasons: (1) `sqlite3` is stdlib, no
new dependency; (2) each add/remove is one atomic, transactional statement,
so a crash mid-write can't leave a household's data half-written the way a
read-whole-file/rewrite-whole-file JSON approach could; (3) per-household
lookups use a real index instead of scanning and re-parsing an entire JSON
blob on every call, which matters once diagnose_error's <500ms budget
depends on list_by_household being cheap (see CLAUDE.md rule 4).

This is the dev/demo implementation behind ApplianceRepository. Production
is intended to run on **Amazon Bedrock AgentCore Memory** instead, behind
the same interface -- see CLAUDE.md.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import date
from pathlib import Path

from fixit_mcp.domain.models import Appliance
from fixit_mcp.repository.in_memory import DEFAULT_SEED

_SCHEMA = """
CREATE TABLE IF NOT EXISTS appliances (
    appliance_id TEXT PRIMARY KEY,
    household_id TEXT NOT NULL,
    brand TEXT NOT NULL,
    model TEXT NOT NULL,
    appliance_type TEXT NOT NULL,
    purchase_date TEXT,
    warranty_end_date TEXT,
    manual_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appliances_household ON appliances(household_id);
"""


class SqliteApplianceRepository:
    """ApplianceRepository backed by a local SQLite file at `db_path`.

    A single shared connection guarded by a lock, rather than a connection
    per call or per thread -- simplest correct option for this server's
    request volume, and avoids sqlite3's "not thread-safe across connections
    without care" footguns entirely. WAL journaling + synchronous=NORMAL
    trade a small, well-understood durability window (loss of the last
    commit on a hard crash, not corruption) for commit latency that stays
    well inside the tool-call latency budget.
    """

    def __init__(self, db_path: Path, seed: dict[str, list[Appliance]] | None = None) -> None:
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._seed_if_empty(seed if seed is not None else DEFAULT_SEED)

    def _seed_if_empty(self, seed: dict[str, list[Appliance]]) -> None:
        with self._lock:
            (count,) = self._conn.execute("SELECT COUNT(*) FROM appliances").fetchone()
            if count > 0:
                return
            for household_id, appliances in seed.items():
                for appliance in appliances:
                    self._insert(household_id, appliance)
            self._conn.commit()

    def list_by_household(self, household_id: str) -> list[Appliance]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT appliance_id, brand, model, appliance_type, purchase_date, "
                "warranty_end_date, manual_id FROM appliances WHERE household_id = ? "
                "ORDER BY appliance_id",
                (household_id,),
            ).fetchall()
        return [_row_to_appliance(row) for row in rows]

    def add(self, household_id: str, appliance: Appliance) -> None:
        with self._lock:
            self._insert(household_id, appliance)
            self._conn.commit()

    def remove(self, household_id: str, appliance_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM appliances WHERE household_id = ? AND appliance_id = ?",
                (household_id, appliance_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def _insert(self, household_id: str, appliance: Appliance) -> None:
        """Caller must hold self._lock."""
        self._conn.execute(
            "INSERT INTO appliances (appliance_id, household_id, brand, model, appliance_type, "
            "purchase_date, warranty_end_date, manual_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                appliance.appliance_id,
                household_id,
                appliance.brand,
                appliance.model,
                appliance.appliance_type,
                appliance.purchase_date.isoformat() if appliance.purchase_date else None,
                appliance.warranty_end_date.isoformat() if appliance.warranty_end_date else None,
                appliance.manual_id,
            ),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _row_to_appliance(row: tuple) -> Appliance:
    appliance_id, brand, model, appliance_type, purchase_date, warranty_end_date, manual_id = row
    return Appliance(
        appliance_id=appliance_id,
        brand=brand,
        model=model,
        appliance_type=appliance_type,
        purchase_date=date.fromisoformat(purchase_date) if purchase_date else None,
        warranty_end_date=date.fromisoformat(warranty_end_date) if warranty_end_date else None,
        manual_id=manual_id,
    )
