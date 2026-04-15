from __future__ import annotations

import asyncio
import base64
import json
import struct

MAX_FRAME_SIZE = 10 * 1024 * 1024  # 10MB
PROTOCOL_VERSION = 1
_HEADER_FMT = "!I"  # big-endian uint32
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


class FrameTooLargeError(Exception):
    pass


def encode_frame(payload: bytes) -> bytes:
    """Wrap payload in a length-prefixed frame."""
    return struct.pack(_HEADER_FMT, len(payload)) + payload


def decode_frame(data: bytes) -> bytes:
    """Extract payload from a length-prefixed frame. Validates size limit."""
    if len(data) < _HEADER_SIZE:
        raise ValueError("Frame too short")
    (length,) = struct.unpack(_HEADER_FMT, data[:_HEADER_SIZE])
    if length > MAX_FRAME_SIZE:
        raise FrameTooLargeError(f"Frame length {length} exceeds {MAX_FRAME_SIZE}")
    return data[_HEADER_SIZE : _HEADER_SIZE + length]


async def read_frame(reader: asyncio.StreamReader) -> bytes:
    """Read one length-prefixed frame from an asyncio StreamReader."""
    header = await reader.readexactly(_HEADER_SIZE)
    (length,) = struct.unpack(_HEADER_FMT, header)
    if length > MAX_FRAME_SIZE:
        raise FrameTooLargeError(f"Frame length {length} exceeds {MAX_FRAME_SIZE}")
    return await reader.readexactly(length)


async def write_frame(writer: asyncio.StreamWriter, payload: bytes) -> None:
    """Write one length-prefixed frame to an asyncio StreamWriter."""
    writer.write(encode_frame(payload))
    await writer.drain()


def make_text_message(body: str) -> str:
    """Create a text message JSON string."""
    return json.dumps({"type": "text", "body": body})


def make_file_message(name: str, data: bytes) -> str:
    """Create a file message JSON string with base64-encoded content."""
    return json.dumps({
        "type": "file",
        "name": name,
        "size": len(data),
        "body": base64.b64encode(data).decode(),
    })


def make_version_message(role: str) -> str:
    """Create a version exchange JSON string."""
    return json.dumps({"version": PROTOCOL_VERSION, "role": role})


def parse_message(raw: str) -> dict:
    """Parse a JSON message envelope. Decodes file data if present."""
    msg = json.loads(raw)
    if msg.get("type") == "file" and "body" in msg:
        msg["file_data"] = base64.b64decode(msg["body"])
    return msg
