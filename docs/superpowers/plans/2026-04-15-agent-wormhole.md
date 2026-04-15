# agent-wormhole Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a secure, ephemeral CLI channel for two Claude Code instances to communicate across machines.

**Architecture:** Python async TCP server/client with SPAKE2 key exchange and AES-256-GCM encryption. One side hosts (listens), the other connects. Messages flow bidirectionally — incoming messages print to stdout as JSON (for Claude Code Monitor), outgoing messages are written to an outbox file that the background process polls and sends.

**Tech Stack:** Python 3.11+, Typer, `spake2` (PAKE), `cryptography` (HKDF + AES-GCM), asyncio, uv

**Spec:** `docs/2026-04-15-agent-wormhole-design.md`

---

## File Structure

```
agent-wormhole/
  pyproject.toml              # uv project config, CLI entry point
  src/
    agent_wormhole/
      __init__.py             # version
      cli.py                  # Typer app: host, connect, send, status, close
      crypto.py               # SPAKE2 handshake, HKDF key derivation, AES-GCM encrypt/decrypt
      protocol.py             # Wire framing (length-prefix), JSON envelopes, version exchange
      channel.py              # Core channel loop: TCP + outbox watcher + stdout printer
      wordlist.py             # Channel code generation and parsing
      words.txt               # 256-word list
      fs.py                   # Secure /tmp directory management, cleanup
  skill/
    agent-wormhole/
      skill.md                # Claude Code skill instructions
  tests/
    test_wordlist.py
    test_crypto.py
    test_protocol.py
    test_fs.py
    test_channel.py           # Integration: host + connect over loopback
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/agent_wormhole/__init__.py`
- Create: `src/agent_wormhole/cli.py`

- [ ] **Step 1: Initialize uv project**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv init --lib --name agent-wormhole
```

This creates `pyproject.toml` and `src/agent_wormhole/__init__.py`. We'll replace both.

- [ ] **Step 2: Write pyproject.toml**

Replace the generated `pyproject.toml` with:

```toml
[project]
name = "agent-wormhole"
version = "0.1.0"
description = "Secure ephemeral channels for AI agent communication"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.9",
    "spake2>=0.9",
    "cryptography>=42.0",
]

[project.scripts]
agent-wormhole = "agent_wormhole.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

- [ ] **Step 3: Write __init__.py**

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Write minimal CLI stub**

Create `src/agent_wormhole/cli.py`:

```python
import typer

app = typer.Typer(name="agent-wormhole", help="Secure ephemeral channels for AI agent communication")


@app.command()
def host(port: int = typer.Option(0, help="Port to listen on (0 = random)")):
    """Host a new channel and wait for a peer to connect."""
    typer.echo("Not implemented yet")


@app.command()
def connect(target: str = typer.Argument(help="<code>@<hostname> to connect to")):
    """Connect to an existing channel."""
    typer.echo("Not implemented yet")


@app.command()
def send(code: str = typer.Argument(help="Channel code"), message: str = typer.Argument(default=None, help="Text message"), file: str = typer.Option(None, "--file", help="Path to file to send")):
    """Send a message or file through a channel."""
    typer.echo("Not implemented yet")


@app.command()
def status():
    """Show active channels."""
    typer.echo("Not implemented yet")


@app.command()
def close(code: str = typer.Argument(help="Channel code to close")):
    """Close a channel and clean up."""
    typer.echo("Not implemented yet")
```

- [ ] **Step 5: Install and verify CLI works**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv sync
uv run agent-wormhole --help
```

Expected: help output showing all 5 commands.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/ uv.lock
git commit -m "feat: project scaffolding with Typer CLI stub"
```

---

### Task 2: Wordlist and Channel Codes

**Files:**
- Create: `src/agent_wormhole/words.txt`
- Create: `src/agent_wormhole/wordlist.py`
- Create: `tests/test_wordlist.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_wordlist.py`:

```python
from agent_wormhole.wordlist import generate_code, parse_code, WORDS


def test_wordlist_has_256_words():
    assert len(WORDS) == 256


def test_wordlist_words_are_lowercase_alpha():
    for word in WORDS:
        assert word.isalpha()
        assert word.islower()
        assert 3 <= len(word) <= 10


def test_generate_code_format():
    code = generate_code(port=9471)
    parts = code.split("-")
    assert len(parts) == 4
    assert parts[0] == "9471"
    assert parts[1] in WORDS
    assert parts[2] in WORDS
    assert parts[3] in WORDS


def test_generate_code_random_port():
    code = generate_code(port=0)
    parts = code.split("-")
    port = int(parts[0])
    assert 1024 <= port <= 65535


def test_parse_code_with_host():
    port, words, hostname = parse_code("9471-alpha-bravo-charlie@myhost")
    assert port == 9471
    assert words == "9471-alpha-bravo-charlie"
    assert hostname == "myhost"


def test_parse_code_without_host():
    port, words, hostname = parse_code("9471-alpha-bravo-charlie")
    assert port == 9471
    assert words == "9471-alpha-bravo-charlie"
    assert hostname is None


def test_parse_code_invalid_format():
    import pytest
    with pytest.raises(ValueError):
        parse_code("invalid")
    with pytest.raises(ValueError):
        parse_code("9471-alpha")
    with pytest.raises(ValueError):
        parse_code("9471-alpha-bravo")


def test_generate_codes_are_unique():
    codes = {generate_code(port=9471) for _ in range(50)}
    assert len(codes) > 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv run pytest tests/test_wordlist.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'agent_wormhole.wordlist'`

- [ ] **Step 3: Create the 256-word list**

