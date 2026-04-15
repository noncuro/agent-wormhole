# agent-wormhole Design Spec

**Date**: 2026-04-15
**Status**: Draft
**Repo**: `~/Documents/GitHub/agent-wormhole` (new, open source)

## Overview

agent-wormhole is a secure, ephemeral communication channel between two Claude Code instances running on different machines. One instance hosts a channel, generates a human-readable code, and the other connects using that code. Messages flow bidirectionally over an encrypted TCP connection. Designed for AI agent-to-agent communication, but general-purpose enough for any CLI-to-CLI secure channel.

## Goals

- Secure enough to send credentials (E2E encrypted, no plaintext on the wire)
- Ephemeral (no persistence, no message board, no server infrastructure)
- Simple CLI that integrates naturally with Claude Code's Monitor tool
- Open-sourceable as a standalone tool
- Works across machines connected via Tailscale (or any direct network path)

## Non-Goals (for v1)

- Relay server (easy extension if project succeeds — would allow NAT traversal without Tailscale)
- Streaming file transfer (v1 uses base64 in-message; fine for files under 10MB)
- Multi-party channels (v1 is strictly two peers)
- Browser-based clients
- Local attacker resistance (both machines assumed single-user; we still use safe file ops as defense-in-depth)

## CLI Interface

Built with Python + Typer, distributed as a `uv`/`pip`-installable package.

### Commands

```bash
# Host a channel (starts listening, generates code)
agent-wormhole host [--port PORT]

# Connect to a channel
agent-wormhole connect <code>@<hostname>

# Send a text message
agent-wormhole send <code> "message text"

# Send a file
agent-wormhole send <code> --file ./path/to/file

# Show active channels
agent-wormhole status

# Close a channel
agent-wormhole close <code>
```

### Channel Codes

Format: `<port>-<word>-<word>-<word>` (e.g., `9471-crossover-clockwork-marble`).

- Port number is encoded in the code so the connector doesn't need to know it separately
- Port is NOT treated as entropy — it is observable
- Three words drawn from a bundled ~256-word list (256^3 = ~16.7M combinations, ~24 bits of entropy)
- Human-readable and typeable, though copy-paste is the expected workflow

## Architecture

### Single Background Process

When `host` or `connect` runs, it starts a single long-running process with three responsibilities:

