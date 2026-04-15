# Relay Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public WebSocket relay server backed by Redis Streams so two agent-wormhole clients can connect without direct network access, and make relay mode the default.

**Architecture:** FastAPI relay server forwards opaque encrypted frames between paired WebSocket clients via Redis Streams. Client-side Transport abstraction lets channel.py work over either direct TCP or relay WebSocket. SPAKE2 + AES-256-GCM encryption is unchanged -- the relay never sees plaintext.

**Tech Stack:** Python 3.11+, FastAPI, `websockets`, `redis.asyncio`, Hatch build system, Railway deployment

**Spec:** `docs/superpowers/specs/2026-04-15-relay-server-design.md`

---

## File Map

### New files

| File | Responsibility |
|------|---------------|
| `src/agent_wormhole/config.py` | `DEFAULT_RELAY_URL`, env var override |
| `src/agent_wormhole/transport.py` | `Transport` ABC, `DirectTransport`, `RelayTransport` |
| `src/agent_wormhole/relay/__init__.py` | Package marker |
| `src/agent_wormhole/relay/server.py` | FastAPI app, `/health`, `/ws` endpoint |
| `src/agent_wormhole/relay/redis_manager.py` | Redis Streams + metadata + cursor operations |
| `src/agent_wormhole/relay/rate_limiter.py` | Message, byte, join-attempt rate limiting |
| `tests/test_config.py` | Config and code format tests |
| `tests/test_transport.py` | Transport abstraction unit tests |
| `tests/test_relay_redis.py` | Redis manager unit tests (uses fakeredis) |
| `tests/test_relay_rate_limiter.py` | Rate limiter unit tests (uses fakeredis) |
| `tests/test_relay_server.py` | Relay server integration tests (FastAPI TestClient + fakeredis) |
| `tests/test_relay_e2e.py` | Full E2E: two clients through relay with real encryption |
| `railway.toml` | Railway deployment config |

### Modified files

| File | Changes |
|------|---------|
| `pyproject.toml` | Add `fastapi`, `uvicorn`, `websockets`, `redis`, `fakeredis` deps |
| `src/agent_wormhole/wordlist.py` | Add `generate_relay_code()` (3 words, no port), update `parse_code()` to handle both formats |
| `src/agent_wormhole/channel.py` | Refactor to use `Transport` interface, add `run_host_relay()` and `run_peer_relay()` |
| `src/agent_wormhole/cli.py` | Add `--direct`, `--relay` flags to `host` and `connect` commands |
| `skill/SKILL.md` | Update to relay-first flow, document TTL/rate limits |
| `tests/test_integration.py` | Update imports if channel.py signatures change |

---

### Task 1: Add dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add relay and test dependencies**

In `pyproject.toml`, add relay server dependencies to `[project.dependencies]` and test dependencies to `[dependency-groups]`:

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
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "websockets>=14.0",
    "redis>=5.0",
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
    "fakeredis>=2.26",
    "httpx>=0.28",
]
```

- [ ] **Step 2: Install dependencies**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv sync`
Expected: all dependencies install successfully

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add relay server dependencies (fastapi, redis, websockets)"
```

---

### Task 2: Config module and relay code generation

**Files:**
- Create: `src/agent_wormhole/config.py`
- Modify: `src/agent_wormhole/wordlist.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write tests for config and code generation**

Create `tests/test_config.py`:

```python
"""Tests for config module and relay/direct code format handling."""
import os
import pytest

from agent_wormhole.config import DEFAULT_RELAY_URL, get_relay_url
from agent_wormhole.wordlist import (
    generate_code,
    generate_relay_code,
    parse_code,
    WORDS,
)


def test_default_relay_url():
    assert DEFAULT_RELAY_URL.startswith("wss://")


def test_get_relay_url_default():
    url = get_relay_url()
    assert url == DEFAULT_RELAY_URL


def test_get_relay_url_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_WORMHOLE_RELAY_URL", "wss://custom.example.com")
    assert get_relay_url() == "wss://custom.example.com"


def test_generate_relay_code_format():
    code = generate_relay_code()
    parts = code.split("-")
    assert len(parts) == 3
    assert all(p in WORDS for p in parts)


def test_generate_relay_code_no_port_prefix():
    code = generate_relay_code()
    # First part should NOT be numeric
    assert not code.split("-")[0].isdigit()


def test_generate_direct_code_has_port():
    code = generate_code(port=9999)
    parts = code.split("-")
    assert len(parts) == 4
    assert parts[0] == "9999"


def test_parse_code_direct_format():
    port, code, hostname = parse_code("9471-alpha-bravo-charlie@myhost")
    assert port == 9471
    assert code == "9471-alpha-bravo-charlie"
    assert hostname == "myhost"


def test_parse_code_relay_format():
    port, code, hostname = parse_code("alpha-bravo-charlie")
    assert port is None
    assert code == "alpha-bravo-charlie"
    assert hostname is None


def test_parse_code_relay_format_no_hostname():
    """Relay codes should not require a hostname."""
    port, code, hostname = parse_code("alpha-bravo-charlie")
    assert port is None
    assert hostname is None


def test_parse_code_detects_direct_vs_relay():
    """First segment numeric = direct mode, otherwise relay."""
    _, direct_code, _ = parse_code("1234-a-b-c@host")
    assert direct_code == "1234-a-b-c"

    _, relay_code, _ = parse_code("a-b-c")
    assert relay_code == "a-b-c"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_config.py -v`
Expected: FAIL -- `config` module doesn't exist, `generate_relay_code` doesn't exist

- [ ] **Step 3: Create config module**

Create `src/agent_wormhole/config.py`:

