"""Google (Gemini) provider adapter (optional extra: ``xmagic-sdk[google]``).

Full implementation lands in Phase 3 (see DESIGN.md roadmap).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from xmagic.providers.base import ChatMessage, Completion, CompletionChunk, Provider


class GoogleProvider(Provider):
    """Chat completions via the ``google-genai`` SDK."""

    name = "google"

    def __init__(self, api_key: str | None = None, **options: Any) -> None:
        super().__init__(api_key=api_key, **options)
        try:
            from google import genai  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "Google support requires the extra: pip install 'xmagic-sdk[google]'"
            ) from e

    def complete(self, messages: list[ChatMessage], *, model: str, **params: Any) -> Completion:
        raise NotImplementedError("Phase 3 (see DESIGN.md)")

    def stream(
        self, messages: list[ChatMessage], *, model: str, **params: Any
    ) -> Iterator[CompletionChunk]:
        raise NotImplementedError("Phase 3 (see DESIGN.md)")
