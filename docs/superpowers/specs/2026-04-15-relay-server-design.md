# Relay Server Design

## Summary

Add a public WebSocket relay server to agent-wormhole so two agents can connect without direct network access to each other. The relay forwards opaque encrypted frames between paired clients, backed by Redis Streams for durability across relay restarts. Relay mode becomes the default; direct TCP mode remains as a fallback.

## Goals

- **Any two agents can connect** regardless of NAT, firewall, or network topology
- **E2E encryption preserved** -- relay is a forwarding layer, never sees plaintext
- **Survive relay restarts** -- Redis Streams persist in-flight handshake and message data
- **Horizontally scalable** -- stateless relay instances behind a load balancer
- **Simple UX** -- host gets a 3-word code, peer connects with just the code. No hostnames, ports, or relay URLs needed in the default flow.

## Architecture

```
Client A (host)                    Relay Server(s)                   Client B (peer)
    |                                    |                                |
    |---- WS connect ------------------>|                                |
    |---- {"action":"join",             |                                |
    |      "code":"...",                |                                |
    |      "role":"host"} ------------>|                                |
    |<--- {"type":"status",             |                                |
    |      "event":"waiting"} ---------|                                |
    |                                    |<---- WS connect --------------|
    |                                    |<---- {"action":"join",        |
    |                                    |       "code":"...",           |
    |                                    |       "role":"peer"} ---------|
    |<--- {"type":"status",             |---- {"type":"status",         |
    |      "event":"paired"} ----------|      "event":"paired"} ------>|
    |                                    |                                |
    |==== binary frames (encrypted) ====|==== binary frames ============|
    |     via Redis Streams              |     via Redis Streams          |
```

### Components

1. **Relay server** -- FastAPI app with WebSocket endpoint, deployed on Railway
2. **Redis** -- Streams for message durability, keys for channel metadata and rate limiting
3. **Client transport abstraction** -- `RelayTransport` alongside existing `DirectTransport`

## Relay Server

### Tech stack

- Python, FastAPI, `websockets`, `redis.asyncio`
- Deployed on Railway with a Railway-managed Redis instance

### Endpoints

- `GET /health` -- returns `{"status":"ok","redis":"connected|disconnected"}`
- `WS /ws` -- main channel endpoint

### WebSocket protocol

1. Client connects to `/ws`
2. Client sends JSON control message: `{"action":"join","code":"<code>","role":"host|peer"}`
3. Relay validates code format, checks rate limits, registers client in Redis metadata
4. Relay responds with status:
   - `{"type":"status","event":"waiting"}` if this client is first
   - `{"type":"status","event":"paired"}` if the other side is already connected (both sides get this)
5. After join, all subsequent messages are **binary WebSocket frames** -- opaque encrypted bytes forwarded via Redis Streams
6. On disconnect: relay sends `{"type":"status","event":"peer_disconnected"}` to the other side

### Relay concurrency model

Per connected client, two concurrent async tasks:

- **Reader**: receives binary frames from the client's WebSocket, `XADD`s to the outbound stream (e.g., host sends to `wormhole:{code}:host-to-peer`)
- **Writer**: `XREAD BLOCK` on the inbound stream (e.g., host reads from `wormhole:{code}:peer-to-host`), forwards frames to the client's WebSocket

### Redis key layout

```
wormhole:{code}:meta          -- Hash {host_connected, peer_connected, created_at, last_activity}
                                 TTL: 1 hour (reset on activity)
wormhole:{code}:host-to-peer  -- Stream: frames from host to peer
wormhole:{code}:peer-to-host  -- Stream: frames from peer to host
wormhole:{code}:rate          -- Counter for sliding window rate limiting, TTL 60s
```

### Channel lifecycle

1. **Create**: First client to join a code creates the meta key and streams
2. **Pair**: Second client joins, both notified with `paired` status
3. **Active**: Frames flow bidirectionally through Redis Streams
4. **Keepalive**: WebSocket pings every 30s reset the TTL on the meta key
5. **Expiry**: Channels expire after **1 hour of inactivity**. Redis TTL on the meta key handles this. A background task runs every 5 minutes to delete orphaned streams whose meta key has expired.
6. **Disconnect**: One side drops -- other side notified. Channel stays alive for reconnection until TTL expires. On reconnect, the client sends a new `join` message with the same code and role. The relay resumes streaming from the client's last-read position in the Redis Stream (tracked by the relay per-client via `XREAD` cursor). No re-handshake is needed at the relay level, but if the SPAKE2 handshake was interrupted, clients must restart it (the handshake messages are still in the stream).

