"""Multi-provider layer: bring your own model via ``provider:model`` refs."""

from xmagic.providers.base import (
    ChatMessage,
    Completion,
    CompletionChunk,
    ContentPart,
    ModelRef,
    Provider,
    TextPart,
    ToolCall,
    ToolDef,
)
from xmagic.providers.registry import get_provider
from xmagic.providers.tool_loop import ToolRun

__all__ = [
    "ChatMessage",
    "Completion",
    "CompletionChunk",
    "ContentPart",
    "ModelRef",
    "Provider",
    "TextPart",
    "ToolCall",
    "ToolDef",
    "ToolRun",
    "get_provider",
]
