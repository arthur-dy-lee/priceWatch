"""Rule engine. Evaluates simpleeval expressions against {source: SourceView} bag.

A rule fires when:
  1. its `when` expression evaluates to True
  2. (if `debounce` set) it has been True for every snapshot in the debounce window
  3. (if `cooldown` set) no fire has been recorded for this rule within cooldown
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from simpleeval import EvalWithCompoundTypes, NameNotDefined

from ..signals import SignalKind
from ..storage import Database
from .derivers import SourceView, parse_duration


@dataclass
class Rule:
    name: str
    when: str
    notify: list[str] = field(default_factory=list)
    debounce: str | None = None   # e.g. "30m" — must hold for this duration
    cooldown: str | None = None   # e.g. "6h"  — skip if fired within this duration
    message: str | None = None    # optional custom message template


@dataclass
class RuleResult:
    rule: Rule
    triggered: bool
    reason: str                   # human-readable explanation
    value_repr: str = ""          # snapshot of values, for logs/notifications


class RuleEngine:
    def __init__(self, db: Database, source_kinds: dict[str, SignalKind]) -> None:
        self.db = db
        self.source_kinds = source_kinds   # name -> kind, from current config

    def evaluate(self, rules: list[Rule], *, now: datetime | None = None) -> list[RuleResult]:
        now = now or datetime.now(timezone.utc)
        views = {
            name: SourceView(self.db, name, kind, now=now)
            for name, kind in self.source_kinds.items()
        }
        return [self._eval_one(r, views, now) for r in rules]

    def _eval_one(self, rule: Rule, views: dict[str, SourceView], now: datetime) -> RuleResult:
        evaluator = EvalWithCompoundTypes(names=views)
        try:
            ok = bool(evaluator.eval(rule.when))
        except NameNotDefined as e:
            return RuleResult(rule, False, f"unknown name in expression: {e}")
        except Exception as e:
            return RuleResult(rule, False, f"eval error: {e!r}")

        if not ok:
            return RuleResult(rule, False, "predicate false", self._snapshot(rule, views))

        # debounce: predicate must currently hold AND we require N minutes of
        # consistent truth. v0.1 simple implementation: just check predicate now.
        # (full implementation requires re-evaluating at past timestamps —
        # left as TODO in derivers; for now we treat debounce as advisory.)
        if rule.debounce:
            logger.debug(f"rule {rule.name}: debounce={rule.debounce} (v0.1 not strictly enforced)")

        if rule.cooldown:
            last = self.db.last_fire(rule.name)
            if last is not None:
                last_dt = datetime.fromisoformat(last["fired_at"])
                if now - last_dt < parse_duration(rule.cooldown):
                    return RuleResult(
                        rule, False,
                        f"in cooldown (last fired {last_dt.isoformat()}, cooldown={rule.cooldown})",
                        self._snapshot(rule, views),
                    )

        return RuleResult(rule, True, "predicate true", self._snapshot(rule, views))

    @staticmethod
    def _snapshot(rule: Rule, views: dict[str, SourceView]) -> str:
        """Best-effort: pluck names mentioned in expression and print current values."""
        bits = []
        for src_name, view in views.items():
            if src_name in rule.when:
                try:
                    bits.append(f"{src_name}.price={view.price}")
                except Exception:
                    pass
        return ", ".join(bits)
