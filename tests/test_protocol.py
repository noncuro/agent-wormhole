import asyncio
import json
import pytest
from agent_wormhole.protocol import (
    encode_frame,
    decode_frame,
    make_text_message,
    make_file_message,
    make_version_message,
    parse_message,
    FrameTooLargeError,
)


def test_encode_decode_frame_roundtrip():
    payload = b"hello world"
    frame = encode_frame(payload)
    assert len(frame) == 4 + len(payload)
    decoded = decode_frame(frame)
    assert decoded == payload


def test_frame_length_prefix_is_big_endian():
    payload = b"test"
    frame = encode_frame(payload)
    length = int.from_bytes(frame[:4], "big")
    assert length == 4


def test_decode_frame_too_large():
    # Craft a frame with length > 10MB
    fake_length = (11 * 1024 * 1024).to_bytes(4, "big")
    with pytest.raises(FrameTooLargeError):
        decode_frame(fake_length + b"x")


def test_make_text_message():
    msg = make_text_message("hello")
    parsed = json.loads(msg)
    assert parsed == {"type": "text", "body": "hello"}


def test_make_file_message():
    msg = make_file_message("test.txt", b"file content here")
    parsed = json.loads(msg)
    assert parsed["type"] == "file"
    assert parsed["name"] == "test.txt"
    assert parsed["size"] == 17
    import base64
    assert base64.b64decode(parsed["body"]) == b"file content here"


def test_make_version_message():
    msg = make_version_message("host")
    parsed = json.loads(msg)
    assert parsed == {"version": 1, "role": "host"}


def test_parse_message_text():
    raw = json.dumps({"type": "text", "body": "hi"})
    msg = parse_message(raw)
    assert msg["type"] == "text"
    assert msg["body"] == "hi"


def test_parse_message_file():
    import base64
    raw = json.dumps({
        "type": "file",
        "name": "x.txt",
        "size": 5,
        "body": base64.b64encode(b"hello").decode(),
    })
    msg = parse_message(raw)
    assert msg["type"] == "file"
    assert msg["name"] == "x.txt"
    assert msg["file_data"] == b"hello"


def test_parse_message_version():
    raw = json.dumps({"version": 1, "role": "peer"})
    msg = parse_message(raw)
    assert msg["version"] == 1
    assert msg["role"] == "peer"


class TestAsyncStreamProtocol:
    """Test reading/writing frames over asyncio streams."""

    @pytest.mark.asyncio
    async def test_read_write_frame(self):
        from agent_wormhole.protocol import write_frame, read_frame

        # Create an in-memory stream pair
        reader = asyncio.StreamReader()

        payload = b"test payload"
        frame = encode_frame(payload)
        reader.feed_data(frame)
        reader.feed_eof()

        result = await read_frame(reader)
        assert result == payload

    @pytest.mark.asyncio
    async def test_read_frame_too_large(self):
        from agent_wormhole.protocol import read_frame

        reader = asyncio.StreamReader()
        fake_length = (11 * 1024 * 1024).to_bytes(4, "big")
        reader.feed_data(fake_length)
        reader.feed_eof()

        with pytest.raises(FrameTooLargeError):
            await read_frame(reader)
