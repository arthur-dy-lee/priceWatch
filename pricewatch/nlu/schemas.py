"""JSON schema + validator for intents produced by the LLM.

We keep the schema small and forgiving: anything the LLM hallucinates is
either coerced to a sane default or surfaced as a clear error.
"""
from __future__ import annotations

from typing import Any

from ..sources.registry import all_registered

# An intent is one of:
#
#   {
#     "action": "add_monitor",
#     "source": {"name": "...", "type": "...", "url": "...", "interval": "1h"},
#     "rules":  [{"name": "...", "when": "...", "notify": ["telegram"], "cooldown": "6h"}, ...]
#   }
#
# or:
#
#   {"action": "remove_monitor", "name": "..."}
#
# Any extra keys are stripped silently.


ALLOWED_NOTIFY = {"telegram", "telegram_matrixapps", "macos"}


def validate_intent(obj: Any) -> dict:
    """Raise ValueError on malformed intent. Returns a normalized copy."""
    if not isinstance(obj, dict):
        raise ValueError(f"intent must be an object, got {type(obj).__name__}")
    action = obj.get("action")
    if action not in {"add_monitor", "remove_monitor"}:
        raise ValueError(f"unknown action: {action!r}")

    if action == "remove_monitor":
        name = obj.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("remove_monitor requires non-empty 'name'")
        return {"action": "remove_monitor", "name": name}

    # add_monitor
    src = obj.get("source")
    if not isinstance(src, dict):
        raise ValueError("add_monitor requires 'source' object")
    out_src: dict[str, Any] = {}
    out_src["name"] = _require_str(src, "name")
    out_src["type"] = _require_str(src, "type")
    if out_src["type"] not in all_registered():
        raise ValueError(
            f"unknown source type {out_src['type']!r}; known: {sorted(all_registered())}"
        )
    out_src["interval"] = src.get("interval") or "1h"
    for k in ("url", "sku"):
        v = src.get(k)
        if v:
            out_src[k] = v

    rules_in = obj.get("rules") or []
    if not isinstance(rules_in, list) or not rules_in:
        raise ValueError("add_monitor requires non-empty 'rules' list")
    out_rules: list[dict] = []
    for r in rules_in:
        if not isinstance(r, dict):
            raise ValueError("each rule must be an object")
        out_rules.append({
            "name": _require_str(r, "name"),
            "when": _require_str(r, "when"),
            "notify": _sanitize_notify(r.get("notify") or ["telegram"]),
            "cooldown": r.get("cooldown") or "6h",
            "debounce": r.get("debounce"),
            "message": r.get("message"),
        })

    return {"action": "add_monitor", "source": out_src, "rules": out_rules}


def _require_str(d: dict, key: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"missing or empty string field {key!r}")
    return v.strip()


def _sanitize_notify(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return ["telegram"]
    out = [str(x) for x in raw if isinstance(x, str) and x in ALLOWED_NOTIFY]
    return out or ["telegram"]
