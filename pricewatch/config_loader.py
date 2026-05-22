"""Load config.yaml into typed objects. Supports ${VAR} env interpolation."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from .rules.engine import Rule
from .settings import PROJECT_ROOT

CONFIG_PATH = PROJECT_ROOT / "pricewatch" / "config.yaml"

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _yaml() -> YAML:
    """A round-trip parser that preserves comments and ordering."""
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _expand_vars(value: Any) -> Any:
    """Recursively expand ${VAR} references in strings. Missing vars -> ''."""
    if isinstance(value, str):
        return _VAR_RE.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand_vars(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_vars(v) for k, v in value.items()}
    return value


# ------------------------------------------------------------------------
# Typed wrappers
# ------------------------------------------------------------------------


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


# ------------------------------------------------------------------------
# Read
# ------------------------------------------------------------------------


def load_raw(path: str | Path | None = None) -> dict:
    """Round-trip read: returns ruamel CommentedMap with comments preserved.

    Useful for programmatic edits via config_ops. Does NOT expand ${VAR}.
    """
    p = Path(path) if path else CONFIG_PATH
    with p.open("r", encoding="utf-8") as f:
        return _yaml().load(f) or {}


def load_config(path: str | Path | None = None) -> Config:
    """Plain read: comments dropped, ${VAR} expanded, returned as typed objects."""
    raw = load_raw(path)
    raw = _expand_vars({k: v for k, v in raw.items()})

    sources = []
    for s in raw.get("sources", []) or []:
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
        for r in raw.get("rules", []) or []
    ]

    notifiers = raw.get("notifiers", {}) or {}
    return Config(sources=sources, rules=rules, notifiers=notifiers)


# ------------------------------------------------------------------------
# Write (atomic)
# ------------------------------------------------------------------------


def dump_raw(data: dict, path: str | Path | None = None) -> None:
    """Atomic write of a (ruamel) document back to disk."""
    p = Path(path) if path else CONFIG_PATH
    _normalize_for_dump(data)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        _yaml().dump(data, f)
    tmp.replace(p)


def _normalize_for_dump(data) -> None:
    """Ruamel emits `key:\\n  # comment\\n[]` for emptied block sequences — invalid YAML.

    Workaround: drop top-level mapping keys whose sequence value is empty.
    load_config() uses `.get(key, [])` so this is round-trip safe.
    """
    if not isinstance(data, dict):
        return
    for k in list(data.keys()):
        v = data[k]
        if isinstance(v, list) and len(v) == 0:
            del data[k]
        else:
            _normalize_for_dump(v)
