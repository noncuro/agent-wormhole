"""Transport abstraction for channel communication."""
from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Callable

from websockets.asyncio.client import connect as ws_connect, ClientConnection
from websockets.exceptions import ConnectionClosed

from agent_wormhole.protocol import read_frame, write_frame


class Transport(ABC):
    """Abstract base for bidirectional frame transport."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish the connection."""

    @abstractmethod
    async def send_frame(self, data: bytes) -> None:
        """Send a single frame."""

    @abstractmethod
    async def recv_frame(self) -> bytes:
        """Receive a single frame. Raises on connection loss."""

    @abstractmethod
    async def close(self) -> None:
        """Close the transport."""


class DirectTransport(Transport):
    """TCP transport -- existing peer-to-peer mode.

    For hosts: connect() starts listening and returns immediately.
    Call accept() to wait for a peer to connect.
    For peers: connect() opens the TCP connection and returns when connected.
    """

    def __init__(self):
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._server: asyncio.Server | None = None
        self._is_host: bool = False
        self._hostname: str | None = None
        self._port: int = 0
        self._accepted: asyncio.Future[
            tuple[asyncio.StreamReader, asyncio.StreamWriter]
        ] | None = None

    @classmethod
    def as_host(cls, port: int = 0) -> DirectTransport:
        t = cls()
        t._is_host = True
        t._port = port
        return t

    @classmethod
    def as_peer(cls, hostname: str, port: int) -> DirectTransport:
        t = cls()
        t._is_host = False
        t._hostname = hostname
        t._port = port
        return t

    @property
    def port(self) -> int:
        """The actual bound port (available after connect for host)."""
        return self._port

    async def connect(self) -> None:
        if self._is_host:
            self._accepted = asyncio.get_event_loop().create_future()

            async def handle_client(
                reader: asyncio.StreamReader, writer: asyncio.StreamWriter
            ):
                if self._accepted and not self._accepted.done():
                    self._accepted.set_result((reader, writer))

            self._server = await asyncio.start_server(
                handle_client, "0.0.0.0", self._port
            )
            self._port = self._server.sockets[0].getsockname()[1]
            # Returns immediately -- call accept() to wait for peer
        else:
            self._reader, self._writer = await asyncio.open_connection(
                self._hostname, self._port
            )

    async def accept(self, timeout: float | None = None) -> None:
        """Wait for a peer to connect (host only). Call after connect()."""
        assert self._accepted is not None, "accept() requires host mode after connect()"
        if timeout:
            self._reader, self._writer = await asyncio.wait_for(
                self._accepted, timeout=timeout
            )
        else:
            self._reader, self._writer = await self._accepted
        if self._server:
            self._server.close()

    async def send_frame(self, data: bytes) -> None:
        assert self._writer is not None
        await write_frame(self._writer, data)

    async def recv_frame(self) -> bytes:
        assert self._reader is not None
        return await read_frame(self._reader)

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
        if self._server:
            self._server.close()


class RelayTransport(Transport):
    """WebSocket transport through a relay server.

    Transparently reconnects on transient network drops. The relay preserves
    per-role cursor position, so frames buffered in the Redis stream while we
    were away are replayed on reconnect. A peer_disconnected control message
    is surfaced via the on_status callback and does not end the channel — the
    peer may be reconnecting, and anything it sends will arrive via the stream.
    """

    RECONNECT_ATTEMPTS = 10
    RECONNECT_DELAY = 1.0
    RECONNECT_BACKOFF = 1.5
    RECONNECT_MAX_DELAY = 5.0

    def __init__(
        self,
        relay_url: str,
        code: str,
        role: str,
        on_status: Callable[[dict], None] | None = None,
    ):
        self._relay_url = relay_url
        self._code = code
        self._role = role
        self._ws: ClientConnection | None = None
        self._status: dict = {}
        self._on_status = on_status
        self._reconnect_lock = asyncio.Lock()
        self._closed = False

    async def _open_ws(self) -> tuple[ClientConnection, dict]:
        ws_url = self._relay_url.rstrip("/") + "/ws"
        ws = await ws_connect(ws_url, open_timeout=30)
        join_msg = json.dumps({
            "action": "join",
            "code": self._code,
            "role": self._role,
        })
        await ws.send(join_msg)
        raw = await ws.recv(decode=False)
        if isinstance(raw, bytes):
            raw = raw.decode()
        status = json.loads(raw)
        if status.get("type") == "error":
            await ws.close()
            raise ConnectionError(
                f"Relay rejected join: {status.get('message', 'unknown error')}"
            )
        return ws, status

    async def connect(self) -> None:
        self._ws, self._status = await self._open_ws()

    @property
    def status(self) -> dict:
        """The join status response from the relay."""
        return self._status

    async def _reconnect_if_stale(self, stale_ws: ClientConnection | None) -> None:
        """Reopen the WS if the one we tried to use is the current (stale) one.

        Retries across slot-taken races (server hasn't yet freed our role after
        the old socket died). Raises if reconnect fails after RECONNECT_ATTEMPTS.
        """
        async with self._reconnect_lock:
            if self._closed:
                raise ConnectionError("transport closed")
            if self._ws is not stale_ws:
                return  # Another coroutine already reconnected
            if self._on_status:
                self._on_status({"type": "status", "event": "reconnecting"})
            if stale_ws is not None:
                try:
                    await stale_ws.close()
                except Exception:
                    pass
            delay = self.RECONNECT_DELAY
            last_exc: Exception | None = None
            for attempt in range(self.RECONNECT_ATTEMPTS):
                try:
                    ws, status = await self._open_ws()
                    self._ws = ws
                    self._status = status
                    if self._on_status:
                        self._on_status({"type": "status", "event": "reconnected"})
                    return
                except Exception as e:
                    last_exc = e
                    if attempt == self.RECONNECT_ATTEMPTS - 1:
                        break
                    await asyncio.sleep(delay)
                    delay = min(delay * self.RECONNECT_BACKOFF, self.RECONNECT_MAX_DELAY)
            raise ConnectionError(f"reconnect failed: {last_exc}")

    async def send_frame(self, data: bytes) -> None:
        for _ in range(2):
            ws = self._ws
            assert ws is not None
            try:
                await ws.send(data)
                return
            except ConnectionClosed:
                await self._reconnect_if_stale(ws)
        raise ConnectionError("send_frame failed after reconnect")

    async def recv_frame(self) -> bytes:
        while True:
            ws = self._ws
            assert ws is not None
            try:
                data = await ws.recv(decode=False)
            except ConnectionClosed:
                await self._reconnect_if_stale(ws)
                continue
            if isinstance(data, str):
                msg = json.loads(data)
                event = msg.get("event") if msg.get("type") == "status" else None
                if event == "peer_disconnected":
                    if self._on_status:
                        self._on_status(msg)
                    continue
                if msg.get("type") == "error":
                    if self._on_status:
                        self._on_status(msg)
                    continue
                # Other status (paired, waiting) after a reconnect — ignore
                continue
            return data

    async def close(self) -> None:
        self._closed = True
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
