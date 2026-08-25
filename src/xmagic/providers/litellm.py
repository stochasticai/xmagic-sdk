"""LiteLLM provider adapter — one adapter, roughly 150 vendors.

Optional extra: ``xmagic-sdk[litellm]``. Model refs look like
``litellm:groq/llama-3.3-70b-versatile``, ``litellm:anthropic/claude-sonnet-5``,
or ``litellm:ollama/llama3`` — the part after ``litellm:`` is passed to LiteLLM
verbatim, so its whole model namespace is addressable without this SDK knowing
anything about it.

This is why Anthropic and Google stayed reserved extension points (DESIGN.md
§4): both are reachable here, and a native adapter is only worth writing when a
vendor-specific need makes routing through LiteLLM wrong.

Two behaviours differ from ``OpenAIProvider`` and are deliberate:

- **A missing API key is not an error.** LiteLLM resolves credentials per
  vendor from the environment (``GROQ_API_KEY``, ``ANTHROPIC_API_KEY``, and so
  on), and local runtimes like Ollama need none at all. Raising on construction
  would break the common case; an explicit key is forwarded when given, and
  otherwise LiteLLM is left to find one and to report it if it cannot.
- **Streamed token counts may be estimated.** When the upstream sends a usage
  frame, LiteLLM passes the measured counts through. When it does not, LiteLLM
  fills the gap with its own tokenizer, and the two are indistinguishable by the
  time they reach us. ``Usage.raw`` keeps the payload so a caller can judge.
  Non-streaming counts always come from the provider's response.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from xmagic.errors import (
    APIConnectionError,
    APITimeoutError,
    XMagicError,
    error_for_status,
)
from xmagic.providers.base import (
    ChatMessage,
    Completion,
    CompletionChunk,
    Provider,
    Usage,
)


def _payload(messages: list[ChatMessage]) -> list[dict[str, str]]:
    """LiteLLM takes the OpenAI message shape, whatever the vendor speaks."""
    return [{"role": m.role, "content": m.content} for m in messages]


def _usage_from(reported: Any) -> Usage | None:
    """Normalize LiteLLM's ``Usage`` onto this SDK's.

    Returns ``None`` rather than a zero-filled ``Usage`` when nothing readable
    arrived: reporting 0 tokens as though it had been measured is worse than
    reporting nothing, and a caller cannot tell the two apart afterwards.
    """
    if reported is None:
        return None

    def count(name: str) -> int | None:
        value = getattr(reported, name, None)
        # bool is a subclass of int; no token count is a bool.
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    dump = getattr(reported, "model_dump", None)
    dumped = dump() if callable(dump) else None
    raw: dict[str, Any] = dumped if isinstance(dumped, dict) else {}

    usage = Usage(
        input_tokens=count("prompt_tokens"),
        output_tokens=count("completion_tokens"),
        total_tokens=count("total_tokens"),
        raw=raw,
    )
    known = (usage.input_tokens, usage.output_tokens, usage.total_tokens)
    # All-zero is LiteLLM's placeholder, not a measurement: a response carrying
    # no usage block still arrives with a zero-filled `Usage` attached. A real
    # exchange cannot have consumed zero prompt tokens, so treat it as absent
    # rather than hand a caller three zeros that look measured.
    if all(v in (None, 0) for v in known):
        return None
    return usage


class LiteLLMProvider(Provider):
    """Chat completions routed through LiteLLM."""

    name = "litellm"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        **options: Any,
    ) -> None:
        super().__init__(api_key=api_key, **options)
        try:
            import litellm
        except ImportError as e:
            raise ImportError(
                "LiteLLM support requires the extra: pip install 'xmagic-sdk[litellm]'"
            ) from e
        self._litellm = litellm
        self._base_url = base_url

    def _call_kwargs(self) -> dict[str, Any]:
        """What LiteLLM should see of our configuration, and nothing else.

        `options` carries registry-supplied extras such as `settings`, which
        `completion` would reject as an unknown parameter.
        """
        kwargs: dict[str, Any] = {}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self._base_url:
            # LiteLLM's spelling. Kept as `base_url` on our side so every adapter
            # takes the same constructor argument.
            kwargs["api_base"] = self._base_url
        return kwargs

    def _translate(self, e: Exception) -> Exception:
        """Map LiteLLM's exceptions onto this SDK's hierarchy.

        LiteLLM normalizes every vendor's failures into its own exception set
        first, so one mapping covers all ~150 of them: a 429 from Groq and a 429
        from Anthropic both arrive as `litellm.RateLimitError` and leave here as
        this SDK's `RateLimitError`.
        """
        exceptions = self._litellm.exceptions
        # Before APIConnectionError: LiteLLM's Timeout is a subclass of it.
        if isinstance(e, exceptions.Timeout):
            return APITimeoutError(f"LiteLLM request timed out: {e}")
        if isinstance(e, exceptions.APIConnectionError):
            return APIConnectionError(f"LiteLLM could not reach the provider: {e}")
        status = getattr(e, "status_code", None)
        if isinstance(status, int) and not isinstance(status, bool):
            return error_for_status(status, type(e).__name__, str(e))
        if isinstance(e, exceptions.OpenAIError):
            # LiteLLM's own base class, despite the name -- covers the failures
            # that never reached a provider, such as an unknown model ref.
            return XMagicError(f"LiteLLM request failed: {e}")
        return e

    def complete(self, messages: list[ChatMessage], *, model: str, **params: Any) -> Completion:
        try:
            resp: Any = self._litellm.completion(
                model=model, messages=_payload(messages), **self._call_kwargs(), **params
            )
        except Exception as e:
            raise self._translate(e) from e
        text = resp.choices[0].message.content or "" if resp.choices else ""
        return Completion(
            text=text,
            model=f"litellm:{model}",
            # `model_dump()` drops `usage`, so the counts would be unreachable
            # from `raw` alone -- they ride on `Usage` instead.
            raw=resp.model_dump(),
            usage=_usage_from(getattr(resp, "usage", None)),
        )

    def stream(
        self, messages: list[ChatMessage], *, model: str, **params: Any
    ) -> Iterator[CompletionChunk]:
        try:
            chunks: Any = self._litellm.completion(
                model=model,
                messages=_payload(messages),
                stream=True,
                **self._call_kwargs(),
                **params,
            )
        except Exception as e:
            raise self._translate(e) from e

        usage: Usage | None = None
        try:
            for chunk in chunks:
                usage = _usage_from(getattr(chunk, "usage", None)) or usage
                if not chunk.choices:
                    continue  # usage-only frames carry no delta
                delta = chunk.choices[0].delta
                # LiteLLM normalizes vendor thinking channels onto this one
                # field, so reasoning renders dimmed for Anthropic and DeepSeek
                # the same way it does for an xMagic agent.
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    yield CompletionChunk(text=reasoning, kind="reasoning")
                if delta.content:
                    yield CompletionChunk(text=delta.content)
        except Exception as e:
            raise self._translate(e) from e

        # `done` is emitted here rather than on `finish_reason`, unlike the
        # OpenAI adapter: usage arrives in a frame *after* the finish reason, so
        # closing the stream early would drop the token counts every time.
        yield CompletionChunk(text="", done=True, usage=usage)

    def capabilities(self) -> dict[str, bool]:
        """Read the flags off LiteLLM rather than hand-maintaining a table.

        The model is whatever the registry parsed out of the ref; constructed
        directly there is none, and the conservative base defaults stand.
        """
        model = getattr(self, "default_model", None)
        if not isinstance(model, str) or not model:
            return super().capabilities()
        # Both report False for a model LiteLLM has no metadata for rather than
        # raising, so an unmapped model reads as "cannot confirm" -- which is
        # also the honest answer. The cost of reading the table instead of
        # keeping our own is that LiteLLM's metadata trails its provider list.
        return {
            "streaming": True,
            "tools": bool(self._litellm.supports_function_calling(model=model)),
            "vision": bool(self._litellm.supports_vision(model=model)),
        }