Create `src/agent_wormhole/words.txt` with 256 distinct, easy-to-spell English words. Use a script to generate it:

```python
# Generate wordlist - run once, save output
# Words should be: lowercase, 3-10 chars, easy to spell, distinct
words = [
    "acorn", "amber", "anvil", "apple", "arrow", "aspen", "atlas", "badge",
    "baker", "basil", "beach", "bell", "birch", "blade", "blaze", "bloom",
    "board", "bonus", "brave", "brick", "bridge", "brook", "brush", "cabin",
    "camel", "candy", "cape", "cargo", "cedar", "chalk", "chase", "chess",
    "chief", "cider", "cliff", "clock", "cloud", "coach", "coast", "cobra",
    "comet", "coral", "crane", "creek", "crest", "cross", "crown", "crush",
    "curve", "dance", "dawn", "delta", "denim", "derby", "desk", "digit",
    "diver", "dodge", "dove", "draft", "dream", "drift", "drum", "dusk",
    "eagle", "ember", "epoch", "equal", "event", "extra", "fable", "falcon",
    "feast", "fence", "field", "flame", "flash", "fleet", "flint", "float",
    "flood", "flora", "focus", "forge", "forum", "frost", "fruit", "gamma",
    "gavel", "gaze", "ghost", "glade", "glass", "gleam", "globe", "grace",
    "grain", "grape", "grasp", "grove", "guard", "guide", "haven", "hawk",
    "hazel", "heart", "hedge", "heron", "honey", "house", "ivory", "jade",
    "jewel", "joint", "judge", "kayak", "kite", "knack", "knoll", "lace",
    "lance", "latch", "lemon", "lever", "light", "lilac", "linen", "lodge",
    "lotus", "lunar", "maple", "march", "marsh", "mason", "match", "medal",
    "merge", "mesa", "metal", "minor", "mirth", "mixer", "moat", "model",
    "molar", "moss", "mural", "nerve", "night", "noble", "north", "novel",
    "oasis", "ocean", "olive", "onset", "opera", "orbit", "otter", "oxide",
    "paint", "panel", "patch", "pearl", "pedal", "penny", "phase", "pilot",
    "pixel", "plank", "plaza", "plume", "point", "polar", "pond", "poppy",
    "pouch", "prism", "prose", "pulse", "quake", "quest", "quiet", "quilt",
    "radar", "rapid", "raven", "realm", "ridge", "rivet", "robin", "rocky",
    "rover", "royal", "sable", "sage", "scale", "scout", "shade", "shark",
    "shell", "shine", "sigma", "silk", "slate", "slope", "smith", "solar",
    "spark", "spice", "spine", "spoke", "stamp", "steel", "stone", "storm",
    "stove", "surge", "sweet", "swift", "table", "talon", "thorn", "tiger",
    "timber", "toast", "torch", "tower", "trail", "trend", "trout", "tulip",
    "ultra", "umbra", "unity", "upper", "urban", "valve", "vault", "vigor",
    "viola", "vivid", "vocal", "watch", "water", "wheat", "wheel", "wing",
    "woven", "yacht", "yield", "zephyr", "zinc", "zone", "alder", "bliss",
]
assert len(words) == 256
assert len(set(words)) == 256
```

Write 256 words (one per line) to `src/agent_wormhole/words.txt`. Verify: `wc -l src/agent_wormhole/words.txt` should show 256.

- [ ] **Step 4: Implement wordlist.py**

Create `src/agent_wormhole/wordlist.py`:

```python
import secrets
import socket
from pathlib import Path


_WORDS_FILE = Path(__file__).parent / "words.txt"
WORDS = _WORDS_FILE.read_text().strip().splitlines()
assert len(WORDS) == 256, f"Expected 256 words, got {len(WORDS)}"


def generate_code(port: int = 0) -> str:
    """Generate a channel code like '9471-alpha-bravo-charlie'.
    
    If port is 0, picks a random available port.
    """
    if port == 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]
    w1 = secrets.choice(WORDS)
    w2 = secrets.choice(WORDS)
    w3 = secrets.choice(WORDS)
    return f"{port}-{w1}-{w2}-{w3}"


def parse_code(target: str) -> tuple[int, str, str | None]:
    """Parse '<port>-<w1>-<w2>-<w3>[@<hostname>]'.
    
    Returns (port, full_code_without_host, hostname_or_None).
    """
    hostname = None
    if "@" in target:
        code_part, hostname = target.rsplit("@", 1)
    else:
        code_part = target
    
    parts = code_part.split("-")
    if len(parts) != 4:
        raise ValueError(f"Invalid channel code: expected <port>-<word>-<word>-<word>, got '{code_part}'")
    
    try:
        port = int(parts[0])
    except ValueError:
        raise ValueError(f"Invalid port in channel code: '{parts[0]}'")
    
    return port, code_part, hostname
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv run pytest tests/test_wordlist.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agent_wormhole/wordlist.py src/agent_wormhole/words.txt tests/test_wordlist.py
git commit -m "feat: channel code generation and parsing with 256-word list"
```

---

### Task 3: Crypto Module (SPAKE2 + HKDF + AES-GCM)

**Files:**
- Create: `src/agent_wormhole/crypto.py`
- Create: `tests/test_crypto.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_crypto.py`:

