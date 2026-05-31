from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from hashlib import sha256

from coincurve import PrivateKey

from agent_wormhole.identity import Identity
from agent_wormhole.nostr.crypto import conversation_key, decrypt, encrypt


@dataclass
class Event:
    pubkey: str
    created_at: int
    kind: int
    tags: list[list[str]]
    content: str
    id: str = ""
    sig: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "pubkey": self.pubkey,
            "created_at": self.created_at,
            "kind": self.kind,
            "tags": self.tags,
            "content": self.content,
            "sig": self.sig,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(
            pubkey=d["pubkey"],
            created_at=d["created_at"],
            kind=d["kind"],
            tags=d.get("tags", []),
            content=d.get("content", ""),
            id=d.get("id", ""),
            sig=d.get("sig", ""),
        )


def serialize_for_id(*, pubkey: str, created_at: int, kind: int, tags: list, content: str) -> str:
    return json.dumps(
        [0, pubkey, created_at, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    )


def build_event(
    identity: Identity,
    *,
    kind: int,
    tags: list[list[str]],
    content: str,
    created_at: int | None = None,
) -> Event:
    if created_at is None:
        created_at = int(time.time())
    pubkey = identity.pubkey_hex
    serial = serialize_for_id(
        pubkey=pubkey, created_at=created_at, kind=kind, tags=tags, content=content
    )
    eid = sha256(serial.encode("utf-8")).digest()
    sig = identity.sign_schnorr(eid)
    return Event(
        pubkey=pubkey,
        created_at=created_at,
        kind=kind,
        tags=tags,
        content=content,
        id=eid.hex(),
        sig=sig.hex(),
    )


def verify_event(ev: Event) -> bool:
    serial = serialize_for_id(
        pubkey=ev.pubkey,
        created_at=ev.created_at,
        kind=ev.kind,
        tags=ev.tags,
        content=ev.content,
    )
    expected_id = sha256(serial.encode("utf-8")).hexdigest()
    if expected_id != ev.id:
        return False
    try:
        return Identity.verify_schnorr(
            bytes.fromhex(ev.id),
            bytes.fromhex(ev.sig),
            bytes.fromhex(ev.pubkey),
        )
    except Exception:
        return False


def _random_skewed_time(now: int | None = None) -> int:
    """created_at within the past 2 days, to obscure delivery timing."""
    if now is None:
        now = int(time.time())
    return now - random.randint(0, 2 * 24 * 60 * 60)


def build_giftwrapped_dm(
    *,
    sender: Identity,
    recipient_pubkey_hex: str,
    content: str,
    now: int | None = None,
) -> Event:
    if now is None:
        now = int(time.time())
    recipient_pubkey = bytes.fromhex(recipient_pubkey_hex)

    # 1. Rumor (kind 14, unsigned)
    rumor_dict = {
        "pubkey": sender.pubkey_hex,
        "created_at": now,
        "kind": 14,
        "tags": [["p", recipient_pubkey_hex]],
        "content": content,
    }
    rumor_serial = serialize_for_id(
        pubkey=sender.pubkey_hex,
        created_at=now,
        kind=14,
        tags=rumor_dict["tags"],
        content=content,
    )
    rumor_dict["id"] = sha256(rumor_serial.encode()).hexdigest()
    rumor_json = json.dumps(rumor_dict, separators=(",", ":"), ensure_ascii=False)

    # 2. Seal (kind 13): NIP-44 encrypt the rumor to recipient, sign with real sender key
    seal_ck = conversation_key(sender._priv.secret, recipient_pubkey)
    seal_content = encrypt(rumor_json, conversation_key=seal_ck)
    seal = build_event(
        sender,
        kind=13,
        tags=[],
        content=seal_content,
        created_at=_random_skewed_time(now),
    )

    # 3. Gift wrap (kind 1059): encrypt the seal JSON with an ephemeral keypair
    ephemeral = PrivateKey()
    ephem_identity = Identity(ephemeral)
    wrap_ck = conversation_key(ephemeral.secret, recipient_pubkey)
    wrap_content = encrypt(
        json.dumps(seal.to_dict(), separators=(",", ":"), ensure_ascii=False),
        conversation_key=wrap_ck,
    )
    wrap = build_event(
        ephem_identity,
        kind=1059,
        tags=[["p", recipient_pubkey_hex]],
        content=wrap_content,
        created_at=_random_skewed_time(now),
    )
    return wrap


def unwrap_giftwrapped_dm(wrap: Event, *, recipient: Identity) -> tuple[str, str]:
    """Return (sender_pubkey_hex, plaintext_content). Raises ValueError on failure."""
    if wrap.kind != 1059:
        raise ValueError(f"not a gift wrap (kind={wrap.kind})")
    if not verify_event(wrap):
        raise ValueError("wrap signature invalid")
    wrap_ck = conversation_key(recipient._priv.secret, bytes.fromhex(wrap.pubkey))
    seal_json = decrypt(wrap.content, conversation_key=wrap_ck)
    seal_dict = json.loads(seal_json)
    seal = Event.from_dict(seal_dict)
    if seal.kind != 13:
        raise ValueError(f"inner event is not a seal (kind={seal.kind})")
    if not verify_event(seal):
        raise ValueError("seal signature invalid")
    seal_ck = conversation_key(recipient._priv.secret, bytes.fromhex(seal.pubkey))
    rumor_json = decrypt(seal.content, conversation_key=seal_ck)
    rumor = json.loads(rumor_json)
    if rumor["pubkey"] != seal.pubkey:
        raise ValueError("rumor.pubkey != seal.pubkey — impersonation attempt")
    return seal.pubkey, rumor["content"]
