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


def test_send_file_fails_when_no_relay_accepts_offer(tmp_path, monkeypatch):
    from agent_wormhole.identity import load_or_create
    from agent_wormhole.trust import Peer, TrustStore

    monkeypatch.setenv("AGENT_WORMHOLE_HOME", str(tmp_path))
    peer = load_or_create(tmp_path / "peer.key")
    TrustStore(tmp_path / "trusted_peers.json").add(
        Peer(pubkey=peer.pubkey_hex, name="bob", relays=["wss://relay"])
    )
    payload = tmp_path / "payload.txt"
    payload.write_text("secret")

    class FakeRelayPool:
        def __init__(self, relays):
            self.relays = relays

        async def connect(self):
            pass

        async def publish(self, ev):
            return {"wss://relay": False}

        async def close(self):
            pass

    async def fake_send_file(*, path, on_code):
        await on_code("4-foo-bar")

    monkeypatch.setattr("agent_wormhole.nostr.client.RelayPool", FakeRelayPool)
    monkeypatch.setattr("agent_wormhole.bulk.send_file", fake_send_file)

    result = runner.invoke(app, ["send-file", "bob", str(payload)])

    assert result.exit_code == 2
    assert "no relay accepted the file offer" in result.stderr
