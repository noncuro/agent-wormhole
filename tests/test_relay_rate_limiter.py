"""Tests for relay rate limiting."""
import pytest
import fakeredis.aioredis

from agent_wormhole.relay.rate_limiter import RateLimiter


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def limiter(redis):
    return RateLimiter(redis)


@pytest.mark.asyncio
async def test_message_rate_under_limit(limiter):
    for _ in range(60):
        allowed = await limiter.check_message_rate("test-code")
        assert allowed is True


@pytest.mark.asyncio
async def test_message_rate_over_limit(limiter):
    for _ in range(60):
        await limiter.check_message_rate("test-code")
    allowed = await limiter.check_message_rate("test-code")
    assert allowed is False


@pytest.mark.asyncio
async def test_byte_rate_under_limit(limiter):
    allowed = await limiter.check_byte_rate("test-code", 1024)
    assert allowed is True


@pytest.mark.asyncio
async def test_byte_rate_over_limit(limiter):
    # 50MB limit
    allowed = await limiter.check_byte_rate("test-code", 50 * 1024 * 1024)
    assert allowed is True
    allowed = await limiter.check_byte_rate("test-code", 1)
    assert allowed is False


@pytest.mark.asyncio
async def test_join_attempts_under_limit(limiter):
    """Failed join attempts under limit should still allow joins."""
    for _ in range(4):
        await limiter.record_failed_join("test-code")
    allowed = await limiter.check_join_attempts("test-code")
    assert allowed is True


@pytest.mark.asyncio
async def test_join_attempts_over_limit(limiter):
    """Too many failed join attempts should block further joins."""
    for _ in range(5):
        await limiter.record_failed_join("test-code")
    allowed = await limiter.check_join_attempts("test-code")
    assert allowed is False


@pytest.mark.asyncio
async def test_channel_count_atomic_under_limit(limiter):
    """First channel for an IP should succeed."""
    allowed = await limiter.check_and_increment_channel_count("1.2.3.4")
    assert allowed is True


@pytest.mark.asyncio
async def test_channel_count_atomic_over_limit(limiter):
    """Channel count at limit should reject and not increment."""
    for _ in range(100):
        await limiter.check_and_increment_channel_count("1.2.3.4")
    allowed = await limiter.check_and_increment_channel_count("1.2.3.4")
    assert allowed is False
