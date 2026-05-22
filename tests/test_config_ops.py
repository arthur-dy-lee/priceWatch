from __future__ import annotations

import textwrap

import pytest

from pricewatch import config_loader, config_ops


SEED = textwrap.dedent("""
    # priceWatch config — user-editable.
    sources:
      # the 993 is iconic
      - name: nb_993_grey
        type: newbalance
        url: https://example.com/993
        interval: 1h

    rules:
      - name: 993 跌破 1000
        when: "nb_993_grey.price < 1000"
        notify: [telegram]
        cooldown: 6h

    notifiers:
      telegram:
        type: telegram
        token: x
""").strip() + "\n"


@pytest.fixture(autouse=True)
def patch_config_path(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(SEED, encoding="utf-8")
    monkeypatch.setattr(config_loader, "CONFIG_PATH", cfg)
    monkeypatch.setattr(config_ops, "load_raw",
                        lambda path=None: config_loader.load_raw(cfg if path is None else path))
    monkeypatch.setattr(config_ops, "dump_raw",
                        lambda data, path=None: config_loader.dump_raw(data, cfg if path is None else path))
    yield


def test_add_source_appends_and_keeps_comments():
    config_ops.add_source("nb_rebel_v5", "newbalance",
                          url="https://example.com/rebel", interval="1h")
    text = config_loader.CONFIG_PATH.read_text(encoding="utf-8")
    assert "nb_rebel_v5" in text
    assert "the 993 is iconic" in text   # comment preserved
    sources = config_ops.list_sources()
    assert {s["name"] for s in sources} == {"nb_993_grey", "nb_rebel_v5"}


def test_add_source_rejects_duplicate():
    with pytest.raises(config_ops.ConfigError):
        config_ops.add_source("nb_993_grey", "newbalance", url="x")


def test_add_source_rejects_unknown_type():
    with pytest.raises(config_ops.ConfigError):
        config_ops.add_source("foo", "unknown_type", url="x")


def test_remove_source_returns_bool():
    assert config_ops.remove_source("nb_993_grey") is True
    assert config_ops.remove_source("nb_993_grey") is False
    assert config_ops.list_sources() == []


def test_add_rule_and_round_trip():
    config_ops.add_rule("test rule", "nb_993_grey.price < 500",
                        notify=["telegram"], cooldown="6h")
    rules = config_ops.list_rules()
    names = [r["name"] for r in rules]
    assert "test rule" in names


def test_add_rule_empty_when_rejected():
    with pytest.raises(config_ops.ConfigError):
        config_ops.add_rule("bad", "   ")


def test_apply_intent_add_monitor():
    intent = {
        "action": "add_monitor",
        "source": {
            "name": "nb_550",
            "type": "newbalance",
            "url": "https://example.com/550",
            "interval": "1h",
        },
        "rules": [
            {"name": "550 cheap", "when": "nb_550.price < 100",
             "notify": ["telegram"], "cooldown": "6h"},
        ],
    }
    changed = config_ops.apply_intent(intent)
    assert "nb_550" in changed["added_sources"]
    assert "550 cheap" in changed["added_rules"]


def test_apply_intent_remove_monitor_drops_dependent_rule():
    config_ops.apply_intent({
        "action": "add_monitor",
        "source": {"name": "nb_550", "type": "newbalance",
                   "url": "https://example.com/550"},
        "rules": [{"name": "550 cheap", "when": "nb_550.price < 100"}],
    })
    changed = config_ops.apply_intent({"action": "remove_monitor", "name": "nb_550"})
    assert "nb_550" in changed["removed_sources"]
    assert "550 cheap" in changed["removed_rules"]
