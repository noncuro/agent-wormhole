"""Two-process end-to-end: pre-populate trust, exchange a text DM via Nostr.

Pairing itself is skill-orchestrated and not in scope for an automated test;
this exercises everything downstream of pairing."""
import asyncio
import json
import os
import sys

import pytest

CLI = [sys.executable, "-m", "agent_wormhole"]


@pytest.mark.asyncio
async def test_send_text_e2e(tmp_path):
    from tests.fake_relay import fake_relay
    async with fake_relay() as (relay_url, _):
        host_home = tmp_path / "host_home"
        peer_home = tmp_path / "peer_home"
        host_home.mkdir()
        peer_home.mkdir()
        env_common = {**os.environ, "AGENT_WORMHOLE_RELAYS": relay_url}

        async def run_cli(*args, home, capture=True):
            return await asyncio.create_subprocess_exec(
                *CLI, *args,
                env={**env_common, "AGENT_WORMHOLE_HOME": str(home)},
                stdout=asyncio.subprocess.PIPE if capture else None,
                stderr=asyncio.subprocess.PIPE if capture else None,
            )

        async def get_pubkey(home):
            proc = await run_cli("identity-envelope", home=home)
            out, _err = await proc.communicate()
            return json.loads(out.decode())["pubkey"]

        host_pub = await get_pubkey(host_home)
        peer_pub = await get_pubkey(peer_home)

        # Host trusts peer as "peer". Peer trusts host as "host".
        rc = await (await run_cli(
            "trust", peer_pub, "peer", "--relays", relay_url, home=host_home,
        )).wait()
        assert rc == 0
        rc = await (await run_cli(
            "trust", host_pub, "host", "--relays", relay_url, home=peer_home,
        )).wait()
        assert rc == 0

        host_listen = await run_cli("listen", home=host_home)

        await asyncio.sleep(0.5)

        send = await run_cli("send", "host", "hello from peer", home=peer_home)
        rc = await asyncio.wait_for(send.wait(), timeout=15)
        assert rc == 0

        line = await asyncio.wait_for(host_listen.stdout.readline(), timeout=10)
        parsed = json.loads(line.decode())
        assert parsed["type"] == "text"
        assert parsed["content"] == "hello from peer"
        # host's trust file labels the sender's pubkey as "peer"
        assert parsed["from"] == "peer"

        host_listen.terminate()
        try:
            await asyncio.wait_for(host_listen.wait(), timeout=5)
        except asyncio.TimeoutError:
            host_listen.kill()
            await host_listen.wait()
