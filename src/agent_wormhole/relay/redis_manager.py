"""Redis Streams manager for relay channel state."""
from __future__ import annotations

import json
import time

from redis.asyncio import Redis

CHANNEL_TTL = 3600  # 1 hour
STREAM_MAXLEN = 1000

# Lua script for atomic join: check-and-set role in meta hash
_JOIN_SCRIPT = """
local meta_key = KEYS[1]
local role_field = ARGV[1] .. "_connected"
local current = redis.call("HGET", meta_key, role_field)
if current == "1" then
    return 0
end
redis.call("HSET", meta_key, role_field, "1")
redis.call("HSET", meta_key, "last_activity", ARGV[2])
if redis.call("HEXISTS", meta_key, "created_at") == 0 then
    redis.call("HSET", meta_key, "created_at", ARGV[2])
end
redis.call("EXPIRE", meta_key, ARGV[3])
return 1
"""


def _meta_key(code: str) -> str:
    return f"wormhole:{code}:meta"


def _stream_key(code: str, from_role: str) -> str:
    other = "peer" if from_role == "host" else "host"
    return f"wormhole:{code}:{from_role}-to-{other}"


def _cursor_key(code: str, role: str) -> str:
    return f"wormhole:{code}:{role}:cursor"


class RedisManager:
    """Manages channel state in Redis."""

    def __init__(self, redis: Redis):
        self._redis = redis
        self._join_script = self._redis.register_script(_JOIN_SCRIPT)

    async def join(self, code: str, role: str) -> bool:
        """Atomically register a role for a channel. Returns False if role already taken."""
        now = str(int(time.time()))
        result = await self._join_script(
            keys=[_meta_key(code)],
            args=[role, now, str(CHANNEL_TTL)],
        )
        if result == 1:
            # Initialize cursor only if not already set (preserves cursor on reconnect)
            cursor_key = _cursor_key(code, role)
            await self._redis.set(cursor_key, "0-0", ex=CHANNEL_TTL, nx=True)
        return result == 1

    async def disconnect(self, code: str, role: str) -> None:
        """Mark a role as disconnected and notify the other side."""
        key = _meta_key(code)
        await self._redis.hset(key, f"{role}_connected", "0")
        # Push a disconnect notification through the stream so the other side's
        # writer loop delivers it as a control message
        stream = _stream_key(code, role)
        await self._redis.xadd(
            stream,
            {"control": json.dumps({"type": "status", "event": "peer_disconnected"}).encode()},
            maxlen=STREAM_MAXLEN,
        )

    async def get_meta(self, code: str) -> dict[str, str]:
        """Get channel metadata."""
        data = await self._redis.hgetall(_meta_key(code))
        return {k.decode(): v.decode() for k, v in data.items()}

    async def is_paired(self, code: str) -> bool:
        """Check if both host and peer are connected."""
        meta = await self.get_meta(code)
        return meta.get("host_connected") == "1" and meta.get("peer_connected") == "1"

    async def send_frame(self, code: str, from_role: str, data: bytes) -> None:
        """Add a frame to the outbound stream for from_role."""
        stream = _stream_key(code, from_role)
        await self._redis.xadd(stream, {"frame": data}, maxlen=STREAM_MAXLEN)
        # Reset TTL on all channel keys
        await self._touch_all(code)

    async def read_frames(
        self, code: str, for_role: str, block_ms: int = 0
    ) -> list[dict]:
        """Read new entries for a role from its inbound stream.

        Returns list of dicts, each with either:
        - {"frame": bytes} for data frames
        - {"control": dict} for control messages (e.g. peer_disconnected)

        Updates the persisted cursor after reading.
        """
        # Inbound stream for 'host' is 'peer-to-host', i.e., the other role's outbound
        other = "peer" if for_role == "host" else "host"
        stream = _stream_key(code, other)
        cursor_key = _cursor_key(code, for_role)

        cursor = await self._redis.get(cursor_key)
        if cursor is None:
            cursor = b"0-0"
        cursor = cursor.decode() if isinstance(cursor, bytes) else cursor

        if block_ms > 0:
            result = await self._redis.xread(
                {stream: cursor}, count=100, block=block_ms
            )
        else:
            result = await self._redis.xread({stream: cursor}, count=100)

        entries = []
        last_id = cursor
        for _stream_name, messages in result:
            for msg_id, fields in messages:
                msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                if b"frame" in fields:
                    entries.append({"frame": fields[b"frame"]})
                elif b"control" in fields:
                    entries.append({"control": json.loads(fields[b"control"])})
                last_id = msg_id_str

        if last_id != cursor:
            await self._redis.set(cursor_key, last_id, ex=CHANNEL_TTL)

        return entries

    async def _touch_all(self, code: str) -> None:
        """Reset TTL on all keys for a channel."""
        pipe = self._redis.pipeline()
        pipe.expire(_meta_key(code), CHANNEL_TTL)
        pipe.expire(_stream_key(code, "host"), CHANNEL_TTL)
        pipe.expire(_stream_key(code, "peer"), CHANNEL_TTL)
        pipe.expire(_cursor_key(code, "host"), CHANNEL_TTL)
        pipe.expire(_cursor_key(code, "peer"), CHANNEL_TTL)
        await pipe.execute()

    async def touch(self, code: str) -> None:
        """Reset TTL on channel (keepalive)."""
        await self._touch_all(code)

    async def cleanup(self, code: str) -> None:
        """Delete all Redis keys for a channel."""
        keys = await self._redis.keys(f"wormhole:{code}:*")
        if keys:
            await self._redis.delete(*keys)
