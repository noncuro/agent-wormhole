from __future__ import annotations

import json
import time
from dataclasses import dataclass
from hashlib import sha256

from agent_wormhole.identity import Identity


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
