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
    "ChatMessage",
    "Completion",
    "CompletionChunk",
    "ModelRef",
    "Provider",
    "get_provider",
]