```python
"""Configuration for agent-wormhole."""
import os

DEFAULT_RELAY_URL = "wss://agent-wormhole-relay.up.railway.app"


def get_relay_url(override: str | None = None) -> str:
    """Return the relay URL, checking override -> env var -> default."""
    if override:
        return override
    return os.environ.get("AGENT_WORMHOLE_RELAY_URL", DEFAULT_RELAY_URL)
```

- [ ] **Step 4: Update wordlist.py to support relay codes**

Modify `src/agent_wormhole/wordlist.py` to add `generate_relay_code()` and update `parse_code()` to handle both 3-word (relay) and 4-part (direct) formats:

```python
import secrets
from pathlib import Path


_WORDS_FILE = Path(__file__).parent / "words.txt"
WORDS = _WORDS_FILE.read_text().strip().splitlines()
assert len(WORDS) == 256, f"Expected 256 words, got {len(WORDS)}"


def generate_code(port: int) -> str:
    """Generate a direct-mode channel code like '9471-alpha-bravo-charlie'.

    Port must be provided (the actual bound port from the server).
    """
    w1 = secrets.choice(WORDS)
    w2 = secrets.choice(WORDS)
    w3 = secrets.choice(WORDS)
    return f"{port}-{w1}-{w2}-{w3}"


def generate_relay_code() -> str:
    """Generate a relay-mode channel code like 'alpha-bravo-charlie'.

    No port prefix -- the relay handles routing.
    """
    w1 = secrets.choice(WORDS)
    w2 = secrets.choice(WORDS)
    w3 = secrets.choice(WORDS)
    return f"{w1}-{w2}-{w3}"


def parse_code(target: str) -> tuple[int | None, str, str | None]:
    """Parse a channel code in either format.

    Direct mode: '<port>-<w1>-<w2>-<w3>[@<hostname>]'
    Relay mode:  '<w1>-<w2>-<w3>'

    Returns (port_or_None, code_without_host, hostname_or_None).
    If first segment is numeric, it's direct mode. Otherwise relay mode.
    """
    hostname = None
    if "@" in target:
        code_part, hostname = target.rsplit("@", 1)
    else:
        code_part = target

    parts = code_part.split("-")

    # Direct mode: first part is numeric port
    if parts[0].isdigit():
        if len(parts) != 4:
            raise ValueError(
                f"Invalid direct-mode code: expected <port>-<word>-<word>-<word>, got '{code_part}'"
            )
        port = int(parts[0])
        return port, code_part, hostname

    # Relay mode: 3 words, no port
    if len(parts) != 3:
        raise ValueError(
            f"Invalid relay-mode code: expected <word>-<word>-<word>, got '{code_part}'"
        )
    return None, code_part, hostname
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_config.py -v`
Expected: all PASS

- [ ] **Step 6: Run existing tests to check for regressions**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest -v`
Expected: all PASS (existing tests use `parse_code` with 4-part format which still works)

- [ ] **Step 7: Commit**

```bash
git add src/agent_wormhole/config.py src/agent_wormhole/wordlist.py tests/test_config.py
git commit -m "feat: add config module and relay code generation"
```

---

### Task 3: Transport abstraction

**Files:**
- Create: `src/agent_wormhole/transport.py`
- Create: `tests/test_transport.py`

- [ ] **Step 1: Write tests for Transport ABC and DirectTransport**

Create `tests/test_transport.py`:

```python
"""Tests for transport abstraction."""
import asyncio
import pytest
from agent_wormhole.transport import DirectTransport, Transport


@pytest.mark.asyncio
async def test_direct_transport_host_peer_roundtrip():
    """DirectTransport host and peer can exchange frames."""
    host = DirectTransport.as_host(port=0)
    await host.connect()  # Starts listening, returns immediately

    actual_port = host.port
    assert actual_port > 0

    peer = DirectTransport.as_peer(hostname="127.0.0.1", port=actual_port)
    # Peer connects, then host accepts
    await peer.connect()
    await host.accept(timeout=5.0)

    # host -> peer
    await host.send_frame(b"hello from host")
    data = await peer.recv_frame()
    assert data == b"hello from host"

    # peer -> host
    await peer.send_frame(b"hello from peer")
    data = await host.recv_frame()
    assert data == b"hello from peer"

    await host.close()
    await peer.close()


@pytest.mark.asyncio
async def test_direct_transport_is_transport_subclass():
    assert issubclass(DirectTransport, Transport)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_transport.py -v`
Expected: FAIL -- `transport` module doesn't exist

- [ ] **Step 3: Implement Transport ABC and DirectTransport**

Create `src/agent_wormhole/transport.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_transport.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wormhole/transport.py tests/test_transport.py
git commit -m "feat: add Transport ABC and DirectTransport"
```

---

### Task 4: Redis manager

**Files:**
- Create: `src/agent_wormhole/relay/__init__.py`
- Create: `src/agent_wormhole/relay/redis_manager.py`
- Create: `tests/test_relay_redis.py`

- [ ] **Step 1: Write tests for RedisManager**

Create `tests/test_relay_redis.py`:

```python
"""Tests for Redis channel management."""
import pytest
import fakeredis.aioredis

from agent_wormhole.relay.redis_manager import RedisManager


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
async def mgr(redis):
    return RedisManager(redis)


@pytest.mark.asyncio
async def test_join_host_creates_channel(mgr):
    ok = await mgr.join("test-code", "host")
    assert ok is True
    meta = await mgr.get_meta("test-code")
    assert meta["host_connected"] == "1"
    assert meta["peer_connected"] == "0"


