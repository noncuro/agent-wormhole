# agent-wormhole

A Claude Code session on your laptop can hand a file, a message, or a secret to a Claude Code session on another machine, sealed end to end so only the two of them can read it. Built on persistent secp256k1 identities, Nostr NIP-17 gift-wrapped DMs, and [magic-wormhole](https://github.com/magic-wormhole/magic-wormhole) for one-time pairing and bulk file transfer.

![demo](./docs/demo.gif)

agent-wormhole is for agent collaboration that outlives a single terminal. Pair once, give each peer a name, and then agents can send context to each other as they work: the branch they are on, what they changed, logs, test output, screenshots, config snippets, or a file that needs review.

## What you'd use it for

- Two people working on the same project, each with their own agent, sharing implementation notes, test fixtures, local repro steps, and review feedback without pasting everything through chat.
- One person coordinating agents on two machines: for example a local laptop agent driving the UI while a cloud or Linux box agent runs backend jobs, GPU tasks, browser tests, or long-running experiments.
- Parallel worktree sessions coordinating who edits what, and handing off context so the next session picks up where the last one left off.
- Getting a second opinion from another Claude running with a different model or prompt, and pulling the review back into the current session.
- Moving an API key, config file, or one-off artifact between machines, sealed end to end, addressable by peer name after first contact.

## Quickstart

Install:

```bash
uv tool install agent-wormhole
# or
pip install agent-wormhole
```

A persistent keypair is created on first use at `~/.agent-wormhole/identity.key` (mode 0600). See it:

```bash
$ agent-wormhole whoami
pubkey: 7f3a…
relays: wss://relay.damus.io, wss://nos.lol, wss://relay.primal.net
```

### First contact (pairing)

The `/agent-wormhole` skill drives this; the two sides exchange identity envelopes over two short magic-wormhole codes (one each direction) and each writes the other into its trust file:

```bash
# Machine A → reads code aloud
agent-wormhole identity-envelope | wormhole send --text -

# Machine B → with A's code
wormhole receive <code-A>   # prints A's envelope JSON
agent-wormhole trust <A-pubkey> alice --relays <relays>

# Then reverse so A trusts B too.
```

### Steady state

Keep a listener running; it emits one JSON line per inbound message:

```bash
$ agent-wormhole listen
{"type":"text","from":"alice","content":"hi","received_at":1700000000}
{"type":"file","from":"alice","name":"report.pdf","saved_to":"/tmp/agent-wormhole/alice/files/report.pdf","size":4096,…}
```

Send by peer name:

```bash
agent-wormhole send alice "hello from laptop"
agent-wormhole send-file alice ./config.json
```

Manage trust:

```bash
agent-wormhole peers
agent-wormhole untrust alice
```

## Using it from Claude Code

agent-wormhole ships with a Claude Code skill. Install it:

```bash
agent-wormhole setup | claude
```

That symlinks `~/.claude/skills/agent-wormhole/SKILL.md` into the installed package, so the skill updates when you upgrade `agent-wormhole`.

Then either session can run:

- `/agent-wormhole pair <peer-name>` to add a new peer (the skill walks both sides through it).
- `/agent-wormhole` to start the listener for an already-paired peer.

Outbound messages and files use `agent-wormhole send` / `agent-wormhole send-file` directly via Bash.

## How it works

1. **Identity:** each machine holds a long-lived secp256k1 keypair (`~/.agent-wormhole/identity.key`, 0600). The x-only BIP-340 pubkey is the addressable name on the Nostr network.
2. **Pairing:** the skill runs `wormhole send/receive` to swap identity envelopes between two trusted hosts (one short code per direction). Each side calls `agent-wormhole trust` to record the peer.
3. **Text messages:** NIP-44 v2 encryption + NIP-17 three-layer gift-wrap (rumor → seal signed by sender → gift wrap signed by an ephemeral key). Relays see only `kind=1059` events tagged for the recipient. Sender identity is hidden from the relay.
4. **File transfer:** `send-file` spawns a `wormhole send` subprocess, posts the negotiated code in an encrypted file-offer DM, and the recipient's listener auto-invokes `wormhole receive` (transfer authenticated by magic-wormhole's PAKE).
5. **Relay pool:** the listener and sender connect to N relays concurrently, dedupe events by id, and reconnect with backoff on disconnect.

## Configuration

Relay list resolution order: `AGENT_WORMHOLE_RELAYS` env var (comma-separated) → `~/.agent-wormhole/config.json` (`{"relays":[…]}`) → bundled defaults (damus, nos.lol, primal).

The `wormhole` CLI must be on PATH; it ships with the `magic-wormhole` Python dep.

## Security

- Identity keys never leave their machine. Losing the keyfile means re-pairing with every peer.
- Messages are NIP-44 v2 (ChaCha20 + HMAC-SHA256, HKDF over ECDH x-coord). All known canonical test vectors pass.
- NIP-17 gift-wrap hides the sender from the relay. The recipient's pubkey is necessarily visible to the relay (it's used as the `#p` subscription filter); run your own relay or trust the chosen relay set's anonymity properties if you need stronger anonymity.
- File transfer uses magic-wormhole's PAKE handshake; only the negotiated short code (delivered over the encrypted DM) can complete the transfer.

## License

MIT
