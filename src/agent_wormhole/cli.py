import asyncio
import os
from importlib.resources import files
from typing import Optional

import typer

from agent_wormhole.channel import run_host, run_peer, send_to_outbox
from agent_wormhole.fs import cleanup_channel, DEFAULT_BASE

app = typer.Typer(name="agent-wormhole", help="Secure ephemeral channels for AI agent communication")


@app.command()
def host(
    port: int = typer.Option(0, help="Port to listen on (0 = random, only used with --direct)"),
    direct: bool = typer.Option(False, "--direct", help="Use direct TCP mode instead of relay"),
    relay: Optional[str] = typer.Option(None, "--relay", help="Custom relay URL (overrides default)"),
):
    """Host a new channel and wait for a peer to connect."""
    asyncio.run(run_host(port=port, direct=direct, relay_url=relay))


@app.command()
def connect(
    target: str = typer.Argument(help="Channel code (relay) or <code>@<hostname> (direct)"),
    relay: Optional[str] = typer.Option(None, "--relay", help="Custom relay URL (overrides default)"),
):
    """Connect to an existing channel."""
    asyncio.run(run_peer(target, relay_url=relay))


@app.command()
def send(
    code: str = typer.Argument(help="Channel code"),
    message: str = typer.Argument(default=None, help="Text message to send"),
    file: str = typer.Option(None, "--file", help="Path to file to send"),
    role: str = typer.Option(None, "--role", help="Role (host/peer). Auto-detected if only one is present."),
):
    """Send a message or file through a channel."""
    if message is None and file is None:
        typer.echo("Error: provide a message or --file", err=True)
        raise typer.Exit(1)
    send_to_outbox(code, message=message, file_path=file, role=role)


@app.command()
def status():
    """Show active channels."""
    base = DEFAULT_BASE
    if not base.exists():
        typer.echo("No active channels")
        return
    channels = [d.name for d in base.iterdir() if d.is_dir()]
    if not channels:
        typer.echo("No active channels")
        return
    for ch in channels:
        has_host = (base / ch / "outbox-host").exists()
        has_peer = (base / ch / "outbox-peer").exists()
        roles = []
        if has_host:
            roles.append("host")
        if has_peer:
            roles.append("peer")
        status_str = f"({', '.join(roles)})" if roles else "(idle)"
        typer.echo(f"  {ch} {status_str}")


@app.command()
def close(code: str = typer.Argument(help="Channel code to close")):
    """Close a channel and clean up all files."""
    cleanup_channel(code)
    typer.echo(f"Channel {code} closed and cleaned up")


@app.command()
def setup():
    """Set up the Claude Code skill for agent-wormhole."""
    import sys
    in_claude = os.environ.get("CLAUDE_CODE") == "1"
    is_piped = not sys.stdout.isatty()

    if not in_claude and not is_piped:
        typer.echo("This command should be run inside Claude Code, or pipe it directly:")
        typer.echo()
        typer.echo("  agent-wormhole setup | claude")
        raise typer.Exit(0)

    # Inside Claude Code or piped to claude — print the skill content for Claude to save
    source = files("agent_wormhole").joinpath("SKILL.md")
    content = source.read_text()
    typer.echo("Save the following content to ~/.claude/skills/agent-wormhole/SKILL.md")
    typer.echo()
    typer.echo(content)
