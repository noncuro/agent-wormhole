# agent-wormhole, identity edition — design spec

**Date:** 2026-05-16
**Branch:** `nostr-identity-rewrite`
**Status:** approved for planning

## Motivation

Today, agent-wormhole creates a single ephemeral channel between two agents that dies when the conversation ends. Every reconnection means a new word-code handshake, no memory of past peers, and bulk files are base64-blobbed through the relay (a 10 MB file becomes ~13 MB of JSON buffered on both endpoints and the relay).

This rewrite gives each machine a long-lived cryptographic identity, lets agents accumulate trust relationships with peers they've paired with before, and routes ongoing messages through Nostr (lean, signed, encrypted, dumb relays you can self-host or use public ones). Bulk file transfer moves to magic-wormhole, with the transfer code negotiated over Nostr so the user never sees it. The one-time pairing dance *also* runs on magic-wormhole, so we delete our entire homegrown rendezvous stack.

The existing word-code pairing UX is preserved: still a short word code, still two-sided, still surfaced through the `/agent-wormhole` skill — just running on magic-wormhole's machinery instead of ours. Monitor-based realtime delivery is preserved end-to-end.

## Goals

- **Persistent identity.** Each machine has a secp256k1 keypair on disk. Pubkey is the address.
- **One-time pairing, many conversations.** Two agents pair once via a magic-wormhole word-code introduction; afterwards they talk over Nostr without re-pairing.
- **Strong sender authentication.** Every inbound message is cryptographically verified to come from a specific pubkey; only messages from pubkeys in the local trust file reach Claude.
- **End-to-end encryption.** Relays see only ciphertext addressed to a pubkey; sender metadata is hidden by NIP-17 gift wrap.
- **Pluggable relay.** Defaults to a curated list of public Nostr relays so it works out of the box; users can point at a self-hosted relay (Railway/strfry/nostr-rs-relay) via env var or config.
- **Big files leave the relay.** Files transfer via magic-wormhole (direct, NAT-traversing, streaming) instead of base64 over the message channel.
- **Skill UX preserved.** `/agent-wormhole` still uses word codes for first contact and Monitor for realtime delivery.
- **Operate no infrastructure.** No agent-wormhole-specific server to deploy or maintain. Public magic-wormhole mailbox + public Nostr relays cover the default install.

## Non-goals

- Federated discovery or "find me a peer." Trust is established by pairing or by manual `trust <pubkey>`.
- Public broadcast / Twitter-style timelines. Even though Nostr supports them, this project is point-to-point.
- Group chat. Future possibility; not in this rewrite.
- Key rotation, key backup/recovery. v1 keys are forever and tied to one machine; losing the key file means losing trust relationships and re-pairing.
- Cross-device identity sync.
- Reimplementing magic-wormhole or Nostr.

## Architecture

```
┌─────────────┐   one-time word-code pairing    ┌─────────────┐
│   Alice     │ ───────  (magic-wormhole) ─────▶│    Bob      │
│             │      exchange pubkeys + relays  │             │
│             │                                  │             │
│  identity   │                                  │  identity   │
│  trust list │                                  │  trust list │
│             │                                  │             │
│  listener ──┼──── NIP-17 DMs over Nostr ──────┼──▶ listener │
│             │     (text, file-offers)         │             │
│             │                                  │             │
│             │◀── magic-wormhole (file bytes) ─┼──           │
└─────────────┘                                  └─────────────┘
```

Three layers, each owned by an existing protocol:

- **Bootstrap** — magic-wormhole word-code pairing, used once per peer pair to exchange identity payloads. We write only the payload-exchange logic on top of the open channel (~50 LOC).
- **Steady-state messaging** — Nostr (NIP-44 ECDH + ChaCha20-Poly1305, wrapped in NIP-17 gift wrap), over any number of relays.
- **Bulk files** — magic-wormhole again, with the transfer code passed inside a Nostr DM.

## Components