```python
import pytest
from agent_wormhole.crypto import (
    Handshake,
    SessionKeys,
    encrypt,
    decrypt,
    MAX_MESSAGE_SIZE,
)


def test_handshake_matching_passwords():
    """Both sides derive the same session keys when passwords match."""
    host = Handshake.host(b"9471-alpha-bravo-charlie")
    peer = Handshake.peer(b"9471-alpha-bravo-charlie")

    msg_host = host.start()
    msg_peer = peer.start()

    keys_host = host.finish(msg_peer)
    keys_peer = peer.finish(msg_host)

    # Host's send key == peer's receive key and vice versa
    assert keys_host.send_key == keys_peer.recv_key
    assert keys_host.recv_key == keys_peer.send_key


def test_handshake_mismatched_passwords():
    """Mismatched passwords produce different keys (and decryption will fail)."""
    host = Handshake.host(b"9471-alpha-bravo-charlie")
    peer = Handshake.peer(b"9471-wrong-wrong-wrong")

    msg_host = host.start()
    msg_peer = peer.start()

    keys_host = host.finish(msg_peer)
    keys_peer = peer.finish(msg_host)

    assert keys_host.send_key != keys_peer.recv_key


def test_encrypt_decrypt_roundtrip():
    """Encrypt then decrypt returns original plaintext."""
    host = Handshake.host(b"test-password")
    peer = Handshake.peer(b"test-password")
    msg_h = host.start()
    msg_p = peer.start()
    keys_host = host.finish(msg_p)
    keys_peer = peer.finish(msg_h)

    plaintext = b"hello world"
    ciphertext = encrypt(keys_host, plaintext, sending=True)
    result = decrypt(keys_peer, ciphertext, receiving=True)
    assert result == plaintext


def test_encrypt_decrypt_reverse_direction():
    """Peer sends to host using the reverse key pair."""
    host = Handshake.host(b"test-password")
    peer = Handshake.peer(b"test-password")
    msg_h = host.start()
    msg_p = peer.start()
    keys_host = host.finish(msg_p)
    keys_peer = peer.finish(msg_h)

    plaintext = b"reply from peer"
    ciphertext = encrypt(keys_peer, plaintext, sending=True)
    result = decrypt(keys_host, ciphertext, receiving=True)
    assert result == plaintext


def test_nonce_increments():
    """Each encryption uses a new nonce; same plaintext produces different ciphertext."""
    host = Handshake.host(b"test-password")
    peer = Handshake.peer(b"test-password")
    msg_h = host.start()
    msg_p = peer.start()
    keys_host = host.finish(msg_p)
    keys_peer = peer.finish(msg_h)

    ct1 = encrypt(keys_host, b"same", sending=True)
    ct2 = encrypt(keys_host, b"same", sending=True)
    assert ct1 != ct2


def test_decrypt_wrong_order_fails():
    """Decrypting out of nonce order fails."""
    host = Handshake.host(b"test-password")
    peer = Handshake.peer(b"test-password")
    msg_h = host.start()
    msg_p = peer.start()
    keys_host = host.finish(msg_p)
    keys_peer = peer.finish(msg_h)

    ct1 = encrypt(keys_host, b"first", sending=True)
    ct2 = encrypt(keys_host, b"second", sending=True)

    # Skip ct1, try to decrypt ct2 first — should fail
    with pytest.raises(Exception):
        decrypt(keys_peer, ct2, receiving=True)


def test_max_message_size_enforced():
    """Messages over MAX_MESSAGE_SIZE are rejected."""
    host = Handshake.host(b"test-password")
    peer = Handshake.peer(b"test-password")
    msg_h = host.start()
    msg_p = peer.start()
    keys_host = host.finish(msg_p)
    _ = peer.finish(msg_h)

    too_large = b"x" * (MAX_MESSAGE_SIZE + 1)
    with pytest.raises(ValueError, match="exceeds maximum"):
        encrypt(keys_host, too_large, sending=True)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv run pytest tests/test_crypto.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'agent_wormhole.crypto'`

- [ ] **Step 3: Implement crypto.py**

Create `src/agent_wormhole/crypto.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from spake2 import SPAKE2_A, SPAKE2_B


MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10MB


@dataclass
class SessionKeys:
    """Direction-separated encryption keys with nonce counters."""

    send_key: bytes
    recv_key: bytes
    _send_nonce: int = field(default=0, repr=False)
    _recv_nonce: int = field(default=0, repr=False)

    def next_send_nonce(self) -> bytes:
        nonce = self._send_nonce.to_bytes(12, "big")
        self._send_nonce += 1
        return nonce

    def next_recv_nonce(self) -> bytes:
        nonce = self._recv_nonce.to_bytes(12, "big")
        self._recv_nonce += 1
        return nonce


class Handshake:
    """SPAKE2 handshake wrapper."""

    def __init__(self, spake_instance, is_host: bool):
        self._spake = spake_instance
        self._is_host = is_host

    @classmethod
    def host(cls, password: bytes) -> Handshake:
        return cls(SPAKE2_A(password), is_host=True)

    @classmethod
    def peer(cls, password: bytes) -> Handshake:
        return cls(SPAKE2_B(password), is_host=False)

    def start(self) -> bytes:
        return self._spake.start()

    def finish(self, other_msg: bytes) -> SessionKeys:
        shared_secret = self._spake.finish(other_msg)
        host_to_peer = _derive_key(shared_secret, b"host-to-peer")
        peer_to_host = _derive_key(shared_secret, b"peer-to-host")
        if self._is_host:
            return SessionKeys(send_key=host_to_peer, recv_key=peer_to_host)
        else:
            return SessionKeys(send_key=peer_to_host, recv_key=host_to_peer)


def _derive_key(secret: bytes, info: bytes) -> bytes:
    return HKDF(
        algorithm=SHA256(),
        length=32,
        salt=None,
        info=info,
    ).derive(secret)


def encrypt(keys: SessionKeys, plaintext: bytes, *, sending: bool) -> bytes:
    if len(plaintext) > MAX_MESSAGE_SIZE:
        raise ValueError(f"Message size {len(plaintext)} exceeds maximum {MAX_MESSAGE_SIZE}")
    if sending:
        nonce = keys.next_send_nonce()
        key = keys.send_key
    else:
        nonce = keys.next_recv_nonce()
        key = keys.recv_key
    return AESGCM(key).encrypt(nonce, plaintext, None)


def decrypt(keys: SessionKeys, ciphertext: bytes, *, receiving: bool) -> bytes:
    if receiving:
        nonce = keys.next_recv_nonce()
        key = keys.recv_key
    else:
        nonce = keys.next_send_nonce()
        key = keys.send_key
    return AESGCM(key).decrypt(nonce, ciphertext, None)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv run pytest tests/test_crypto.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_wormhole/crypto.py tests/test_crypto.py
git commit -m "feat: SPAKE2 handshake with direction-separated AES-256-GCM encryption"
```

