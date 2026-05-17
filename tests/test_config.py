import json
import os
import pytest
from agent_wormhole.config import resolve_relays, DEFAULT_RELAYS


def test_defaults_when_nothing_set(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_WORMHOLE_RELAYS", raising=False)
    assert resolve_relays(config_path=tmp_path / "missing.json") == DEFAULT_RELAYS


def test_env_overrides_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORMHOLE_RELAYS", "wss://a,wss://b")
    assert resolve_relays(config_path=tmp_path / "missing.json") == ["wss://a", "wss://b"]


def test_file_overrides_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_WORMHOLE_RELAYS", raising=False)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"relays": ["wss://x"]}))
    assert resolve_relays(config_path=cfg) == ["wss://x"]


def test_env_beats_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORMHOLE_RELAYS", "wss://from-env")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"relays": ["wss://from-file"]}))
    assert resolve_relays(config_path=cfg) == ["wss://from-env"]


def test_env_strips_whitespace(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_WORMHOLE_RELAYS", " wss://a , wss://b ")
    assert resolve_relays(config_path=tmp_path / "x.json") == ["wss://a", "wss://b"]
