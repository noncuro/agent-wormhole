import secrets
from pathlib import Path


_WORDS_FILE = Path(__file__).parent / "words.txt"
WORDS = _WORDS_FILE.read_text().strip().splitlines()
assert len(WORDS) == 256, f"Expected 256 words, got {len(WORDS)}"


def generate_code(port: int) -> str:
    """Generate a direct-mode channel code like '9471-alpha-bravo-charlie'.

    Port must be provided (the actual bound port from the server).
    """
    w1 = secrets.choice(WORDS)
    w2 = secrets.choice(WORDS)
    w3 = secrets.choice(WORDS)
    return f"{port}-{w1}-{w2}-{w3}"


def generate_relay_code() -> str:
    """Generate a relay-mode channel code like 'alpha-bravo-charlie'.

    No port prefix -- the relay handles routing.
    """
    w1 = secrets.choice(WORDS)
    w2 = secrets.choice(WORDS)
    w3 = secrets.choice(WORDS)
    return f"{w1}-{w2}-{w3}"


def parse_code(target: str) -> tuple[int | None, str, str | None]:
    """Parse a channel code in either format.

    Direct mode: '<port>-<w1>-<w2>-<w3>[@<hostname>]'
    Relay mode:  '<w1>-<w2>-<w3>'

    Returns (port_or_None, code_without_host, hostname_or_None).
    If first segment is numeric, it's direct mode. Otherwise relay mode.
    """
    hostname = None
    if "@" in target:
        code_part, hostname = target.rsplit("@", 1)
    else:
        code_part = target

    parts = code_part.split("-")

    # Direct mode: first part is numeric port
    if parts[0].isdigit():
        if len(parts) != 4:
            raise ValueError(
                f"Invalid direct-mode code: expected <port>-<word>-<word>-<word>, got '{code_part}'"
            )
        port = int(parts[0])
        return port, code_part, hostname

    # Relay mode: 3 words, no port
    if len(parts) != 3:
        raise ValueError(
            f"Invalid relay-mode code: expected <word>-<word>-<word>, got '{code_part}'"
        )
    return None, code_part, hostname
