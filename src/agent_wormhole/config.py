from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
]

DEFAULT_HOME = Path.home() / ".agent-wormhole"


def resolve_relays(config_path: Path | None = None) -> list[str]:
    env = os.environ.get("AGENT_WORMHOLE_RELAYS")
    if env:
        return [r.strip() for r in env.split(",") if r.strip()]
    if config_path is None:
        config_path = DEFAULT_HOME / "config.json"
    if config_path.exists():
        data = json.loads(Path(config_path).read_text())
        if "relays" in data:
            return list(data["relays"])
    return list(DEFAULT_RELAYS)
