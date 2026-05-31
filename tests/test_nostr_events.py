import json
import time
import pytest
from agent_wormhole.identity import load_or_create
from agent_wormhole.nostr.events import (
    Event,
    build_event,
    serialize_for_id,
    verify_event,
)


def test_serialize_for_id_is_deterministic():
    s = serialize_for_id(
        pubkey="aa" * 32,
        created_at=1700000000,
        kind=1,
        tags=[["p", "bb" * 32]],
        content="hi",
    )
    assert s == json.dumps(
        [0, "aa" * 32, 1700000000, 1, [["p", "bb" * 32]], "hi"],
        separators=(",", ":"),
        ensure_ascii=False,
    )


def test_build_event_round_trips(tmp_path):
    ident = load_or_create(tmp_path / "k")
    ev = build_event(ident, kind=1, tags=[], content="hello", created_at=1700000000)
    assert ev.pubkey == ident.pubkey_hex
    assert ev.kind == 1
    assert ev.content == "hello"
    assert len(ev.id) == 64
    assert len(ev.sig) == 128
    assert verify_event(ev) is True


def test_verify_rejects_tampered_content(tmp_path):
    ident = load_or_create(tmp_path / "k")
    ev = build_event(ident, kind=1, tags=[], content="hello")
    bad = Event(**{**ev.__dict__, "content": "goodbye"})
    assert verify_event(bad) is False


from agent_wormhole.nostr.events import (
    build_giftwrapped_dm,
    unwrap_giftwrapped_dm,
)
from agent_wormhole.identity import load_or_create as _load


def test_giftwrap_roundtrip(tmp_path):
    sender = _load(tmp_path / "s")
    recipient = _load(tmp_path / "r")

    wrap = build_giftwrapped_dm(
        sender=sender,
        recipient_pubkey_hex=recipient.pubkey_hex,
        content="hi alice",
    )

    assert wrap.kind == 1059
    assert ["p", recipient.pubkey_hex] in wrap.tags
    assert wrap.pubkey != sender.pubkey_hex

    sender_pub, plaintext = unwrap_giftwrapped_dm(wrap, recipient=recipient)
    assert sender_pub == sender.pubkey_hex
    assert plaintext == "hi alice"


def test_giftwrap_rejects_wrong_recipient(tmp_path):
    sender = _load(tmp_path / "s")
    intended = _load(tmp_path / "r1")
    stranger = _load(tmp_path / "r2")

    wrap = build_giftwrapped_dm(
        sender=sender,
        recipient_pubkey_hex=intended.pubkey_hex,
        content="secret",
    )
    with pytest.raises(ValueError):
        unwrap_giftwrapped_dm(wrap, recipient=stranger)
