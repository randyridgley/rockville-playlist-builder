import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

CACHE_DIR = Path(os.environ.get("PLAYLIST_BUILDER_CACHE", Path.home() / ".cache" / "playlist-builder"))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")


class ConfigError(RuntimeError):
    pass


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"{name} is not set. Add it to .env (see .env.example).")
    return value


def optional(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or default
