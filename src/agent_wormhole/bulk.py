from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Awaitable, Callable


_CODE_RE = re.compile(r"[Ww]ormhole code is:\s*(\S+)")
_RECEIVE_CODE_RE = re.compile(r"^\d+-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+$")


def _validate_receive_code(code: str) -> None:
    if not isinstance(code, str) or _RECEIVE_CODE_RE.fullmatch(code) is None:
        raise ValueError(f"invalid wormhole code: {code!r}")


def is_wormhole_code(s: str) -> bool:
    """True if `s` is a syntactically valid magic-wormhole code (n-word-word…).

    Used by the skill's first-contact routing to recognize when a user has
    pasted a pairing code (→ join) rather than a peer name (→ listen/invite).
    """
    return isinstance(s, str) and _RECEIVE_CODE_RE.fullmatch(s) is not None


async def _send_scanning_for_code(
    args: list[str],
    *,
    on_code: Callable[[str], Awaitable[None]],
    stdin_text: str | None = None,
) -> None:
    """Run a `wormhole send …` subprocess. Call on_code(code) as soon as the
    rendezvous code is printed, then wait for the receiver to pick up. If the
    on_code callback raises, the subprocess is torn down before re-raising.

    Shared by send_file (path arg, no stdin) and send_text (--text -, stdin)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if stdin_text is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        if stdin_text is not None:
            proc.stdin.write(stdin_text.encode())
            await proc.stdin.drain()
            proc.stdin.close()

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
    except BaseException:
        await _terminate_process(proc)
        raise
    if rc != 0:
        raise RuntimeError(f"wormhole send exited {rc}")


async def _terminate_process(proc) -> None:
    if proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


async def send_file(
    *,
    path: Path,
    on_code: Callable[[str], Awaitable[None]],
) -> None:
    """Run `wormhole send <path>`. Calls on_code(code) as soon as the
    rendezvous code is printed, then waits for transfer to complete."""
    await _send_scanning_for_code(["wormhole", "send", str(path)], on_code=on_code)


async def receive_file(
    *,
    code: str,
    dest_dir: Path,
    accept: bool = True,
) -> Path:
    """Run `wormhole receive <code>` in dest_dir. Return path of received file."""
    _validate_receive_code(code)
    args = ["wormhole", "receive"]
    if accept:
        args.append("--accept-file")
    args.append("--")
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


async def send_text(
    text: str,
    *,
    on_code: Callable[[str], Awaitable[None]],
) -> None:
    """Run `wormhole send --text -`, feeding `text` on stdin. Calls on_code(code)
    as soon as the rendezvous code is printed, then waits for the receiver to
    pick up."""
    await _send_scanning_for_code(
        ["wormhole", "send", "--text", "-"], on_code=on_code, stdin_text=text,
    )


async def receive_text(code: str) -> str:
    """Run `wormhole receive -- <code>` and return the transferred message.

    magic-wormhole prints the received text to stdout and its progress chatter
    to stderr; we return the stdout line that parses as our JSON envelope, or
    the last non-empty stdout line if none parses."""
    _validate_receive_code(code)
    proc = await asyncio.create_subprocess_exec(
        "wormhole", "receive", "--", code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"wormhole receive failed: {err.decode(errors='replace')}")
    lines = [ln for ln in out.decode(errors="replace").splitlines() if ln.strip()]
    if not lines:
        raise RuntimeError("wormhole receive produced no text")
    for ln in lines:
        try:
            json.loads(ln)
            return ln
        except ValueError:
            continue
    return lines[-1]
