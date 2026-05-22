"""Unified Signal schema. All sources emit Signal instances regardless of domain."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SignalKind(str, Enum):
    PRICE = "price"   # consumer goods: NB, JD, Taobao, ...
    STOCK = "stock"   # equities: A-shares, US stocks
    ODDS = "odds"     # bookmaker odds

    @classmethod
    def from_str(cls, raw: str) -> "SignalKind":
        return cls(raw.lower())


@dataclass(frozen=True)
class Signal:
    """One observation at one point in time, normalized across all sources."""

    kind: SignalKind
    source: str            # logical source name from config, e.g. "nb_993_grey"
    id: str                # canonical id within the source's domain (SKU, ticker, match+book)
    value: float           # the headline number (price / share-price / odds)
    ts: datetime           # observation time, always UTC
    currency: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            object.__setattr__(self, "ts", self.ts.replace(tzinfo=timezone.utc))
