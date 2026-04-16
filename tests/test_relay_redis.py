"""Tests for Redis channel management."""
import pytest
import fakeredis.aioredis

from agent_wormhole.relay.redis_manager import RedisManager


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
async def mgr(redis):
    return RedisManager(redis)


@pytest.mark.asyncio
async def test_join_host_creates_channel(mgr):
    ok = await mgr.join("test-code", "host")
    assert ok is True
    meta = await mgr.get_meta("test-code")
    assert meta["host_connected"] == "1"
    assert meta.get("peer_connected", "0") == "0"


@pytest.mark.asyncio
async def test_join_peer_after_host(mgr):
    await mgr.join("test-code", "host")
    ok = await mgr.join("test-code", "peer")
    assert ok is True
    meta = await mgr.get_meta("test-code")
    assert meta["host_connected"] == "1"
    assert meta["peer_connected"] == "1"


@pytest.mark.asyncio
async def test_join_duplicate_role_rejected(mgr):
    await mgr.join("test-code", "host")
    ok = await mgr.join("test-code", "host")
    assert ok is False


@pytest.mark.asyncio
async def test_send_and_receive_frame(mgr):
    await mgr.join("test-code", "host")
    await mgr.join("test-code", "peer")

    await mgr.send_frame("test-code", "host", b"hello from host")
    entries = await mgr.read_frames("test-code", "peer")
    assert len(entries) == 1
    assert entries[0]["frame"] == b"hello from host"


@pytest.mark.asyncio
async def test_cursor_persists_across_reads(mgr):
    await mgr.join("test-code", "host")
    await mgr.join("test-code", "peer")

    await mgr.send_frame("test-code", "host", b"msg1")
    await mgr.send_frame("test-code", "host", b"msg2")

    # First read gets both
    entries = await mgr.read_frames("test-code", "peer")
    assert len(entries) == 2

    # Second read gets nothing (cursor advanced)
    entries = await mgr.read_frames("test-code", "peer")
    assert len(entries) == 0

    # New message after cursor
    await mgr.send_frame("test-code", "host", b"msg3")
    entries = await mgr.read_frames("test-code", "peer")
    assert len(entries) == 1
    assert entries[0]["frame"] == b"msg3"


@pytest.mark.asyncio
async def test_disconnect_updates_meta(mgr):
    await mgr.join("test-code", "host")
    await mgr.join("test-code", "peer")
    await mgr.disconnect("test-code", "host")
    meta = await mgr.get_meta("test-code")
    assert meta["host_connected"] == "0"
    assert meta["peer_connected"] == "1"


@pytest.mark.asyncio
async def test_is_paired(mgr):
    await mgr.join("test-code", "host")
    assert await mgr.is_paired("test-code") is False
    await mgr.join("test-code", "peer")
    assert await mgr.is_paired("test-code") is True


@pytest.mark.asyncio
async def test_cleanup_removes_all_keys(mgr, redis):
    await mgr.join("test-code", "host")
    await mgr.join("test-code", "peer")
    await mgr.send_frame("test-code", "host", b"data")
    await mgr.cleanup("test-code")

    keys = await redis.keys("wormhole:test-code:*")
    assert len(keys) == 0
