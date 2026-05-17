from __future__ import annotations

import os
from pathlib import Path

DEFAULT_BASE = Path("/tmp/agent-wormhole")


def sanitize_filename(name: str) -> str | None:
    if not name or name in (".", ".."):
        return None
    basename = os.path.basename(name)
    if basename != name or ".." in name:
        return None
    return basename


def init_peer_dir(peer: str, *, base: Path = DEFAULT_BASE) -> Path:
    """Create (or verify) the per-peer directory tree with secure permissions."""
    if base.exists():
        st = base.stat()
        if st.st_uid != os.getuid():
            raise PermissionError(f"{base} is owned by uid {st.st_uid}, not current user")
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    pdir = base / peer
    pdir.mkdir(mode=0o700, exist_ok=True)
    (pdir / "files").mkdir(mode=0o700, exist_ok=True)
    return pdir


def outbox_path(peer: str, *, base: Path = DEFAULT_BASE) -> Path:
    return base / peer / "outbox"


def inbox_files_dir(peer: str, *, base: Path = DEFAULT_BASE) -> Path:
    return base / peer / "files"


def safe_save_file(peer: str, name: str, data: bytes, *, base: Path = DEFAULT_BASE) -> Path:
    safe = sanitize_filename(name)
    if safe is None:
        raise ValueError(f"unsafe filename: {name!r}")
    target = inbox_files_dir(peer, base=base) / safe
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return target
