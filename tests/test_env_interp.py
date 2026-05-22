from __future__ import annotations

import os
import textwrap

import pytest

from pricewatch.config_loader import load_config


def test_var_expansion(monkeypatch, tmp_path):
    """${VAR} in yaml strings should be replaced from the process env."""
    monkeypatch.setenv("PW_TEST_TOKEN", "secret-123")
    monkeypatch.setenv("PW_TEST_CHAT", "789")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(textwrap.dedent("""
        sources: []
        rules: []
        notifiers:
          telegram:
            type: telegram
            token: ${PW_TEST_TOKEN}
            chat_id: ${PW_TEST_CHAT}
    """).strip(), encoding="utf-8")

    cfg = load_config(cfg_path)
    assert cfg.notifiers["telegram"]["token"] == "secret-123"
    assert cfg.notifiers["telegram"]["chat_id"] == "789"


def test_missing_var_expands_to_empty(monkeypatch, tmp_path):
    """Missing env vars expand to empty string, not to the literal placeholder."""
    monkeypatch.delenv("PW_TEST_MISSING", raising=False)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(textwrap.dedent("""
        sources: []
        rules: []
        notifiers:
          telegram:
            type: telegram
            token: ${PW_TEST_MISSING}
    """).strip(), encoding="utf-8")

    cfg = load_config(cfg_path)
    assert cfg.notifiers["telegram"]["token"] == ""
