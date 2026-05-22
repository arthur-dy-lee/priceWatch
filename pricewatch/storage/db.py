"""SQLite storage: snapshots (one row per fetch) + rule_fires (cooldown ledger)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..settings import settings
from ..signals import Signal, SignalKind

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    sig_id      TEXT    NOT NULL,
    value       REAL    NOT NULL,
    currency    TEXT,
    ts          TEXT    NOT NULL,
    meta_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap_source_ts  ON snapshots(source, ts DESC);

CREATE TABLE IF NOT EXISTS rule_fires (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name   TEXT    NOT NULL,
    fired_at    TEXT    NOT NULL,
    payload     TEXT
);
CREATE INDEX IF NOT EXISTS idx_rule_fires_name_ts ON rule_fires(rule_name, fired_at DESC);
"""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(str(path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # ---------- snapshots ----------

    def insert_snapshot(self, sig: Signal) -> None:
        self.conn.execute(
            "INSERT INTO snapshots(source, kind, sig_id, value, currency, ts, meta_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sig.source,
                sig.kind.value,
                sig.id,
                sig.value,
                sig.currency,
                sig.ts.isoformat(),
                json.dumps(sig.meta, ensure_ascii=False) if sig.meta else None,
            ),
        )

    def latest(self, source: str) -> sqlite3.Row | None:
        row = self.conn.execute(
            "SELECT * FROM snapshots WHERE source=? ORDER BY ts DESC LIMIT 1",
            (source,),
        ).fetchone()
        return row

    def latest_n(self, source: str, n: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM snapshots WHERE source=? ORDER BY ts DESC LIMIT ?",
                (source, n),
            ).fetchall()
        )

    def window(self, source: str, since_iso: str) -> list[sqlite3.Row]:
        """All snapshots for source with ts >= since_iso, ordered by ts ASC."""
        return list(
            self.conn.execute(
                "SELECT * FROM snapshots WHERE source=? AND ts >= ? ORDER BY ts ASC",
                (source, since_iso),
            ).fetchall()
        )

    def closest_before_or_at(self, source: str, ts_iso: str) -> sqlite3.Row | None:
        """Most recent snapshot at or before ts_iso — used for N-day lookback."""
        return self.conn.execute(
            "SELECT * FROM snapshots WHERE source=? AND ts <= ? ORDER BY ts DESC LIMIT 1",
            (source, ts_iso),
        ).fetchone()

    def known_sources(self) -> list[str]:
        return [r["source"] for r in self.conn.execute(
            "SELECT DISTINCT source FROM snapshots ORDER BY source"
        )]

    def kind_of(self, source: str) -> SignalKind | None:
        row = self.conn.execute(
            "SELECT kind FROM snapshots WHERE source=? ORDER BY ts DESC LIMIT 1",
            (source,),
        ).fetchone()
        return SignalKind(row["kind"]) if row else None

    # ---------- rule fires ----------

    def record_fire(self, rule_name: str, payload: dict | None = None) -> None:
        self.conn.execute(
            "INSERT INTO rule_fires(rule_name, fired_at, payload) VALUES (?, ?, ?)",
            (rule_name, _utcnow_iso(), json.dumps(payload, ensure_ascii=False) if payload else None),
        )

    def last_fire(self, rule_name: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM rule_fires WHERE rule_name=? ORDER BY fired_at DESC LIMIT 1",
            (rule_name,),
        ).fetchone()

    def close(self) -> None:
        self.conn.close()


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database(settings.db_path)
    return _db