@pytest.mark.asyncio
async def test_join_peer_after_host(mgr):
    await mgr.join("test-code", "host")
    ok = await mgr.join("test-code", "peer")
    assert ok is True
    meta = await mgr.get_meta("test-code")
    assert meta["host_connected"] == "1"
    assert meta["peer_connected"] == "1"


@pytest.mark.asyncio
async def test_join_duplicate_role_rejected(mgr):
    await mgr.join("test-code", "host")
    ok = await mgr.join("test-code", "host")
    assert ok is False


@pytest.mark.asyncio
async def test_send_and_receive_frame(mgr):
    await mgr.join("test-code", "host")
    await mgr.join("test-code", "peer")

    await mgr.send_frame("test-code", "host", b"hello from host")
    frames = await mgr.read_frames("test-code", "peer")
    assert len(frames) == 1
    assert frames[0] == b"hello from host"


@pytest.mark.asyncio
async def test_cursor_persists_across_reads(mgr):
    await mgr.join("test-code", "host")
    await mgr.join("test-code", "peer")

    await mgr.send_frame("test-code", "host", b"msg1")
    await mgr.send_frame("test-code", "host", b"msg2")

    # First read gets both
    frames = await mgr.read_frames("test-code", "peer")
    assert len(frames) == 2

    # Second read gets nothing (cursor advanced)
    frames = await mgr.read_frames("test-code", "peer")
    assert len(frames) == 0

    # New message after cursor
    await mgr.send_frame("test-code", "host", b"msg3")
    frames = await mgr.read_frames("test-code", "peer")
    assert len(frames) == 1
    assert frames[0] == b"msg3"


@pytest.mark.asyncio
async def test_disconnect_updates_meta(mgr):
    await mgr.join("test-code", "host")
    await mgr.join("test-code", "peer")
    await mgr.disconnect("test-code", "host")
    meta = await mgr.get_meta("test-code")
    assert meta["host_connected"] == "0"
    assert meta["peer_connected"] == "1"


@pytest.mark.asyncio
async def test_is_paired(mgr):
    await mgr.join("test-code", "host")
    assert await mgr.is_paired("test-code") is False
    await mgr.join("test-code", "peer")
    assert await mgr.is_paired("test-code") is True


@pytest.mark.asyncio
async def test_cleanup_removes_all_keys(mgr, redis):
    await mgr.join("test-code", "host")
    await mgr.join("test-code", "peer")
    await mgr.send_frame("test-code", "host", b"data")
    await mgr.cleanup("test-code")

    keys = await redis.keys("wormhole:test-code:*")
    assert len(keys) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_relay_redis.py -v`
Expected: FAIL -- module doesn't exist

- [ ] **Step 3: Create relay package and RedisManager**

Create `src/agent_wormhole/relay/__init__.py`:

```python
```

Create `src/agent_wormhole/relay/redis_manager.py`:

```python
"""Redis Streams manager for relay channel state."""
from __future__ import annotations

import time

from redis.asyncio import Redis

CHANNEL_TTL = 3600  # 1 hour
STREAM_MAXLEN = 1000

# Lua script for atomic join: check-and-set role in meta hash
_JOIN_SCRIPT = """
local meta_key = KEYS[1]
local role_field = ARGV[1] .. "_connected"
local current = redis.call("HGET", meta_key, role_field)
if current == "1" then
    return 0
end
redis.call("HSET", meta_key, role_field, "1")
redis.call("HSET", meta_key, "last_activity", ARGV[2])
if redis.call("HEXISTS", meta_key, "created_at") == 0 then
    redis.call("HSET", meta_key, "created_at", ARGV[2])
end
redis.call("EXPIRE", meta_key, ARGV[3])
return 1
"""


def _meta_key(code: str) -> str:
    return f"wormhole:{code}:meta"


def _stream_key(code: str, from_role: str) -> str:
    other = "peer" if from_role == "host" else "host"
    return f"wormhole:{code}:{from_role}-to-{other}"


def _cursor_key(code: str, role: str) -> str:
    return f"wormhole:{code}:{role}:cursor"


class RedisManager:
    """Manages channel state in Redis."""

    def __init__(self, redis: Redis):
        self._redis = redis
        self._join_script = self._redis.register_script(_JOIN_SCRIPT)

    async def join(self, code: str, role: str) -> bool:
        """Atomically register a role for a channel. Returns False if role already taken."""
        now = str(int(time.time()))
        result = await self._join_script(
            keys=[_meta_key(code)],
            args=[role, now, str(CHANNEL_TTL)],
        )
        if result == 1:
            # Initialize cursor to read from beginning
            cursor_key = _cursor_key(code, role)
            await self._redis.set(cursor_key, "0-0", ex=CHANNEL_TTL)
        return result == 1

    async def disconnect(self, code: str, role: str) -> None:
        """Mark a role as disconnected."""
        key = _meta_key(code)
        await self._redis.hset(key, f"{role}_connected", "0")

    async def get_meta(self, code: str) -> dict[str, str]:
        """Get channel metadata."""
        data = await self._redis.hgetall(_meta_key(code))
        return {k.decode(): v.decode() for k, v in data.items()}

    async def is_paired(self, code: str) -> bool:
        """Check if both host and peer are connected."""
        meta = await self.get_meta(code)
        return meta.get("host_connected") == "1" and meta.get("peer_connected") == "1"

    async def send_frame(self, code: str, from_role: str, data: bytes) -> None:
        """Add a frame to the outbound stream for from_role."""
        stream = _stream_key(code, from_role)
        await self._redis.xadd(stream, {"frame": data}, maxlen=STREAM_MAXLEN)
        # Reset TTL on activity
        await self._redis.expire(_meta_key(code), CHANNEL_TTL)

    async def read_frames(
        self, code: str, for_role: str, block_ms: int = 0
    ) -> list[bytes]:
        """Read new frames for a role from its inbound stream.

        Updates the persisted cursor after reading.
        """
        # Inbound stream for 'host' is 'peer-to-host', i.e., the other role's outbound
        other = "peer" if for_role == "host" else "host"
        stream = _stream_key(code, other)
        cursor_key = _cursor_key(code, for_role)

        cursor = await self._redis.get(cursor_key)
        if cursor is None:
            cursor = b"0-0"
        cursor = cursor.decode() if isinstance(cursor, bytes) else cursor

        if block_ms > 0:
            result = await self._redis.xread(
                {stream: cursor}, count=100, block=block_ms
            )
        else:
            result = await self._redis.xread({stream: cursor}, count=100)

        frames = []
        last_id = cursor
        for _stream_name, messages in result:
            for msg_id, fields in messages:
                msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                frames.append(fields[b"frame"])
                last_id = msg_id_str

        if last_id != cursor:
            await self._redis.set(cursor_key, last_id, ex=CHANNEL_TTL)

        return frames

    async def touch(self, code: str) -> None:
        """Reset TTL on channel (keepalive)."""
        await self._redis.expire(_meta_key(code), CHANNEL_TTL)
        for role in ("host", "peer"):
            await self._redis.expire(_cursor_key(code, role), CHANNEL_TTL)

    async def cleanup(self, code: str) -> None:
        """Delete all Redis keys for a channel."""
        keys = await self._redis.keys(f"wormhole:{code}:*")
        if keys:
            await self._redis.delete(*keys)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_relay_redis.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wormhole/relay/ tests/test_relay_redis.py
