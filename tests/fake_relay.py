"""In-process Nostr relay for tests. Pure-Python; no external services."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import websockets


class FakeRelay:
    def __init__(self):
        self.events: list[dict] = []
        self.subs: dict = {}  # ws -> {sid: filter}

    async def _handle(self, ws):
        self.subs[ws] = {}
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg[0] == "EVENT":
                    ev = msg[1]
                    self.events.append(ev)
                    await ws.send(json.dumps(["OK", ev["id"], True, ""]))
                    for w, subs in list(self.subs.items()):
                        for sid, flt in subs.items():
                            if self._matches(ev, flt):
                                try:
                                    await w.send(json.dumps(["EVENT", sid, ev]))
                                except Exception:
                                    pass
                elif msg[0] == "REQ":
                    sid, flt = msg[1], msg[2]
                    self.subs[ws][sid] = flt
                    for ev in self.events:
                        if self._matches(ev, flt):
                            await ws.send(json.dumps(["EVENT", sid, ev]))
                    await ws.send(json.dumps(["EOSE", sid]))
                elif msg[0] == "CLOSE":
                    self.subs[ws].pop(msg[1], None)
        finally:
            self.subs.pop(ws, None)

    @staticmethod
    def _matches(ev: dict, flt: dict) -> bool:
        if "kinds" in flt and ev["kind"] not in flt["kinds"]:
            return False
        if "authors" in flt and ev["pubkey"] not in flt["authors"]:
            return False
        for k, v in flt.items():
            if k.startswith("#"):
                tag = k[1:]
                ev_tag_vals = [
                    t[1] for t in ev.get("tags", []) if t and t[0] == tag and len(t) > 1
                ]
                if not any(val in v for val in ev_tag_vals):
                    return False
        return True


@asynccontextmanager
async def fake_relay():
    relay = FakeRelay()
    server = await websockets.serve(relay._handle, "127.0.0.1", 0)
    sock = next(iter(server.sockets))
    port = sock.getsockname()[1]
    try:
        yield (f"ws://127.0.0.1:{port}", relay)
    finally:
        server.close()
        await server.wait_closed()
