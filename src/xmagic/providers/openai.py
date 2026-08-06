"""OpenAI provider adapter — the worked example of a non-xMagic model.

Optional extra: ``xmagic-sdk[openai]``. Model refs look like ``openai:gpt-5``.

This is the one vendor-native adapter. Anthropic and Google remain reserved
extension points; if a second native adapter is ever wanted, this file is the
pattern to copy — message mapping, error translation into the SDK's own
hierarchy, and a stream that yields a terminal ``done`` chunk.

Unlike ``XMagicProvider``, ``model`` here really is a model name: OpenAI selects
per call, so there is no agent to create and no server-side session. Multi-turn
context is whatever the caller passes in ``messages``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from xmagic.errors import ConfigurationError, XMagicError, error_for_status
from xmagic.providers.base import ChatMessage, Completion, CompletionChunk, Provider


def _payload(messages: list[ChatMessage]) -> list[dict[str, str]]:
    """OpenAI takes the message list verbatim — no flattening, unlike xMagic."""
    return [{"role": m.role, "content": m.content} for m in messages]


class OpenAIProvider(Provider):
    """Chat completions via the official ``openai`` SDK."""

    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        **options: Any,
    ) -> None:
        super().__init__(api_key=api_key, **options)
        try:
            import openai
        except ImportError as e:
            raise ImportError(
                "OpenAI support requires the extra: pip install 'xmagic-sdk[openai]'"
            ) from e
        if not api_key:
            raise ConfigurationError(
                "No OpenAI API key. Set OPENAI_API_KEY, or add [providers.openai] "
                "api_key to ~/.config/xmagic/config.toml."
            )
        self._openai = openai
        # `options` carries registry-supplied extras such as `settings`, which the
        # OpenAI constructor would reject -- so pass only what it understands.
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def _translate(self, e: Exception) -> Exception:
        """Map OpenAI's exceptions onto this SDK's hierarchy.

        Callers (and the CLI's `except XMagicError`) should not have to know which
        vendor raised. Status codes carry over unchanged, so a 429 from OpenAI
        surfaces as the same `RateLimitError` a 429 from xMagic would.
        """
        if isinstance(e, self._openai.APIStatusError):
            return error_for_status(e.status_code, type(e).__name__, str(e))
        if isinstance(e, self._openai.APIError):
            return XMagicError(f"OpenAI request failed: {e}")
        return e

    def complete(self, messages: list[ChatMessage], *, model: str, **params: Any) -> Completion:
        try:
            resp = self._client.chat.completions.create(
                model=model, messages=_payload(messages), **params
            )
        except Exception as e:
            raise self._translate(e) from e
        text = resp.choices[0].message.content or "" if resp.choices else ""
        return Completion(text=text, model=f"openai:{model}", raw=resp.model_dump())

    def stream(
        self, messages: list[ChatMessage], *, model: str, **params: Any
    ) -> Iterator[CompletionChunk]:
        try:
            chunks = self._client.chat.completions.create(
                model=model, messages=_payload(messages), stream=True, **params
            )
        except Exception as e:
            raise self._translate(e) from e
        for chunk in chunks:
            if not chunk.choices:
                continue  # usage-only frames carry no delta
            choice = chunk.choices[0]
            # Not an OpenAI field. Several OpenAI-compatible backends reachable
            # through `base_url` do send it, and `getattr` costs nothing when they
            # do not -- so reasoning renders dimmed there rather than vanishing.
            reasoning = getattr(choice.delta, "reasoning_content", None)
            if reasoning:
                yield CompletionChunk(text=reasoning, kind="reasoning")
            if choice.delta.content:
                yield CompletionChunk(text=choice.delta.content)
            if choice.finish_reason:
                yield CompletionChunk(text="", done=True)

    def capabilities(self) -> dict[str, bool]:
        return {"streaming": True, "tools": True, "vision": True}
