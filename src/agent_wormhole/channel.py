from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from typing import Callable, TextIO

from agent_wormhole.crypto import Handshake, SessionKeys, decrypt, encrypt
from agent_wormhole.fs import (
    DEFAULT_BASE,
    cleanup_channel,
    get_outbox_path,
    init_channel_dir,
    safe_save_file,
    safe_save_text,
)
from agent_wormhole.protocol import (
    FrameTooLargeError,
    make_version_message,
    parse_message,
    read_frame,
    write_frame,
)
from agent_wormhole.wordlist import generate_code, parse_code

TEXT_STDOUT_LIMIT = 1024  # 1KB


def _emit(output: TextIO, data: dict) -> None:
    """Print a JSON line to the output stream, flush immediately."""
    output.write(json.dumps(data) + "\n")
    output.flush()


async def _do_handshake(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    password: bytes,
    is_host: bool,
) -> SessionKeys:
    """Perform SPAKE2 handshake over the TCP connection."""
    if is_host:
        hs = Handshake.host(password)
    else:
        hs = Handshake.peer(password)

    my_msg = hs.start()
    await write_frame(writer, my_msg)
    their_msg = await read_frame(reader)
    keys = hs.finish(their_msg)

    # Version exchange
    role = "host" if is_host else "peer"
    version_msg = make_version_message(role).encode()
    encrypted = encrypt(keys, version_msg, sending=True)
    await write_frame(writer, encrypted)

    their_version_enc = await read_frame(reader)
    their_version_raw = decrypt(keys, their_version_enc, receiving=True).decode()
    their_version = json.loads(their_version_raw)

    if their_version.get("version") != 1:
        raise ValueError(f"Incompatible protocol version: {their_version}")

    return keys


async def _outbox_watcher(
    code: str,
    keys: SessionKeys,
    writer: asyncio.StreamWriter,
    *,
    base: Path = DEFAULT_BASE,
) -> None:
    """Poll the outbox file and send new messages over the wire."""
    outbox_path = get_outbox_path(code, base=base)
    last_pos = 0

    while True:
        await asyncio.sleep(0.1)
        if not outbox_path.exists():
            continue

        content = outbox_path.read_text()
        if len(content) <= last_pos:
            continue

        new_content = content[last_pos:]
        last_pos = len(content)

        for line in new_content.strip().split("\n"):
            if not line.strip():
                continue
            msg = json.loads(line)
            if msg["type"] == "file" and "path" in msg:
                file_data = Path(msg["path"]).read_bytes()
                wire_msg = json.dumps({
                    "type": "file",
                    "name": msg["name"],
                    "size": len(file_data),
                    "body": base64.b64encode(file_data).decode(),
                })
            else:
                wire_msg = line

            encrypted = encrypt(keys, wire_msg.encode(), sending=True)
            await write_frame(writer, encrypted)


async def _receiver(
    code: str,
    keys: SessionKeys,
    reader: asyncio.StreamReader,
    output: TextIO,
    *,
    base: Path = DEFAULT_BASE,
) -> None:
    """Read incoming messages from TCP, decrypt, and print to stdout."""
    while True:
        try:
            encrypted = await read_frame(reader)
        except (asyncio.IncompleteReadError, ConnectionError):
            _emit(output, {"type": "status", "event": "disconnected"})
            return

        try:
            raw = decrypt(keys, encrypted, receiving=True).decode()
        except Exception:
            # Decrypt failure means nonce desync or tampered data — channel is broken
            _emit(output, {"type": "status", "event": "error", "detail": "decryption failed, closing channel"})
            return

        msg = parse_message(raw)

        if msg.get("type") == "text":
            body = msg["body"]
            if len(body) <= TEXT_STDOUT_LIMIT:
                _emit(output, {"type": "text", "body": body})
            else:
                path = safe_save_text(code, body, base=base)
                _emit(output, {"type": "text", "saved_to": str(path), "size": len(body)})

        elif msg.get("type") == "file":
            file_data = msg["file_data"]
            name = msg["name"]
            path = safe_save_file(code, name, file_data, base=base)
            _emit(output, {"type": "file", "name": name, "saved_to": str(path), "size": len(file_data)})


