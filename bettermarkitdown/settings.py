"""Choices made on the setup page, kept between runs. Never a key: keys live in
the password store (credentials.py).

Precedence everywhere: a command-line flag, then an environment variable, then
these settings, then the built-in default.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

AUDIENCES = ("human", "agent", "both")
HELP_LEVELS = ("assisted", "automatic")


@dataclass
class Settings:
    audience: str = ""        # human | agent | both
    help_level: str = ""      # assisted | automatic
    provider: str = ""        # a PROVIDERS id
    model: str = ""
    setup_done: bool = False


def config_dir() -> Path:
    """$BMID_CONFIG_DIR, else the platform's per-user settings folder."""
    override = os.environ.get("BMID_CONFIG_DIR", "").strip()
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home()) / "BetterMarkItDown"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "BetterMarkItDown"
    base = os.environ.get("XDG_CONFIG_HOME", "").strip() or str(Path.home() / ".config")
    return Path(base) / "bettermarkitdown"


def path() -> Path:
    return config_dir() / "settings.json"


def load() -> Settings:
    """The saved settings; defaults if there are none or the file is unreadable."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in data.items() if k in known})


def save(settings: Settings) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


def update(**changes) -> Settings:
    """Change some settings, checking each value, and save."""
    from .providers import PROVIDERS

    current = load()
    for name, value in changes.items():
        if name == "audience" and value not in AUDIENCES:
            raise ValueError(f"audience must be one of {', '.join(AUDIENCES)}")
        if name == "help_level" and value not in HELP_LEVELS:
            raise ValueError(f"help_level must be one of {', '.join(HELP_LEVELS)}")
        if name == "provider" and value not in PROVIDERS:
            raise ValueError(f"unknown provider '{value}'")
        if name == "model" and not isinstance(value, str):
            raise ValueError("model must be text")
        if name == "setup_done":
            value = bool(value)
        if name not in {f.name for f in fields(Settings)}:
            raise ValueError(f"unknown setting '{name}'")
        setattr(current, name, value)
    save(current)
    return current
