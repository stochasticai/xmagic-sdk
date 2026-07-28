"""Provider abstraction: bring-your-own-model across xMagic, OpenAI, Anthropic,
Google, and (optionally) anything LiteLLM supports.

Models are addressed as ``provider:model``, e.g.::

    xmagic:<agent_id>
    openai:gpt-4o
    anthropic:claude-sonnet-4-5
    google:gemini-2.5-pro
    litellm:groq/llama-3.3-70b
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ChatMessage:
    """Provider-neutral chat message."""

    role: Role
    content: str


@dataclass
class Completion:
    """Provider-neutral completion result."""

    text: str
    model: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompletionChunk:
    """A streamed delta."""

    text: str
    done: bool = False


@dataclass
class ModelRef:
    """Parsed ``provider:model`` reference."""

    provider: str
    model: str

    @classmethod
    def parse(cls, ref: str, default_provider: str = "xmagic") -> ModelRef:
        provider, sep, model = ref.partition(":")
        if not sep:
            return cls(provider=default_provider, model=ref)
        return cls(provider=provider.lower(), model=model)


class Provider(ABC):
    """Minimal chat-completion interface every adapter implements.

    Normalization (message shapes, streaming quirks, tool calls) belongs in
    the adapter — callers only ever see these three methods.
    """

    name: str

    def __init__(self, api_key: str | None = None, **options: Any) -> None:
        self.api_key = api_key
        self.options = options

    @abstractmethod
    def complete(self, messages: list[ChatMessage], *, model: str, **params: Any) -> Completion:
        """Blocking chat completion."""

    @abstractmethod
    def stream(
        self, messages: list[ChatMessage], *, model: str, **params: Any
    ) -> Iterator[CompletionChunk]:
        """Streaming chat completion."""

    def capabilities(self) -> dict[str, bool]:
        """Feature flags callers may branch on (streaming, tools, vision...)."""
        return {"streaming": True, "tools": False, "vision": False}
