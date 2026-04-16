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
3. Both sides perform a SPAKE2 key exchange -- proving they both know the code without transmitting it
4. Two direction-separated AES-256-GCM keys are derived via HKDF
5. Messages flow bidirectionally over the encrypted channel

## Claude Code Skill

agent-wormhole ships with a Claude Code skill so your AI agents know how to use it. After installing the package, run inside Claude Code:

```bash
agent-wormhole setup
```

Claude will read the output and configure the skill automatically. Then any Claude Code session can use `/agent-wormhole` to host, connect, and exchange messages.

If you're not in Claude Code, the command will give you a paste-ready command to run.

## Security

- **E2E encrypted**: AES-256-GCM with direction-separated keys
- **SPAKE2 key exchange**: Password-authenticated, no code on wire
- **Forward secrecy**: Unique session key per connection
- **Single-use channels**: Host accepts one connection, then stops listening
- **Ephemeral**: All temp files cleaned up on channel close

## License

MIT
