from __future__ import annotations

import asyncio
import importlib.resources as importlib_resources
import json
import os
import socket
import sys
from pathlib import Path

import typer

from agent_wormhole.config import DEFAULT_HOME, resolve_relays
from agent_wormhole.identity import load_or_create
from agent_wormhole.listener import Listener
from agent_wormhole.trust import Peer, TrustStore

app = typer.Typer(name="agent-wormhole", help="Persistent identity + Nostr DMs for AI agents")


def _home() -> Path:
    return Path(os.environ.get("AGENT_WORMHOLE_HOME") or DEFAULT_HOME)


def _identity_path() -> Path:
    return _home() / "identity.key"


def _trust_path() -> Path:
    return _home() / "trusted_peers.json"


def _config_path() -> Path:
    return _home() / "config.json"


def _local_name() -> str:
    return socket.gethostname()


@app.command()
def whoami():
    """Print this machine's pubkey and configured relays."""
    ident = load_or_create(_identity_path())
    relays = resolve_relays(config_path=_config_path())
    typer.echo(f"pubkey: {ident.pubkey_hex}")
    typer.echo(f"relays: {', '.join(relays) if relays else '(none)'}")


@app.command("identity-envelope")
def identity_envelope():
    """Print this machine's identity envelope as one JSON line.

    The /agent-wormhole skill pipes this through `wormhole send --text`
    during pairing:
        wormhole send --text "$(agent-wormhole identity-envelope)"
    """
    ident = load_or_create(_identity_path())
    relays = resolve_relays(config_path=_config_path())
    payload = {
        "type": "identity",
        "pubkey": ident.pubkey_hex,
        "name": _local_name(),
        "relays": relays,
    }
    typer.echo(json.dumps(payload))


@app.command()
def listen():
    """Long-running. Subscribe to inbound DMs; emit JSON lines for Monitor."""
    ident = load_or_create(_identity_path())
    trust = TrustStore(_trust_path())
    relays = resolve_relays(config_path=_config_path())

    async def _run():
        listener = Listener(identity=ident, trust=trust, relays=relays)
        await listener.start()
        try:
            await asyncio.Event().wait()
        finally:
            await listener.stop()

    asyncio.run(_run())


@app.command()
def setup():
    """Set up the Claude Code skill for agent-wormhole."""
    in_claude = os.environ.get("CLAUDE_CODE") == "1"
    is_piped = not sys.stdout.isatty()
    if not in_claude and not is_piped:
        typer.echo("Run inside Claude Code, or pipe: agent-wormhole setup | claude")
        raise typer.Exit(0)
    source = importlib_resources.files("agent_wormhole").joinpath("SKILL.md")
    with importlib_resources.as_file(source) as skill_path:
        skill_path_str = str(skill_path)
    skill_dir = "~/.claude/skills/agent-wormhole"
    skill_dest = f"{skill_dir}/SKILL.md"
    typer.echo("Please run these shell commands:")
    typer.echo(f"  mkdir -p {skill_dir}")
    typer.echo(f"  ln -sf {skill_path_str} {skill_dest}")


@app.command()
def send(
    peer: str = typer.Argument(help="Peer name (from trust list)"),
    message: str = typer.Argument(help="Text message"),
):
    """Send an encrypted text DM."""
    from agent_wormhole.nostr.client import RelayPool
    from agent_wormhole.nostr.events import build_giftwrapped_dm

    ident = load_or_create(_identity_path())
    trust = TrustStore(_trust_path())
    target = trust.by_name(peer) or trust.by_pubkey(peer)
    if target is None:
        typer.echo(f"unknown peer: {peer}", err=True)
        raise typer.Exit(1)

    relays = target.relays or resolve_relays(config_path=_config_path())

    async def _send():
        pool = RelayPool(relays)
        await pool.connect()
        wrap = build_giftwrapped_dm(
            sender=ident,
            recipient_pubkey_hex=target.pubkey,
            content=message,
        )
        acks = await pool.publish(wrap)
        await pool.close()
        if not any(acks.values()):
            typer.echo("no relay accepted the message", err=True)
            raise typer.Exit(2)
        typer.echo(f"sent to {target.name} via {sum(acks.values())}/{len(acks)} relays")

    asyncio.run(_send())


@app.command("send-file")
def send_file_cmd(
    peer: str = typer.Argument(help="Peer name (from trust list)"),
    path: Path = typer.Argument(help="File to send"),
):
    """Negotiate a magic-wormhole code with the peer over Nostr, transfer the file."""
    import hashlib
    from agent_wormhole.bulk import send_file as bulk_send_file
    from agent_wormhole.nostr.client import RelayPool
    from agent_wormhole.nostr.events import build_giftwrapped_dm
    from agent_wormhole.listener import FILE_OFFER_MARKER

    if not path.exists():
        typer.echo(f"no such file: {path}", err=True)
        raise typer.Exit(1)

    ident = load_or_create(_identity_path())
    trust = TrustStore(_trust_path())
    target = trust.by_name(peer) or trust.by_pubkey(peer)
    if target is None:
        typer.echo(f"unknown peer: {peer}", err=True)
        raise typer.Exit(1)
    relays = target.relays or resolve_relays(config_path=_config_path())

    h = hashlib.sha256(path.read_bytes()).hexdigest()
    size = path.stat().st_size

    async def _run():
        pool = RelayPool(relays)
        await pool.connect()

        async def on_code(code: str) -> None:
            offer = {
                "type": "file-offer",
                "name": path.name,
                "size": size,
                "sha256": h,
                "wormhole_code": code,
                "expires_in": 300,
            }
            wrap = build_giftwrapped_dm(
                sender=ident,
                recipient_pubkey_hex=target.pubkey,
                content=FILE_OFFER_MARKER + json.dumps(offer),
            )
            acks = await pool.publish(wrap)
            if not any(acks.values()):
                typer.echo("no relay accepted the file offer", err=True)
                raise typer.Exit(2)
            typer.echo(
                f"offered {path.name} to {target.name} "
                f"via {sum(acks.values())}/{len(acks)} relays; waiting for pickup…"
            )

        try:
            await bulk_send_file(path=path, on_code=on_code)
        finally:
            await pool.close()
        typer.echo("done")

    asyncio.run(_run())


@app.command()
def peers():
    """List trusted peers."""
    trust = TrustStore(_trust_path())
    rows = trust.all()
    if not rows:
        typer.echo("(no trusted peers — pair via the /agent-wormhole skill)")
        return
    for p in rows:
        relays_label = ",".join(p.relays) or "(default)"
        typer.echo(f"  {p.name:20s} {p.pubkey[:12]}…  relays={relays_label}")


@app.command()
def trust(
    pubkey: str = typer.Argument(help="64-char hex pubkey"),
    name: str = typer.Argument(help="Friendly name (must be unique locally)"),
    relays: str = typer.Option("", "--relays", help="Comma-separated relay URLs"),
):
    """Manually add a peer (out-of-band introduction)."""
    if len(pubkey) != 64:
        typer.echo("pubkey must be 64 hex chars (x-only)", err=True)
        raise typer.Exit(1)
    store = TrustStore(_trust_path())
    store.add(Peer(pubkey=pubkey, name=name, relays=[r for r in relays.split(",") if r]))
    typer.echo(f"added {name} ({pubkey[:12]}…)")


@app.command()
def untrust(name_or_pubkey: str = typer.Argument(help="Peer name or full pubkey")):
    """Remove a peer from the trust file."""
    store = TrustStore(_trust_path())
    store.remove(name_or_pubkey)
    typer.echo(f"removed {name_or_pubkey}")
