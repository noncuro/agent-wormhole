from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

DEFAULT_BASE = Path("/tmp/agent-wormhole")


def sanitize_filename(name: str) -> str | None:
    """Return the filename if safe, None if it contains path traversal."""
    if not name or name in (".", ".."):
        return None
    basename = os.path.basename(name)
    if basename != name or ".." in name:
        return None
    return basename


def init_channel_dir(code: str, *, base: Path = DEFAULT_BASE) -> Path:
    """Create the channel directory structure with secure permissions.

    Clears any stale outbox from a previous session.
    Verifies ownership of existing base directory.
    """
    if base.exists():
        stat = base.stat()
        if stat.st_uid != os.getuid():
            raise PermissionError(f"Base directory {base} is owned by uid {stat.st_uid}, not current user")
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    channel_dir = base / code
    channel_dir.mkdir(mode=0o700, exist_ok=True)
    (channel_dir / "files").mkdir(mode=0o700, exist_ok=True)
    (channel_dir / "messages").mkdir(mode=0o700, exist_ok=True)

    # Clear stale outbox
    outbox = channel_dir / "outbox"
    if outbox.exists():
        outbox.unlink()

    return channel_dir


def cleanup_channel(code: str, *, base: Path = DEFAULT_BASE) -> None:
    """Remove all files for a channel."""
    channel_dir = base / code
    if channel_dir.exists():
        shutil.rmtree(channel_dir)


def get_outbox_path(code: str, *, base: Path = DEFAULT_BASE) -> Path:
    """Get the outbox file path for a channel."""
    return base / code / "outbox"


def safe_save_file(code: str, name: str, data: bytes, *, base: Path = DEFAULT_BASE) -> Path:
    """Save a received file with sanitized name and secure permissions."""
    safe_name = sanitize_filename(name)
    if safe_name is None:
        raise ValueError(f"Invalid filename: {name!r}")

    path = base / code / "files" / safe_name
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


def safe_save_text(code: str, text: str, *, base: Path = DEFAULT_BASE) -> Path:
    """Save a large text message to a file with secure permissions."""
    timestamp = str(int(time.time() * 1000))
    path = base / code / "messages" / f"{timestamp}.txt"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, text.encode())
    finally:
        os.close(fd)
    return path