git commit -m "feat: add Redis manager for relay channel state"
```

---

### Task 5: Rate limiter

**Files:**
- Create: `src/agent_wormhole/relay/rate_limiter.py`
- Create: `tests/test_relay_rate_limiter.py`

- [ ] **Step 1: Write tests for RateLimiter**

Create `tests/test_relay_rate_limiter.py`:

```python
"""Tests for relay rate limiting."""
import pytest
import fakeredis.aioredis

from agent_wormhole.relay.rate_limiter import RateLimiter


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def limiter(redis):
    return RateLimiter(redis)


@pytest.mark.asyncio
async def test_message_rate_under_limit(limiter):
    for _ in range(60):
        allowed = await limiter.check_message_rate("test-code")
        assert allowed is True


@pytest.mark.asyncio
async def test_message_rate_over_limit(limiter):
    for _ in range(60):
        await limiter.check_message_rate("test-code")
    allowed = await limiter.check_message_rate("test-code")
    assert allowed is False


@pytest.mark.asyncio
async def test_byte_rate_under_limit(limiter):
    allowed = await limiter.check_byte_rate("test-code", 1024)
    assert allowed is True


@pytest.mark.asyncio
async def test_byte_rate_over_limit(limiter):
    # 50MB limit
    allowed = await limiter.check_byte_rate("test-code", 50 * 1024 * 1024)
    assert allowed is True
    allowed = await limiter.check_byte_rate("test-code", 1)
    assert allowed is False


@pytest.mark.asyncio
async def test_join_attempts_under_limit(limiter):
    for _ in range(5):
        allowed = await limiter.check_join_attempts("test-code")
        assert allowed is True


@pytest.mark.asyncio
async def test_join_attempts_over_limit(limiter):
    for _ in range(5):
        await limiter.check_join_attempts("test-code")
    allowed = await limiter.check_join_attempts("test-code")
    assert allowed is False


@pytest.mark.asyncio
async def test_channel_count_under_limit(limiter):
    for i in range(100):
        await limiter.increment_channel_count("1.2.3.4")
    allowed = await limiter.check_channel_count("1.2.3.4")
    assert allowed is False


@pytest.mark.asyncio
async def test_channel_count_first_channel(limiter):
    allowed = await limiter.check_channel_count("1.2.3.4")
    assert allowed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_relay_rate_limiter.py -v`
Expected: FAIL

- [ ] **Step 3: Implement RateLimiter**

Create `src/agent_wormhole/relay/rate_limiter.py`:

```python
"""Rate limiting for relay server."""
from __future__ import annotations

from redis.asyncio import Redis

MSG_RATE_LIMIT = 60  # messages per minute
BYTE_RATE_LIMIT = 50 * 1024 * 1024  # 50 MB per minute
JOIN_ATTEMPT_LIMIT = 5  # per code per minute
CHANNEL_LIMIT_PER_IP = 100  # active channels per source IP
RATE_WINDOW = 60  # seconds