1. **TCP connection** — holds the encrypted link to the peer
2. **Stdout printer** — prints incoming messages to stdout as JSON (consumed by Claude Code's Monitor tool)
3. **Outbox watcher** — watches `/tmp/agent-wormhole/<code>/outbox` for outgoing messages, sends them over the wire

No daemon, no Unix socket, no PID files. The process lives as a Claude Code background job (via Monitor or `run_in_background`).

### Sending Messages

`agent-wormhole send <code> "msg"` appends to `/tmp/agent-wormhole/<code>/outbox`. The background process detects the new content via polling (0.1s interval) and sends it encrypted over TCP.

For files, `send --file` writes a JSON envelope to the outbox with base64-encoded content.

### Receiving Messages

The background process prints incoming messages to stdout as **strict JSON only** (one JSON object per line). Since every stdout line becomes a Monitor notification in Claude's context window, we minimize what goes to stdout:

- **Status events**: `{"type":"status","event":"connected"}`, `{"type":"status","event":"channel","code":"9471-crossover-clockwork-marble"}`
- **Text messages (<=1KB)**: `{"type":"text","body":"hello from instance A"}`
- **Text messages (>1KB)**: saved to file, then: `{"type":"text","saved_to":"/tmp/agent-wormhole/messages/1713200000.txt","size":4096}`
- **File messages**: saved to file, then: `{"type":"file","name":"config.json","saved_to":"/tmp/agent-wormhole/files/config.json","size":2048}`

All stdout is machine-parseable JSON. No raw text output, no control characters. This prevents output injection from a malicious peer and keeps Monitor notifications clean.

### File System Security

All paths under `/tmp/agent-wormhole/`:
- Root directory created with `mode 0700`, owned by current user
- All files created with `mode 0600`
- On startup, verify ownership of existing directory (refuse to use if owned by another user)
- Received filenames are sanitized: `os.path.basename()` only, reject any name containing `..` or `/`
- **Cleanup on close**: `agent-wormhole close` or channel disconnect deletes all files under `/tmp/agent-wormhole/<code>/` (outbox, received messages, received files)

### Claude Code Integration

**Host side** (Claude instance A):
```python
Monitor(
    command="agent-wormhole host",
    description="Wormhole channel host",
    persistent=True
)
# stdout: {"type":"status","event":"channel","code":"9471-crossover-clockwork-marble"}
# stdout: {"type":"status","event":"waiting"}
# stdout: {"type":"status","event":"connected"}
# Then: incoming messages as JSON lines
```

**Connect side** (Claude instance B):
```python
Monitor(
    command="agent-wormhole connect 9471-crossover-clockwork-marble@macbook",
    description="Wormhole channel peer",
    persistent=True
)
# stdout: {"type":"status","event":"connected"}
# Then: incoming messages as JSON lines
```

**Sending** (either side):
```bash
agent-wormhole send 9471-crossover-clockwork-marble "hello from A"
```

## Connection & Handshake Protocol

1. **Host** starts TCP server on a random available port (or user-specified). Generates channel code. Prints code to stdout. Waits for exactly one connection — after a peer connects (successfully or not), the host stops listening. Single-use channel.

2. **Connector** parses `<code>@<hostname>`, extracts port from code, connects via TCP.

3. **SPAKE2 handshake**:
   - Both sides use the full channel code (including port prefix) as the SPAKE2 password
   - SPAKE2 (from the `spake2` Python package — `cryptography` does not expose SPAKE2 publicly) performs a password-authenticated key exchange
   - Produces a shared session key without sending the code over the wire
   - If codes don't match, handshake fails — no information leaks about the code
   - After failed handshake, host closes the listener (no retry, no brute-force window)

4. **Key derivation**: The SPAKE2 shared secret is fed into HKDF-SHA256 to produce two AES-256 keys:
   - `host_to_peer_key` = HKDF(secret, info=b"host-to-peer")
   - `peer_to_host_key` = HKDF(secret, info=b"peer-to-host")
   - Each direction uses its own key with an independent incrementing 96-bit nonce counter starting at 0
   - This prevents nonce reuse across directions (catastrophic for AES-GCM)

5. **Session encryption**: All subsequent messages encrypted with AES-256-GCM using the direction-appropriate key. Nonces are implicit incrementing counters — the receiver tracks the expected next nonce and rejects anything else (provides replay protection).

### Security Properties

- **Mutual authentication**: Both sides prove knowledge of the code via SPAKE2
- **Forward secrecy**: Unique session key per connection, even with the same code
- **E2E encryption**: An eavesdropper (or future relay server) learns nothing
- **No code on wire**: SPAKE2 ensures the password is never transmitted
- **Direction-separated keys**: Prevents nonce reuse across bidirectional traffic
- **Replay protection**: Implicit via incrementing nonce counter — replayed ciphertexts fail decryption
- **Single-use channels**: Host accepts one connection attempt, then stops listening

## Message Protocol

### Wire Format

```
[4 bytes: payload length (big-endian uint32)][encrypted payload]
```

The receiver rejects any frame with advertised length > 10MB before allocating memory (prevents resource exhaustion).

### Payload Format (after decryption)

JSON envelope:

```json
{"type": "text", "body": "hello from instance A"}
{"type": "file", "name": "config.json", "size": 2048, "body": "<base64>"}
```

### Outbox File Format

Each entry in the outbox is a JSON line:

```json
{"type": "text", "body": "hello"}
{"type": "file", "name": "config.json", "path": "/abs/path/to/config.json"}
```

The background process reads each line, encodes files to base64, encrypts, and sends. The outbox file is deleted on process startup (fresh per session — no stale message replay).

### Protocol Version

The first message after SPAKE2 handshake is a version exchange:
```json
{"version": 1, "role": "host"}
{"version": 1, "role": "peer"}
```
Both sides verify compatible versions before proceeding. This allows future protocol evolution without breaking existing clients.

### Limits

- Max message/file size: 10MB (enforced at wire level before allocation)
- Text messages >1KB are saved to file instead of printed to stdout
- Channel code entropy: ~24 bits (256^3 words, port excluded from entropy calculation). Sufficient for ephemeral single-use channels where an attacker gets one attempt before the host shuts down.

## Project Structure

```
agent-wormhole/
  pyproject.toml          # uv/pip project config
  README.md
  LICENSE                 # MIT
  src/
    agent_wormhole/
      __init__.py
      cli.py              # Typer CLI entry point
      host.py             # Host logic (TCP server, handshake, main loop)
      connect.py          # Connect logic (TCP client, handshake, main loop)
      crypto.py           # SPAKE2 handshake, HKDF key derivation, AES-GCM encrypt/decrypt
      protocol.py         # Message framing, JSON envelopes, outbox parsing
      wordlist.py         # Channel code generation and parsing
      words.txt           # ~256 word list
  skill/
    agent-wormhole/       # Claude Code skill directory
      skill.md            # Skill instructions for Claude Code instances
  tests/
    test_crypto.py
    test_protocol.py
    test_integration.py
```

### Dependencies

- `typer` — CLI framework
- `spake2` — SPAKE2 password-authenticated key exchange
- `cryptography` — HKDF-SHA256, AES-256-GCM
- Standard library: `asyncio`, `json`, `base64`, `pathlib`, `os`, `signal`

File watching: polling (0.1s interval) for outbox changes. Simple, cross-platform, no extra dependencies. Latency is negligible for this use case.

## Claude Code Skill

A skill that ships with the repo at `skill/agent-wormhole/skill.md`. Teaches Claude Code instances:

- How to host a channel and share the code
- How to connect to a channel
- How to send text and files
- How to set up Monitor for receiving
- How to parse the JSON stdout format
- Message conventions (JSON for structured data, acknowledgment patterns)
- **Cleanup awareness**: Save any received credentials, configs, or important data to their permanent destination (1Password, .env, project files, etc.) before closing the channel — cleanup wipes all temp files
- How to signal "done" and close the channel

The skill can be symlinked into `~/.claude/skills/` for use across projects.

## Future Enhancements

- **Relay server**: A lightweight TCP proxy that routes by channel code, enabling NAT traversal without Tailscale. Both peers connect outbound to the relay. Easy extension of the current architecture — the E2E encryption means the relay never sees plaintext.
- **Streaming file transfer**: For files >10MB, stream chunks instead of base64-in-message. Would add a `{"type": "file_stream", ...}` message type with chunked transfer.
- **Multi-party channels**: Allow 3+ peers. Would require the relay server architecture.
- **MCP server**: Expose send/receive as MCP tools instead of CLI commands, removing the outbox-file indirection.