---

### Task 4: Wire Protocol (Framing + JSON Envelopes)

**Files:**
- Create: `src/agent_wormhole/protocol.py`
- Create: `tests/test_protocol.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_protocol.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv run pytest tests/test_protocol.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'agent_wormhole.protocol'`

- [ ] **Step 3: Implement protocol.py**

Create `src/agent_wormhole/protocol.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv run pytest tests/test_protocol.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_wormhole/protocol.py tests/test_protocol.py
git commit -m "feat: wire protocol with length-prefixed framing and JSON envelopes"
```

---

### Task 5: Secure File System Module

**Files:**
- Create: `src/agent_wormhole/fs.py`
- Create: `tests/test_fs.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fs.py`:

```python
import os
import stat
import pytest
from pathlib import Path
from agent_wormhole.fs import (
    init_channel_dir,
    cleanup_channel,
    safe_save_file,
    safe_save_text,
    get_outbox_path,
    sanitize_filename,
)


@pytest.fixture
def tmp_base(tmp_path):
    """Use tmp_path as the base directory instead of /tmp/agent-wormhole."""
    return tmp_path


def test_init_channel_dir_creates_structure(tmp_base):
    channel_dir = init_channel_dir("1234-alpha-bravo-charlie", base=tmp_base)
    assert channel_dir.exists()
    assert (channel_dir / "files").exists()
    assert (channel_dir / "messages").exists()
    # Check permissions
    mode = stat.S_IMODE(channel_dir.stat().st_mode)
    assert mode == 0o700


def test_init_channel_dir_clears_stale_outbox(tmp_base):
    channel_dir = tmp_base / "1234-alpha-bravo-charlie"
    channel_dir.mkdir(parents=True)
    outbox = channel_dir / "outbox"
    outbox.write_text("stale data")
    init_channel_dir("1234-alpha-bravo-charlie", base=tmp_base)
    assert not outbox.exists()


def test_cleanup_channel_removes_all(tmp_base):
    channel_dir = init_channel_dir("1234-alpha-bravo-charlie", base=tmp_base)
    (channel_dir / "files" / "test.txt").write_text("data")
    (channel_dir / "messages" / "msg.txt").write_text("hello")
    cleanup_channel("1234-alpha-bravo-charlie", base=tmp_base)
    assert not channel_dir.exists()


def test_safe_save_file(tmp_base):
    channel_dir = init_channel_dir("1234-alpha-bravo-charlie", base=tmp_base)
    path = safe_save_file("1234-alpha-bravo-charlie", "test.txt", b"content", base=tmp_base)
    assert path.exists()
    assert path.read_bytes() == b"content"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_safe_save_file_rejects_traversal(tmp_base):
    init_channel_dir("1234-alpha-bravo-charlie", base=tmp_base)
    with pytest.raises(ValueError, match="Invalid filename"):
        safe_save_file("1234-alpha-bravo-charlie", "../etc/passwd", b"hack", base=tmp_base)
    with pytest.raises(ValueError, match="Invalid filename"):
        safe_save_file("1234-alpha-bravo-charlie", "/etc/passwd", b"hack", base=tmp_base)
    with pytest.raises(ValueError, match="Invalid filename"):
        safe_save_file("1234-alpha-bravo-charlie", "foo/bar.txt", b"hack", base=tmp_base)


def test_safe_save_text(tmp_base):
    channel_dir = init_channel_dir("1234-alpha-bravo-charlie", base=tmp_base)
    path = safe_save_text("1234-alpha-bravo-charlie", "long text here", base=tmp_base)
    assert path.exists()
    assert path.read_text() == "long text here"


def test_sanitize_filename():
    assert sanitize_filename("hello.txt") == "hello.txt"
    assert sanitize_filename("path/to/file.txt") is None
    assert sanitize_filename("../escape.txt") is None
    assert sanitize_filename("/absolute.txt") is None
    assert sanitize_filename("..") is None
    assert sanitize_filename(".") is None
    assert sanitize_filename("") is None


def test_get_outbox_path(tmp_base):
    init_channel_dir("1234-alpha-bravo-charlie", base=tmp_base)
    path = get_outbox_path("1234-alpha-bravo-charlie", base=tmp_base)
    assert path == tmp_base / "1234-alpha-bravo-charlie" / "outbox"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv run pytest tests/test_fs.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'agent_wormhole.fs'`

- [ ] **Step 3: Implement fs.py**

Create `src/agent_wormhole/fs.py`:

