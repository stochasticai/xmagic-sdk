"""Multi-provider layer: bring your own model via ``provider:model`` refs."""

from xmagic.providers.base import (
    ChatMessage,
    Completion,
    CompletionChunk,
    ModelRef,
    Provider,
)
from xmagic.providers.registry import get_provider

__all__ = [
    "Provider",
    "ChatMessage",
    "Completion",
    "CompletionChunk",
    "ModelRef",
    "get_provider",
]
