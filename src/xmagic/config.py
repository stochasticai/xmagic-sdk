"""Configuration handling.

Precedence: explicit kwargs > environment variables > config file > defaults.

Config file location: ``~/.config/xmagic/config.toml`` (override with
``XMAGIC_CONFIG_PATH``). Example::

    [xmagic]
    api_key = "xm-..."
    base_url = "https://api.xmagic.ai/xmagic-backend/v1"
    default_agent_id = "..."

    [providers.openai]
    api_key = "sk-..."
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_BASE_URL = "https://api.xmagic.ai/xmagic-backend/v1"
ENV_API_KEY = "XMAGIC_API_KEY"
ENV_BASE_URL = "XMAGIC_BASE_URL"
ENV_CONFIG_PATH = "XMAGIC_CONFIG_PATH"


def config_path() -> Path:
    """Return the config file path (respects XMAGIC_CONFIG_PATH)."""
    if override := os.environ.get(ENV_CONFIG_PATH):
        return Path(override).expanduser()
    return Path.home() / ".config" / "xmagic" / "config.toml"


def _load_file() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


class Settings(BaseModel):
    """Resolved SDK settings."""

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    default_agent_id: str | None = None
    timeout: float = Field(default=60.0, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Retries on 429/5xx")
    provider_keys: dict[str, str] = Field(
        default_factory=dict,
        description="Per-provider API keys, e.g. {'openai': 'sk-...'}",
    )

    @classmethod
    def load(cls, **overrides: Any) -> "Settings":
        """Build settings from file + env + explicit overrides."""
        data: dict[str, Any] = {}
        raw = _load_file()
        data.update(raw.get("xmagic", {}))
        data["provider_keys"] = {
            name: section["api_key"]
            for name, section in raw.get("providers", {}).items()
            if isinstance(section, dict) and "api_key" in section
        }
        if key := os.environ.get(ENV_API_KEY):
            data["api_key"] = key
        if url := os.environ.get(ENV_BASE_URL):
            data["base_url"] = url
        data.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**data)