```python
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

DEFAULT_BASE = Path("/tmp/agent-wormhole")


def sanitize_filename(name: str) -> str | None:
    """Return the filename if safe, None if it contains path traversal."""
    if not name or name in (".", ".."):
        return None
    basename = os.path.basename(name)
    if basename != name or ".." in name:
        return None
    return basename


def init_channel_dir(code: str, *, base: Path = DEFAULT_BASE) -> Path:
    """Create the channel directory structure with secure permissions.
    
    Clears any stale outbox from a previous session.
    """
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    channel_dir = base / code
    channel_dir.mkdir(mode=0o700, exist_ok=True)
    (channel_dir / "files").mkdir(mode=0o700, exist_ok=True)
    (channel_dir / "messages").mkdir(mode=0o700, exist_ok=True)
    
    # Clear stale outbox
    outbox = channel_dir / "outbox"
    if outbox.exists():
        outbox.unlink()
    
    return channel_dir


def cleanup_channel(code: str, *, base: Path = DEFAULT_BASE) -> None:
    """Remove all files for a channel."""
    channel_dir = base / code
    if channel_dir.exists():
        shutil.rmtree(channel_dir)


def get_outbox_path(code: str, *, base: Path = DEFAULT_BASE) -> Path:
    """Get the outbox file path for a channel."""
    return base / code / "outbox"


def safe_save_file(code: str, name: str, data: bytes, *, base: Path = DEFAULT_BASE) -> Path:
    """Save a received file with sanitized name and secure permissions."""
    safe_name = sanitize_filename(name)
    if safe_name is None:
        raise ValueError(f"Invalid filename: {name!r}")
    
    path = base / code / "files" / safe_name
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


def safe_save_text(code: str, text: str, *, base: Path = DEFAULT_BASE) -> Path:
    """Save a large text message to a file with secure permissions."""
    timestamp = str(int(time.time() * 1000))
    path = base / code / "messages" / f"{timestamp}.txt"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, text.encode())
    finally:
        os.close(fd)
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv run pytest tests/test_fs.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_wormhole/fs.py tests/test_fs.py
git commit -m "feat: secure file system module with cleanup and path sanitization"
```

---

### Task 6: Channel Core (TCP + Outbox + Stdout)

**Files:**
- Create: `src/agent_wormhole/channel.py`
- Create: `tests/test_channel.py`

This is the core async loop that ties everything together: TCP connection, SPAKE2 handshake, outbox watching, and stdout printing.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_channel.py`:

```python
import asyncio
import json
import pytest
from unittest.mock import patch
from io import StringIO

from agent_wormhole.channel import run_host, run_peer, send_to_outbox


class TestEndToEnd:
    """Integration tests: host and peer communicate over loopback."""

    @pytest.mark.asyncio
    async def test_host_peer_connect_and_exchange_text(self):
        host_output = StringIO()
        peer_output = StringIO()

        async def host_task():
            code = await run_host(port=0, output=host_output, timeout=5.0)
            return code

        async def peer_task(code: str):
            await run_peer(f"{code}@127.0.0.1", output=peer_output, timeout=5.0)

        # Start host, get the code, then connect peer
        code_future: asyncio.Future[str] = asyncio.Future()
        
        async def host_with_code():
            code = await run_host(
                port=0,
                output=host_output,
                timeout=5.0,
                on_code=lambda c: code_future.set_result(c),
            )

        host = asyncio.create_task(host_with_code())
        code = await asyncio.wait_for(code_future, timeout=5.0)
        peer = asyncio.create_task(peer_task(code))

        # Wait for connection
        await asyncio.sleep(0.5)

        # Send text from host to peer via outbox
        send_to_outbox(code, "hello from host")
        await asyncio.sleep(0.3)

        # Check peer received the message
        peer_lines = peer_output.getvalue().strip().split("\n")
        text_msgs = [json.loads(l) for l in peer_lines if '"type":"text"' in l or '"type": "text"' in l]
        assert any(m["body"] == "hello from host" for m in text_msgs)

        # Cleanup
        host.cancel()
        peer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await host
        with pytest.raises(asyncio.CancelledError):
            await peer

    @pytest.mark.asyncio
    async def test_version_exchange(self):
        """Both sides exchange version messages on connect."""
        host_output = StringIO()
        peer_output = StringIO()
        code_future: asyncio.Future[str] = asyncio.Future()

        async def host_with_code():
            await run_host(
                port=0, output=host_output, timeout=5.0,
                on_code=lambda c: code_future.set_result(c),
            )

        host = asyncio.create_task(host_with_code())
        code = await asyncio.wait_for(code_future, timeout=5.0)
        peer = asyncio.create_task(
            run_peer(f"{code}@127.0.0.1", output=peer_output, timeout=5.0)
        )

        await asyncio.sleep(0.5)

        # Both sides should have printed a "connected" status
        for output in [host_output, peer_output]:
            lines = output.getvalue().strip().split("\n")
            status_msgs = [json.loads(l) for l in lines if "status" in l]
            events = [m.get("event") for m in status_msgs]
            assert "connected" in events

        host.cancel()
        peer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await host
        with pytest.raises(asyncio.CancelledError):
            await peer


class TestSendToOutbox:
    def test_send_text_creates_outbox_entry(self, tmp_path):
        from agent_wormhole.fs import init_channel_dir
        code = "1234-alpha-bravo-charlie"
        init_channel_dir(code, base=tmp_path)
        send_to_outbox(code, "hello", base=tmp_path)
        
        outbox = tmp_path / code / "outbox"
        lines = outbox.read_text().strip().split("\n")
        assert len(lines) == 1
        msg = json.loads(lines[0])
        assert msg == {"type": "text", "body": "hello"}

    def test_send_file_creates_outbox_entry(self, tmp_path):
        from agent_wormhole.fs import init_channel_dir
        code = "1234-alpha-bravo-charlie"
        init_channel_dir(code, base=tmp_path)
        
        test_file = tmp_path / "test.txt"
        test_file.write_text("file content")
        
        send_to_outbox(code, file_path=str(test_file), base=tmp_path)
        
        outbox = tmp_path / code / "outbox"
        lines = outbox.read_text().strip().split("\n")
        msg = json.loads(lines[0])
        assert msg["type"] == "file"
        assert msg["name"] == "test.txt"
        assert msg["path"] == str(test_file)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv run pytest tests/test_channel.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'agent_wormhole.channel'`

- [ ] **Step 3: Implement channel.py**

Create `src/agent_wormhole/channel.py`:

```python
from __future__ import annotations

