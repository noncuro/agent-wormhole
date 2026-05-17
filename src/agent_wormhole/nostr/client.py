from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass

import websockets

from agent_wormhole.nostr.events import Event


@dataclass
class Subscription:
    sub_id: str
    queue: asyncio.Queue

    async def next(self) -> Event:
        return await self.queue.get()


class RelayPool:
    def __init__(self, urls: list[str]):
        self._urls = urls
        self._conns: dict[str, "websockets.WebSocketClientProtocol"] = {}
        self._readers: list[asyncio.Task] = []
        self._subs: dict[str, tuple[Subscription, dict]] = {}
        self._seen_ids: set[str] = set()
        self._ack_waiters: dict[str, dict[str, asyncio.Future]] = {}

    async def connect(self) -> None:
        for url in self._urls:
            try:
                ws = await websockets.connect(url, open_timeout=10)
            except Exception:
                continue
            self._conns[url] = ws
            self._readers.append(asyncio.create_task(self._reader(url, ws)))

    async def _reader(self, url: str, ws) -> None:
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                tag = msg[0] if msg else None
                if tag == "EVENT":
                    _, sub_id, ev_dict = msg
                    if ev_dict["id"] in self._seen_ids:
                        continue
                    self._seen_ids.add(ev_dict["id"])
                    entry = self._subs.get(sub_id)
                    if entry is not None:
                        await entry[0].queue.put(Event.from_dict(ev_dict))
                elif tag == "EOSE":
                    pass
                elif tag == "OK":
                    _, ev_id, ok, _msg = msg
                    waiters = self._ack_waiters.get(ev_id)
                    if waiters and url in waiters and not waiters[url].done():
                        waiters[url].set_result(bool(ok))
        except Exception:
            pass

    async def publish(self, ev: Event) -> dict[str, bool]:
        waiters = {url: asyncio.get_running_loop().create_future() for url in self._conns}
        self._ack_waiters[ev.id] = waiters
        for url, ws in self._conns.items():
            await ws.send(json.dumps(["EVENT", ev.to_dict()]))
        results: dict[str, bool] = {}
        for url, fut in waiters.items():
            try:
                results[url] = await asyncio.wait_for(fut, timeout=5.0)
            except asyncio.TimeoutError:
                results[url] = False
        self._ack_waiters.pop(ev.id, None)
        return results

    async def subscribe(self, flt: dict) -> Subscription:
        sub_id = secrets.token_hex(8)
        sub = Subscription(sub_id=sub_id, queue=asyncio.Queue())
        self._subs[sub_id] = (sub, flt)
        for ws in self._conns.values():
            await ws.send(json.dumps(["REQ", sub_id, flt]))
        return sub

    async def unsubscribe(self, sub_id: str) -> None:
        for ws in self._conns.values():
            try:
                await ws.send(json.dumps(["CLOSE", sub_id]))
            except Exception:
                pass
        self._subs.pop(sub_id, None)

    async def close(self) -> None:
        for t in self._readers:
            t.cancel()
        for ws in self._conns.values():
            try:
                await ws.close()
            except Exception:
                pass
