from __future__ import annotations

import json
import os
import time
from pathlib import Path

# Entries older than this are pruned on save so the store stays small. Nostr
# relays don't retain forever, and the cold-start baseline re-marks anything
# still on a relay, so pruning can't resurrect an already-read message.
_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


class SeenStore:
    """Durable 'mark as read' set, keyed on stable message (rumor) ids.

    This is the source of truth for "have I already surfaced this message?".
    It's exact and time-independent: a message read once stays read across
    restarts and across every relay that replays it. `existed` records whether
    the file was already present at construction — the cold-start signal.

    path=None keeps everything in memory (used by tests / ephemeral runs) and
    reports existed=False, i.e. always a cold start.
    """

    def __init__(self, path: Path | None):
        self._path = Path(path) if path is not None else None
        self._ids: dict[str, int] = {}
        self.existed = bool(self._path and self._path.exists())
        if self.existed:
            self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            # A corrupt/unreadable store shouldn't wedge the listener; treat as
            # empty (worst case: one extra baseline pass).
            self._ids = {}
            return
        for entry in raw.get("seen", []):
            # entry: [id, created_at]
            if isinstance(entry, list) and len(entry) == 2:
                self._ids[entry[0]] = int(entry[1])

    def __contains__(self, msg_id: str) -> bool:
        return msg_id in self._ids

    def add(self, msg_id: str, created_at: int | None = None) -> None:
        self._ids[msg_id] = int(created_at if created_at is not None else time.time())
        self._save()

    def _save(self) -> None:
        if self._path is None:
            return
        cutoff = int(time.time()) - _MAX_AGE_SECONDS
        kept = {i: ts for i, ts in self._ids.items() if ts >= cutoff}
        self._ids = kept
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps({"seen": [[i, ts] for i, ts in kept.items()]}).encode())
        finally:
            os.close(fd)
        os.replace(tmp, self._path)