| Module | Purpose |
|---|---|
| `identity.py` | Load or create secp256k1 keypair at `~/.agent-wormhole/identity.key` (mode 0600). Expose `my_pubkey()`, `sign()`, `decrypt_for_me()`. |
| `trust.py` | Read/write `~/.agent-wormhole/trusted_peers.json`. Map `{pubkey → {name, relays, added_at}}`. Lookups by pubkey or name. |
| `nostr.py` | Minimal Nostr client. Relay-pool websockets, REQ/EVENT framing, NIP-01 event signing, NIP-44 encryption, NIP-17 gift-wrap/unwrap. No NIP-04 (deprecated). |
| `pairing.py` | Wraps magic-wormhole's pairing API. Both sides open a wormhole with the shared word code, exchange one identity envelope each, then close. On success, both sides write the peer into their trust file. |
| `bulk.py` | Thin wrapper around magic-wormhole for file send/receive. Returns codes; consumes codes. |
| `listener.py` | Long-running subscribe loop. REQ for kind-1059 events tagged to my pubkey across all configured relays. Decrypt → trust-check → dispatch (text → stdout line, file-offer → bulk receive → stdout line). |
| `cli.py` | Typer commands (see CLI surface). |
| `fs.py` | Per-peer inbound files directory + outbox file under `/tmp/agent-wormhole/<peer>/`. Refactored from per-channel. |
| `config.py` | Resolve relay list and other settings from (in order): env vars, optional `~/.agent-wormhole/config.json`, code defaults. |

### Boundaries

- `identity.py` is the only module that reads the private key file.
- `nostr.py` is the only module that talks to Nostr relays directly.
- `trust.py` is the only module that mutates the trust file.
- `listener.py` is the only module that writes to stdout in the long-running process.
- `cli.py` orchestrates; it does not contain crypto, network, or trust logic.

## Filesystem layout

```
~/.agent-wormhole/
  identity.key              # secp256k1 priv key, mode 0600
  trusted_peers.json        # whitelist + metadata, mode 0600
  config.json               # optional; env vars and code defaults work without it

/tmp/agent-wormhole/
  <peer_name>/
    outbox                  # CLI writes here, listener consumes
    files/                  # inbound files land here (mode 0600)
```

`<peer_name>` is the friendly name from the trust file. If absent, the first 12 hex chars of the pubkey are used.

## CLI surface

| Command | Behavior |
|---|---|
| `agent-wormhole pair` | Host role: generate a magic-wormhole word code, print it, wait for peer, exchange identities, write trust file. |
| `agent-wormhole pair <code>` | Peer role: connect with the code, exchange identities, write trust file. |
| `agent-wormhole listen` | Long-running. Subscribe to NIP-17 DMs addressed to my pubkey across all configured relays. Emit one JSON line per delivered (trusted) event. Untrusted events are silently dropped. |
| `agent-wormhole send <peer> <msg>` | Resolve peer (name → pubkey via trust file). Sign and NIP-17 wrap the message. Publish EVENT to all configured relays. |
| `agent-wormhole send-file <peer> <path>` | Start a magic-wormhole sender, capture the code, send a `file-offer` DM to the peer with metadata + code + expiry. Hold the wormhole open until the peer connects or the timeout fires. |
| `agent-wormhole peers` | List trusted peers (name, short pubkey, last-seen if tracked). |
| `agent-wormhole whoami` | Print my pubkey (npub + hex), configured relays. |
| `agent-wormhole trust <pubkey> <name> [--relays ...]` | Manually add a peer (out-of-band introduction). |
| `agent-wormhole untrust <peer>` | Remove a peer from the trust file. |
| `agent-wormhole setup` | Unchanged — installs the skill. |

The existing single-channel `send` / `recv` commands are removed. The skill is updated accordingly.

## Data flow

### Pairing (once per peer)

1. Alice runs `agent-wormhole pair`. Allocates a magic-wormhole code (`4-foo-bar`), prints it.
2. Bob runs `agent-wormhole pair 4-foo-bar`. magic-wormhole's SPAKE2 handshake completes; both sides have a shared session key.
3. Each side sends a single envelope through the open wormhole: `{"type":"identity","pubkey":"<hex>","name":"<friendly>","relays":["wss://..."]}`.
4. Each side verifies the other's envelope, then writes the peer into its `trusted_peers.json`.
5. Wormhole closes. Pairing is complete.

The CLI prints the peer's name + short pubkey on success so the user can confirm out-of-band if desired.

### Text message (steady state)

1. `send alice "hello"` resolves `alice` → pubkey via trust file.
2. CLI constructs a NIP-17 gift-wrapped DM:
   - Rumor (unsigned): `{kind:14, pubkey: my_pub, content: "hello", created_at: now}`
   - Seal (kind 13): rumor encrypted to alice with NIP-44, signed by my real key.
   - Gift wrap (kind 1059): seal encrypted to alice with NIP-44, signed by an ephemeral key, tagged `["p", alice_pub]`.
