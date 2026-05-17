import asyncio
import json
import io
import pytest
from agent_wormhole.identity import load_or_create
from agent_wormhole.trust import Peer, TrustStore
from agent_wormhole.nostr.client import RelayPool
from agent_wormhole.nostr.events import build_giftwrapped_dm
from agent_wormhole.listener import Listener
from tests.fake_relay import fake_relay


@pytest.mark.asyncio
async def test_trusted_text_dm_emitted_to_stdout(tmp_path):
    async with fake_relay() as (url, _):
        me = load_or_create(tmp_path / "me")
        sender = load_or_create(tmp_path / "sender")
        trust = TrustStore(tmp_path / "trust.json")
        trust.add(Peer(pubkey=sender.pubkey_hex, name="bob", relays=[url]))

        out = io.StringIO()
        listener = Listener(
            identity=me,
            trust=trust,
            relays=[url],
            stdout=out,
        )
        await listener.start()

        send_pool = RelayPool([url])
        await send_pool.connect()
        wrap = build_giftwrapped_dm(
            sender=sender,
            recipient_pubkey_hex=me.pubkey_hex,
            content="hi",
        )
        await send_pool.publish(wrap)
        await send_pool.close()

        for _ in range(40):
            await asyncio.sleep(0.05)
            if out.getvalue():
                break
        await listener.stop()
        lines = [l for l in out.getvalue().splitlines() if l]
        assert lines, "listener emitted nothing"
        parsed = json.loads(lines[0])
        assert parsed["type"] == "text"
        assert parsed["from"] == "bob"
        assert parsed["content"] == "hi"


@pytest.mark.asyncio
async def test_untrusted_sender_dropped(tmp_path):
    async with fake_relay() as (url, _):
        me = load_or_create(tmp_path / "me")
        stranger = load_or_create(tmp_path / "stranger")
        trust = TrustStore(tmp_path / "trust.json")

        out = io.StringIO()
        listener = Listener(identity=me, trust=trust, relays=[url], stdout=out)
        await listener.start()

        send_pool = RelayPool([url])
        await send_pool.connect()
        wrap = build_giftwrapped_dm(
            sender=stranger,
            recipient_pubkey_hex=me.pubkey_hex,
            content="malicious",
        )
        await send_pool.publish(wrap)
        await send_pool.close()

        await asyncio.sleep(0.3)
        await listener.stop()
        assert out.getvalue() == ""
