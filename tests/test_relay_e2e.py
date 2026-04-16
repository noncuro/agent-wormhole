"""End-to-end test: two clients communicate through the relay server."""
import asyncio
import json
import pytest
from io import StringIO

import fakeredis.aioredis
import uvicorn

from agent_wormhole.channel import run_host, run_peer, send_to_outbox
from agent_wormhole.relay import server as relay_server_module
from agent_wormhole.relay.server import app


@pytest.fixture
async def fake_redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
async def relay_server(fake_redis):
    """Start the relay server on a random port for testing."""
    # Set the module-level Redis instance directly (bypasses get_redis() creation)
    relay_server_module._redis = fake_redis

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)

    # Get the actual bound port
    task = asyncio.create_task(server.serve())
    # Wait for server to start
    while not server.started:
        await asyncio.sleep(0.05)

    # Extract port from server sockets
    port = None
    for s in server.servers:
        for sock in s.sockets:
            addr = sock.getsockname()
            port = addr[1]
            break
        if port:
            break

    relay_url = f"ws://127.0.0.1:{port}"
    yield relay_url

    server.should_exit = True
    await task
    relay_server_module._redis = None


@pytest.mark.asyncio
async def test_e2e_relay_text_roundtrip(relay_server, tmp_path):
    """Host and peer exchange text messages through the relay."""
    host_out = StringIO()
    peer_out = StringIO()
    code_future: asyncio.Future[str] = asyncio.Future()

    async def run_h():
        await run_host(
            output=host_out,
            timeout=10.0,
            on_code=lambda c: code_future.set_result(c),
            base=tmp_path,
            relay_url=relay_server,
        )

    host_task = asyncio.create_task(run_h())
    code = await asyncio.wait_for(code_future, timeout=5.0)

    peer_task = asyncio.create_task(
        run_peer(code, output=peer_out, timeout=10.0, base=tmp_path, relay_url=relay_server)
    )

    await asyncio.sleep(1.0)

    # Host sends to peer
    send_to_outbox(code, "hello via relay", role="host", base=tmp_path)
    await asyncio.sleep(0.5)

    peer_lines = [json.loads(l) for l in peer_out.getvalue().strip().split("\n") if l.strip()]
    assert any(m.get("body") == "hello via relay" for m in peer_lines)

    # Peer sends to host
    send_to_outbox(code, "reply via relay", role="peer", base=tmp_path)
    await asyncio.sleep(0.5)

    host_lines = [json.loads(l) for l in host_out.getvalue().strip().split("\n") if l.strip()]
    assert any(m.get("body") == "reply via relay" for m in host_lines)

    host_task.cancel()
    peer_task.cancel()
    await asyncio.gather(host_task, peer_task, return_exceptions=True)
