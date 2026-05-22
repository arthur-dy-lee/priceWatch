"""Programmatic, comment-preserving edits to config.yaml.

Used by:
  * CLI subcommands (`pricewatch add-source`, ...)
  * HTTP IPC layer (matrixApps / external callers)
  * NLU intent parser (after the LLM produces structured JSON)

Every mutation funnels through here so we have one place to enforce
validation, name-uniqueness, and atomic writes.
"""
from __future__ import annotations

from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .config_loader import dump_raw, load_raw
from .sources.registry import all_registered


class ConfigError(ValueError):
    """Raised on duplicate names, unknown source types, malformed input."""


def _ensure_block(doc: CommentedMap, key: str, kind: type) -> Any:
    """Make sure doc[key] exists as the expected ruamel container."""
    if key not in doc or doc[key] is None:
        doc[key] = kind()
    return doc[key]


def _exists(seq: CommentedSeq, name: str) -> bool:
    return any(isinstance(x, dict) and x.get("name") == name for x in seq)


def _remove_by_name(seq: CommentedSeq, name: str) -> bool:
    for i, x in enumerate(seq):
        if isinstance(x, dict) and x.get("name") == name:
            del seq[i]
            return True
    return False


# ----------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------


def add_source(name: str, type_: str, *, interval: str = "1h", **cfg: Any) -> None:
    """Append a new source. Raises ConfigError on duplicate or unknown type."""
    if type_ not in all_registered():
        raise ConfigError(
            f"unknown source type '{type_}'. known: {', '.join(all_registered()) or '(none)'}"
        )
    doc = load_raw()
    sources = _ensure_block(doc, "sources", CommentedSeq)
    if _exists(sources, name):
        raise ConfigError(f"source '{name}' already exists")
    entry = CommentedMap()
    entry["name"] = name
    entry["type"] = type_
    entry["interval"] = interval
    for k, v in cfg.items():
        if v is not None:
            entry[k] = v
    sources.append(entry)
    dump_raw(doc)


def remove_source(name: str) -> bool:
    doc = load_raw()
    sources = doc.get("sources") or []
    removed = _remove_by_name(sources, name) if sources else False
    if removed:
        dump_raw(doc)
    return removed


def list_sources() -> list[dict]:
    doc = load_raw()
    return [dict(s) for s in (doc.get("sources") or [])]


# ----------------------------------------------------------------------
# Rules
# ----------------------------------------------------------------------


def add_rule(
    name: str,
    when: str,
    *,
    notify: list[str] | None = None,
    cooldown: str | None = None,
    debounce: str | None = None,
    message: str | None = None,
) -> None:
    if not when.strip():
        raise ConfigError("rule 'when' expression cannot be empty")
    doc = load_raw()
    rules = _ensure_block(doc, "rules", CommentedSeq)
    if _exists(rules, name):
        raise ConfigError(f"rule '{name}' already exists")
    entry = CommentedMap()
    entry["name"] = name
    entry["when"] = when
    if notify:
        entry["notify"] = list(notify)
    if cooldown:
        entry["cooldown"] = cooldown
    if debounce:
        entry["debounce"] = debounce
    if message:
        entry["message"] = message
    rules.append(entry)
    dump_raw(doc)


def remove_rule(name: str) -> bool:
    doc = load_raw()
    rules = doc.get("rules") or []
    removed = _remove_by_name(rules, name) if rules else False
    if removed:
        dump_raw(doc)
    return removed


def list_rules() -> list[dict]:
    doc = load_raw()
    return [dict(r) for r in (doc.get("rules") or [])]


# ----------------------------------------------------------------------
# Bulk apply — used by NLU pipeline
# ----------------------------------------------------------------------


def apply_intent(intent: dict) -> dict:
    """Apply a structured intent (see nlu.schemas.Intent).

    Returns a dict describing what changed, suitable for surfacing back
    to the user.
    """
    action = intent.get("action")
    changed = {"action": action, "added_sources": [], "added_rules": [],
               "removed_sources": [], "removed_rules": []}

    if action == "add_monitor":
        src = intent["source"]
        add_source(src["name"], src["type"],
                   interval=src.get("interval", "1h"),
                   **{k: v for k, v in src.items()
                      if k not in ("name", "type", "interval")})
        changed["added_sources"].append(src["name"])

        for r in intent.get("rules", []):
            add_rule(r["name"], r["when"],
                     notify=r.get("notify"),
                     cooldown=r.get("cooldown"),
                     debounce=r.get("debounce"),
                     message=r.get("message"))
            changed["added_rules"].append(r["name"])
        return changed

    if action == "remove_monitor":
        name = intent["name"]
        if remove_source(name):
            changed["removed_sources"].append(name)
        # Also drop any rules that only reference this source.
        for r in list_rules():
            if name in (r.get("when") or "") and remove_rule(r["name"]):
                changed["removed_rules"].append(r["name"])
        return changed

    raise ConfigError(f"unknown intent action: {action!r}")
