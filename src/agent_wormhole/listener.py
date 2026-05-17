from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import IO

from agent_wormhole.identity import Identity
from agent_wormhole.nostr.client import RelayPool, Subscription
from agent_wormhole.nostr.events import unwrap_giftwrapped_dm
from agent_wormhole.trust import TrustStore


class Listener:
    def __init__(
        self,
        *,
        identity: Identity,
        trust: TrustStore,
        relays: list[str],
        stdout: IO = sys.stdout,
    ):
        self._identity = identity
        self._trust = trust
        self._relays = relays
        self._stdout = stdout
        self._pool: RelayPool | None = None
        self._sub: Subscription | None = None
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self._pool = RelayPool(self._relays)
        await self._pool.connect()
        self._sub = await self._pool.subscribe(
            {"kinds": [1059], "#p": [self._identity.pubkey_hex]}
        )
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while not self._stopped.is_set():
            try:
                ev = await asyncio.wait_for(self._sub.next(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            await self._handle(ev)

    async def _handle(self, ev) -> None:
        try:
            sender_pub, content = unwrap_giftwrapped_dm(ev, recipient=self._identity)
        except Exception as e:
            print(f"agent-wormhole: dropped malformed DM: {e}", file=sys.stderr)
            return
        peer = self._trust.by_pubkey(sender_pub)
        if peer is None:
            print(
                f"agent-wormhole: dropped DM from untrusted {sender_pub[:12]}",
                file=sys.stderr,
            )
            return
        self._emit_text(peer.name, peer.pubkey, content)

    def _emit_text(self, name: str, pubkey: str, content: str) -> None:
        line = json.dumps({
            "type": "text",
            "from": name,
            "pubkey": pubkey[:12],
            "content": content,
            "received_at": int(time.time()),
        })
        self._stdout.write(line + "\n")
        self._stdout.flush()

    async def stop(self) -> None:
        self._stopped.set()
        if self._task:
            self._task.cancel()
        if self._pool:
            await self._pool.close()
