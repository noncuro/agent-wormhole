---
name: agent-wormhole
description: Pair with another Claude Code instance and exchange encrypted messages and files. Use to send/receive text, credentials, or files between AI agent sessions. First contact pairs identities; afterwards, peers are addressable by name forever.
argument-hint: "[pair <peer-name>] | (no args = open listener for already-paired peers)"
---

# Agent Wormhole

Encrypted, identity-based communication between Claude Code instances using Nostr DMs and magic-wormhole for bulk files.

## Quick Reference

| You want to... | Command |
|---|---|
| **Pair** with a new peer (first contact) | `/agent-wormhole pair <peer-name>` |
| **Listen** for messages from already-paired peers | `/agent-wormhole` |
| **Send** to a paired peer | `agent-wormhole send <peer> "<msg>"` |
| **Send a file** to a paired peer | `agent-wormhole send-file <peer> <path>` |

## Prerequisites

```bash
agent-wormhole --help        # must succeed
wormhole --version           # required for pairing + bulk files; ships with magic-wormhole
```

If not installed:

```bash
uv tool install agent-wormhole
agent-wormhole setup    # prints how to symlink the skill
```

**Note:** This skill requires the Monitor tool, built into Claude Code since v2.1.98. If Monitor isn't available, run `claude update`.

## Quiet-by-default output policy

Every Monitor notification becomes a line in the user's transcript. Don't narrate setup, handshakes, or `received` lines you'll handle automatically. **Only speak when there's something actionable**: a code to read aloud, an inbound text you want the user to see, a delivered file, or an error.

## Pairing (first contact)

Pairing exchanges identity envelopes over magic-wormhole, in both directions, then writes each side's trust file. The skill drives both Claude instances through it.

You need TWO short wormhole codes — one each direction. The user reads them between machines (aloud, paste, etc.).

**Role A (sender goes first):**

1. Print this machine's envelope and start `wormhole send` to ship it. Use Bash:
   ```bash
   agent-wormhole identity-envelope | wormhole send --text -
   ```
   Capture stderr/stdout for the line `Wormhole code is: <code-A>`. Tell the user: **"Read this code to the other machine: `<code-A>`"**.

2. When the other side echoes back its envelope, the user gives you Code B. Run:
   ```bash
   wormhole receive <code-B>
   ```
   It prints a single JSON line (the peer's envelope). Parse it:
   ```json
   {"type":"identity","pubkey":"...","name":"...","relays":["wss://..."]}
   ```
   Then add to your trust file:
   ```bash
   agent-wormhole trust <pubkey> <peer-name> --relays <comma-relays>
   ```
   Use the `<peer-name>` the user supplied to `/agent-wormhole pair <peer-name>`, not the hostname inside the envelope.

**Role B (the side that ran `/agent-wormhole pair <name>` after being given Code A):**

Same flow, reversed: `wormhole receive <code-A>` first, parse, run `agent-wormhole trust`, then `agent-wormhole identity-envelope | wormhole send --text -`, surface Code B for the user to read back.

Once both sides have `trust`'d each other, fall through into the "listen" flow below.

## Listening (already paired)

For an existing peer, skip pairing entirely. Start the listener under Monitor and stay quiet until something arrives.

```
Monitor(
  command="agent-wormhole listen",
  description="Inbound agent-wormhole DMs",
  persistent=True
)
```

Each notification is one JSON line:

- **Text**: `{"type":"text","from":"<peer>","pubkey":"<short>","content":"<msg>","received_at":<ts>}`
- **File** (auto-received from a trusted peer): `{"type":"file","from":"<peer>","name":"<file>","saved_to":"<path>","size":<bytes>,"received_at":<ts>}` — the file is already on disk under `/tmp/agent-wormhole/<peer>/files/`. Use Read tool to load.

Display incoming text to the user clearly: **`<peer> says:` `<msg>`**. For files, mention the path and offer to open/process it.

## Sending

```bash
agent-wormhole send <peer> "your message"
agent-wormhole send-file <peer> /path/to/file
```

`send` is for text. `send-file` initiates a magic-wormhole transfer in the background, posts a tiny file-offer DM, and the recipient's listener auto-accepts (no user interaction needed on the other side). Use `send-file` for anything >100 KB or any binary payload.

## Trust management

```bash
agent-wormhole peers              # list paired peers
agent-wormhole whoami             # this machine's pubkey + relays
agent-wormhole untrust <peer>     # revoke trust
```

## Security model

- Identity is a persistent secp256k1 keypair at `~/.agent-wormhole/identity.key` (mode 0600). Losing it means re-pairing with every peer.
- All messages are NIP-17 gift-wrapped DMs — relay operators see only `kind=1059` events with the recipient's pubkey tagged. Sender identity is hidden from relays.
- Untrusted senders are silently dropped (no notification to you).
- File transfer uses magic-wormhole's PAKE handshake; only the negotiated code (delivered over the encrypted Nostr DM) can complete the transfer.
