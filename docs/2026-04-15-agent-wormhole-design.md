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

Format: `<port>-<word>-<word>` (e.g., `9471-crossover-clockwork`).

- Port number is encoded in the code so the connector doesn't need to know it separately
- Words drawn from a bundled ~256-word list (~16M combinations)
- Human-readable and typeable, though copy-paste is the expected workflow

## Architecture

### Single Background Process

When `host` or `connect` runs, it starts a single long-running process with three responsibilities:

1. **TCP connection** — holds the encrypted link to the peer
2. **Stdout printer** — prints incoming messages to stdout (consumed by Claude Code's Monitor tool)
3. **Outbox watcher** — watches `/tmp/agent-wormhole/<code>.outbox` for outgoing messages, sends them over the wire

No daemon, no Unix socket, no PID files. The process lives as a Claude Code background job (via Monitor or `run_in_background`).

### Sending Messages

`agent-wormhole send <code> "msg"` appends to `/tmp/agent-wormhole/<code>.outbox`. The background process detects the new content via polling (0.1s interval) and sends it encrypted over TCP.

For files, `send --file` writes a JSON envelope to the outbox with base64-encoded content.

### Receiving Messages

The background process prints incoming messages to stdout. Since every stdout line becomes a Monitor notification in Claude's context window, we minimize what goes to stdout:

- **Text messages (<=1KB)**: printed directly to stdout as a single line (or JSON-wrapped if multiline)
- **Text messages (>1KB)**: saved to `/tmp/agent-wormhole/messages/<timestamp>.txt`, then a reference is printed:
  ```json
  {"type":"text","saved_to":"/tmp/agent-wormhole/messages/1713200000.txt","size":4096}
  ```
- **File messages**: always saved to `/tmp/agent-wormhole/files/<filename>`, then a JSON status line is printed:
  ```json
  {"type":"file","name":"config.json","saved_to":"/tmp/agent-wormhole/files/config.json","size":2048}
  ```

This keeps Monitor notifications small and context-friendly. Claude can read the saved file when it needs the full content.

### Claude Code Integration

**Host side** (Claude instance A):
```python
Monitor(
    command="agent-wormhole host",
    description="Wormhole channel host",
    persistent=True
)
# First stdout line: "CHANNEL 9471-crossover-clockwork"
# Then: "WAITING"
# Then: "CONNECTED"
# Then: incoming messages as they arrive
```

**Connect side** (Claude instance B):
```python
Monitor(
    command="agent-wormhole connect 9471-crossover-clockwork@macbook",
    description="Wormhole channel peer",
    persistent=True
)
# First stdout line: "CONNECTED"
# Then: incoming messages
```

**Sending** (either side):
```bash
agent-wormhole send 9471-crossover-clockwork "hello from A"
```

## Connection & Handshake Protocol

1. **Host** starts TCP server on a random available port (or user-specified). Generates channel code. Prints code to stdout. Waits for connection.

2. **Connector** parses `<code>@<hostname>`, extracts port from code, connects via TCP.

3. **SPAKE2 handshake**:
   - Both sides use the channel code as the SPAKE2 password
   - SPAKE2 (from Python `cryptography` library) performs a password-authenticated key exchange
   - Produces a shared session key without sending the code over the wire
   - If codes don't match, handshake fails — no information leaks about the code

4. **Session encryption**: All subsequent messages encrypted with AES-256-GCM using the SPAKE2-derived session key. Each message gets a unique nonce (incrementing counter).

### Security Properties

- **Mutual authentication**: Both sides prove knowledge of the code
- **Forward secrecy**: Unique session key per connection, even with the same code
- **E2E encryption**: An eavesdropper (or future relay server) learns nothing
- **No code on wire**: SPAKE2 ensures the password is never transmitted

## Message Protocol

### Wire Format

```
[4 bytes: payload length (big-endian uint32)][encrypted payload]
```

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

The background process reads each line, encodes files to base64, encrypts, and sends.

### Limits

- Max message/file size: 10MB
- Text messages >1KB are saved to file instead of printed to stdout
- Channel code entropy: ~24 bits (port range + 256^2 words). Sufficient for ephemeral channels where an attacker would need to brute-force the SPAKE2 handshake in real time.

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
      crypto.py           # SPAKE2 handshake, AES-GCM encrypt/decrypt
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
- `cryptography` — SPAKE2, AES-256-GCM
- Standard library: `asyncio`, `json`, `base64`, `pathlib`, `os`, `signal`

File watching: polling (0.1s interval) for outbox changes. Simple, cross-platform, no extra dependencies. Latency is negligible for this use case.

## Claude Code Skill

A skill that ships with the repo at `skill/agent-wormhole/skill.md`. Teaches Claude Code instances:

- How to host a channel and share the code
- How to connect to a channel
- How to send text and files
- How to set up Monitor for receiving
- Message conventions (JSON for structured data, acknowledgment patterns)
- How to signal "done" and close the channel

The skill can be symlinked into `~/.claude/skills/` for use across projects.

## Future Enhancements

- **Relay server**: A lightweight TCP proxy that routes by channel code, enabling NAT traversal without Tailscale. Both peers connect outbound to the relay. Easy extension of the current architecture.
- **Streaming file transfer**: For files >10MB, stream chunks instead of base64-in-message. Would add a `{"type": "file_stream", ...}` message type with chunked transfer.
- **Multi-party channels**: Allow 3+ peers. Would require the relay server architecture.
- **MCP server**: Expose send/receive as MCP tools instead of CLI commands, removing the outbox-file indirection.
