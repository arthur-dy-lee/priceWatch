from __future__ import annotations

from pricewatch.rules.engine import Rule, RuleEngine
from pricewatch.signals import SignalKind


def test_rule_triggers_when_predicate_true(seeded_db, now):
    engine = RuleEngine(seeded_db, {"foo": SignalKind.PRICE})
    res = engine.evaluate([Rule(name="r1", when="foo.price < 2000")], now=now)[0]
    assert res.triggered is True


def test_rule_does_not_trigger_when_false(seeded_db, now):
    engine = RuleEngine(seeded_db, {"foo": SignalKind.PRICE})
    res = engine.evaluate([Rule(name="r1", when="foo.price > 9999")], now=now)[0]
    assert res.triggered is False


def test_rule_unknown_name_does_not_crash(seeded_db, now):
    engine = RuleEngine(seeded_db, {"foo": SignalKind.PRICE})
    res = engine.evaluate([Rule(name="r1", when="bar.price < 100")], now=now)[0]
    assert res.triggered is False
    assert "unknown" in res.reason.lower() or "name" in res.reason.lower()


def test_rule_combined_and_or(seeded_db, now):
    engine = RuleEngine(seeded_db, {"foo": SignalKind.PRICE})
    rule = Rule(name="combo", when="foo.price < 2000 and foo.pct_change_7d < 0")
    assert engine.evaluate([rule], now=now)[0].triggered is True


def test_cooldown_blocks_second_fire(seeded_db, now):
    engine = RuleEngine(seeded_db, {"foo": SignalKind.PRICE})
    rule = Rule(name="cd-rule", when="foo.price < 2000", cooldown="1h")
    res1 = engine.evaluate([rule], now=now)[0]
    assert res1.triggered is True
    # Caller records the fire after a trigger.
    seeded_db.record_fire("cd-rule")
    res2 = engine.evaluate([rule], now=now)[0]
    assert res2.triggered is False
    assert "cooldown" in res2.reason.lower()
