"""Derived-field computation. Reads SQLite history on demand; nothing is materialized.

A `SourceView` is a lazy attribute-bag that exposes the field set for one source.
The rule engine builds {source_name: SourceView} and hands it to simpleeval as
`names`, so expressions like `nb_993_grey.pct_change_7d` resolve naturally.

Field set is determined by SignalKind:
  - all kinds:  price, price_prev, ts, pct_change_1d, pct_change_7d, pct_change_30d,
                min_7d, max_7d, min_30d, max_30d, avg_7d, avg_30d, min_all, max_all,
                drop_from_max_30d
  - stock kind: additionally exposes meta keys: open, close, high, low, volume, pe,
                market_cap (read from snapshot.meta_json if present)
  - odds kind:  additionally exposes meta keys: implied_prob, book
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ..signals import SignalKind
from ..storage import Database

# ---- duration parsing ----------------------------------------------------

_DUR_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$")


def parse_duration(s: str) -> timedelta:
    """'30s' / '15m' / '1h' / '7d' -> timedelta."""
    m = _DUR_RE.match(s)
    if not m:
        raise ValueError(f"bad duration: {s!r}")
    n, unit = int(m.group(1)), m.group(2)
    return {
        "s": timedelta(seconds=n),
        "m": timedelta(minutes=n),
        "h": timedelta(hours=n),
        "d": timedelta(days=n),
    }[unit]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---- common (price-like) field set --------------------------------------

_COMMON_FIELDS: tuple[str, ...] = (
    "value", "price",
    "price_prev", "value_prev",
    "ts",
    "pct_change_1d", "pct_change_7d", "pct_change_30d",
    "min_7d", "max_7d", "avg_7d",
    "min_30d", "max_30d", "avg_30d",
    "min_all", "max_all",
    "drop_from_max_30d",
)

_STOCK_META_FIELDS: tuple[str, ...] = (
    "open", "close", "high", "low", "volume", "pe", "market_cap",
)

_ODDS_META_FIELDS: tuple[str, ...] = (
    "implied_prob", "book",
)


def fields_for(kind: SignalKind) -> tuple[str, ...]:
    """Public: which fields a kind exposes. Used by CLI `pricewatch fields`."""
    extra: tuple[str, ...] = ()
    if kind == SignalKind.STOCK:
        extra = _STOCK_META_FIELDS
    elif kind == SignalKind.ODDS:
        extra = _ODDS_META_FIELDS
    return _COMMON_FIELDS + extra


# ---- the lazy view ------------------------------------------------------


class SourceView:
    """Attribute access -> derived field. Cached per evaluation pass."""

    def __init__(self, db: Database, source: str, kind: SignalKind, now: datetime | None = None):
        self._db = db
        self._source = source
        self._kind = kind
        self._now = now or _utcnow()
        self._cache: dict[str, Any] = {}
        self._latest_row = db.latest(source)
        self._meta = self._load_meta(self._latest_row)

    @staticmethod
    def _load_meta(row) -> dict:
        if row and row["meta_json"]:
            try:
                return json.loads(row["meta_json"])
            except Exception:
                return {}
        return {}

    # ---- public field accessors ----

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._cache:
            return self._cache[name]
        val = self._compute(name)
        self._cache[name] = val
        return val

    def available_fields(self) -> list[str]:
        return list(fields_for(self._kind))

    def snapshot_summary(self) -> dict[str, Any]:
        """For CLI introspection — eagerly compute every field."""
        return {f: getattr(self, f) for f in self.available_fields()}

    # ---- compute one field ----

    def _compute(self, name: str) -> Any:
        if self._latest_row is None:
            return None

        if name in ("value", "price"):
            return float(self._latest_row["value"])
        if name == "ts":
            return self._latest_row["ts"]

        if name in ("value_prev", "price_prev"):
            rows = self._db.latest_n(self._source, 2)
            return float(rows[1]["value"]) if len(rows) >= 2 else None

        if name.startswith("pct_change_"):
            days = self._parse_days(name[len("pct_change_"):])
            return self._pct_change(days)

        if name.startswith("min_") or name.startswith("max_") or name.startswith("avg_"):
            return self._agg(name)

        if name == "drop_from_max_30d":
            cur = self._compute("price")
            mx = self._compute("max_30d")
            if cur is None or mx is None or mx == 0:
                return None
            return (cur - mx) / mx * 100.0

        # stock/odds meta passthrough
        if self._kind == SignalKind.STOCK and name in _STOCK_META_FIELDS:
            return self._meta.get(name)
        if self._kind == SignalKind.ODDS and name in _ODDS_META_FIELDS:
            return self._meta.get(name)

        raise AttributeError(f"{self._source} has no field '{name}'")

    # ---- helpers ----

    @staticmethod
    def _parse_days(suffix: str) -> int:
        # '1d' -> 1, '7d' -> 7
        if not suffix.endswith("d"):
            raise AttributeError(f"unsupported window '{suffix}'")
        return int(suffix[:-1])

    def _pct_change(self, days: int) -> float | None:
        cur = self._compute("price")
        if cur is None:
            return None
        cutoff = (self._now - timedelta(days=days)).isoformat()
        baseline = self._db.closest_before_or_at(self._source, cutoff)
        if baseline is None or baseline["value"] == 0:
            return None
        return (cur - baseline["value"]) / baseline["value"] * 100.0

    def _agg(self, name: str) -> float | None:
        """min_7d / max_30d / avg_7d / min_all / max_all."""
        op, _, window = name.partition("_")
        if window == "all":
            rows = self._db.window(self._source, "0000-01-01T00:00:00+00:00")
        else:
            days = self._parse_days(window)
            since = (self._now - timedelta(days=days)).isoformat()
            rows = self._db.window(self._source, since)
        if not rows:
            return None
        vals = [r["value"] for r in rows]
        return {
            "min": min(vals),
            "max": max(vals),
            "avg": sum(vals) / len(vals),
        }[op]
