---
name: agent-wormhole
description: Open a secure ephemeral channel to communicate with another Claude Code instance. Use when you need to send or receive messages, credentials, or files to/from another AI agent session.
argument-hint: "<action> (host, connect <code>)"
---

# Agent Wormhole

Secure, encrypted communication channel between two Claude Code instances.

## Quick Reference

| You want to... | Command |
|---|---|
| **Host** a new channel | `/agent-wormhole` (no args) — hosts and gives you a code to share |
| **Connect** to a channel | `/agent-wormhole connect <code>` — paste the code the host gave you |

## Prerequisites

`agent-wormhole` must be installed and this skill must be set up. Check both:

```bash
agent-wormhole --help
```

If not installed:

```bash
pip install agent-wormhole
# or: uv tool install agent-wormhole
```

If this skill isn't yet in `~/.claude/skills/agent-wormhole/`, run the setup command and it will print step-by-step instructions for you to follow:

```bash
agent-wormhole setup
```

**Note:** This skill requires the Monitor tool, built into Claude Code since v2.1.98. If Monitor isn't available, run `claude update`.

## Quiet-by-default output policy

Every Monitor notification becomes a line in the user's transcript. Narrating each one (`Starting...`, `Waiting...`, `Paired...`) produces visual noise that adds nothing. So:

- **Do not announce** that you're starting, waiting, or that the handshake is in progress.
- **Do not narrate** intermediate events (`paired`, `reconnecting`, `reconnected`). Consume them silently.
- **Only speak when there's something actionable for the user**: the code to share (host), successful connection, disconnection, or an error.

If there's nothing to say, say nothing — let the next meaningful event be the first thing the user reads from you.

## Hosting a Channel (you are the initiator)

Start a channel and share the code with the other instance:

1. Start the channel using Monitor — **do not emit any message before or after this call**:
   ```
   Monitor(
     command="agent-wormhole host",
     description="Wormhole channel",
     persistent=True
   )
   ```
2. Silently consume events until you receive `{"type":"status","event":"channel","code":"<word>-<word>-<word>"}`. This is the first thing you announce to the user:
   ```
   /agent-wormhole connect <code>
   ```
   No hostname needed -- the relay server handles routing.
3. Silently wait for `{"type":"status","event":"connected"}`. Announce connection in one short line, then stand by.

## Connecting to a Channel (you received a code)

If invoked as `/agent-wormhole connect <code>`, parse the code from the argument.

1. Start listening using Monitor — **no preamble message**:
   ```
   Monitor(
     command="agent-wormhole connect <code>",
     description="Wormhole channel",
     persistent=True
   )
   ```
2. Silently wait for `{"type":"status","event":"connected"}`. Do not narrate `waiting` or `paired`.
3. On `connected`, tell the user you're connected and ready to send/receive in one short line.

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

When displaying messages to the user, format them clearly so both sides of the conversation are easy to distinguish:

- Incoming messages: **Peer says:** `<message>`
- Outgoing messages (after sending): **Sent:** `<message>`
- Status events: display inline, e.g. `[connected]`, `[peer disconnected]`

## Channel Limits

- **Inactivity timeout**: Channels expire after **1 hour** with no messages or keepalives. Finish work promptly or send periodic messages to keep the channel alive.
- **Rate limits**: 60 messages/minute, 50 MB/minute per channel. Batch small messages where practical.
- **Max frame size**: 10 MB per message/file.
- **Disconnection**: If the peer disconnects, you'll receive `{"type":"status","event":"peer_disconnected"}`. The channel stays alive -- the peer can reconnect within the 1-hour TTL.
- **Auto-reconnect on network blips**: If your own websocket drops (flaky wifi, brief outage), the client reconnects silently and replays any frames buffered by the relay while you were away. You'll see `{"type":"status","event":"reconnecting"}` followed by `{"type":"status","event":"reconnected"}`. No action needed. If reconnect fails after several retries, you'll get `{"type":"status","event":"disconnected"}` and the channel ends. If you see `peer_disconnected`, wait a few seconds -- the peer's client will reconnect automatically and any message they send next will reach you.

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
- `{"type":"status","event":"paired"}` -- peer found on relay, handshake starting
- `{"type":"status","event":"connected"}` -- peer connected, ready to communicate
- `{"type":"status","event":"disconnected"}` -- peer disconnected
- `{"type":"status","event":"peer_disconnected"}` -- peer dropped (relay mode, channel still alive; peer may auto-reconnect)
- `{"type":"status","event":"reconnecting"}` -- our websocket dropped, reopening (transient)
- `{"type":"status","event":"reconnected"}` -- websocket back up, resuming
- `{"type":"status","event":"handshake_failed","detail":"..."}` -- authentication failed (wrong code)
- `{"type":"status","event":"error","detail":"..."}` -- other error
