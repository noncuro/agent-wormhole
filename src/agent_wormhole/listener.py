from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import IO

from agent_wormhole.bulk import receive_file
from agent_wormhole.fs import DEFAULT_BASE, inbox_files_dir, init_peer_dir
from agent_wormhole.identity import Identity
from agent_wormhole.nostr.client import RelayPool, Subscription
from agent_wormhole.nostr.events import unwrap_giftwrapped_dm
from agent_wormhole.trust import TrustStore

FILE_OFFER_MARKER = "__agent-wormhole-file-offer__:"


class Listener:
    def __init__(
        self,
        *,
        identity: Identity,
        trust: TrustStore,
        relays: list[str],
        stdout: IO = sys.stdout,
        files_base: Path = DEFAULT_BASE,
        file_receive_timeout: float = 300.0,
    ):
        self._identity = identity
        self._trust = trust
        self._relays = relays
        self._stdout = stdout
        self._files_base = files_base
        self._file_receive_timeout = file_receive_timeout
        self._pool: RelayPool | None = None
        self._sub: Subscription | None = None
        self._task: asyncio.Task | None = None
        self._file_tasks: set[asyncio.Task] = set()
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
        if content.startswith(FILE_OFFER_MARKER):
            task = asyncio.create_task(
                self._handle_file_offer(peer, content[len(FILE_OFFER_MARKER):])
            )
            self._file_tasks.add(task)
            task.add_done_callback(self._file_tasks.discard)
            return
        self._emit_text(peer.name, peer.pubkey, content)

    async def _handle_file_offer(self, peer, payload_json: str) -> None:
        try:
            offer = json.loads(payload_json)
        except Exception as e:
            print(f"agent-wormhole: malformed file-offer: {e}", file=sys.stderr)
            return
        init_peer_dir(peer.name, base=self._files_base)
        dest_dir = inbox_files_dir(peer.name, base=self._files_base)
        try:
            saved = await asyncio.wait_for(
                receive_file(
                    code=offer["wormhole_code"],
                    dest_dir=dest_dir,
                    accept=True,
                ),
                timeout=self._file_receive_timeout,
            )
        except asyncio.TimeoutError:
            print("agent-wormhole: file receive timed out", file=sys.stderr)
            return
        except Exception as e:
            print(f"agent-wormhole: file receive failed: {e}", file=sys.stderr)
            return
        line = json.dumps({
            "type": "file",
            "from": peer.name,
            "pubkey": peer.pubkey[:12],
            "name": offer.get("name", saved.name),
            "saved_to": str(saved),
            "size": offer.get("size"),
            "received_at": int(time.time()),
        })
        self._stdout.write(line + "\n")
        self._stdout.flush()

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
            await asyncio.gather(self._task, return_exceptions=True)
        if self._file_tasks:
            tasks = list(self._file_tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._pool:
            await self._pool.close()