### Rate limiting

- **60 messages/minute per channel** -- sliding window counter in Redis. Excess messages rejected with a JSON error frame.
- **100 active channels per source IP** -- prevents resource exhaustion from a single actor. Checked at join time.
- **10 MB max frame size** -- matches existing client-side limit.

## Client Changes

### Transport abstraction

Refactor `channel.py` to separate transport from protocol logic:

```python
class Transport(ABC):
    async def connect(self) -> None: ...
    async def send_frame(self, data: bytes) -> None: ...
    async def recv_frame(self) -> bytes: ...
    async def close(self) -> None: ...

class DirectTransport(Transport):
    """Existing TCP logic -- host listens, peer connects directly."""

class RelayTransport(Transport):
    """WebSocket connection to relay server."""
```

The SPAKE2 handshake, encryption, and message handling code stays identical -- it reads/writes frames through whichever transport is active.

### Transport selection

| Command | Transport | Notes |
|---------|-----------|-------|
| `agent-wormhole host` | RelayTransport | Default, uses `DEFAULT_RELAY_URL` |
| `agent-wormhole host --direct` | DirectTransport | Legacy mode |
| `agent-wormhole host --relay wss://custom.example.com` | RelayTransport | Custom relay |
| `agent-wormhole connect <3-word-code>` | RelayTransport | Default |
| `agent-wormhole connect <code>@<hostname>` | DirectTransport | Backward compatible |

### Code format

- **Relay mode**: 3 words only (`crossover-clockwork-marble`), no port prefix
- **Direct mode**: port-prefixed (`9471-crossover-clockwork-marble`)
- Detection is unambiguous: if the first segment is numeric, it's direct mode

### Default relay URL

```python
# src/agent_wormhole/config.py
DEFAULT_RELAY_URL = "wss://agent-wormhole-relay.up.railway.app"
```

Overridable via `--relay` flag or `AGENT_WORMHOLE_RELAY_URL` environment variable.

## Skill Updates

Update `SKILL.md` to:

- Use relay mode as the default flow (no hostname needed, just share the 3-word code)
- Document the **1-hour inactivity TTL** so agents send keepalives or finish work promptly
- Document **rate limits** (60 msg/min) so agents batch appropriately
- Document `peer_disconnected` status and that channels survive brief disconnections
- Document `--direct` flag for local/Tailscale scenarios
- Keep direct mode documented as a fallback option

## Project structure

```
src/agent_wormhole/
├── relay/
│   ├── __init__.py
│   ├── server.py        -- FastAPI app, WebSocket handler
│   ├── redis_manager.py -- Redis Streams + metadata operations
│   └── rate_limiter.py  -- Rate limiting logic
├── transport.py          -- Transport ABC, DirectTransport, RelayTransport
├── config.py             -- DEFAULT_RELAY_URL and other config
├── channel.py            -- Refactored to use Transport interface
├── crypto.py             -- Unchanged
├── protocol.py           -- Unchanged
├── ...
```

## Deployment

- **Platform**: Railway
- **Services**: 1 web service (relay) + 1 Redis instance
- **Dockerfile** or Railway `nixpacks` for the relay service
- Health check on `GET /health`
- Environment variables: `REDIS_URL` (provided by Railway Redis plugin)

## Error handling

- **Relay unreachable**: Client retries with exponential backoff (3 attempts), then fails with clear error message suggesting `--direct` mode
- **Redis down**: Relay health check reports unhealthy, returns 503. Active WebSocket connections get an error frame and are closed.
- **Duplicate role**: If a second host tries to join a code that already has a host, relay rejects with `{"type":"error","message":"role already taken"}`
- **Invalid code**: Relay rejects with `{"type":"error","message":"invalid code format"}`

## Security considerations

- Relay is zero-knowledge about message content (E2E encrypted via SPAKE2 + AES-256-GCM)
- Code entropy: 3 words from 256-word list = ~24 bits. Sufficient for ephemeral channels with 1-hour TTL. Brute-force at 60 msg/min rate limit would take ~19 days per code.
- Rate limiting and per-IP channel limits prevent resource exhaustion
- No authentication required (public service), abuse mitigated through rate limits
- WebSocket connections use TLS (wss://) for transport-level encryption on top of E2E encryption
