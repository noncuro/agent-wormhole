import json
import pytest
import stat
from agent_wormhole.trust import TrustStore, Peer


def test_add_and_lookup(tmp_path):
    store = TrustStore(tmp_path / "trust.json")
    store.add(Peer(pubkey="aa" * 32, name="alice", relays=["wss://r1"]))
    assert store.by_name("alice").pubkey == "aa" * 32
    assert store.by_pubkey("aa" * 32).name == "alice"


def test_persists_across_instances(tmp_path):
    path = tmp_path / "trust.json"
    a = TrustStore(path)
    a.add(Peer(pubkey="bb" * 32, name="bob", relays=[]))
    b = TrustStore(path)
    assert b.by_name("bob").pubkey == "bb" * 32


def test_file_mode_is_0600(tmp_path):
    path = tmp_path / "trust.json"
    store = TrustStore(path)
    store.add(Peer(pubkey="cc" * 32, name="c", relays=[]))
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_remove(tmp_path):
    store = TrustStore(tmp_path / "trust.json")
    store.add(Peer(pubkey="dd" * 32, name="d", relays=[]))
    store.remove("d")
    assert store.by_name("d") is None


def test_name_collision_raises(tmp_path):
    store = TrustStore(tmp_path / "trust.json")
    store.add(Peer(pubkey="11" * 32, name="alice", relays=[]))
    with pytest.raises(ValueError):
        store.add(Peer(pubkey="22" * 32, name="alice", relays=[]))


@pytest.mark.parametrize("name", ["../alice", "/tmp/alice", "..", "alice/keys"])
def test_path_like_peer_name_raises(tmp_path, name):
    store = TrustStore(tmp_path / "trust.json")
    with pytest.raises(ValueError):
        store.add(Peer(pubkey="11" * 32, name=name, relays=[]))


def test_malformed_file_raises(tmp_path):
    path = tmp_path / "trust.json"
    path.write_text("not json")
    with pytest.raises(ValueError):
        TrustStore(path)


def test_list_peers(tmp_path):
    store = TrustStore(tmp_path / "trust.json")
    store.add(Peer(pubkey="11" * 32, name="a", relays=[]))
    store.add(Peer(pubkey="22" * 32, name="b", relays=[]))
    names = sorted(p.name for p in store.all())
    assert names == ["a", "b"]