3. CLI publishes the gift wrap as an EVENT to all configured relays. Returns once at least one relay ACKs.
4. Alice's `listen` process has an open REQ `{"kinds":[1059], "#p":[alice_pub]}` against all relays.
5. On EVENT arrival, listener: decrypts gift wrap → decrypts seal → reads sealed sender's real pubkey → looks up in trust file.
6. If trusted: emit `{"type":"text","from":"Bob","pubkey":"<short>","content":"hello","received_at":...}` JSON line to stdout. Monitor delivers to Claude.
7. If untrusted: silently drop.

### File transfer

1. `send-file alice ./report.pdf` invokes magic-wormhole sender, captures the code (e.g. `4-foo-bar`).
2. CLI sends a file-offer DM:
   ```json
   {"type":"file-offer","name":"report.pdf","size":12345,
    "sha256":"...","wormhole_code":"4-foo-bar","expires_in":300}
   ```
3. Sender process holds the wormhole open, waiting.
4. Alice's listener decrypts the file-offer (trusted sender, gated by trust check above).
5. Listener invokes magic-wormhole receiver with that code; bytes land at `<peer>/files/report.pdf`, mode 0600.
6. Listener emits `{"type":"file","from":"Bob","name":"report.pdf","saved_to":"...","size":12345,"sha256_verified":true}` JSON line.
7. If sender receives no connection within `expires_in` seconds, sender process exits cleanly and emits a `{"type":"warning","file_offer_expired":...}` line locally.

Sha256 is computed by sender and verified by receiver to catch transit corruption. Magic-wormhole already provides integrity, but verifying the offer-stated hash also ties the file we received to the file the sender announced.

## Relay configuration

Resolution order: env var → optional `config.json` → code defaults.

- **Code defaults.** 2-3 reputable public Nostr relays (e.g. `wss://relay.damus.io`, `wss://nos.lol`, `wss://relay.primal.net`). magic-wormhole uses its own public mailbox by default — nothing to configure for first-run.
- **Env var.** `AGENT_WORMHOLE_RELAYS=wss://my.relay,wss://other.relay` overrides the relay list. Comma-separated.
- **Config file (optional).** `~/.agent-wormhole/config.json`:
  ```json
  {"relays": ["wss://my-strfry.example.com"]}
  ```

There is no agent-wormhole-operated server. Self-hosters point `AGENT_WORMHOLE_RELAYS` at their own strfry / nostr-rs-relay; magic-wormhole self-hosters set its own env var (`WORMHOLE_RELAY_URL`).

## Skill UX

The `/agent-wormhole` skill is updated:

- **First contact:** the user invokes `/agent-wormhole` on both machines, words are exchanged, pairing completes. Skill text gains one line: *"Identity saved. You can talk to this peer again later without re-pairing — just run `agent-wormhole listen` and the other side can `send <name> <msg>` anytime."*
- **Returning peer:** the user invokes `/agent-wormhole` with a peer name already in the trust file. The skill skips the pairing dance entirely, starts `listen` if not already running, and tells Claude to use `send <name>` / `send-file <name>` for outgoing.
- **File send:** the skill instructs Claude to use `send-file` for any payload >100 KB or any non-text payload.

Monitor integration is unchanged. Listener emits one JSON line per delivered event, same shape as today.

## Error handling and edge cases

- **Untrusted sender.** Silent drop from stdout. Stderr gets a one-line debug breadcrumb.
- **Malformed event.** Logged to stderr; not raised to Claude.
- **All relays unreachable.** Listener retries each relay with exponential backoff (cap 60s). Emits `{"type":"warning","relay_status":[...]}` lines on state transitions so Claude can see degradation.
- **Partial relay failure.** Continue with whichever relays connect. Publish requires at least one ACK or the send returns an error.
- **Pairing collision on name.** If the trust file already has a peer with this name (different pubkey), prompt to overwrite or pick a new local alias. The pubkey is the truth; the name is local.
- **File offer expires before pickup.** Sender's magic-wormhole code times out (default 5 min). Receiver's late attempt fails fast; listener emits a warning line.
- **Identity file missing.** `listen`, `send`, `send-file` refuse to start with a clear error. `pair` and `whoami` auto-create on first run.
- **Identity file corrupt / wrong permissions.** Refuse to start. Print remediation instruction.
- **Clock skew.** Nostr events have `created_at`. Listener tolerates up to 5 minutes of skew; older or future-dated events are dropped with a stderr warning.

## Security model

