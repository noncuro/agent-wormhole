"""Channel logic: handshake, send/receive loops."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from typing import Callable, TextIO

from agent_wormhole.config import get_relay_url
from agent_wormhole.crypto import Handshake, SessionKeys, decrypt, encrypt
from agent_wormhole.fs import (
    DEFAULT_BASE,
    cleanup_channel,
    detect_role,
    get_outbox_path,
    init_channel_dir,
    safe_save_file,
    safe_save_text,
)
from agent_wormhole.protocol import make_version_message, parse_message
from agent_wormhole.transport import DirectTransport, RelayTransport, Transport
from agent_wormhole.wordlist import generate_code, generate_relay_code, parse_code

TEXT_STDOUT_LIMIT = 1024  # 1KB


def _emit(output: TextIO, data: dict) -> None:
    """Print a JSON line to the output stream, flush immediately."""
    output.write(json.dumps(data) + "\n")
    output.flush()


async def _do_handshake(
    transport: Transport,
    password: bytes,
    is_host: bool,
) -> SessionKeys:
    """Perform SPAKE2 handshake over the transport."""
    if is_host:
        hs = Handshake.host(password)
    else:
        hs = Handshake.peer(password)

    my_msg = hs.start()
    await transport.send_frame(my_msg)
    their_msg = await transport.recv_frame()
    keys = hs.finish(their_msg)

    # Version exchange
    role = "host" if is_host else "peer"
    version_msg = make_version_message(role).encode()
    encrypted = encrypt(keys, version_msg, sending=True)
    await transport.send_frame(encrypted)

    their_version_enc = await transport.recv_frame()
    their_version_raw = decrypt(keys, their_version_enc, receiving=True).decode()
    their_version = json.loads(their_version_raw)

    if their_version.get("version") != 1:
        raise ValueError(f"Incompatible protocol version: {their_version}")

    return keys


async def _outbox_watcher(
    code: str,
    keys: SessionKeys,
    transport: Transport,
    *,
    role: str,
    base: Path = DEFAULT_BASE,
) -> None:
    """Poll the outbox file and send new messages over the transport."""
    outbox_path = get_outbox_path(code, role=role, base=base)
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
            await transport.send_frame(encrypted)


async def _receiver(
    code: str,
    keys: SessionKeys,
    transport: Transport,
    output: TextIO,
    *,
    base: Path = DEFAULT_BASE,
) -> None:
    """Read incoming messages from transport, decrypt, and print to stdout."""
    while True:
        try:
            encrypted = await transport.recv_frame()
        except (asyncio.IncompleteReadError, ConnectionError):
            _emit(output, {"type": "status", "event": "disconnected"})
            return

        try:
            raw = decrypt(keys, encrypted, receiving=True).decode()
        except Exception:
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


async def _run_channel(
    transport: Transport,
    code: str,
    role: str,
    output: TextIO,
    base: Path,
) -> None:
    """Common logic: handshake then run send/receive loops."""
    try:
        keys = await _do_handshake(transport, code.encode(), is_host=(role == "host"))
    except Exception as e:
        _emit(output, {"type": "status", "event": "handshake_failed", "detail": str(e)})
        await transport.close()
        cleanup_channel(code, base=base)
        return

    _emit(output, {"type": "status", "event": "connected"})

    try:
        await asyncio.gather(
            _outbox_watcher(code, keys, transport, role=role, base=base),
            _receiver(code, keys, transport, output, base=base),
        )
    finally:
        await transport.close()
        cleanup_channel(code, base=base)


async def run_host(
    port: int = 0,
    output: TextIO = sys.stdout,
    timeout: float | None = None,
    on_code: Callable[[str], None] | None = None,
    base: Path = DEFAULT_BASE,
    *,
    relay_url: str | None = None,
    direct: bool = False,
) -> None:
    """Host a channel: listen, handshake, then run send/receive loops.

    By default uses relay mode. Pass direct=True for legacy TCP mode.
    """
    if direct:
        # Legacy direct TCP mode
        transport = DirectTransport.as_host(port=port)
        await transport.connect()  # Starts listening, returns immediately
        code = generate_code(port=transport.port)
        init_channel_dir(code, role="host", base=base)

        _emit(output, {"type": "status", "event": "channel", "code": code})
        _emit(output, {"type": "status", "event": "waiting"})

        if on_code:
            on_code(code)

        # Wait for peer to connect
        try:
            await transport.accept(timeout=timeout)
        except asyncio.TimeoutError:
            _emit(output, {"type": "status", "event": "timeout"})
            await transport.close()
            cleanup_channel(code, base=base)
            return

        await _run_channel(transport, code, "host", output, base)
    else:
        # Relay mode
        code = generate_relay_code()
        init_channel_dir(code, role="host", base=base)

        _emit(output, {"type": "status", "event": "channel", "code": code})

        if on_code:
            on_code(code)

        url = get_relay_url(relay_url)
        transport = RelayTransport(url, code, "host")

        try:
            await transport.connect()
        except Exception as e:
            _emit(output, {"type": "status", "event": "connection_failed", "detail": str(e)})
            cleanup_channel(code, base=base)
            return

        status_event = transport.status.get("event", "waiting")
        _emit(output, {"type": "status", "event": status_event})

        try:
            if timeout:
                await asyncio.wait_for(
                    _run_channel(transport, code, "host", output, base),
                    timeout=timeout,
                )
            else:
                await _run_channel(transport, code, "host", output, base)
        except asyncio.TimeoutError:
            _emit(output, {"type": "status", "event": "timeout"})
            await transport.close()
            cleanup_channel(code, base=base)


async def run_peer(
    target: str,
    output: TextIO = sys.stdout,
    timeout: float | None = None,
    base: Path = DEFAULT_BASE,
    *,
    relay_url: str | None = None,
) -> None:
    """Connect to a hosted channel, handshake, then run send/receive loops."""
    port, code, hostname = parse_code(target)

    if port is not None:
        # Direct mode (has port prefix and hostname)
        if not hostname:
            raise ValueError("Direct-mode target must include hostname: <code>@<hostname>")

        init_channel_dir(code, role="peer", base=base)
        transport = DirectTransport.as_peer(hostname=hostname, port=port)

        try:
            if timeout:
                await asyncio.wait_for(transport.connect(), timeout=timeout)
            else:
                await transport.connect()
        except Exception as e:
            _emit(output, {"type": "status", "event": "connection_failed", "detail": str(e)})
            cleanup_channel(code, base=base)
            return
    else:
        # Relay mode (3-word code, no port)
        init_channel_dir(code, role="peer", base=base)
        url = get_relay_url(relay_url)
        transport = RelayTransport(url, code, "peer")

        try:
            await transport.connect()
        except Exception as e:
            _emit(output, {"type": "status", "event": "connection_failed", "detail": str(e)})
            cleanup_channel(code, base=base)
            return

    try:
        if timeout:
            await asyncio.wait_for(
                _run_channel(transport, code, "peer", output, base),
                timeout=timeout,
            )
        else:
            await _run_channel(transport, code, "peer", output, base)
    except asyncio.TimeoutError:
        _emit(output, {"type": "status", "event": "timeout"})
        await transport.close()
        cleanup_channel(code, base=base)


def send_to_outbox(
    code: str,
    message: str | None = None,
    *,
    file_path: str | None = None,
    role: str | None = None,
    base: Path = DEFAULT_BASE,
) -> None:
    """Append a message to the channel's outbox file.

    If role is None, auto-detects which role is present locally.
    On same-machine setups (both roles present), role must be specified.
    """
    if role is None:
        role = detect_role(code, base=base)
    outbox = get_outbox_path(code, role=role, base=base)
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
