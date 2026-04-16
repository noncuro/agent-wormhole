# TODO

## Claude Code Plugin Support

The repo could be structured as a native Claude Code plugin, enabling auto-discovery
of the skill without a manual `setup` step.

### What's needed

1. Rename `skill/` to `skills/agent-wormhole/` (plural, with subdirectory)
2. Optionally add `.claude-plugin/plugin.json` for metadata:
   ```json
   {
     "name": "agent-wormhole",
     "description": "Secure ephemeral channels for AI agent communication",
     "version": "0.1.0"
   }
   ```
3. Optionally add a `marketplace.json` at repo root so the repo acts as its own marketplace

### Install flow for users

```
# In Claude Code:
/plugin marketplace add noncuro/agent-wormhole
/plugin install agent-wormhole
```

This auto-discovers the skill — no `pip install` needed for the skill itself.
Users still need `pip install agent-wormhole` for the CLI binary.

### What plugins can provide

- Skills (what we need)
- Agents (specialized subagents)
- Hooks (event handlers)
- MCP servers
- Executables (scripts added to PATH)

### Considerations

- Plugin system is relatively new — the `setup` command is a good fallback
- Renaming `skill/` → `skills/agent-wormhole/` is a breaking change for anyone
  who symlinked the old path
- Could support both: plugin structure for discovery + `setup` command for manual install
