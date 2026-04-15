import typer

app = typer.Typer(name="agent-wormhole", help="Secure ephemeral channels for AI agent communication")


@app.command()
def host(port: int = typer.Option(0, help="Port to listen on (0 = random)")):
    """Host a new channel and wait for a peer to connect."""
    typer.echo("Not implemented yet")


@app.command()
def connect(target: str = typer.Argument(help="<code>@<hostname> to connect to")):
    """Connect to an existing channel."""
    typer.echo("Not implemented yet")


@app.command()
def send(code: str = typer.Argument(help="Channel code"), message: str = typer.Argument(default=None, help="Text message"), file: str = typer.Option(None, "--file", help="Path to file to send")):
    """Send a message or file through a channel."""
    typer.echo("Not implemented yet")


@app.command()
def status():
    """Show active channels."""
    typer.echo("Not implemented yet")


@app.command()
def close(code: str = typer.Argument(help="Channel code to close")):
    """Close a channel and clean up."""
    typer.echo("Not implemented yet")
