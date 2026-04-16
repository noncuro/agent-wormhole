"""Rate limiting for relay server."""
from __future__ import annotations

from redis.asyncio import Redis

MSG_RATE_LIMIT = 60  # messages per minute
BYTE_RATE_LIMIT = 50 * 1024 * 1024  # 50 MB per minute
JOIN_ATTEMPT_LIMIT = 5  # per code per minute
CHANNEL_LIMIT_PER_IP = 100  # active channels per source IP
RATE_WINDOW = 60  # seconds


class RateLimiter:
    """Sliding window rate limiter backed by Redis."""

    def __init__(self, redis: Redis):
        self._redis = redis

    async def check_message_rate(self, code: str) -> bool:
        """Check and increment message rate. Returns True if allowed."""
        key = f"wormhole:{code}:rate"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, RATE_WINDOW)
        return count <= MSG_RATE_LIMIT

    async def check_byte_rate(self, code: str, size: int) -> bool:
        """Check and increment byte rate. Returns True if allowed."""
        key = f"wormhole:{code}:bytes"
        count = await self._redis.incrby(key, size)
        if count == size:
            await self._redis.expire(key, RATE_WINDOW)
        return count <= BYTE_RATE_LIMIT

    async def record_failed_join(self, code: str) -> None:
        """Record a failed join attempt for a code."""
        key = f"wormhole:{code}:join-attempts"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, RATE_WINDOW)

    async def check_join_attempts(self, code: str) -> bool:
        """Check if a code has too many failed join attempts. Returns True if allowed."""
        key = f"wormhole:{code}:join-attempts"
        count = await self._redis.get(key)
        if count is None:
            return True
        return int(count) < JOIN_ATTEMPT_LIMIT

    async def check_and_increment_channel_count(self, ip: str) -> bool:
        """Atomically check and increment channel count for an IP.

        Returns True if under limit (and count was incremented).
        Returns False if at/over limit (count unchanged).
        """
        key = f"wormhole:ip:{ip}:channels"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, 3600)
        if count > CHANNEL_LIMIT_PER_IP:
            # Over limit -- undo the increment
            await self._redis.decr(key)
            return False
        return True

    async def decrement_channel_count(self, ip: str) -> None:
        """Decrement active channel count for an IP."""
        key = f"wormhole:ip:{ip}:channels"
        count = await self._redis.decr(key)
        if count <= 0:
            await self._redis.delete(key)
