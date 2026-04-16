"""Transport abstraction for channel communication."""
from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod

from websockets.asyncio.client import connect as ws_connect, ClientConnection

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
    """WebSocket transport through a relay server."""

    def __init__(self, relay_url: str, code: str, role: str):
        self._relay_url = relay_url
        self._code = code
        self._role = role
        self._ws: ClientConnection | None = None
        self._status: dict = {}

    async def connect(self) -> None:
        ws_url = self._relay_url.rstrip("/") + "/ws"
        self._ws = await ws_connect(ws_url)
        # Send join message
        join_msg = json.dumps({
            "action": "join",
            "code": self._code,
            "role": self._role,
        })
        await self._ws.send(join_msg)
        # Wait for status response
        raw = await self._ws.recv(decode=False)
        if isinstance(raw, bytes):
            raw = raw.decode()
        status = json.loads(raw)
        if status.get("type") == "error":
            raise ConnectionError(
                f"Relay rejected join: {status.get('message', 'unknown error')}"
            )
        self._status = status

    @property
    def status(self) -> dict:
        """The join status response from the relay."""
        return self._status

    async def send_frame(self, data: bytes) -> None:
        assert self._ws is not None
        await self._ws.send(data)

    async def recv_frame(self) -> bytes:
        assert self._ws is not None
        data = await self._ws.recv(decode=False)
        if isinstance(data, str):
            # Could be a JSON control message from relay
            msg = json.loads(data)
            if msg.get("type") == "status" and msg.get("event") == "peer_disconnected":
                raise ConnectionError("Peer disconnected")
            if msg.get("type") == "error":
                raise ConnectionError(f"Relay error: {msg.get('message')}")
            # For paired notifications, recurse to get the next binary frame
            return await self.recv_frame()
        return data

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()
