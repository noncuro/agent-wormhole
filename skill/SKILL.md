---
name: agent-wormhole
description: Open a secure ephemeral channel to communicate with another Claude Code instance. Use when you need to send or receive messages, credentials, or files to/from another AI agent session.
argument-hint: "<action> (host, connect <code>@<hostname>)"
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

1. Determine the hostname of this machine:
   ```bash
   hostname
   ```
2. Start the channel using Monitor:
   ```
   Monitor(
     command="agent-wormhole host",
     description="Wormhole channel",
     persistent=True
   )
   ```
3. The first notification will contain the channel code:
   `{"type":"status","event":"channel","code":"<port>-<word>-<word>-<word>"}`
4. Tell the user to give the other Claude session this ready-to-paste command:
   ```
   /agent-wormhole connect <code>@<hostname>
   ```
   where `<hostname>` is this machine's hostname from step 1. This gives the other agent a single copy-paste command to connect.
5. Wait for `{"type":"status","event":"connected"}` before sending messages.

## Connecting to a Channel (you received a code)

If invoked as `/agent-wormhole connect <code>@<hostname>`, parse the target from the argument.

1. Start listening using Monitor:
   ```
   Monitor(
     command="agent-wormhole connect <code>@<hostname>",
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

## Status Events

- `{"type":"status","event":"channel","code":"..."}` -- channel created (host only)
- `{"type":"status","event":"waiting"}` -- waiting for peer (host only)
- `{"type":"status","event":"connected"}` -- peer connected, ready to communicate
- `{"type":"status","event":"disconnected"}` -- peer disconnected
- `{"type":"status","event":"handshake_failed","detail":"..."}` -- authentication failed (wrong code)
- `{"type":"status","event":"error","detail":"..."}` -- other error
