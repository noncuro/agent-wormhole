"""Configuration for agent-wormhole."""
import os

DEFAULT_RELAY_URL = "wss://agent-wormhole-relay.up.railway.app"


def get_relay_url(override: str | None = None) -> str:
    """Return the relay URL, checking override -> env var -> default."""
    if override:
        return override
    return os.environ.get("AGENT_WORMHOLE_RELAY_URL", DEFAULT_RELAY_URL)
