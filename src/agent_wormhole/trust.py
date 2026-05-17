from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Peer:
    pubkey: str          # 64-char hex (x-only)
    name: str
    relays: list[str] = field(default_factory=list)
    added_at: int = field(default_factory=lambda: int(time.time()))


class TrustStore:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._peers: dict[str, Peer] = {}
        if self._path.exists():
            self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"trust file {self._path} is malformed: {e}")
        for entry in raw.get("peers", []):
            p = Peer(**entry)
            self._peers[p.pubkey] = p

    def _save(self) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps(
                {"peers": [asdict(p) for p in self._peers.values()]},
                indent=2,
            ).encode())
        finally:
            os.close(fd)
        os.replace(tmp, self._path)

    def add(self, peer: Peer) -> None:
        if any(p.name == peer.name for p in self._peers.values() if p.pubkey != peer.pubkey):
            raise ValueError(f"a different peer is already named {peer.name!r}")
        self._peers[peer.pubkey] = peer
        self._save()

    def remove(self, name_or_pubkey: str) -> None:
        target = self.by_name(name_or_pubkey) or self.by_pubkey(name_or_pubkey)
        if target is None:
            return
        del self._peers[target.pubkey]
        self._save()

    def by_name(self, name: str) -> Peer | None:
        for p in self._peers.values():
            if p.name == name:
                return p
        return None

    def by_pubkey(self, pubkey: str) -> Peer | None:
        return self._peers.get(pubkey)

    def all(self) -> list[Peer]:
        return list(self._peers.values())
