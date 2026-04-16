"""FastAPI relay server for agent-wormhole."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from redis.asyncio import Redis

from agent_wormhole.relay.redis_manager import RedisManager
from agent_wormhole.relay.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

_redis: Redis | None = None
CODE_PATTERN = re.compile(r"^[a-z]+-[a-z]+-[a-z]+$")


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379")
        )
    return _redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


app = FastAPI(title="agent-wormhole relay", lifespan=lifespan)


@app.get("/health")
async def health():
    try:
        redis = await get_redis()
        await redis.ping()
        return {"status": "ok", "redis": "connected"}
    except Exception:
        return {"status": "ok", "redis": "disconnected"}


MAX_FRAME_SIZE = 10 * 1024 * 1024  # 10 MB


@app.websocket("/ws")
async def websocket_handler(ws: WebSocket):
    await ws.accept()
    redis = await get_redis()
    mgr = RedisManager(redis)
    limiter = RateLimiter(redis)

    code: str | None = None
    role: str | None = None
    joined_ok = False
    client_ip = ws.client.host if ws.client else "unknown"

    try:
        # Wait for join message
        raw = await ws.receive_text()
        msg = json.loads(raw)

        if msg.get("action") != "join":
            await ws.send_text(
                json.dumps({"type": "error", "message": "expected join action"})
            )
            await ws.close()
            return

        code = msg.get("code", "")
        role = msg.get("role", "")

        if role not in ("host", "peer"):
            await ws.send_text(
                json.dumps({"type": "error", "message": "unable to join channel"})
            )
            await ws.close()
            return

        if not CODE_PATTERN.match(code):
            await ws.send_text(
                json.dumps({"type": "error", "message": "unable to join channel"})
            )
            await ws.close()
            return

        # Rate limit: channels per IP (atomic check-and-increment)
        if not await limiter.check_and_increment_channel_count(client_ip):
            await ws.send_text(
                json.dumps({"type": "error", "message": "too many channels"})
            )
            await ws.close()
            return

        # Atomic join
        ok = await mgr.join(code, role)
        if not ok:
            # Only count failed join attempts (not successful ones)
            await limiter.record_failed_join(code)
            await limiter.decrement_channel_count(client_ip)
            await ws.send_text(
                json.dumps({"type": "error", "message": "unable to join channel"})
            )
            await ws.close()
            return

        joined_ok = True

        # Check if too many failed join attempts on this code
        if not await limiter.check_join_attempts(code):
            await ws.send_text(
                json.dumps({"type": "error", "message": "rate limited"})
            )
            await ws.close()
            return

        # Check if paired
        if await mgr.is_paired(code):
            await ws.send_text(
                json.dumps({"type": "status", "event": "paired"})
            )
        else:
            await ws.send_text(
                json.dumps({"type": "status", "event": "waiting"})
            )

        # Run reader and writer concurrently
        await asyncio.gather(
            _ws_reader(ws, mgr, limiter, code, role),
            _ws_writer(ws, mgr, code, role),
        )

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket handler error")
    finally:
        if joined_ok and code and role:
            await mgr.disconnect(code, role)
            await limiter.decrement_channel_count(client_ip)


async def _ws_reader(
    ws: WebSocket,
    mgr: RedisManager,
    limiter: RateLimiter,
    code: str,
    role: str,
) -> None:
    """Read binary frames from WebSocket, push to Redis Stream."""
    while True:
        data = await ws.receive_bytes()

        if len(data) > MAX_FRAME_SIZE:
            await ws.send_text(
                json.dumps({"type": "error", "message": "frame too large"})
            )
            continue

        if not await limiter.check_message_rate(code):
            await ws.send_text(
                json.dumps({"type": "error", "message": "rate limited"})
            )
            continue

        if not await limiter.check_byte_rate(code, len(data)):
            await ws.send_text(
                json.dumps({"type": "error", "message": "rate limited"})
            )
            continue

        await mgr.send_frame(code, role, data)


async def _ws_writer(
    ws: WebSocket,
    mgr: RedisManager,
    code: str,
    role: str,
) -> None:
    """Read entries from Redis Stream, send to WebSocket."""
    while True:
        entries = await mgr.read_frames(code, role, block_ms=1000)

        if not entries:
            continue

        for entry in entries:
            if "frame" in entry:
                await ws.send_bytes(entry["frame"])
            elif "control" in entry:
                await ws.send_text(json.dumps(entry["control"]))
