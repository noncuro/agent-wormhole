# agent-wormhole

A Claude Code session on your laptop can hand a file, a message, or a secret to a Claude Code session on another machine, sealed end to end so only the two of them can read it. It's like [Magic Wormhole](https://github.com/magic-wormhole/magic-wormhole) for AI agents.

![demo](./docs/demo.gif)

## What you'd use it for

- Moving an API key between machines, sealed end to end and cleaned up as soon as the channel closes.
- Two parallel worktree sessions coordinating who edits what, and handing off context so the next session picks up where the last one left off.
- Getting a second opinion from another Claude running with a different model or prompt, and pulling the review back into the current session.
- Two agents pair programming, one on the frontend and one on the backend, trading schemas and test fixtures in real time.

## Quickstart

Install:

```bash
uv tool install agent-wormhole
# or
pip install agent-wormhole
```

Host a channel:

```bash
$ agent-wormhole host
{"type":"status","event":"channel","code":"9471-crossover-clockwork-marble"}
```

Connect from the other side with that code:

```bash
$ agent-wormhole connect 9471-crossover-clockwork-marble
{"type":"status","event":"connected"}
```

Send a message or a file:

```bash
agent-wormhole send 9471-crossover-clockwork-marble "hello from laptop"
agent-wormhole send 9471-crossover-clockwork-marble --file ./config.json
```

Close the channel:

```bash
agent-wormhole close 9471-crossover-clockwork-marble
```

## Using it from Claude Code

agent-wormhole ships with a Claude Code skill so your agents know how to host a channel, connect to one, and trade messages on their own. Install it with one piped command:

```bash
agent-wormhole setup | claude
```

That pipes the skill configuration into Claude Code, which symlinks `~/.claude/skills/agent-wormhole/SKILL.md` into the installed package so the skill updates when you upgrade `agent-wormhole`.

Then either session can run:

- `/agent-wormhole` to host a new channel and print a code to share with the other session.
- `/agent-wormhole connect <code>` to join the channel from the other side.

The skill teaches Claude to use Monitor for real-time message delivery, send text and files, wait for the peer to join, and clean up the channel when the work is done.

## Security

- End to end encrypted with AES-256-GCM, and the two directions use separate keys derived via HKDF.
- SPAKE2 password-authenticated key exchange, so both sides prove they know the channel code while keeping the code off the wire entirely.
- A fresh session key for every connection, so a compromised session reveals only itself.
- Channels are single-use, and the host stops listening after the first peer connects.
- Channels are ephemeral, with temp files cleaned up on close and a one-hour inactivity timeout.

The relay server is a blind router. It pairs two parties holding the same channel code and shuttles encrypted frames between them. The relay only sees envelope metadata, and the payload stays encrypted end to end the whole trip.

## How it works

1. The host generates a human-readable channel code and registers it with the relay.
2. The peer connects to the relay with the same code.
3. The relay pairs them and streams encrypted frames between the two sockets.
4. The host and peer run a SPAKE2 key exchange over that stream, proving they both know the code while keeping it off the wire.
5. Two direction-separated AES-256-GCM keys are derived via HKDF.
6. Messages and files flow bidirectionally over the encrypted channel.

For machines on the same network or the same Tailnet, you can skip the relay with `--direct`:

```bash
# host listens on a local TCP port
agent-wormhole host --direct

# peer connects with a port-prefixed code and a hostname
agent-wormhole connect <port>-<word>-<word>-<word>@<hostname>
```

## Channel limits

The relay enforces a few limits:

- Channels expire after an hour of inactivity, and sending any message or keepalive resets the clock.
- 60 messages per minute and 50 MB per minute per channel.
- 10 MB maximum per frame.

## License

MIT
