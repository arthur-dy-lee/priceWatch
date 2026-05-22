from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..signals import Signal, SignalKind


class Source(ABC):
    """Adapter for one logical data source: scrape/api/etc., emit a Signal.

    Subclasses are registered under a string `type` used in config.yaml.
    Each configured source becomes one Source instance with its own `name`
    (e.g. "nb_993_grey") and `cfg` (the rest of the yaml block).
    """

    # Domain this source produces; subclasses override.
    kind: SignalKind = SignalKind.PRICE

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        self.name = name
        self.cfg = cfg

    @abstractmethod
    async def fetch(self) -> Signal:
        """Return one Signal snapshot. Raise on failure — caller handles retries."""

    @property
    def interval(self) -> str:
        """Polling interval from config, e.g. '30m', '1h'. Default 1h."""
        return str(self.cfg.get("interval", "1h"))
