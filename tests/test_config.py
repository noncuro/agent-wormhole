"""Tests for config module and relay/direct code format handling."""
import os
import pytest

from agent_wormhole.config import DEFAULT_RELAY_URL, get_relay_url
from agent_wormhole.wordlist import (
    generate_code,
    generate_relay_code,
    parse_code,
    WORDS,
)


def test_default_relay_url():
    assert DEFAULT_RELAY_URL.startswith("wss://")


def test_get_relay_url_default():
    url = get_relay_url()
    assert url == DEFAULT_RELAY_URL


def test_get_relay_url_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_WORMHOLE_RELAY_URL", "wss://custom.example.com")
    assert get_relay_url() == "wss://custom.example.com"


def test_generate_relay_code_format():
    code = generate_relay_code()
    parts = code.split("-")
    assert len(parts) == 3
    assert all(p in WORDS for p in parts)


def test_generate_relay_code_no_port_prefix():
    code = generate_relay_code()
    # First part should NOT be numeric
    assert not code.split("-")[0].isdigit()


def test_generate_direct_code_has_port():
    code = generate_code(port=9999)
    parts = code.split("-")
    assert len(parts) == 4
    assert parts[0] == "9999"


def test_parse_code_direct_format():
    port, code, hostname = parse_code("9471-alpha-bravo-charlie@myhost")
    assert port == 9471
    assert code == "9471-alpha-bravo-charlie"
    assert hostname == "myhost"


def test_parse_code_relay_format():
    port, code, hostname = parse_code("alpha-bravo-charlie")
    assert port is None
    assert code == "alpha-bravo-charlie"
    assert hostname is None


def test_parse_code_relay_format_no_hostname():
    """Relay codes should not require a hostname."""
    port, code, hostname = parse_code("alpha-bravo-charlie")
    assert port is None
    assert hostname is None


def test_parse_code_detects_direct_vs_relay():
    """First segment numeric = direct mode, otherwise relay."""
    _, direct_code, _ = parse_code("1234-a-b-c@host")
    assert direct_code == "1234-a-b-c"

    _, relay_code, _ = parse_code("a-b-c")
    assert relay_code == "a-b-c"