class RateLimiter:
    """Sliding window rate limiter backed by Redis."""

    def __init__(self, redis: Redis):
        self._redis = redis

    async def check_message_rate(self, code: str) -> bool:
        """Check and increment message rate. Returns True if allowed."""
        key = f"wormhole:{code}:rate"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, RATE_WINDOW)
        return count <= MSG_RATE_LIMIT

    async def check_byte_rate(self, code: str, size: int) -> bool:
        """Check and increment byte rate. Returns True if allowed."""
        key = f"wormhole:{code}:bytes"
        count = await self._redis.incrby(key, size)
        if count == size:
            await self._redis.expire(key, RATE_WINDOW)
        return count <= BYTE_RATE_LIMIT

    async def check_join_attempts(self, code: str) -> bool:
        """Check and increment join attempts per code. Returns True if allowed."""
        key = f"wormhole:{code}:join-attempts"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, RATE_WINDOW)
        return count <= JOIN_ATTEMPT_LIMIT

    async def check_channel_count(self, ip: str) -> bool:
        """Check if IP is under the active channel limit."""
        key = f"wormhole:ip:{ip}:channels"
        count = await self._redis.get(key)
        if count is None:
            return True
        return int(count) < CHANNEL_LIMIT_PER_IP

    async def increment_channel_count(self, ip: str) -> None:
        """Increment active channel count for an IP."""
        key = f"wormhole:ip:{ip}:channels"
        await self._redis.incr(key)
        await self._redis.expire(key, 3600)  # Expire with channel TTL

    async def decrement_channel_count(self, ip: str) -> None:
        """Decrement active channel count for an IP."""
        key = f"wormhole:ip:{ip}:channels"
        count = await self._redis.decr(key)
        if count <= 0:
            await self._redis.delete(key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_relay_rate_limiter.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wormhole/relay/rate_limiter.py tests/test_relay_rate_limiter.py
git commit -m "feat: add rate limiter for relay server"
```

---

### Task 6: Relay server (FastAPI app)

**Files:**
- Create: `src/agent_wormhole/relay/server.py`
- Create: `tests/test_relay_server.py`

- [ ] **Step 1: Write tests for relay server**

Create `tests/test_relay_server.py`:

```python
"""Tests for the relay FastAPI server."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
from httpx import AsyncClient, ASGITransport

from agent_wormhole.relay.server import app, get_redis


@pytest.fixture
async def fake_redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
async def client(fake_redis):
    app.dependency_overrides[get_redis] = lambda: fake_redis
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_health_redis_down():
    """Health check reports redis disconnected when Redis is unavailable."""
    mock_redis = AsyncMock()
    mock_redis.ping.side_effect = Exception("connection refused")
    app.dependency_overrides[get_redis] = lambda: mock_redis
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["redis"] == "disconnected"
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_relay_server.py -v`
Expected: FAIL

- [ ] **Step 3: Implement relay server**

Create `src/agent_wormhole/relay/server.py`:

```python
"""FastAPI relay server for agent-wormhole."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from redis.asyncio import Redis

from agent_wormhole.relay.redis_manager import RedisManager
from agent_wormhole.relay.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

app = FastAPI(title="agent-wormhole relay")

_redis: Redis | None = None
CODE_PATTERN = re.compile(r"^[a-z]+-[a-z]+-[a-z]+$")


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379")
        )
    return _redis


@app.on_event("shutdown")
async def shutdown():
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


@app.get("/health")
async def health():
    try:
        redis = await get_redis()
        await redis.ping()
        return {"status": "ok", "redis": "connected"}
    except Exception:
        return {"status": "ok", "redis": "disconnected"}


@app.websocket("/ws")
async def websocket_handler(ws: WebSocket):
    await ws.accept()
    redis = await get_redis()
    mgr = RedisManager(redis)
    limiter = RateLimiter(redis)

    code: str | None = None
    role: str | None = None
    client_ip = ws.client.host if ws.client else "unknown"

    try:
        # Wait for join message
        raw = await ws.receive_text()
        msg = json.loads(raw)

        if msg.get("action") != "join":
            await ws.send_text(
                json.dumps({"type": "error", "message": "expected join action"})
            )
            await ws.close()
            return

        code = msg.get("code", "")
        role = msg.get("role", "")

        if role not in ("host", "peer"):
            await ws.send_text(
                json.dumps({"type": "error", "message": "unable to join channel"})
            )
            await ws.close()
            return

        if not CODE_PATTERN.match(code):
            await ws.send_text(
                json.dumps({"type": "error", "message": "unable to join channel"})
            )
            await ws.close()
            return

        # Rate limit: join attempts per code
        if not await limiter.check_join_attempts(code):
            await ws.send_text(
                json.dumps({"type": "error", "message": "rate limited"})
            )
            await ws.close()
            return

        # Rate limit: channels per IP
        if not await limiter.check_channel_count(client_ip):
            await ws.send_text(
                json.dumps({"type": "error", "message": "too many channels"})
            )
            await ws.close()
            return

        # Atomic join
        ok = await mgr.join(code, role)
        if not ok:
            await ws.send_text(
                json.dumps({"type": "error", "message": "unable to join channel"})
            )
            await ws.close()
            return

        await limiter.increment_channel_count(client_ip)

        # Check if paired
        if await mgr.is_paired(code):
            await ws.send_text(
                json.dumps({"type": "status", "event": "paired"})
            )
            # Notify the other side if they're connected via a stream message
            # (The other side's writer loop will pick up paired status from meta)
        else:
            await ws.send_text(
                json.dumps({"type": "status", "event": "waiting"})
            )

        # Run reader and writer concurrently
        await asyncio.gather(
            _ws_reader(ws, mgr, limiter, code, role),
            _ws_writer(ws, mgr, code, role),
        )

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket handler error")
    finally:
        if code and role:
            await mgr.disconnect(code, role)
            await limiter.decrement_channel_count(client_ip)


async def _ws_reader(
    ws: WebSocket,
    mgr: RedisManager,
    limiter: RateLimiter,
    code: str,
    role: str,
) -> None:
    """Read binary frames from WebSocket, push to Redis Stream."""
    while True:
        data = await ws.receive_bytes()

        if not await limiter.check_message_rate(code):
            await ws.send_text(
                json.dumps({"type": "error", "message": "rate limited"})
            )
            continue

        if not await limiter.check_byte_rate(code, len(data)):
            await ws.send_text(
                json.dumps({"type": "error", "message": "rate limited"})
            )
            continue

        await mgr.send_frame(code, role, data)


