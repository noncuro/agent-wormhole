"""Tests for the relay FastAPI server."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
from httpx import AsyncClient, ASGITransport

from agent_wormhole.relay.server import app, get_redis


@pytest.fixture
async def fake_redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
async def client(fake_redis):
    app.dependency_overrides[get_redis] = lambda: fake_redis
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_health_redis_down():
    """Health check reports redis disconnected when Redis is unavailable."""
    mock_redis = AsyncMock()
    mock_redis.ping.side_effect = Exception("connection refused")
    app.dependency_overrides[get_redis] = lambda: mock_redis
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["redis"] == "disconnected"
    app.dependency_overrides.clear()
