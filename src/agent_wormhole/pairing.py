"""Single-code first-contact pairing.

The inviter ships its identity envelope over **one** magic-wormhole code and
stays subscribed for a Nostr reply. The joiner receives that envelope over the
code, trusts the inviter, then sends its own envelope back **over Nostr**. A
one-time nonce — carried only inside the PAKE-protected wormhole payload —
binds the reply: only the holder of the code learns it, so a third party who
scrapes the inviter's pubkey from relay tags cannot complete pairing for their
own key. The inviter also checks that the authenticated sender pubkey matches
the pubkey claimed in the reply body.

This reuses the existing asyncio relay pool and gift-wrap crypto rather than
magic-wormhole's Twisted Python API, so the whole module stays async."""
from __future__ import annotations

import asyncio
import json
import re
import secrets
from typing import Awaitable, Callable

from agent_wormhole import bulk
from agent_wormhole.identity import Identity
from agent_wormhole.nostr.client import RelayPool
from agent_wormhole.nostr.events import build_giftwrapped_dm, unwrap_giftwrapped_dm
from agent_wormhole.trust import Peer, TrustStore

INVITE_TYPE = "pairing-invite"
ACCEPT_TYPE = "pairing-accept"
PROTOCOL_VERSION = 1

Emit = Callable[[dict], None]


def _slug(name: str) -> str:
    """Turn a hostname into a filesystem-safe, stable peer name.

    "macbook pro" -> "macbook-pro", "Mac.lan" -> "mac-lan". The original
    hostname is reported back to the agent so it can surface the name (and
    offer a rename) rather than coercing silently."""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name or "").strip("-").lower()
    return s or "peer"


async def invite(
    *,
    identity: Identity,
    trust: TrustStore,
    relays: list[str],
    on_code: Callable[[str], Awaitable[None]],
    emit: Emit,
    name: str | None = None,
    timeout: float = 120.0,
) -> bool:
    """Inviter side. Returns True on success, False on timeout.

    Subscribes for the reply *before* shipping the invite, so a fast joiner
    cannot race ahead of our subscription. `on_code` is awaited with the single
    wormhole code for the agent to read to the user; `emit` receives the
    terminal `paired` / `pairing-timeout` event as a dict."""
    nonce = secrets.token_hex(16)
    pool = RelayPool(relays)
    await pool.connect()
    sub = await pool.subscribe({"kinds": [1059], "#p": [identity.pubkey_hex]})
    try:
        invite_env = json.dumps({
            "type": INVITE_TYPE,
            "v": PROTOCOL_VERSION,
            "pubkey": identity.pubkey_hex,
            "name": _local_hostname(),
            "relays": relays,
            "nonce": nonce,
        })
        # Blocks until the joiner picks up the code; the accept arrives after.
        await bulk.send_text(invite_env, on_code=on_code)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                emit({"type": "pairing-timeout"})
                return False
            try:
                ev = await asyncio.wait_for(sub.next(), timeout=remaining)
            except asyncio.TimeoutError:
                emit({"type": "pairing-timeout"})
                return False
            accept = _decode_accept(ev, identity=identity, nonce=nonce)
            if accept is None:
                continue
            sender_pub, body = accept
            peer_name = name or _slug(body.get("name", ""))
            trust.add(Peer(
                pubkey=sender_pub,
                name=peer_name,
                relays=list(body.get("relays", [])),
            ))
            emit({
                "type": "paired",
                "peer": peer_name,
                "peer_hostname": body.get("name", ""),
                "pubkey": sender_pub[:12],
            })
            return True
    finally:
        await pool.unsubscribe(sub.sub_id)
        await pool.close()


async def join(
    *,
    identity: Identity,
    trust: TrustStore,
    relays: list[str],
    code: str,
    emit: Emit,
    name: str | None = None,
) -> bool:
    """Joiner side. Receive the invite over the wormhole code, trust the
    inviter, and reply with our own envelope over Nostr (echoing the nonce)."""
    text = await bulk.receive_text(code)
    invite_env = json.loads(text)
    if invite_env.get("type") != INVITE_TYPE:
        raise ValueError(f"not a pairing invite (type={invite_env.get('type')!r})")
    inviter_pub = invite_env["pubkey"]
    inviter_relays = list(invite_env.get("relays", []))
    nonce = invite_env["nonce"]

    peer_name = name or _slug(invite_env.get("name", ""))
    trust.add(Peer(pubkey=inviter_pub, name=peer_name, relays=inviter_relays))

    accept_env = json.dumps({
        "type": ACCEPT_TYPE,
        "v": PROTOCOL_VERSION,
        "pubkey": identity.pubkey_hex,
        "name": _local_hostname(),
        "relays": relays,
        "nonce": nonce,
    })
    wrap = build_giftwrapped_dm(
        sender=identity,
        recipient_pubkey_hex=inviter_pub,
        content=accept_env,
    )
    # Reply on the inviter's relays — that is where it is subscribed.
    pool = RelayPool(inviter_relays or relays)
    await pool.connect()
    try:
        acks = await pool.publish(wrap)
    finally:
        await pool.close()
    if not any(acks.values()):
        raise RuntimeError("no relay accepted the pairing reply")

    emit({
        "type": "paired",
        "peer": peer_name,
        "peer_hostname": invite_env.get("name", ""),
        "pubkey": inviter_pub[:12],
    })
    return True


def _decode_accept(ev, *, identity: Identity, nonce: str) -> tuple[str, dict] | None:
    """Return (authenticated_sender_pubkey, accept_body) if `ev` is a valid,
    nonce-matching pairing-accept addressed to us; else None."""
    try:
        sender_pub, content = unwrap_giftwrapped_dm(ev, recipient=identity)
    except Exception:
        return None
    try:
        body = json.loads(content)
    except ValueError:
        return None
    if body.get("type") != ACCEPT_TYPE:
        return None
    if body.get("nonce") != nonce:
        return None
    # The reply must claim the same key the gift-wrap authenticated.
    if body.get("pubkey") != sender_pub:
        return None
    return sender_pub, body


def _local_hostname() -> str:
    import socket

    return socket.gethostname()
