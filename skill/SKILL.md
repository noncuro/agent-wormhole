---
name: agent-wormhole
description: Pair with another Claude Code instance and communicate files and messages securely. Use to send/receive text, credentials, or files between AI agent sessions. First contact pairs identities from a single short code; afterwards, peers are addressable by name forever.
argument-hint: "[a pairing code like 7-foo-bar] | [connect / pair] | (no args = listen for paired peers)"
---

# Agent Wormhole

agent-wormhole gives two Claude Code sessions a secure, encrypted channel — for messages, credentials, or files. Think Magic Wormhole, but for agents talking to each other: two machines, or two people collaborating through their respective agents.

## The one rule that governs everything here

**The CLI is yours, not the user's.** The user never sees or types a command, flag, pubkey, file path, or relay URL. They speak in plain language ("connect me to my laptop", "send this to Dana") and you run everything silently with Bash. The **only** technical token that ever crosses to the user is a short **pairing code** (looks like `7-foo-bar`) — you read one out, or they paste one in. Report outcomes in human terms ("Paired with macbook-air. Listening." / "Sent."), never the mechanics. Only reveal commands if the user explicitly asks for the technical details.

## Deciding what to do (first message)

Look at what the user said and pick exactly one path:

1. **They gave you a pairing code** — any token matching `\b\d+-[a-z]+(?:-[a-z]+)+\b` (e.g. "connect to `7-foo-bar`", or just `7-foo-bar` pasted in) → **Join** (below). The code means the other side already started pairing; your job is to complete it. Do not start your own invite.
2. **They want to connect/pair but gave no code** → **Invite** (below). You generate one code and read it to them.
3. **Anything else** — no args, or they name a peer you've already paired with → **Listen** (below).

If it is genuinely ambiguous whether they are starting fresh or joining, ask in plain language: *"Did the other side already give you a code to use? If so, paste it and I'll connect. Otherwise I'll start a new connection and give you a code to read across."*

## Prerequisites

Check quietly; only surface a problem if one fails:

```bash
agent-wormhole --help        # CLI present
wormhole --version           # magic-wormhole present (needed for pairing + files)
```

If missing: `uv tool install agent-wormhole`, then `agent-wormhole setup` for skill wiring. This skill also needs the **Monitor** tool (built into Claude Code since v2.1.98); if it's absent, tell the user to run `claude update`.

## Pairing — Invite (you generate the one code)

First contact now takes a **single code, read one direction**. You ship this machine's identity over a wormhole code and stay subscribed for the reply; the other side completes it automatically.

Run the inviter under Monitor so you catch each step as it streams:

```
Monitor(
  command="agent-wormhole pair-invite",
  description="Pairing — waiting for the other side",
  persistent=False
)
```

It emits one JSON line per step:

- `{"type":"pairing-code","code":"7-foo-bar"}` → **immediately** tell the user: *"Read this code to the other machine: `7-foo-bar`."*
- `{"type":"paired","peer":"<name>","peer_hostname":"<hostname>"}` → pairing succeeded. Tell the user: *"Paired with `<hostname>`."* Then fall through to **Listen**. (If the stored `peer` name differs from what the user calls the machine, mention it and offer to rename — see Trust management.)
- `{"type":"pairing-timeout"}` → tell the user the other side didn't connect in time and offer to try again.

If the user wants the peer stored under a specific name, pass it: `agent-wormhole pair-invite --name <name>`.

## Pairing — Join (the user gave you a code)

The other machine is inviting; you have its code. This is quick — receive, trust, reply:

```bash
agent-wormhole pair-join <code>
```

It prints `{"type":"paired","peer":"<name>","peer_hostname":"<hostname>"}` on success, or `{"type":"error","error":"…"}` on failure. On success tell the user *"Paired with `<hostname>`."* and fall through to **Listen**. Pass `--name <name>` if the user wants a specific local name.

Once `paired` appears on either side, **both** machines are mutually trusted from that one code. No second code, no reading anything back.

## Listening (already paired)

For an existing peer, skip pairing. Start the listener under Monitor and stay silent until something arrives:

