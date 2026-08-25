"""Google (Gemini) provider adapter — a reserved extension point, not working code.

Gemini is reachable today as ``litellm:gemini/<model>``, so this adapter exists
to keep a native path open (vendor-specific params, no LiteLLM dependency) if it
is ever wanted, not because anything needs it. There is deliberately no
``[google]`` extra: the SDK it would install is unused until the adapter is
implemented. Phase 3, see DESIGN.md roadmap.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from xmagic.providers.base import (
    ChatMessage,
    Completion,
    CompletionChunk,
    Provider,
    ToolDef,
)

# Said the same way whether or not the vendor SDK happens to be installed --
# `google-genai` is absent by default, but a transitive dependency could pull it
# in and silently change which of the two errors below a user sees.
_UNIMPLEMENTED = (
    "GoogleProvider is a reserved extension point and is not implemented (Phase 3). "
    "Use `litellm:gemini/<model>` instead."
)


class GoogleProvider(Provider):
    """Chat completions via the ``google-genai`` SDK."""

    name = "google"

    def __init__(self, api_key: str | None = None, **options: Any) -> None:
        super().__init__(api_key=api_key, **options)
        try:
            from google import genai  # noqa: F401
        except ImportError as e:
            raise ImportError(
                f"{_UNIMPLEMENTED} If you are implementing this adapter, "
                "`pip install google-genai`."
            ) from e

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[ToolDef] | None = None,
        **params: Any,
    ) -> Completion:
        raise NotImplementedError(_UNIMPLEMENTED)

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[ToolDef] | None = None,
        **params: Any,
    ) -> Iterator[CompletionChunk]:
        raise NotImplementedError(_UNIMPLEMENTED)
