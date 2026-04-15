import secrets
from pathlib import Path


_WORDS_FILE = Path(__file__).parent / "words.txt"
WORDS = _WORDS_FILE.read_text().strip().splitlines()
assert len(WORDS) == 256, f"Expected 256 words, got {len(WORDS)}"


def generate_code(port: int) -> str:
    """Generate a channel code like '9471-alpha-bravo-charlie'.

    Port must be provided (the actual bound port from the server).
    """
    w1 = secrets.choice(WORDS)
    w2 = secrets.choice(WORDS)
    w3 = secrets.choice(WORDS)
    return f"{port}-{w1}-{w2}-{w3}"


def parse_code(target: str) -> tuple[int, str, str | None]:
    """Parse '<port>-<w1>-<w2>-<w3>[@<hostname>]'.

    Returns (port, full_code_without_host, hostname_or_None).
    """
    hostname = None
    if "@" in target:
        code_part, hostname = target.rsplit("@", 1)
    else:
        code_part = target

    parts = code_part.split("-")
    if len(parts) != 4:
        raise ValueError(f"Invalid channel code: expected <port>-<word>-<word>-<word>, got '{code_part}'")

    try:
        port = int(parts[0])
    except ValueError:
        raise ValueError(f"Invalid port in channel code: '{parts[0]}'")

    return port, code_part, hostname
