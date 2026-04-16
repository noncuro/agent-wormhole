"""Transport abstraction for channel communication."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

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
