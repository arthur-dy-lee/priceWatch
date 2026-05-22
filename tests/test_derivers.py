from __future__ import annotations

import pytest

from pricewatch.rules.derivers import SourceView, parse_duration
from pricewatch.signals import SignalKind


def test_parse_duration():
    assert parse_duration("30s").total_seconds() == 30
    assert parse_duration("15m").total_seconds() == 900
    assert parse_duration("1h").total_seconds() == 3600
    assert parse_duration("7d").total_seconds() == 7 * 86400
    with pytest.raises(ValueError):
        parse_duration("nope")


def test_view_basic_fields(seeded_db, now):
    v = SourceView(seeded_db, "foo", SignalKind.PRICE, now=now)
    assert v.price == 1150.0
    assert v.value == 1150.0
    assert v.ts is not None


def test_view_min_max_window(seeded_db, now):
    v = SourceView(seeded_db, "foo", SignalKind.PRICE, now=now)
    # latest is 1150; values decrease as we go forward in time, so 7d window
    # contains the lowest values.
    assert v.min_7d <= v.min_30d
    assert v.max_30d >= v.max_7d


def test_view_pct_change(seeded_db, now):
    v = SourceView(seeded_db, "foo", SignalKind.PRICE, now=now)
    # 7d ago value ~ 1220, now 1150 -> roughly -5.7%
    assert v.pct_change_7d < 0
    assert -10 < v.pct_change_7d < 0


def test_view_drop_from_max_30d(seeded_db, now):
    v = SourceView(seeded_db, "foo", SignalKind.PRICE, now=now)
    # cur=1150, max_30d should be near 1500 -> drop ~ -23%
    assert v.drop_from_max_30d < -10


def test_view_empty_source(db, now):
    v = SourceView(db, "nonexistent", SignalKind.PRICE, now=now)
    assert v.price is None
    assert v.pct_change_7d is None