async def _ws_writer(
    ws: WebSocket,
    mgr: RedisManager,
    code: str,
    role: str,
) -> None:
    """Read frames from Redis Stream, send to WebSocket."""
    while True:
        frames = await mgr.read_frames(code, role, block_ms=1000)

        if not frames:
            # Check if peer just connected (transition from waiting to paired)
            if await mgr.is_paired(code):
                # Send paired notification in case the other side just joined
                # (idempotent -- client ignores duplicate paired events)
                pass
            continue

        for frame in frames:
            await ws.send_bytes(frame)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_relay_server.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wormhole/relay/server.py tests/test_relay_server.py
git commit -m "feat: add FastAPI relay server with WebSocket handler"
```

---

### Task 7: RelayTransport

**Files:**
- Modify: `src/agent_wormhole/transport.py`
- Modify: `tests/test_transport.py`

- [ ] **Step 1: Add RelayTransport tests**

Append to `tests/test_transport.py`:

```python
from unittest.mock import AsyncMock, MagicMock
from agent_wormhole.transport import RelayTransport


@pytest.mark.asyncio
async def test_relay_transport_is_transport_subclass():
    assert issubclass(RelayTransport, Transport)
```

Note: Full E2E relay transport tests are in Task 10 (test_relay_e2e.py) since they require a running relay server. This test just verifies the class structure.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_transport.py::test_relay_transport_is_transport_subclass -v`
Expected: FAIL -- `RelayTransport` doesn't exist

- [ ] **Step 3: Implement RelayTransport**

Add to `src/agent_wormhole/transport.py`, after the `DirectTransport` class:

```python
import json
from websockets.asyncio.client import connect as ws_connect, ClientConnection


class RelayTransport(Transport):
    """WebSocket transport through a relay server."""

    def __init__(self, relay_url: str, code: str, role: str):
        self._relay_url = relay_url
        self._code = code
        self._role = role
        self._ws: ClientConnection | None = None

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
        return getattr(self, "_status", {})

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_transport.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wormhole/transport.py tests/test_transport.py
git commit -m "feat: add RelayTransport for WebSocket relay connections"
```

---

### Task 8: Refactor channel.py to use Transport

**Files:**
- Modify: `src/agent_wormhole/channel.py`
- Modify: `tests/test_integration.py`

- [ ] **Step 1: Refactor channel.py**

Rewrite `channel.py` to use the `Transport` interface. The key change is that `_do_handshake`, `_outbox_watcher`, and `_receiver` now use `transport.send_frame()` / `transport.recv_frame()` instead of raw `asyncio.StreamReader` / `asyncio.StreamWriter`. The public API (`run_host`, `run_peer`) stays backward-compatible.

Replace the full content of `src/agent_wormhole/channel.py`:

```python
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

        await _run_channel(transport, code, "host", output, base)


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

    await _run_channel(transport, code, "peer", output, base)


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
```

- [ ] **Step 2: Run existing integration tests**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_integration.py -v`
Expected: all PASS. The existing tests use `run_host(port=0, ...)` which now defaults to relay mode, but since there's no relay server running, we need to update them to use `direct=True`.

- [ ] **Step 3: Update integration tests for direct mode**

Modify `tests/test_integration.py` -- update all `run_host` calls to pass `direct=True`:

In `test_full_text_roundtrip`, change:
```python
await run_host(port=0, output=host_out, timeout=5.0,
               on_code=lambda c: code_future.set_result(c), base=tmp_base)
```
to:
```python
await run_host(port=0, output=host_out, timeout=5.0,
               on_code=lambda c: code_future.set_result(c), base=tmp_base,
               direct=True)
```

Apply the same change to `test_file_transfer` and `test_large_text_saved_to_file`.

- [ ] **Step 4: Run all tests**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wormhole/channel.py tests/test_integration.py
git commit -m "refactor: channel.py uses Transport abstraction, relay mode default"
```

---

### Task 9: Update CLI with --direct and --relay flags

**Files:**
- Modify: `src/agent_wormhole/cli.py`

- [ ] **Step 1: Update CLI**

Replace the content of `src/agent_wormhole/cli.py`:

```python
import asyncio
from typing import Optional

import typer

from agent_wormhole.channel import run_host, run_peer, send_to_outbox
from agent_wormhole.fs import cleanup_channel, DEFAULT_BASE

app = typer.Typer(name="agent-wormhole", help="Secure ephemeral channels for AI agent communication")


@app.command()
def host(
    port: int = typer.Option(0, help="Port to listen on (0 = random, only used with --direct)"),
    direct: bool = typer.Option(False, "--direct", help="Use direct TCP mode instead of relay"),
    relay: Optional[str] = typer.Option(None, "--relay", help="Custom relay URL (overrides default)"),
):
    """Host a new channel and wait for a peer to connect."""
    asyncio.run(run_host(port=port, direct=direct, relay_url=relay))


@app.command()
def connect(
    target: str = typer.Argument(help="Channel code (relay) or <code>@<hostname> (direct)"),
    relay: Optional[str] = typer.Option(None, "--relay", help="Custom relay URL (overrides default)"),
):
    """Connect to an existing channel."""
    asyncio.run(run_peer(target, relay_url=relay))


@app.command()
def send(
    code: str = typer.Argument(help="Channel code"),
    message: str = typer.Argument(default=None, help="Text message to send"),
    file: str = typer.Option(None, "--file", help="Path to file to send"),
    role: str = typer.Option(None, "--role", help="Role (host/peer). Auto-detected if only one is present."),
):
    """Send a message or file through a channel."""
    if message is None and file is None:
        typer.echo("Error: provide a message or --file", err=True)
        raise typer.Exit(1)
    send_to_outbox(code, message=message, file_path=file, role=role)


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
        has_host = (base / ch / "outbox-host").exists()
        has_peer = (base / ch / "outbox-peer").exists()
        roles = []
        if has_host:
            roles.append("host")
        if has_peer:
            roles.append("peer")
        status_str = f"({', '.join(roles)})" if roles else "(idle)"
        typer.echo(f"  {ch} {status_str}")


@app.command()
def close(code: str = typer.Argument(help="Channel code to close")):
    """Close a channel and clean up all files."""
    cleanup_channel(code)
    typer.echo(f"Channel {code} closed and cleaned up")
```

