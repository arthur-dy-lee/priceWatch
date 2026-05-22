from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pricewatch.signals import Signal, SignalKind
from pricewatch.storage.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)


def make_signal(source: str, value: float, ts: datetime,
                kind: SignalKind = SignalKind.PRICE,
                meta: dict | None = None) -> Signal:
    return Signal(
        kind=kind,
        source=source,
        id="test",
        value=value,
        currency="CNY",
        ts=ts,
        meta=meta or {},
    )


@pytest.fixture
def seeded_db(db: Database, now: datetime) -> Database:
    """A source 'foo' with 35 daily snapshots, value decreasing from 1500 to 1150."""
    for i in range(35, 0, -1):
        ts = now - timedelta(days=i)
        value = 1500 - (35 - i) * 10  # 1150 -> 1500 going backward
        db.insert_snapshot(make_signal("foo", value, ts))
    # latest snapshot at "now": 1150
    db.insert_snapshot(make_signal("foo", 1150.0, now))
    return db
