import asyncio
import pytest
from agent_wormhole.identity import load_or_create
from agent_wormhole.nostr.client import RelayPool
from agent_wormhole.nostr.events import build_event


@pytest.mark.asyncio
async def test_publish_then_subscribe_delivers(relay, tmp_path):
    url, _server = relay
    ident = load_or_create(tmp_path / "k")
    pool = RelayPool([url])
    await pool.connect()

    ev = build_event(ident, kind=1, tags=[], content="hello")
    acks = await pool.publish(ev)
    assert acks[url] is True

    sub = await pool.subscribe({"kinds": [1]})
    received_event = await asyncio.wait_for(sub.next(), timeout=2.0)
    assert received_event.content == "hello"

    await pool.close()


@pytest.mark.asyncio
async def test_dedupe_across_relays(tmp_path):
    from tests.fake_relay import fake_relay
    async with fake_relay() as (u1, _), fake_relay() as (u2, _):
        ident = load_or_create(tmp_path / "k")
        pool = RelayPool([u1, u2])
        await pool.connect()
        ev = build_event(ident, kind=1, tags=[], content="dup")
        await pool.publish(ev)

        sub = await pool.subscribe({"kinds": [1]})
        first = await asyncio.wait_for(sub.next(), timeout=2.0)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub.next(), timeout=0.3)
        assert first.id == ev.id
        await pool.close()


@pytest.mark.asyncio
async def test_connect_tolerates_dead_relay():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    url = f"ws://127.0.0.1:{port}"

    pool = RelayPool([url])
    await pool.connect()
    sub = await pool.subscribe({"kinds": [1]})
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.next(), timeout=0.3)
    await pool.close()


@pytest.mark.asyncio
async def test_resubscribe_after_disconnect(tmp_path):
    """If a relay closes mid-flight, the pool reconnects and resends REQ."""
    from tests.fake_relay import fake_relay

    async with fake_relay() as (url, _):
        ident = load_or_create(tmp_path / "k")
        pool = RelayPool([url])
        await pool.connect()
        sub = await pool.subscribe({"kinds": [1]})

        ws = next(iter(pool._conns.values()))
        await ws.close()

        # Wait for reconnect (initial backoff 1.0s).
        await asyncio.sleep(2.0)
        ev = build_event(ident, kind=1, tags=[], content="post-reconnect")
        await pool.publish(ev)
        got = await asyncio.wait_for(sub.next(), timeout=3.0)
        assert got.content == "post-reconnect"
        await pool.close()
