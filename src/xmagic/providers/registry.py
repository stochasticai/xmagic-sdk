"""Provider registry and ``provider:model`` resolution.

Built-in providers are registered lazily; third parties can add adapters via
the ``xmagic.providers`` entry-point group (see pyproject.toml).
"""

from __future__ import annotations

from importlib import import_module, metadata
from typing import Any

from xmagic.config import Settings
from xmagic.errors import ConfigurationError
from xmagic.providers.base import ModelRef, Provider

_BUILTINS: dict[str, tuple[str, str]] = {
    "xmagic": ("xmagic.providers.xmagic", "XMagicProvider"),
    "openai": ("xmagic.providers.openai", "OpenAIProvider"),
    "anthropic": ("xmagic.providers.anthropic", "AnthropicProvider"),
    "google": ("xmagic.providers.google", "GoogleProvider"),
    "litellm": ("xmagic.providers.litellm", "LiteLLMProvider"),
}

_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
}


def _load_class(name: str) -> type[Provider]:
    if name in _BUILTINS:
        module_name, cls_name = _BUILTINS[name]
        return getattr(import_module(module_name), cls_name)
    for ep in metadata.entry_points(group="xmagic.providers"):
        if ep.name == name:
            return ep.load()
    raise ConfigurationError(
        f"Unknown provider '{name}'. Built-ins: {', '.join(sorted(_BUILTINS))}."
    )


def get_provider(ref: str | ModelRef, settings: Settings | None = None, **options: Any) -> Provider:
    """Resolve ``provider:model`` (or a ModelRef) to a configured Provider.

    API key resolution: explicit option > env var > config file
    (``[providers.<name>] api_key``).
    """
    import os

    model_ref = ModelRef.parse(ref) if isinstance(ref, str) else ref
    settings = settings or Settings.load()
    cls = _load_class(model_ref.provider)
    api_key = (
        options.pop("api_key", None)
        or os.environ.get(_ENV_KEYS.get(model_ref.provider, ""), None)
        or settings.provider_keys.get(model_ref.provider)
        or (settings.api_key if model_ref.provider == "xmagic" else None)
    )
    provider = cls(api_key=api_key, settings=settings, **options)
    provider.default_model = model_ref.model  # type: ignore[attr-defined]
    return provider