async def run_host(
    port: int = 0,
    output: TextIO = sys.stdout,
    timeout: float | None = None,
    on_code: Callable[[str], None] | None = None,
    base: Path = DEFAULT_BASE,
) -> None:
    """Host a channel: listen, handshake, then run send/receive loops."""
    # Bind first, then generate code with the actual port (avoids race condition)
    connected: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = asyncio.Future()

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        if not connected.done():
            connected.set_result((reader, writer))

    server = await asyncio.start_server(handle_client, "0.0.0.0", port)
    actual_port = server.sockets[0].getsockname()[1]
    code = generate_code(port=actual_port)
    channel_dir = init_channel_dir(code, base=base)

    _emit(output, {"type": "status", "event": "channel", "code": code})
    _emit(output, {"type": "status", "event": "waiting"})

    if on_code:
        on_code(code)

    try:
        if timeout:
            reader, writer = await asyncio.wait_for(connected, timeout=timeout)
        else:
            reader, writer = await connected
    except asyncio.TimeoutError:
        server.close()
        _emit(output, {"type": "status", "event": "timeout"})
        cleanup_channel(code, base=base)
        return

    # Stop accepting new connections (single-use)
    server.close()

    try:
        keys = await _do_handshake(reader, writer, code.encode(), is_host=True)
    except Exception as e:
        _emit(output, {"type": "status", "event": "handshake_failed", "detail": str(e)})
        writer.close()
        cleanup_channel(code, base=base)
        return

    _emit(output, {"type": "status", "event": "connected"})

    try:
        # Run outbox watcher and receiver concurrently
        await asyncio.gather(
            _outbox_watcher(code, keys, writer, base=base),
            _receiver(code, keys, reader, output, base=base),
        )
    finally:
        writer.close()
        cleanup_channel(code, base=base)


async def run_peer(
    target: str,
    output: TextIO = sys.stdout,
    timeout: float | None = None,
    base: Path = DEFAULT_BASE,
) -> None:
    """Connect to a hosted channel, handshake, then run send/receive loops."""
    port, code, hostname = parse_code(target)
    if not hostname:
        raise ValueError("Target must include hostname: <code>@<hostname>")

    channel_dir = init_channel_dir(code, base=base)

    try:
        if timeout:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(hostname, port), timeout=timeout
            )
        else:
            reader, writer = await asyncio.open_connection(hostname, port)
    except Exception as e:
        _emit(output, {"type": "status", "event": "connection_failed", "detail": str(e)})
        cleanup_channel(code, base=base)
        return

    try:
        keys = await _do_handshake(reader, writer, code.encode(), is_host=False)
    except Exception as e:
        _emit(output, {"type": "status", "event": "handshake_failed", "detail": str(e)})
        writer.close()
        cleanup_channel(code, base=base)
        return

    _emit(output, {"type": "status", "event": "connected"})

    try:
        await asyncio.gather(
            _outbox_watcher(code, keys, writer, base=base),
            _receiver(code, keys, reader, output, base=base),
        )
    finally:
        writer.close()
        cleanup_channel(code, base=base)


def send_to_outbox(
    code: str,
    message: str | None = None,
    *,
    file_path: str | None = None,
    base: Path = DEFAULT_BASE,
) -> None:
    """Append a message to the channel's outbox file."""
    outbox = get_outbox_path(code, base=base)
    if message is not None:
        entry = json.dumps({"type": "text", "body": message})
    elif file_path is not None:
        name = Path(file_path).name
        entry = json.dumps({"type": "file", "name": name, "path": str(Path(file_path).resolve())})
    else:
        raise ValueError("Must provide either message or file_path")

    fd = os.open(str(outbox), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (entry + "\n").encode())
    finally:
        os.close(fd)