import asyncio
import json
import sys
import time
from io import StringIO
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
    make_text_message,
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
    their_version_raw = decrypt(keys, their_version_enc, receiving=True)
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
                import base64
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
            _emit(output, {"type": "status", "event": "error", "detail": "decryption failed"})
            continue

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
    code = generate_code(port=port)
    port_actual, _, _ = parse_code(code)
    channel_dir = init_channel_dir(code, base=base)

    _emit(output, {"type": "status", "event": "channel", "code": code})
    _emit(output, {"type": "status", "event": "waiting"})

    if on_code:
        on_code(code)

    connected: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = asyncio.Future()

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        if not connected.done():
            connected.set_result((reader, writer))

    server = await asyncio.start_server(handle_client, "0.0.0.0", port_actual)

    try:
        if timeout:
            reader, writer = await asyncio.wait_for(connected, timeout=timeout)
        else:
            reader, writer = await connected
    except asyncio.TimeoutError:
        server.close()
        _emit(output, {"type": "status", "event": "timeout"})
        return

    # Stop accepting new connections (single-use)
    server.close()

    try:
        keys = await _do_handshake(reader, writer, code.encode(), is_host=True)
    except Exception as e:
        _emit(output, {"type": "status", "event": "handshake_failed", "detail": str(e)})
        writer.close()
        return

    _emit(output, {"type": "status", "event": "connected"})

    # Run outbox watcher and receiver concurrently
    await asyncio.gather(
        _outbox_watcher(code, keys, writer, base=base),
        _receiver(code, keys, reader, output, base=base),
    )


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
        return

    try:
        keys = await _do_handshake(reader, writer, code.encode(), is_host=False)
    except Exception as e:
        _emit(output, {"type": "status", "event": "handshake_failed", "detail": str(e)})
        writer.close()
        return

    _emit(output, {"type": "status", "event": "connected"})

    await asyncio.gather(
        _outbox_watcher(code, keys, writer, base=base),
        _receiver(code, keys, reader, output, base=base),
    )


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

    with open(outbox, "a") as f:
        f.write(entry + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv run pytest tests/test_channel.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent_wormhole/channel.py tests/test_channel.py
git commit -m "feat: core channel loop with TCP, outbox watcher, and encrypted messaging"
```

---

### Task 7: Wire Up CLI Commands

**Files:**
- Modify: `src/agent_wormhole/cli.py`

- [ ] **Step 1: Write a manual smoke test plan**

No automated test here — this wires the CLI to the already-tested internals. We'll verify manually.

- [ ] **Step 2: Implement the full CLI**

Replace `src/agent_wormhole/cli.py` with:

```python
import asyncio
import sys

import typer

from agent_wormhole.channel import run_host, run_peer, send_to_outbox
from agent_wormhole.fs import cleanup_channel, DEFAULT_BASE

app = typer.Typer(name="agent-wormhole", help="Secure ephemeral channels for AI agent communication")


@app.command()
def host(port: int = typer.Option(0, help="Port to listen on (0 = random)")):
    """Host a new channel and wait for a peer to connect."""
    asyncio.run(run_host(port=port))


@app.command()
def connect(target: str = typer.Argument(help="<code>@<hostname> to connect to")):
    """Connect to an existing channel."""
    asyncio.run(run_peer(target))


@app.command()
def send(
    code: str = typer.Argument(help="Channel code"),
    message: str = typer.Argument(default=None, help="Text message to send"),
    file: str = typer.Option(None, "--file", help="Path to file to send"),
):
    """Send a message or file through a channel."""
    if message is None and file is None:
        typer.echo("Error: provide a message or --file", err=True)
        raise typer.Exit(1)
    send_to_outbox(code, message=message, file_path=file)


@app.command()
def status():
    """Show active channels."""
    base = DEFAULT_BASE
    if not base.exists():
        typer.echo("No active channels")
        return
    channels = [d.name for d in base.iterdir() if d.is_dir()]
    if not channels:
        typer.echo("No active channels")
        return
    for ch in channels:
        outbox = base / ch / "outbox"
        has_outbox = outbox.exists()
        typer.echo(f"  {ch} {'(active)' if has_outbox else '(idle)'}")


@app.command()
def close(code: str = typer.Argument(help="Channel code to close")):
    """Close a channel and clean up all files."""
    cleanup_channel(code)
    typer.echo(f"Channel {code} closed and cleaned up")
```

- [ ] **Step 3: Smoke test — host in one terminal, connect in another**

Terminal 1:
```bash
cd ~/Documents/GitHub/agent-wormhole
uv run agent-wormhole host
# Note the channel code from stdout JSON
```

Terminal 2:
```bash
cd ~/Documents/GitHub/agent-wormhole
uv run agent-wormhole connect <code>@127.0.0.1
# Should see {"type":"status","event":"connected"}
```

Terminal 3:
```bash
cd ~/Documents/GitHub/agent-wormhole
uv run agent-wormhole send <code> "hello world"
# Terminal 2 should show: {"type":"text","body":"hello world"}
```

- [ ] **Step 4: Commit**

```bash
git add src/agent_wormhole/cli.py
git commit -m "feat: wire CLI commands to channel core"
```

---

### Task 8: Claude Code Skill

**Files:**
- Create: `skill/agent-wormhole/skill.md`

- [ ] **Step 1: Create skill directory**

```bash
mkdir -p ~/Documents/GitHub/agent-wormhole/skill/agent-wormhole
```

- [ ] **Step 2: Write the skill**

Create `skill/agent-wormhole/skill.md`:

```markdown
---
name: agent-wormhole
description: Open a secure ephemeral channel to communicate with another Claude Code instance. Use when you need to send or receive messages, credentials, or files to/from another AI agent session.
---

# Agent Wormhole

Secure, encrypted communication channel between two Claude Code instances.

## Prerequisites

`agent-wormhole` must be installed: `uv tool install agent-wormhole` or `pip install agent-wormhole`.

## Hosting a Channel (you are the initiator)

Start a channel and share the code with the other instance:

1. Start the channel using Monitor:
   ```
   Monitor(
     command="agent-wormhole host",
     description="Wormhole channel",
     persistent=True
   )
   ```
2. The first notification will contain the channel code:
   `{"type":"status","event":"channel","code":"<port>-<word>-<word>-<word>"}`
3. Tell the user the code so they can provide it to the other Claude instance.
4. Wait for `{"type":"status","event":"connected"}` before sending messages.

## Connecting to a Channel (you received a code)

1. Start listening using Monitor:
   ```
   Monitor(
     command="agent-wormhole connect <code>@<hostname>",
     description="Wormhole channel",
     persistent=True
   )
   ```
2. Wait for `{"type":"status","event":"connected"}`.

## Sending Messages

Use Bash to send:

```bash
agent-wormhole send <code> "your message here"
```

To send a file:
```bash
agent-wormhole send <code> --file /path/to/file
```

## Receiving Messages

Messages arrive as Monitor notifications (JSON lines):

- **Text**: `{"type":"text","body":"the message"}`
- **Large text** (>1KB): `{"type":"text","saved_to":"/tmp/agent-wormhole/messages/123.txt","size":4096}` — use Read tool to get the content
- **File**: `{"type":"file","name":"config.json","saved_to":"/tmp/agent-wormhole/files/config.json","size":2048}` — use Read tool to get the file

## Important: Save Before Closing

Channel cleanup deletes ALL temporary files. Before closing a channel, save anything important to its permanent destination:

- **Credentials/API keys** -> 1Password, .env files, or project config
- **Config files** -> Copy to the project directory
- **Important text** -> Save to a file in the project

## Closing

```bash
agent-wormhole close <code>
```

Or just cancel the Monitor — the channel cleans up on disconnect.

## Status Events

- `{"type":"status","event":"channel","code":"..."}` — channel created (host only)
- `{"type":"status","event":"waiting"}` — waiting for peer (host only)
- `{"type":"status","event":"connected"}` — peer connected, ready to communicate
- `{"type":"status","event":"disconnected"}` — peer disconnected
- `{"type":"status","event":"handshake_failed","detail":"..."}` — authentication failed (wrong code)
- `{"type":"status","event":"error","detail":"..."}` — other error
```

- [ ] **Step 3: Commit**

```bash
git add skill/
git commit -m "feat: Claude Code skill for agent-wormhole usage"
```

---

### Task 9: README and License

**Files:**
- Create: `README.md`
- Create: `LICENSE`

- [ ] **Step 1: Write README.md**

Create `README.md`:

```markdown
# agent-wormhole

Secure, ephemeral communication channels for AI agent instances. Think [Magic Wormhole](https://github.com/magic-wormhole/magic-wormhole), but designed for Claude Code and other AI coding agents to talk to each other.

## Install

```bash
pip install agent-wormhole
# or
uv tool install agent-wormhole
```

## Quick Start

**Machine A** (host):
```bash
agent-wormhole host
# Output: {"type":"status","event":"channel","code":"9471-crossover-clockwork-marble"}
```

**Machine B** (connect):
```bash
agent-wormhole connect 9471-crossover-clockwork-marble@machine-a-hostname
# Output: {"type":"status","event":"connected"}
```

**Send messages** (either side):
```bash
agent-wormhole send 9471-crossover-clockwork-marble "hello from A"
agent-wormhole send 9471-crossover-clockwork-marble --file ./config.json
```

## How It Works

1. Host generates a human-readable channel code and listens on a TCP port
2. Peer connects using the code (which includes the port number)
3. Both sides perform a SPAKE2 key exchange — proving they both know the code without transmitting it
4. Two direction-separated AES-256-GCM keys are derived via HKDF
5. Messages flow bidirectionally over the encrypted channel

## Claude Code Integration

agent-wormhole is designed to work with Claude Code's Monitor tool for real-time bidirectional messaging between AI agent sessions. See `skill/agent-wormhole/skill.md` for the Claude Code skill.

## Security

- **E2E encrypted**: AES-256-GCM with direction-separated keys
- **SPAKE2 key exchange**: Password-authenticated, no code on wire
- **Forward secrecy**: Unique session key per connection
- **Single-use channels**: Host accepts one connection, then stops listening
- **Ephemeral**: All temp files cleaned up on channel close

## License

MIT
```

- [ ] **Step 2: Write LICENSE**

Create `LICENSE` with the MIT license text, copyright 2026.

- [ ] **Step 3: Commit**

```bash
git add README.md LICENSE
git commit -m "docs: README and MIT license"
```

---

### Task 10: Full Integration Test (Cross-Process)

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write the integration test**

Create `tests/test_integration.py`:

```python
"""Full integration test: host and peer in the same process over loopback."""
import asyncio
import json
import pytest
from io import StringIO
from pathlib import Path

from agent_wormhole.channel import run_host, run_peer, send_to_outbox
from agent_wormhole.fs import init_channel_dir, get_outbox_path


@pytest.fixture
def tmp_base(tmp_path):
    return tmp_path


@pytest.mark.asyncio
async def test_full_text_roundtrip(tmp_base):
    """Host sends text to peer, peer sends text to host."""
    host_out = StringIO()
    peer_out = StringIO()
    code_future: asyncio.Future[str] = asyncio.Future()

    async def run_h():
        await run_host(port=0, output=host_out, timeout=5.0,
                       on_code=lambda c: code_future.set_result(c), base=tmp_base)

    host_task = asyncio.create_task(run_h())
    code = await asyncio.wait_for(code_future, timeout=5.0)

    peer_task = asyncio.create_task(
        run_peer(f"{code}@127.0.0.1", output=peer_out, timeout=5.0, base=tmp_base)
    )

    await asyncio.sleep(0.5)

    # Host sends to peer
    send_to_outbox(code, "hello peer", base=tmp_base)
    await asyncio.sleep(0.3)

    peer_lines = [json.loads(l) for l in peer_out.getvalue().strip().split("\n") if l.strip()]
    assert any(m.get("body") == "hello peer" for m in peer_lines)

    # Peer sends to host
    send_to_outbox(code, "hello host", base=tmp_base)
    await asyncio.sleep(0.3)

    host_lines = [json.loads(l) for l in host_out.getvalue().strip().split("\n") if l.strip()]
    assert any(m.get("body") == "hello host" for m in host_lines)

    host_task.cancel()
    peer_task.cancel()
    await asyncio.gather(host_task, peer_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_file_transfer(tmp_base):
    """Host sends a file to peer."""
    host_out = StringIO()
    peer_out = StringIO()
    code_future: asyncio.Future[str] = asyncio.Future()

    async def run_h():
        await run_host(port=0, output=host_out, timeout=5.0,
                       on_code=lambda c: code_future.set_result(c), base=tmp_base)

    host_task = asyncio.create_task(run_h())
    code = await asyncio.wait_for(code_future, timeout=5.0)
    peer_task = asyncio.create_task(
        run_peer(f"{code}@127.0.0.1", output=peer_out, timeout=5.0, base=tmp_base)
    )

    await asyncio.sleep(0.5)

    # Create a test file and send it
    test_file = tmp_base / "send_me.txt"
    test_file.write_text("secret credentials here")
    send_to_outbox(code, file_path=str(test_file), base=tmp_base)
    await asyncio.sleep(0.5)

    # Check peer received the file
    peer_lines = [json.loads(l) for l in peer_out.getvalue().strip().split("\n") if l.strip()]
    file_msgs = [m for m in peer_lines if m.get("type") == "file"]
    assert len(file_msgs) == 1
    assert file_msgs[0]["name"] == "send_me.txt"

    saved_path = Path(file_msgs[0]["saved_to"])
    assert saved_path.exists()
    assert saved_path.read_text() == "secret credentials here"

    host_task.cancel()
    peer_task.cancel()
    await asyncio.gather(host_task, peer_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_large_text_saved_to_file(tmp_base):
    """Text over 1KB is saved to file instead of printed inline."""
    host_out = StringIO()
    peer_out = StringIO()
    code_future: asyncio.Future[str] = asyncio.Future()

    async def run_h():
        await run_host(port=0, output=host_out, timeout=5.0,
                       on_code=lambda c: code_future.set_result(c), base=tmp_base)

    host_task = asyncio.create_task(run_h())
    code = await asyncio.wait_for(code_future, timeout=5.0)
    peer_task = asyncio.create_task(
        run_peer(f"{code}@127.0.0.1", output=peer_out, timeout=5.0, base=tmp_base)
    )

    await asyncio.sleep(0.5)

    large_text = "x" * 2000
    send_to_outbox(code, large_text, base=tmp_base)
    await asyncio.sleep(0.5)

    peer_lines = [json.loads(l) for l in peer_out.getvalue().strip().split("\n") if l.strip()]
    text_msgs = [m for m in peer_lines if m.get("type") == "text"]
    saved_msgs = [m for m in text_msgs if "saved_to" in m]
    assert len(saved_msgs) == 1
    assert saved_msgs[0]["size"] == 2000

    saved_path = Path(saved_msgs[0]["saved_to"])
    assert saved_path.read_text() == large_text

    host_task.cancel()
    peer_task.cancel()
    await asyncio.gather(host_task, peer_task, return_exceptions=True)
```

- [ ] **Step 2: Run all tests**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: full integration tests for text, file, and large message handling"
```

---

### Task 11: Run Full Test Suite and Final Cleanup

- [ ] **Step 1: Run the complete test suite**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv run pytest tests/ -v --tb=short
```

Expected: all tests PASS.

- [ ] **Step 2: Verify CLI works end-to-end**

```bash
uv run agent-wormhole --help
uv run agent-wormhole host --help
uv run agent-wormhole connect --help
uv run agent-wormhole send --help
uv run agent-wormhole status
```

- [ ] **Step 3: Verify the package installs cleanly**

```bash
cd ~/Documents/GitHub/agent-wormhole
uv build
uv pip install dist/agent_wormhole-0.1.0-py3-none-any.whl --system --force-reinstall
agent-wormhole --help
```

- [ ] **Step 4: Final commit if any cleanup was needed**

```bash
git log --oneline
# Verify commit history looks clean
```
