import asyncio
import json
import pytest
from io import StringIO

from agent_wormhole.channel import run_host, run_peer, send_to_outbox


class TestEndToEnd:
    """Integration tests: host and peer communicate over loopback."""

    @pytest.mark.asyncio
    async def test_host_peer_connect_and_exchange_text(self):
        host_output = StringIO()
        peer_output = StringIO()
        code_future: asyncio.Future[str] = asyncio.Future()

        async def host_with_code():
            await run_host(
                port=0,
                output=host_output,
                timeout=5.0,
                on_code=lambda c: code_future.set_result(c),
            )

        host = asyncio.create_task(host_with_code())
        code = await asyncio.wait_for(code_future, timeout=5.0)
        peer = asyncio.create_task(
            run_peer(f"{code}@127.0.0.1", output=peer_output, timeout=5.0)
        )

        # Wait for connection
        await asyncio.sleep(0.5)

        # Send text from host to peer via outbox
        send_to_outbox(code, "hello from host", role="host")
        await asyncio.sleep(0.3)

        # Check peer received the message
        peer_lines = peer_output.getvalue().strip().split("\n")
        text_msgs = [json.loads(l) for l in peer_lines if '"type": "text"' in l or '"type":"text"' in l]
        assert any(m["body"] == "hello from host" for m in text_msgs)

        # Cleanup
        host.cancel()
        peer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await host
        with pytest.raises(asyncio.CancelledError):
            await peer

    @pytest.mark.asyncio
    async def test_version_exchange(self):
        """Both sides exchange version messages on connect."""
        host_output = StringIO()
        peer_output = StringIO()
        code_future: asyncio.Future[str] = asyncio.Future()

        async def host_with_code():
            await run_host(
                port=0, output=host_output, timeout=5.0,
                on_code=lambda c: code_future.set_result(c),
            )

        host = asyncio.create_task(host_with_code())
        code = await asyncio.wait_for(code_future, timeout=5.0)
        peer = asyncio.create_task(
            run_peer(f"{code}@127.0.0.1", output=peer_output, timeout=5.0)
        )

        await asyncio.sleep(0.5)

        # Both sides should have printed a "connected" status
        for output in [host_output, peer_output]:
            lines = output.getvalue().strip().split("\n")
            status_msgs = [json.loads(l) for l in lines if "status" in l]
            events = [m.get("event") for m in status_msgs]
            assert "connected" in events

        host.cancel()
        peer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await host
        with pytest.raises(asyncio.CancelledError):
            await peer


class TestSendToOutbox:
    def test_send_text_creates_outbox_entry(self, tmp_path):
        from agent_wormhole.fs import init_channel_dir
        code = "1234-alpha-bravo-charlie"
        init_channel_dir(code, role="host", base=tmp_path)
        send_to_outbox(code, "hello", role="host", base=tmp_path)

        outbox = tmp_path / code / "outbox-host"
        lines = outbox.read_text().strip().split("\n")
        assert len(lines) == 1
        msg = json.loads(lines[0])
        assert msg == {"type": "text", "body": "hello"}

    def test_send_file_creates_outbox_entry(self, tmp_path):
        from agent_wormhole.fs import init_channel_dir
        code = "1234-alpha-bravo-charlie"
        init_channel_dir(code, role="host", base=tmp_path)

        test_file = tmp_path / "test.txt"
        test_file.write_text("file content")

        send_to_outbox(code, file_path=str(test_file), role="host", base=tmp_path)

        outbox = tmp_path / code / "outbox-host"
        lines = outbox.read_text().strip().split("\n")
        msg = json.loads(lines[0])
        assert msg["type"] == "file"
        assert msg["name"] == "test.txt"
        assert msg["path"] == str(test_file)
