"""OpenAI provider adapter — a reserved extension point, not working code.

OpenAI is reachable today as ``litellm:openai/<model>``, so this adapter exists
to keep a native path open (vendor-specific params, no LiteLLM dependency) if it
is ever wanted, not because anything needs it. There is deliberately no
``[openai]`` extra: the SDK it would install is unused until the adapter is
implemented. Phase 3, see DESIGN.md roadmap.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from xmagic.providers.base import ChatMessage, Completion, CompletionChunk, Provider

# Said the same way whether or not the vendor SDK happens to be installed. That
# matters most here: LiteLLM depends on `openai`, so installing the [litellm]
# extra makes the import below succeed and routes users to the second error.
_UNIMPLEMENTED = (
    "OpenAIProvider is a reserved extension point and is not implemented (Phase 3). "
    "Use `litellm:openai/<model>` instead."
)


class OpenAIProvider(Provider):
    """Chat completions via the official ``openai`` SDK."""

    name = "openai"

    def __init__(self, api_key: str | None = None, **options: Any) -> None:
        super().__init__(api_key=api_key, **options)
        try:
            import openai  # noqa: F401
        except ImportError as e:
            raise ImportError(
                f"{_UNIMPLEMENTED} If you are implementing this adapter, `pip install openai`."
            ) from e

    def complete(self, messages: list[ChatMessage], *, model: str, **params: Any) -> Completion:
        raise NotImplementedError(_UNIMPLEMENTED)

    def stream(
        self, messages: list[ChatMessage], *, model: str, **params: Any
    ) -> Iterator[CompletionChunk]:
        raise NotImplementedError(_UNIMPLEMENTED)
