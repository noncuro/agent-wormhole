import asyncio
import json

import pytest

from agent_wormhole import bulk
from agent_wormhole.identity import load_or_create
from agent_wormhole.nostr.client import RelayPool
from agent_wormhole.nostr.events import build_giftwrapped_dm
from agent_wormhole.pairing import (
    ACCEPT_TYPE,
    PROTOCOL_VERSION,
    _decode_accept,
    _slug,
    invite,
    join,
)
from agent_wormhole.trust import TrustStore
from tests.fake_relay import fake_relay

CODE = "7-foo-bar"


def _accept_wrap(sender, recipient_pub, *, nonce, claimed_pubkey=None, typ=ACCEPT_TYPE):
    body = {
        "type": typ,
        "v": PROTOCOL_VERSION,
        "pubkey": claimed_pubkey or sender.pubkey_hex,
        "name": "joiner-host",
        "relays": [],
        "nonce": nonce,
    }
    return build_giftwrapped_dm(
        sender=sender,
        recipient_pubkey_hex=recipient_pub,
        content=json.dumps(body),
    )


def test_slug():
    assert _slug("macbook pro") == "macbook-pro"
    assert _slug("Mac.lan") == "mac-lan"
    assert _slug("macbook-air") == "macbook-air"
    assert _slug("") == "peer"
    assert _slug("!!!") == "peer"


@pytest.mark.asyncio
async def test_decode_accept_accepts_matching_nonce(tmp_path):
    me = load_or_create(tmp_path / "me")
    sender = load_or_create(tmp_path / "sender")
    wrap = _accept_wrap(sender, me.pubkey_hex, nonce="abc123")

    result = _decode_accept(wrap, identity=me, nonce="abc123")
    assert result is not None
    sender_pub, body = result
    assert sender_pub == sender.pubkey_hex
    assert body["nonce"] == "abc123"


@pytest.mark.asyncio
async def test_decode_accept_rejects_wrong_nonce(tmp_path):
    me = load_or_create(tmp_path / "me")
    sender = load_or_create(tmp_path / "sender")
    wrap = _accept_wrap(sender, me.pubkey_hex, nonce="not-the-nonce")
    assert _decode_accept(wrap, identity=me, nonce="real-nonce") is None


@pytest.mark.asyncio
async def test_decode_accept_rejects_pubkey_mismatch(tmp_path):
    """A reply that claims a pubkey other than the gift-wrap's authenticated
    sender is rejected, even with the right nonce."""
    me = load_or_create(tmp_path / "me")
    sender = load_or_create(tmp_path / "sender")
    other = load_or_create(tmp_path / "other")
    wrap = _accept_wrap(sender, me.pubkey_hex, nonce="n", claimed_pubkey=other.pubkey_hex)
    assert _decode_accept(wrap, identity=me, nonce="n") is None


@pytest.mark.asyncio
async def test_decode_accept_rejects_wrong_type(tmp_path):
    me = load_or_create(tmp_path / "me")
    sender = load_or_create(tmp_path / "sender")
    wrap = _accept_wrap(sender, me.pubkey_hex, nonce="n", typ="something-else")
    assert _decode_accept(wrap, identity=me, nonce="n") is None


@pytest.mark.asyncio
async def test_pairing_happy_path_mutual_trust(tmp_path, monkeypatch):
    """Full single-code flow over a fake relay: the wormhole channel is faked
    (an in-process queue); the Nostr reply is real. Both sides end mutually
    trusting from ONE code."""
    async with fake_relay() as (url, _):
        inviter = load_or_create(tmp_path / "inviter")
        joiner = load_or_create(tmp_path / "joiner")
        inviter_trust = TrustStore(tmp_path / "inviter_trust.json")
        joiner_trust = TrustStore(tmp_path / "joiner_trust.json")

        channel: asyncio.Queue = asyncio.Queue()  # stand-in for the wormhole

        async def fake_send_text(text, *, on_code):
            await on_code(CODE)
            await channel.put(text)

        async def fake_receive_text(code):
            assert code == CODE
            return await channel.get()

        monkeypatch.setattr(bulk, "send_text", fake_send_text)
        monkeypatch.setattr(bulk, "receive_text", fake_receive_text)

        inviter_events: list[dict] = []
        joiner_events: list[dict] = []
        codes: list[str] = []

        async def on_code(code):
            codes.append(code)

        await asyncio.gather(
            invite(
                identity=inviter,
                trust=inviter_trust,
                relays=[url],
                on_code=on_code,
                emit=inviter_events.append,
                timeout=10.0,
            ),
            join(
                identity=joiner,
                trust=joiner_trust,
                relays=[url],
                code=CODE,
                emit=joiner_events.append,
            ),
        )

        # Exactly one code, read once.
        assert codes == [CODE]
        # Both sides trust each other by pubkey.
        assert inviter_trust.by_pubkey(joiner.pubkey_hex) is not None
        assert joiner_trust.by_pubkey(inviter.pubkey_hex) is not None
        # Both emitted a terminal `paired` event.
        assert any(e["type"] == "paired" for e in inviter_events)
        assert any(e["type"] == "paired" for e in joiner_events)


@pytest.mark.asyncio
async def test_invite_ignores_reply_without_correct_nonce(tmp_path, monkeypatch):
    """A third party who scraped the inviter's pubkey from relay tags but never
    saw the code (so never learned the nonce) cannot complete pairing: their
    valid-but-wrong-nonce reply is ignored and the inviter times out."""
    async with fake_relay() as (url, _):
        inviter = load_or_create(tmp_path / "inviter")
        stranger = load_or_create(tmp_path / "stranger")
        inviter_trust = TrustStore(tmp_path / "inviter_trust.json")

        async def fake_send_text(text, *, on_code):
            await on_code(CODE)
            # Stranger races a reply for their OWN key with a guessed nonce.
            pool = RelayPool([url])
            await pool.connect()
            wrap = _accept_wrap(stranger, inviter.pubkey_hex, nonce="guessed-wrong")
            await pool.publish(wrap)
            await pool.close()

        monkeypatch.setattr(bulk, "send_text", fake_send_text)

        events: list[dict] = []

        async def on_code(code):
            pass

        ok = await invite(
            identity=inviter,
            trust=inviter_trust,
            relays=[url],
            on_code=on_code,
            emit=events.append,
            timeout=1.0,
        )

        assert ok is False
        assert any(e["type"] == "pairing-timeout" for e in events)
        assert inviter_trust.by_pubkey(stranger.pubkey_hex) is None
        assert inviter_trust.all() == []


@pytest.mark.asyncio
async def test_invite_times_out_if_code_is_never_picked_up(tmp_path, monkeypatch):
    async with fake_relay() as (url, _):
        inviter = load_or_create(tmp_path / "inviter")
        inviter_trust = TrustStore(tmp_path / "inviter_trust.json")
        send_was_cancelled = False

        async def fake_send_text(text, *, on_code):
            nonlocal send_was_cancelled
            await on_code(CODE)
            try:
                await asyncio.Event().wait()
            finally:
                send_was_cancelled = True

        monkeypatch.setattr(bulk, "send_text", fake_send_text)

        events: list[dict] = []
        codes: list[str] = []

        async def on_code(code):
            codes.append(code)

        ok = await invite(
            identity=inviter,
            trust=inviter_trust,
            relays=[url],
            on_code=on_code,
            emit=events.append,
            timeout=0.05,
        )

        assert ok is False
        assert codes == [CODE]
        assert events == [{"type": "pairing-timeout"}]
        assert send_was_cancelled is True
        assert inviter_trust.all() == []
