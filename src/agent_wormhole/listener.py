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
from agent_wormhole.nostr.client import EoseMarker, RelayPool, Subscription
from agent_wormhole.nostr.events import unwrap_giftwrapped_dm
from agent_wormhole.seen import SeenStore
from agent_wormhole.trust import TrustStore

FILE_OFFER_MARKER = "__agent-wormhole-file-offer__:"

# On a cold start, if some relays never send EOSE (down / slow), don't baseline
# forever — the seen-store is the correctness backstop, so a grace timeout is safe.
_BASELINE_GRACE_SECONDS = 15.0


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
        seen_path: Path | None = None,
        replay: bool = False,
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
        # Durable "mark as read" + cold-start baseline.
        self._replay = replay
        self._seen = SeenStore(seen_path)
        # Cold start = we've never persisted a seen-set before. On a cold start we
        # silently baseline whatever history the relays replay (so a first listen
        # doesn't firehose days of backlog). --replay opts back into the firehose.
        self._baseline = (not self._seen.existed) and not replay
        self._eose_urls: set[str] = set()
        self._expected_eose = 1
        self._baseline_suppressed = 0
        self._baseline_through = 0
        self._baseline_deadline = 0.0

    async def start(self) -> None:
        self._pool = RelayPool(self._relays)
        await self._pool.connect()
        self._expected_eose = max(1, len(self._pool.connected_urls()))
        self._sub = await self._pool.subscribe(
            {"kinds": [1059], "#p": [self._identity.pubkey_hex]}
        )
        if self._baseline:
            self._baseline_deadline = asyncio.get_event_loop().time() + _BASELINE_GRACE_SECONDS
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while not self._stopped.is_set():
            try:
                item = await asyncio.wait_for(self._sub.next(), timeout=0.5)
            except asyncio.TimeoutError:
                if self._baseline and asyncio.get_event_loop().time() >= self._baseline_deadline:
                    self._finish_baseline()
                continue
            if isinstance(item, EoseMarker):
                self._eose_urls.add(item.url)
                if self._baseline and len(self._eose_urls) >= self._expected_eose:
                    self._finish_baseline()
                continue
            await self._handle(item)

    def _finish_baseline(self) -> None:
        if not self._baseline:
            return
        self._baseline = False
        if self._baseline_suppressed > 0:
            line = json.dumps({
                "type": "backlog",
                "suppressed": self._baseline_suppressed,
                "through": self._baseline_through,
                "received_at": int(time.time()),
            })
            self._stdout.write(line + "\n")
            self._stdout.flush()

    async def _handle(self, ev) -> None:
        try:
            dm = unwrap_giftwrapped_dm(ev, recipient=self._identity)
        except Exception as e:
            print(f"agent-wormhole: dropped malformed DM: {e}", file=sys.stderr)
            return
        sender_pub, content = dm.sender_pubkey, dm.content
        peer = self._trust.by_pubkey(sender_pub)
        if peer is None:
            print(
                f"agent-wormhole: dropped DM from untrusted {sender_pub[:12]}",
                file=sys.stderr,
            )
            return
        if not self._replay:
            # Durable mark-as-read: a message surfaced once is never surfaced again,
            # across restarts and across every relay that replays it.
            if dm.rumor_id in self._seen:
                return
            self._seen.add(dm.rumor_id, dm.created_at)
            if self._baseline:
                # Cold-start history: mark read, count for the summary, don't surface.
                self._baseline_suppressed += 1
                self._baseline_through = max(self._baseline_through, dm.created_at)
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