- **Private key compromise** = full impersonation + decryption of past DMs. Same threat model as an SSH private key. Stored mode 0600, owner-checked. No backup or recovery — losing it means re-pairing every peer.
- **Trust file compromise** = attacker can add their own pubkey to your whitelist and start delivering messages to your Claude. Mode 0600, owner-checked.
- **Pairing MITM** = an active attacker who can both observe and modify magic-wormhole traffic during pairing could swap the exchanged pubkeys. Mitigation: pairing CLI prints the peer's short pubkey on success; users / Claude can confirm out-of-band before relying on the channel for anything sensitive. This is exactly magic-wormhole's own threat model.
- **Relay sees message content** = no. NIP-44 ciphertext only.
- **Relay sees sender identity** = no. NIP-17 gift wrap uses an ephemeral signing key for the outer event.
- **Relay sees *recipient* identity** = **yes.** Your listener's REQ filter `{"#p":[your_pubkey]}` necessarily reveals your pubkey to the relay, and the relay learns your IP when you connect. A persistent observer correlates your pubkey to your network presence across sessions. This is *worse* than today's design, where the relay only saw an ephemeral pair code. Mitigation: run your own relay (or point at one you trust). Use Tor if you need stronger anonymity — we don't ship that.
- **No forward secrecy for past DMs.** If your priv key is exfiltrated, previously-sent DMs to you that an attacker captured at the relay become decryptable. NIP-44 v2 does not provide FS. Acceptable for v1.

## Testing strategy

- **Unit tests**
  - NIP-44 encrypt/decrypt round-trip against canonical test vectors.
  - NIP-17 gift-wrap unwrap with a known-good payload.
  - Trust file load/save, including malformed input rejection.
  - Filename sanitization (reuse existing tests).
  - Identity key file: creation with correct perms, owner check, refusal on bad perms.
- **Integration tests**
  - Spin up an in-process Nostr relay fixture (subprocess `nostr-rs-relay` or a pure-Python test relay).
  - Two `agent-wormhole` processes: pair → trust files mutate correctly → send text → listener emits expected JSON line.
  - File transfer end-to-end through magic-wormhole (test mode against local rendezvous).
  - Untrusted sender: confirm zero stdout output.
  - Relay restart mid-listen: confirm reconnect with backoff and a `relay_status` warning.
- The existing wormhole pairing tests are deleted along with the homegrown wormhole code. Pairing is now tested end-to-end via magic-wormhole's test mailbox.

## Migration

This is a clean break, not a backwards-compatible evolution. Strategy:

- Old single-channel commands (`send` / `recv`) are removed. Anyone with an active old-style channel finishes that session, then upgrades.
- New release is a major version bump (0.2.0).
- README and skill text call out the new pairing model and the persistent identity directory.
- No automated migration: there's nothing in `/tmp/agent-wormhole/<code>` worth preserving across versions.

## What we keep, delete, add

**Keep (with light refactor):**
- `fs.py` — refactored from per-channel to per-peer.
- `cli.py` skeleton (Typer command shell).
- `skill/SKILL.md` UX shell, updated text.
- `pyproject.toml`, release workflow, packaging.

**Delete entirely:**
- `relay/` — no more agent-wormhole-operated rendezvous; magic-wormhole's public mailbox replaces it.
- `wordlist.py` — magic-wormhole provides the PGP-word list.
- `crypto.py` — Nostr handles steady-state crypto; magic-wormhole handles the bootstrap handshake.
- `transport.py` — both bootstrap and steady-state transports come from libraries now.
- `channel.py` — the homegrown channel/session abstraction goes away.
- `protocol.py` file-as-base64 path.

**Add:**
- `identity.py`, `trust.py`, `nostr.py`, `pairing.py` (magic-wormhole wrapper), `bulk.py`, `listener.py`, expanded `cli.py`, new tests.

**New dependencies:**
- `pynostr` (Nostr protocol library) — alternative: hand-roll ~300 LOC; pynostr pulls in `secp256k1` and `websockets` we'd want regardless.
- `magic-wormhole` — used for both bootstrap and bulk transfer. Pulls in Twisted + autobahn + spake2.

## Open questions for implementation

These are deferred to the plan/implementation phase; flagged here so they aren't lost:

- **pynostr vs hand-roll.** pynostr's NIP-17 / NIP-44 support level needs verification. If NIP-17 isn't supported, we either layer it ourselves (~50 LOC) or pick a different library.
- **magic-wormhole integration.** Library is Twisted-based. Use it directly (with Twisted ↔ asyncio bridge) or subprocess the `wormhole` CLI (simpler, fewer deps to wrangle, costs us a process per pairing/transfer). Default leaning subprocess.
- **Listener concurrency model.** asyncio is the obvious fit for Nostr's websocket-heavy I/O. Confirmed if magic-wormhole is subprocessed (no Twisted in our process).
