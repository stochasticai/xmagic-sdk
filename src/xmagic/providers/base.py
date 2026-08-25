"""Provider abstraction: bring-your-own-model across xMagic, OpenAI, Anthropic,
Google, and (optionally) anything LiteLLM supports.

Models are addressed as ``provider:model``, e.g.::

    xmagic:<agent_id>
    openai:gpt-4o
    anthropic:claude-sonnet-5
    google:gemini-2.5-pro
    litellm:groq/llama-3.3-70b
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias, get_type_hints

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class TextPart:
    """A run of text inside a structured message body."""

    text: str
    type: Literal["text"] = "text"


ContentPart: TypeAlias = TextPart
"""One block of a structured message body.

A union of one for now. Image and audio parts land with multimodal input, which
is its own item in TODO.md; the alias exists so that adding them does not change
`ChatMessage`'s type again.
"""


@dataclass
class ToolDef:
    """A tool offered to the model, as JSON Schema.

    ``strict`` asks the vendor to constrain generation to the schema, which is
    the difference between arguments that usually parse and arguments that
    always do. It is not free: strict schemas must mark every property required
    and forbid additional ones, so :meth:`from_callable` turns it off rather than
    emitting a schema the vendor will reject.
    """

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    strict: bool = False

    @classmethod
    def from_callable(
        cls,
        fn: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> ToolDef:
        """Derive a tool definition from a typed Python function.

        The signature becomes the JSON Schema and the docstring becomes the
        description, so a tool is written once rather than twice — which is the
        difference between this being pleasant and being a schema-writing
        exercise (DESIGN.md §13.6, stage C).

        `strict` is set only for a flat, fully-required schema: strict mode
        constrains every level of the schema, so a parameter with a default or a
        nested model (which pydantic emits under `$defs`) turns it off rather
        than sending something the vendor rejects outright.

        Raises `ValueError` for signatures JSON Schema cannot express, and for
        annotations that cannot be resolved.
        """
        from pydantic import create_model

        try:
            hints = get_type_hints(fn)
        except NameError as e:
            # `from __future__ import annotations` makes annotations strings, and
            # a type defined inside a function is not in the module namespace
            # that resolves them. The bare NameError names the type and nothing
            # else, which is not enough to act on.
            raise ValueError(
                f"{fn.__name__}: could not resolve its annotations ({e}). A type "
                "referenced by a tool must be importable at module level -- one "
                "defined inside a function is not, under postponed annotations."
            ) from e
        fields: dict[str, Any] = {}
        for param_name, param in inspect.signature(fn).parameters.items():
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                raise ValueError(
                    f"{fn.__name__}: *args/**kwargs cannot be described as JSON Schema. "
                    "Give the tool explicit named parameters."
                )
            if param_name not in hints:
                raise ValueError(
                    f"{fn.__name__}: parameter '{param_name}' has no type annotation, "
                    "so its schema cannot be derived."
                )
            default = ... if param.default is inspect.Parameter.empty else param.default
            fields[param_name] = (hints[param_name], default)

        schema: dict[str, Any] = create_model(
            f"{fn.__name__}_arguments", **fields
        ).model_json_schema()
        # pydantic names the model; the name belongs to the tool, not the schema.
        schema.pop("title", None)
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        # Strict mode requires every property to be required and additional ones
        # forbidden, at every level. `$defs` means pydantic emitted a nested
        # model, whose inner objects this does not rewrite -- so claim strict
        # only for the flat case rather than send a schema the vendor rejects.
        strict = set(required) == set(properties) and "$defs" not in schema
        if strict:
            schema["additionalProperties"] = False

        return cls(
            name=name or fn.__name__,
            description=description or (inspect.getdoc(fn) or ""),
            parameters=schema,
            strict=strict,
        )


@dataclass
class ToolCall:
    """A model's request to run one tool.

    ``arguments`` is parsed, not a JSON string (DESIGN.md §13.4, D1). OpenAI
    types it as `str` on the wire; making every caller `json.loads` something
    with no guarantee that it parses is the abstraction failing at its one job.
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMessage:
    """Provider-neutral chat message.

    Three fields exist only for tool calling, and all three are optional, so
    every message written before they existed still constructs unchanged:

    - ``content`` accepts a list of parts, because an Anthropic-style body is a
      list of typed blocks rather than a string.
    - ``content`` accepts ``None``, because an assistant turn that only calls
      tools has no text at all.
    - ``tool_calls`` carries what the assistant asked for, and ``tool_call_id``
      correlates a ``role="tool"`` result with the call that requested it.
      Without the id a result cannot be matched to its call, which is what made
      `Role`'s existing ``"tool"`` member unusable.
    """

    role: Role
    content: str | list[ContentPart] | None = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class Usage:
    """Token counts for one exchange, where the provider reports them.

    Every field is optional because providers disagree on what they send, and
    xMagic's shape is unconfirmed -- ``token_usage`` comes from the backend's
    private ``TokenType`` enum rather than the published API reference, and no
    recorded live stream has contained one. ``raw`` keeps whatever arrived, so a
    caller can reach past this model when it turns out to be wrong.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Completion:
    """Provider-neutral completion result."""

    text: str
    model: str
    raw: dict[str, Any] = field(default_factory=dict)
    usage: Usage | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    """What the model wants run. Empty unless `tools=` was passed and used."""


ChunkKind = Literal["response", "reasoning"]


@dataclass
class CompletionChunk:
    """A streamed delta.

    ``kind`` separates the model's visible answer from its thinking, so a caller
    can render them differently. Adapters that expose no reasoning channel emit
    the default and callers need not branch.
    """

    text: str
    done: bool = False
    kind: ChunkKind = "response"
    usage: Usage | None = None
    """Set on the terminal chunk when the provider reported token counts."""


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
    def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[ToolDef] | None = None,
        **params: Any,
    ) -> Completion:
        """Blocking chat completion."""

    @abstractmethod
    def stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[ToolDef] | None = None,
        **params: Any,
    ) -> Iterator[CompletionChunk]:
        """Streaming chat completion.

        `tools` is accepted and rejected rather than ignored: accumulating
        argument fragments across deltas is stage B (DESIGN.md §13.6), and
        silently dropping the calls a model made is the failure this surface
        exists to prevent.
        """

    def capabilities(self) -> dict[str, bool]:
        """Feature flags callers may branch on (streaming, tools, vision...).

        ``tools`` means **per-call tool definitions** — whether this adapter
        accepts `tools=` (DESIGN.md §13.4, D4). An agent with tools registered
        platform-side is a real capability, and a different one; it does not
        make this flag true.
        """
        return {"streaming": True, "tools": False, "vision": False}
