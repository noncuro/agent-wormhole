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
