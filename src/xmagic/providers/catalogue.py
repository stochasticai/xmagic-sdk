"""What models are reachable, read off LiteLLM's catalogue.

**This lists what LiteLLM can reach, not what xMagic offers.** xMagic documents
no model selection at all — `model` in a `xmagic:` ref is an agent id, no
endpoint takes a model parameter, and none lists models (DESIGN.md §10.6). So
this answers "what can I put after `-m`", and on the xMagic side the answer is
"an agent id", which is not something to enumerate here.

The data is LiteLLM's own metadata, which is why nothing here is hand-maintained
and why it can be wrong: it trails the provider list, and roughly a third of the
chat models carry no capability flags at all. Those read as unknown rather than
as unsupported — the two are different, and collapsing them would quietly
mislabel every model LiteLLM has not annotated yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# LiteLLM ships a documentation placeholder in the same mapping as real models.
_PLACEHOLDER_KEYS = frozenset({"sample_spec"})


@dataclass(frozen=True)
class ModelInfo:
    """One model, as LiteLLM describes it.

    ``ref`` is the whole point: it is directly usable as ``xmagic chat -m <ref>``
    or ``get_provider(<ref>)``, so nothing has to be reassembled by hand.
    """

    ref: str
    name: str
    provider: str
    mode: str
    context_window: int | None = None
    input_cost_per_1m: float | None = None
    output_cost_per_1m: float | None = None
    tools: bool | None = None
    """None means LiteLLM has no flag for this model — unknown, not unsupported."""
    vision: bool | None = None


def _import_litellm() -> Any:
    try:
        import litellm
    except ImportError as e:
        raise ImportError(
            "Model listing requires the extra: pip install 'xmagic-sdk[litellm]'"
        ) from e
    return litellm


def _ref(provider: str, name: str) -> str:
    """Build a ref this SDK can parse back.

    LiteLLM's keys are inconsistent about the provider prefix -- ``groq/gemma-7b-it``
    carries one, ``claude-3-opus-20240229`` does not -- so strip it before adding
    it back, rather than emitting ``litellm:groq/groq/gemma-7b-it``.
    """
    return f"litellm:{provider}/{name.removeprefix(f'{provider}/')}"


def _cost_per_1m(spec: dict[str, Any], key: str) -> float | None:
    value = spec.get(key)
    return float(value) * 1_000_000 if isinstance(value, int | float) else None


def _flag(spec: dict[str, Any], key: str) -> bool | None:
    value = spec.get(key)
    return value if isinstance(value, bool) else None


def _int(spec: dict[str, Any], key: str) -> int | None:
    value = spec.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def list_models(
    *,
    provider: str | None = None,
    search: str | None = None,
    mode: str | None = "chat",
) -> list[ModelInfo]:
    """Models LiteLLM knows about, filtered and sorted by ref.

    ``mode`` defaults to ``"chat"`` because that is the only thing the `Provider`
    interface does: LiteLLM's catalogue also carries embedding, image, and audio
    models, and listing them next to chat models would advertise something
    ``complete`` and ``stream`` cannot do. Pass ``mode=None`` for everything.
    """
    litellm = _import_litellm()
    catalogue: dict[str, Any] = litellm.model_cost
    needle = search.lower() if search else None

    found: list[ModelInfo] = []
    for name, spec in catalogue.items():
        if name in _PLACEHOLDER_KEYS or not isinstance(spec, dict):
            continue
        model_provider = spec.get("litellm_provider")
        model_mode = spec.get("mode")
        if not isinstance(model_provider, str) or not isinstance(model_mode, str):
            continue
        if mode is not None and model_mode != mode:
            continue
        if provider is not None and model_provider != provider:
            continue
        ref = _ref(model_provider, name)
        if needle is not None and needle not in ref.lower():
            continue
        found.append(
            ModelInfo(
                ref=ref,
                name=name,
                provider=model_provider,
                mode=model_mode,
                context_window=_int(spec, "max_input_tokens"),
                input_cost_per_1m=_cost_per_1m(spec, "input_cost_per_token"),
                output_cost_per_1m=_cost_per_1m(spec, "output_cost_per_token"),
                tools=_flag(spec, "supports_function_calling"),
                vision=_flag(spec, "supports_vision"),
            )
        )
    return sorted(found, key=lambda m: m.ref)


def list_providers(*, mode: str | None = "chat") -> list[tuple[str, int]]:
    """Providers with at least one model, and how many, most models first."""
    counts: dict[str, int] = {}
    for model in list_models(mode=mode):
        counts[model.provider] = counts.get(model.provider, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))