- [ ] **Step 2: Verify CLI help**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run agent-wormhole host --help`
Expected: shows `--direct` and `--relay` options

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run agent-wormhole connect --help`
Expected: shows `--relay` option

- [ ] **Step 3: Run all tests**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add src/agent_wormhole/cli.py
git commit -m "feat: add --direct and --relay flags to CLI"
```

---

### Task 10: Full E2E relay test

**Files:**
- Create: `tests/test_relay_e2e.py`

- [ ] **Step 1: Write E2E test**

Create `tests/test_relay_e2e.py`:

```python
"""End-to-end test: two clients communicate through the relay server."""
import asyncio
import json
import pytest
from io import StringIO

import fakeredis.aioredis
import uvicorn

from agent_wormhole.channel import run_host, run_peer, send_to_outbox
from agent_wormhole.relay.server import app, get_redis


@pytest.fixture
async def fake_redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
async def relay_server(fake_redis):
    """Start the relay server on a random port for testing."""
    app.dependency_overrides[get_redis] = lambda: fake_redis

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)

    # Get the actual bound port
    task = asyncio.create_task(server.serve())
    # Wait for server to start
    while not server.started:
        await asyncio.sleep(0.05)

    # Extract port from server sockets
    port = None
    for s in server.servers:
        for sock in s.sockets:
            addr = sock.getsockname()
            port = addr[1]
            break
        if port:
            break

    relay_url = f"ws://127.0.0.1:{port}"
    yield relay_url

    server.should_exit = True
    await task
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_e2e_relay_text_roundtrip(relay_server, tmp_path):
    """Host and peer exchange text messages through the relay."""
    host_out = StringIO()
    peer_out = StringIO()
    code_future: asyncio.Future[str] = asyncio.Future()

    async def run_h():
        await run_host(
            output=host_out,
            timeout=10.0,
            on_code=lambda c: code_future.set_result(c),
            base=tmp_path,
            relay_url=relay_server,
        )

    host_task = asyncio.create_task(run_h())
    code = await asyncio.wait_for(code_future, timeout=5.0)

    peer_task = asyncio.create_task(
        run_peer(code, output=peer_out, timeout=10.0, base=tmp_path, relay_url=relay_server)
    )

    await asyncio.sleep(1.0)

    # Host sends to peer
    send_to_outbox(code, "hello via relay", role="host", base=tmp_path)
    await asyncio.sleep(0.5)

    peer_lines = [json.loads(l) for l in peer_out.getvalue().strip().split("\n") if l.strip()]
    assert any(m.get("body") == "hello via relay" for m in peer_lines)

    # Peer sends to host
    send_to_outbox(code, "reply via relay", role="peer", base=tmp_path)
    await asyncio.sleep(0.5)

    host_lines = [json.loads(l) for l in host_out.getvalue().strip().split("\n") if l.strip()]
    assert any(m.get("body") == "reply via relay" for m in host_lines)

    host_task.cancel()
    peer_task.cancel()
    await asyncio.gather(host_task, peer_task, return_exceptions=True)
```

- [ ] **Step 2: Run E2E test**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest tests/test_relay_e2e.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/cahnd/Documents/GitHub/agent-wormhole && uv run pytest -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_relay_e2e.py
git commit -m "test: add E2E relay test with in-process server"
```

---

### Task 11: Update SKILL.md

**Files:**
- Modify: `skill/SKILL.md`

- [ ] **Step 1: Update SKILL.md to relay-first flow**

Replace the content of `skill/SKILL.md`:

```markdown
---
name: agent-wormhole
description: Open a secure ephemeral channel to communicate with another Claude Code instance. Use when you need to send or receive messages, credentials, or files to/from another AI agent session.
argument-hint: "<action> (host, connect <code>)"
---

# Agent Wormhole

Secure, encrypted communication channel between two Claude Code instances.

## Prerequisites

`agent-wormhole` must be installed. Check if it's available:

```bash
agent-wormhole --help
```

If not installed, install it:

```bash
pip install git+https://github.com/noncuro/agent-wormhole.git
```

Or with uv:

```bash
uv tool install git+https://github.com/noncuro/agent-wormhole.git
```

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
   `{"type":"status","event":"channel","code":"<word>-<word>-<word>"}`
3. Tell the user to give the other Claude session this ready-to-paste command:
   ```
   /agent-wormhole connect <code>
   ```
   No hostname needed -- the relay server handles routing.
4. Wait for `{"type":"status","event":"connected"}` before sending messages.

## Connecting to a Channel (you received a code)

If invoked as `/agent-wormhole connect <code>`, parse the code from the argument.

1. Start listening using Monitor:
   ```
   Monitor(
     command="agent-wormhole connect <code>",
     description="Wormhole channel",
     persistent=True
   )
   ```
2. Wait for `{"type":"status","event":"connected"}`.
3. Tell the user you're connected and ready to send/receive.

## Sending Messages

Use Bash to send. Include `--role host` or `--role peer` matching your side of the channel:

```bash
# If you hosted the channel:
agent-wormhole send <code> "your message here" --role host