```
Monitor(
  command="agent-wormhole listen",
  description="Inbound agent-wormhole messages",
  persistent=True
)
```

The listener is **quiet by default**: it keeps a durable seen-store (keyed on
message id), so a message is surfaced exactly once — never re-flooded when relays
replay history on reconnect. On the very first run it silently baselines existing
backlog and emits a one-line summary instead of the firehose. So you won't drown
in stale history; only genuinely new messages arrive.

Each notification is one JSON line:

- **Text**: `{"type":"text","from":"<peer>","content":"<msg>",…}` → show it plainly: **`<peer> says:` `<msg>`**.
- **File** (auto-received from a trusted peer): `{"type":"file","from":"<peer>","name":"<file>","saved_to":"<path>",…}` → the file is already on disk. Mention you received it and offer to open or process it; use the Read tool on `saved_to`.
- **Backlog** (cold-start summary, not a message): `{"type":"backlog","suppressed":<N>,"through":<ts>}` → N old messages were marked-read without surfacing. **Don't act on it**; at most note "cleared N old messages." Use `agent-wormhole listen --replay` only if you need to audit the suppressed history.

### Quiet-by-default output policy

Every Monitor notification becomes a line in the user's transcript. Don't narrate setup, handshakes, or housekeeping. **Speak only when there's something actionable**: a code to read aloud, an inbound message, a received file, or an error.

## Sending

When the user asks to send something to a paired peer, do it silently and confirm in one word:

- Text or a small secret → send it; then say **"Sent."**
- A file, or anything large or binary → send the file; then say **"Delivered."** The recipient's listener auto-accepts; nothing is required on their end.

Don't show the command or echo the payload back unless asked.

## Trust management (plain-language)

The user may say things like "who am I connected to?", "call that machine 'laptop'", or "forget that connection." Handle these silently and answer in plain language — list peer names, confirm a rename, confirm a removal. Never print pubkeys or relay URLs unless asked.

## Security model

- Identity is a persistent secp256k1 keypair stored locally (mode 0600). Losing it means re-pairing with every peer.
- All messages are NIP-17 gift-wrapped DMs: relays see only an opaque wrapped event tagged to the recipient. Sender identity is hidden from relays.
- Untrusted senders are silently dropped — you're never notified.
- Pairing security: the invite travels over magic-wormhole's PAKE-protected channel and carries a one-time **nonce**. The reply comes back over Nostr and must echo that nonce, and the authenticated sender key must match the key claimed in the reply. Because the nonce is only ever exposed inside the wormhole channel, a third party who scrapes the inviter's public key from relay metadata cannot complete pairing for their own key.
- File transfer uses magic-wormhole's PAKE handshake; only the code, delivered inside the encrypted DM, can complete the transfer.

---

## Internal reference (for the agent — never shown to the user)

Full CLI surface. Use these directly; do not surface them.

| Purpose | Command |
|---|---|
| Inviter side of pairing (emits `pairing-code`, then `paired`/`pairing-timeout`) | `agent-wormhole pair-invite [--name <name>] [--timeout <sec>]` |
| Joiner side of pairing (emits `paired`/`error`) | `agent-wormhole pair-join <code> [--name <name>]` |
| Listen for inbound messages (JSON lines; run under Monitor) | `agent-wormhole listen` |
| Send text | `agent-wormhole send <peer> "<msg>"` |
| Send a file | `agent-wormhole send-file <peer> <path>` |
| List paired peers | `agent-wormhole peers` |
| Rename a peer | `agent-wormhole rename <old> <new>` |
| This machine's pubkey + relays | `agent-wormhole whoami` |
| Revoke a peer | `agent-wormhole untrust <peer>` |

Notes:
- `pair-invite` blocks until the reply arrives or it times out — that's why it runs under Monitor, so you can surface the code mid-run.
- Inbound files land under `/tmp/agent-wormhole/<peer>/files/`.
- `identity-envelope` and manual `trust <pubkey> <name> --relays …` still exist for out-of-band introductions, but single-code pairing replaces the old two-code dance.
