# CLAUDE.md

## Overview

agent-wormhole provides secure, encrypted ephemeral channels for AI agent instances to communicate. Think Magic Wormhole, but for Claude Code sessions talking to each other.

## Installation

The `agent-wormhole` CLI must be installed for the `/agent-wormhole` skill to work. On first use, check if it's available and install if not:

```bash
# Check
agent-wormhole --help

uv tool install agent-wormhole
agent-wormhole setup | claude
```

The second command pipes skill configuration directly into Claude Code, which sets up `~/.claude/skills/agent-wormhole/SKILL.md` as a symlink into the installed package so skill updates flow in when you upgrade `agent-wormhole`.

**For development (working in this repo)**: instead of the install-time symlink, point it at this repo so edits to `skill/SKILL.md` are live immediately:

```bash
mkdir -p ~/.claude/skills/agent-wormhole
ln -sf "$(pwd)/skill/SKILL.md" ~/.claude/skills/agent-wormhole/SKILL.md
```

If symlinks aren't supported (e.g. some Windows setups), copy the file instead.

## Development

Python 3.11+, built with Hatch.

```bash
uv sync                  # install deps
uv run pytest            # run tests
```

## Releasing to PyPI

Publishing is automated via `.github/workflows/publish.yml`. Trigger is a `v*` tag push; auth is PyPI Trusted Publishing (OIDC) through the `pypi` GitHub environment — no API token secret.

To cut a release:

```bash
# 1. bump version in pyproject.toml (e.g. 0.2.0 -> 0.2.1)
# 2. commit and push
git commit -am "chore: bump version to 0.2.1"
git push
# 3. tag and push the tag
git tag v0.2.1 && git push origin v0.2.1
```

The workflow verifies the tag matches `pyproject.toml` version before building, so keep them in sync. Published artifact: https://pypi.org/p/agent-wormhole.

## Project structure

- `src/agent_wormhole/` — core library
  - `identity.py` — secp256k1 keypair, Schnorr signing, ECDH
  - `trust.py` — trusted peers store
  - `config.py` — relay resolution
  - `fs.py` — per-peer outbox/files layout
  - `nostr/` — NIP-44 v2 crypto, NIP-01 events, NIP-17 gift-wrap, async relay pool
  - `bulk.py` — magic-wormhole subprocess for file transfer
  - `listener.py` — long-running asyncio listener; emits JSON lines for Monitor
  - `cli.py` — typer CLI
- `skill/` — Claude Code skill definition (symlinked into the package)
- `tests/` — pytest tests, plus an in-process FakeRelay fixture

## Notes

- The skill uses the **Monitor** tool (built-in since Claude Code v2.1.98). If Monitor is not available, update Claude Code (`claude update`). Monitor is required for real-time message delivery — there is no fallback path.
- The `wormhole` CLI must be on PATH for pairing and `send-file`/listener auto-receive. It ships as a console script of the `magic-wormhole` Python dep, so any uv-managed venv has it.
