from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Awaitable, Callable


_CODE_RE = re.compile(r"[Ww]ormhole code is:\s*(\S+)")


async def send_file(
    *,
    path: Path,
    on_code: Callable[[str], Awaitable[None]],
) -> None:
    """Run `wormhole send <path>`. Calls on_code(code) as soon as the
    rendezvous code is printed, then waits for transfer to complete."""
    proc = await asyncio.create_subprocess_exec(
        "wormhole", "send", str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    code_seen = False
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        if not code_seen:
            m = _CODE_RE.search(line.decode(errors="replace"))
            if m:
                code_seen = True
                await on_code(m.group(1))
    rc = await proc.wait()
    if rc != 0:
        raise RuntimeError(f"wormhole send exited {rc}")


async def receive_file(
    *,
    code: str,
    dest_dir: Path,
    accept: bool = True,
) -> Path:
    """Run `wormhole receive <code>` in dest_dir. Return path of received file."""
    args = ["wormhole", "receive"]
    if accept:
        args.append("--accept-file")
    args.append(code)
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(dest_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"wormhole receive failed: {err.decode(errors='replace')}")
    files = sorted(dest_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("wormhole receive did not produce a file")
    return files[0]
