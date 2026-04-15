import asyncio

import typer

from agent_wormhole.channel import run_host, run_peer, send_to_outbox
from agent_wormhole.fs import cleanup_channel, DEFAULT_BASE

app = typer.Typer(name="agent-wormhole", help="Secure ephemeral channels for AI agent communication")


@app.command()
def host(port: int = typer.Option(0, help="Port to listen on (0 = random)")):
    """Host a new channel and wait for a peer to connect."""
    asyncio.run(run_host(port=port))


@app.command()
def connect(target: str = typer.Argument(help="<code>@<hostname> to connect to")):
    """Connect to an existing channel."""
    asyncio.run(run_peer(target))


@app.command()
def send(
    code: str = typer.Argument(help="Channel code"),
    message: str = typer.Argument(default=None, help="Text message to send"),
    file: str = typer.Option(None, "--file", help="Path to file to send"),
):
    """Send a message or file through a channel."""
    if message is None and file is None:
        typer.echo("Error: provide a message or --file", err=True)
        raise typer.Exit(1)
    send_to_outbox(code, message=message, file_path=file)


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
        outbox = base / ch / "outbox"
        has_outbox = outbox.exists()
        typer.echo(f"  {ch} {'(active)' if has_outbox else '(idle)'}")


@app.command()
def close(code: str = typer.Argument(help="Channel code to close")):
    """Close a channel and clean up all files."""
    cleanup_channel(code)
    typer.echo(f"Channel {code} closed and cleaned up")
