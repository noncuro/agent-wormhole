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

## Project structure

- `src/agent_wormhole/` — core library (CLI, crypto, channel logic)
- `skill/` — Claude Code skill definition
- `tests/` — pytest tests

## Notes

- The skill uses the **Monitor** tool (built-in since Claude Code v2.1.98). If Monitor is not available, update Claude Code (`claude update`). Monitor is required for real-time message delivery — there is no fallback path.
