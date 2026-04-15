# CLAUDE.md

## Overview

agent-wormhole provides secure, encrypted ephemeral channels for AI agent instances to communicate. Think Magic Wormhole, but for Claude Code sessions talking to each other.

## Installation

The `agent-wormhole` CLI must be installed for the `/agent-wormhole` skill to work. On first use, check if it's available and install if not:

```bash
# Check
agent-wormhole --help

# Install (pick one)
pip install git+https://github.com/noncuro/agent-wormhole.git
uv tool install git+https://github.com/noncuro/agent-wormhole.git
```

The skill file at `skill/SKILL.md` should be symlinked or copied into `~/.claude/skills/agent-wormhole/SKILL.md` so Claude Code sessions can use `/agent-wormhole`.

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
