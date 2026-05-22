from __future__ import annotations

import pytest

from pricewatch.nlu.schemas import validate_intent


def test_validate_add_monitor_minimum():
    out = validate_intent({
        "action": "add_monitor",
        "source": {"name": "nb_x", "type": "newbalance", "url": "https://x"},
        "rules": [{"name": "r", "when": "nb_x.price < 100"}],
    })
    assert out["action"] == "add_monitor"
    assert out["source"]["interval"] == "1h"      # defaulted
    assert out["rules"][0]["notify"] == ["telegram"]    # defaulted
    assert out["rules"][0]["cooldown"] == "6h"          # defaulted


def test_validate_remove_monitor():
    out = validate_intent({"action": "remove_monitor", "name": "nb_x"})
    assert out == {"action": "remove_monitor", "name": "nb_x"}


def test_unknown_action_rejected():
    with pytest.raises(ValueError):
        validate_intent({"action": "burn_it_down"})


def test_unknown_source_type_rejected():
    with pytest.raises(ValueError):
        validate_intent({
            "action": "add_monitor",
            "source": {"name": "x", "type": "ftxprime", "url": "https://x"},
            "rules": [{"name": "r", "when": "x.price < 1"}],
        })


def test_notify_sanitized():
    out = validate_intent({
        "action": "add_monitor",
        "source": {"name": "nb_x", "type": "newbalance", "url": "https://x"},
        "rules": [{"name": "r", "when": "nb_x.price < 1",
                   "notify": ["telegram", "garbage", "macos"]}],
    })
    assert set(out["rules"][0]["notify"]) == {"telegram", "macos"}


def test_empty_rules_rejected():
    with pytest.raises(ValueError):
        validate_intent({
            "action": "add_monitor",
            "source": {"name": "nb_x", "type": "newbalance", "url": "https://x"},
            "rules": [],
        })
