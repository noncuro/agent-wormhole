"""Full integration test: host and peer in the same process over loopback."""
import asyncio
import json
import pytest
from io import StringIO
from pathlib import Path

from agent_wormhole.channel import run_host, run_peer, send_to_outbox
from agent_wormhole.fs import init_channel_dir, get_outbox_path


@pytest.fixture
def tmp_base(tmp_path):
    return tmp_path


@pytest.mark.asyncio
async def test_full_text_roundtrip(tmp_base):
    """Host sends text to peer, peer sends text to host."""
    host_out = StringIO()
    peer_out = StringIO()
    code_future: asyncio.Future[str] = asyncio.Future()

    async def run_h():
        await run_host(port=0, output=host_out, timeout=5.0,
                       on_code=lambda c: code_future.set_result(c), base=tmp_base)

    host_task = asyncio.create_task(run_h())
    code = await asyncio.wait_for(code_future, timeout=5.0)

    peer_task = asyncio.create_task(
        run_peer(f"{code}@127.0.0.1", output=peer_out, timeout=5.0, base=tmp_base)
    )

    await asyncio.sleep(0.5)

    # Host sends to peer
    send_to_outbox(code, "hello peer", role="host", base=tmp_base)
    await asyncio.sleep(0.3)

    peer_lines = [json.loads(l) for l in peer_out.getvalue().strip().split("\n") if l.strip()]
    assert any(m.get("body") == "hello peer" for m in peer_lines)

    # Peer sends to host
    send_to_outbox(code, "hello host", role="peer", base=tmp_base)
    await asyncio.sleep(0.3)

    host_lines = [json.loads(l) for l in host_out.getvalue().strip().split("\n") if l.strip()]
    assert any(m.get("body") == "hello host" for m in host_lines)

    host_task.cancel()
    peer_task.cancel()
    await asyncio.gather(host_task, peer_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_file_transfer(tmp_base):
    """Host sends a file to peer."""
    host_out = StringIO()
    peer_out = StringIO()
    code_future: asyncio.Future[str] = asyncio.Future()

    async def run_h():
        await run_host(port=0, output=host_out, timeout=5.0,
                       on_code=lambda c: code_future.set_result(c), base=tmp_base)

    host_task = asyncio.create_task(run_h())
    code = await asyncio.wait_for(code_future, timeout=5.0)
    peer_task = asyncio.create_task(
        run_peer(f"{code}@127.0.0.1", output=peer_out, timeout=5.0, base=tmp_base)
    )

    await asyncio.sleep(0.5)

    # Create a test file and send it
    test_file = tmp_base / "send_me.txt"
    test_file.write_text("secret credentials here")
    send_to_outbox(code, file_path=str(test_file), role="host", base=tmp_base)
    await asyncio.sleep(0.5)

    # Check peer received the file
    peer_lines = [json.loads(l) for l in peer_out.getvalue().strip().split("\n") if l.strip()]
    file_msgs = [m for m in peer_lines if m.get("type") == "file"]
    assert len(file_msgs) == 1
    assert file_msgs[0]["name"] == "send_me.txt"

    saved_path = Path(file_msgs[0]["saved_to"])
    assert saved_path.exists()
    assert saved_path.read_text() == "secret credentials here"

    host_task.cancel()
    peer_task.cancel()
    await asyncio.gather(host_task, peer_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_large_text_saved_to_file(tmp_base):
    """Text over 1KB is saved to file instead of printed inline."""
    host_out = StringIO()
    peer_out = StringIO()
    code_future: asyncio.Future[str] = asyncio.Future()

    async def run_h():
        await run_host(port=0, output=host_out, timeout=5.0,
                       on_code=lambda c: code_future.set_result(c), base=tmp_base)

    host_task = asyncio.create_task(run_h())
    code = await asyncio.wait_for(code_future, timeout=5.0)
    peer_task = asyncio.create_task(
        run_peer(f"{code}@127.0.0.1", output=peer_out, timeout=5.0, base=tmp_base)
    )

    await asyncio.sleep(0.5)

    large_text = "x" * 2000
    send_to_outbox(code, large_text, role="host", base=tmp_base)
    await asyncio.sleep(0.5)

    peer_lines = [json.loads(l) for l in peer_out.getvalue().strip().split("\n") if l.strip()]
    text_msgs = [m for m in peer_lines if m.get("type") == "text"]
    saved_msgs = [m for m in text_msgs if "saved_to" in m]
    assert len(saved_msgs) == 1
    assert saved_msgs[0]["size"] == 2000

    saved_path = Path(saved_msgs[0]["saved_to"])
    assert saved_path.read_text() == large_text

    host_task.cancel()
    peer_task.cancel()
    await asyncio.gather(host_task, peer_task, return_exceptions=True)
