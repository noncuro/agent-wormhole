from typer.testing import CliRunner
from agent_wormhole.cli import app


runner = CliRunner()


def test_help_lists_new_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    out = result.stdout
    for cmd in (
        "identity-envelope", "listen", "send", "send-file",
        "peers", "whoami", "trust", "untrust", "setup",
    ):
        assert cmd in out


def test_whoami_creates_identity_and_prints_pubkey(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORMHOLE_HOME", str(tmp_path))
    result = runner.invoke(app, ["whoami"])
    assert result.exit_code == 0
    assert "pubkey" in result.stdout.lower()
    assert (tmp_path / "identity.key").exists()


def test_identity_envelope_emits_valid_json(tmp_path, monkeypatch):
    import json as _json
    monkeypatch.setenv("AGENT_WORMHOLE_HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_WORMHOLE_RELAYS", "wss://a")
    result = runner.invoke(app, ["identity-envelope"])
    assert result.exit_code == 0
    payload = _json.loads(result.stdout.strip())
    assert payload["type"] == "identity"
    assert len(payload["pubkey"]) == 64
    assert payload["relays"] == ["wss://a"]