# If you connected to the channel:
agent-wormhole send <code> "your message here" --role peer
```

To send a file:
```bash
agent-wormhole send <code> --file /path/to/file --role host
```

The `--role` flag is required when both host and peer run on the same machine. On separate machines it auto-detects.

## Receiving Messages

Messages arrive as Monitor notifications (JSON lines):

- **Text**: `{"type":"text","body":"the message"}`
- **Large text** (>1KB): `{"type":"text","saved_to":"/tmp/agent-wormhole/messages/123.txt","size":4096}` -- use Read tool to get the content
- **File**: `{"type":"file","name":"config.json","saved_to":"/tmp/agent-wormhole/files/config.json","size":2048}` -- use Read tool to get the file

## Channel Limits

- **Inactivity timeout**: Channels expire after **1 hour** with no messages or keepalives. Finish work promptly or send periodic messages to keep the channel alive.
- **Rate limits**: 60 messages/minute, 50 MB/minute per channel. Batch small messages where practical.
- **Max frame size**: 10 MB per message/file.
- **Disconnection**: If the peer disconnects, you'll receive `{"type":"status","event":"peer_disconnected"}`. The channel stays alive -- the peer can reconnect within the 1-hour TTL.

## Important: Save Before Closing

Channel cleanup deletes ALL temporary files. Before closing a channel, save anything important to its permanent destination:

- **Credentials/API keys** -> 1Password, .env files, or project config
- **Config files** -> Copy to the project directory
- **Important text** -> Save to a file in the project

## Closing

```bash
agent-wormhole close <code>
```

The channel also cleans up automatically on disconnect (e.g., if the peer closes their end or the Monitor is cancelled). Prefer explicit `close` to ensure cleanup happens.

## Direct Mode (Local/Tailscale)

For machines on the same network, you can skip the relay:

```bash
# Host (direct TCP)
agent-wormhole host --direct

# Peer (code includes port, needs hostname)
agent-wormhole connect <port>-<word>-<word>-<word>@<hostname>
```

## Status Events

- `{"type":"status","event":"channel","code":"..."}` -- channel created (host only)
- `{"type":"status","event":"waiting"}` -- waiting for peer
- `{"type":"status","event":"paired"}` -- peer found on relay, handshake starting
- `{"type":"status","event":"connected"}` -- peer connected, ready to communicate
- `{"type":"status","event":"disconnected"}` -- peer disconnected
- `{"type":"status","event":"peer_disconnected"}` -- peer dropped (relay mode, channel still alive)
- `{"type":"status","event":"handshake_failed","detail":"..."}` -- authentication failed (wrong code)
- `{"type":"status","event":"error","detail":"..."}` -- other error
```

- [ ] **Step 2: Commit**

```bash
git add skill/SKILL.md
git commit -m "docs: update SKILL.md for relay-first workflow with TTL/rate limit docs"
```

---

### Task 12: Railway deployment config

**Files:**
- Create: `railway.toml`

- [ ] **Step 1: Create railway.toml**

Create `railway.toml` in the project root:

```toml
[build]
builder = "NIXPACKS"

[deploy]
startCommand = "uvicorn agent_wormhole.relay.server:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/health"
healthcheckTimeout = 100
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10
```

- [ ] **Step 2: Commit**

```bash
git add railway.toml
git commit -m "chore: add railway.toml for relay server deployment"
```

---

### Task 13: Deploy to Railway

**Files:**
- Modify: `src/agent_wormhole/config.py` (update DEFAULT_RELAY_URL after deploy)

- [ ] **Step 1: Create Railway project**

Use Railway MCP or CLI:
```bash
railway login  # if not already authenticated
```

Then use `mcp__Railway__create-project-and-link` with:
- projectName: "agent-wormhole-relay"
- workspacePath: "/Users/cahnd/Documents/GitHub/agent-wormhole"

- [ ] **Step 2: Add Redis service**

Add Redis via Railway dashboard or template. Set `REDIS_URL` variable on the relay service referencing `${{Redis.REDIS_URL}}`.

Use `mcp__Railway__set-variables` with:
- workspacePath: "/Users/cahnd/Documents/GitHub/agent-wormhole"
- variables: `REDIS_URL=${{Redis.REDIS_URL}}`

- [ ] **Step 3: Generate public domain**

Use `mcp__Railway__generate-domain` to get a public URL.

- [ ] **Step 4: Deploy**

Use `mcp__Railway__deploy` or push to main:
```bash
git push origin main
```

- [ ] **Step 5: Verify deployment**

Check health endpoint:
```bash
curl https://<domain>.up.railway.app/health
```
Expected: `{"status":"ok","redis":"connected"}`

Check logs:
Use `mcp__Railway__get-logs` with logType: "deploy"

- [ ] **Step 6: Update DEFAULT_RELAY_URL**

Update `src/agent_wormhole/config.py` with the actual Railway domain:

```python
DEFAULT_RELAY_URL = "wss://<actual-domain>.up.railway.app"
```

- [ ] **Step 7: Commit and redeploy**

```bash
git add src/agent_wormhole/config.py
git commit -m "chore: set DEFAULT_RELAY_URL to deployed Railway domain"
git push origin main
```

---

### Task 14: Manual smoke test

- [ ] **Step 1: Test relay mode end-to-end**

In terminal 1:
```bash
agent-wormhole host
```
Copy the 3-word code from output.

In terminal 2:
```bash
agent-wormhole connect <code>
```

Both should show `connected`.

- [ ] **Step 2: Exchange messages**

```bash
# Terminal 1
agent-wormhole send <code> "hello from host" --role host

# Terminal 2
agent-wormhole send <code> "hello from peer" --role peer
```

Verify messages appear in the other terminal's output.

- [ ] **Step 3: Test direct mode still works**

```bash
# Terminal 1
agent-wormhole host --direct

# Terminal 2
agent-wormhole connect <code>@localhost
```

Verify messages still work in direct mode.
