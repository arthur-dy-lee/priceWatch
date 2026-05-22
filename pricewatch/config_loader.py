"""Load config.yaml into typed objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .rules.engine import Rule
from .settings import PROJECT_ROOT


@dataclass
class SourceCfg:
    name: str
    type: str
    cfg: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    sources: list[SourceCfg]
    rules: list[Rule]
    notifiers: dict[str, dict[str, Any]]


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else PROJECT_ROOT / "pricewatch" / "config.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    sources = []
    for s in raw.get("sources", []):
        name = s["name"]
        type_ = s["type"]
        rest = {k: v for k, v in s.items() if k not in ("name", "type")}
        sources.append(SourceCfg(name=name, type=type_, cfg=rest))

    rules = [
        Rule(
            name=r["name"],
            when=r["when"],
            notify=list(r.get("notify", [])),
            debounce=r.get("debounce"),
            cooldown=r.get("cooldown"),
            message=r.get("message"),
        )
        for r in raw.get("rules", [])
    ]

    notifiers = raw.get("notifiers", {}) or {}
    return Config(sources=sources, rules=rules, notifiers=notifiers)
