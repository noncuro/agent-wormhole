"""Tests for durable 'mark as read' (persistent seen-store) + cold-start baseline.

The bug these guard against: Nostr relays replay all stored history on every
subscribe, and the seen-set was in-memory only — so each `listen` re-flooded
with days-old messages. Fix: persist the seen-set (keyed on the stable inner
rumor id) so a message read once stays read across restarts; and on a cold
start, silently baseline pre-existing history (emit a summary, not the firehose).
"""
import asyncio
import io
import json

import pytest

from agent_wormhole.identity import load_or_create
from agent_wormhole.trust import Peer, TrustStore
from agent_wormhole.nostr.client import RelayPool
from agent_wormhole.nostr.events import build_giftwrapped_dm
from agent_wormhole.listener import Listener
from tests.fake_relay import fake_relay


async def _publish(url, sender, recipient, content):
    pool = RelayPool([url])
    await pool.connect()
    wrap = build_giftwrapped_dm(
        sender=sender, recipient_pubkey_hex=recipient.pubkey_hex, content=content
    )
    await pool.publish(wrap)
    await pool.close()


async def _drain(out, needle=None, tries=40):
    for _ in range(tries):
        await asyncio.sleep(0.05)
        if (needle is None and out.getvalue()) or (needle and needle in out.getvalue()):
            return
    return


def _lines(out):
    return [json.loads(l) for l in out.getvalue().splitlines() if l]


@pytest.mark.asyncio
async def test_persistent_seen_dedup_across_restart(tmp_path):
    """A message read in one listen must NOT be re-emitted by the next listen,
    even though the relay replays it from stored history."""
    async with fake_relay() as (url, _):
        me = load_or_create(tmp_path / "me")
        sender = load_or_create(tmp_path / "sender")
        trust = TrustStore(tmp_path / "trust.json")
        trust.add(Peer(pubkey=sender.pubkey_hex, name="bob", relays=[url]))
        seen_path = tmp_path / "seen.json"

        # --- first listen: message arrives live and is emitted ---
        out1 = io.StringIO()
        l1 = Listener(identity=me, trust=trust, relays=[url], stdout=out1,
                      seen_path=seen_path)
        await l1.start()
        await _drain(out1)  # wait for cold-start EOSE (no history yet)
        await _publish(url, sender, me, "hello")
        await _drain(out1, "hello")
        await l1.stop()
        assert any(m.get("content") == "hello" for m in _lines(out1))
        assert seen_path.exists()

        # --- second listen: relay REPLAYS "hello" as history; must be suppressed ---
        out2 = io.StringIO()
        l2 = Listener(identity=me, trust=trust, relays=[url], stdout=out2,
                      seen_path=seen_path)
        await l2.start()
        await asyncio.sleep(0.4)
        await l2.stop()
        texts = [m for m in _lines(out2) if m.get("type") == "text"]
        assert texts == [], f"stale history re-emitted on restart: {texts}"


@pytest.mark.asyncio
async def test_cold_start_baselines_history_with_summary(tmp_path):
    """On a cold start with pre-existing history, don't firehose it — emit a
    single backlog summary and mark it read. A later live message still emits."""
    async with fake_relay() as (url, _):
        me = load_or_create(tmp_path / "me")
        sender = load_or_create(tmp_path / "sender")
        trust = TrustStore(tmp_path / "trust.json")
        trust.add(Peer(pubkey=sender.pubkey_hex, name="bob", relays=[url]))
        seen_path = tmp_path / "seen.json"

        # pre-existing history on the relay (sent BEFORE we ever listen)
        await _publish(url, sender, me, "old-1")
        await _publish(url, sender, me, "old-2")

        out = io.StringIO()
        listener = Listener(identity=me, trust=trust, relays=[url], stdout=out,
                            seen_path=seen_path)
        await listener.start()
        await _drain(out)  # summary
        # now a genuinely new live message
        await _publish(url, sender, me, "new-live")
        await _drain(out, "new-live")
        await listener.stop()

        msgs = _lines(out)
        texts = [m for m in msgs if m.get("type") == "text"]
        summaries = [m for m in msgs if m.get("type") == "backlog"]
        # history suppressed, not emitted as text
        assert not any(m["content"] in ("old-1", "old-2") for m in texts)
        # exactly one summary reporting 2 suppressed
        assert len(summaries) == 1 and summaries[0]["suppressed"] == 2
        # the live one still comes through
        assert any(m["content"] == "new-live" for m in texts)


@pytest.mark.asyncio
async def test_replay_flag_emits_history(tmp_path):
    """--replay restores the old firehose: stored history IS emitted."""
    async with fake_relay() as (url, _):
        me = load_or_create(tmp_path / "me")
        sender = load_or_create(tmp_path / "sender")
        trust = TrustStore(tmp_path / "trust.json")
        trust.add(Peer(pubkey=sender.pubkey_hex, name="bob", relays=[url]))

        await _publish(url, sender, me, "historic")

        out = io.StringIO()
        listener = Listener(identity=me, trust=trust, relays=[url], stdout=out,
                            seen_path=tmp_path / "seen.json", replay=True)
        await listener.start()
        await _drain(out, "historic")
        await listener.stop()
        assert any(m.get("content") == "historic" for m in _lines(out))
