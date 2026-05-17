import typer

app = typer.Typer(name="agent-wormhole", help="Persistent identity + Nostr DMs for AI agents")


@app.command()
def setup():
    """Placeholder; real setup re-added in a later task."""
    raise NotImplementedError
