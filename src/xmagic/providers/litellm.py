"""LiteLLM provider adapter — long-tail escape hatch for 100+ providers.

Optional extra: ``xmagic-sdk[litellm]``. Model refs look like
``litellm:groq/llama-3.3-70b``. Full implementation lands in Phase 3.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from xmagic.providers.base import ChatMessage, Completion, CompletionChunk, Provider


class LiteLLMProvider(Provider):
    """Chat completions routed through LiteLLM."""

    name = "litellm"

    def __init__(self, api_key: str | None = None, **options: Any) -> None:
        super().__init__(api_key=api_key, **options)
        try:
            import litellm  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "LiteLLM support requires the extra: pip install 'xmagic-sdk[litellm]'"
            ) from e

    def complete(self, messages: list[ChatMessage], *, model: str, **params: Any) -> Completion:
        raise NotImplementedError("Phase 3 (see DESIGN.md)")

    def stream(
        self, messages: list[ChatMessage], *, model: str, **params: Any
    ) -> Iterator[CompletionChunk]:
        raise NotImplementedError("Phase 3 (see DESIGN.md)")
