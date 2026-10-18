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
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, get_type_hints

if TYPE_CHECKING:
    from pydantic import BaseModel

    from xmagic.providers.tool_loop import ToolRun

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


def claim_strict(schema: dict[str, Any]) -> bool:
    """Whether a JSON Schema can honestly be sent under a vendor's strict mode.

    Strict mode requires every property to be required and additional ones
    forbidden, at every level. `$defs` means pydantic emitted a nested model,
    whose inner objects this does not rewrite -- so strict is claimed only for
    the flat, fully-required case rather than sending a schema the vendor
    rejects outright. When it is claimed, the schema is amended in place to
    forbid additional properties, which strict mode also demands.
    """
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    strict = set(required) == set(properties) and "$defs" not in schema
    if strict:
        schema["additionalProperties"] = False
    return strict


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
    fn: Callable[..., Any] | None = field(default=None, repr=False, compare=False)
    """The callable this definition was derived from, kept for `run_tools`.

    `from_callable` sets it; a hand-built `ToolDef` may leave it `None` and
    still be sent to `complete`, but the execution loop has nothing to call
    and refuses it. Excluded from comparison and repr: two definitions that
    describe the same tool are the same definition, wherever the code lives.
    """
    arguments_model: type[BaseModel] | None = field(default=None, repr=False, compare=False)
    """The pydantic model `parameters` was generated from, when one exists.

    `run_tools` validates a call's arguments through it, which is what turns
    a nested-object argument into the model instance the function's signature
    actually names rather than a plain dict. Internal plumbing, same
    comparison rules as `fn`.
    """

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

        arguments_model = create_model(f"{fn.__name__}_arguments", **fields)
        schema: dict[str, Any] = arguments_model.model_json_schema()
        # pydantic names the model; the name belongs to the tool, not the schema.
        schema.pop("title", None)
        strict = claim_strict(schema)

        return cls(
            name=name or fn.__name__,
            description=description or (inspect.getdoc(fn) or ""),
            parameters=schema,
            strict=strict,
            fn=fn,
            arguments_model=arguments_model,
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
    id: str | None = None
    """The provider's identifier for this response, when it sent one.

    xMagic's `message_id`, which `chats.get_message` and the worklist review
    flow take; OpenAI's `chatcmpl-...` id; whatever LiteLLM passes through.
    `None` when the provider reported none.
    """
    parsed: BaseModel | None = None
    """`text` validated into the `response_format=` model, when one was given.

    Never silently `None` for a request that asked for a schema: text that does
    not validate raises instead, so a caller who asked for a `Weather` gets a
    `Weather` or an exception (DESIGN.md §14).
    """


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
    tool_calls: list[ToolCall] = field(default_factory=list)
    """What the model wants run, on the terminal chunk only.

    Arguments arrive as JSON string fragments spread across deltas and mean
    nothing until the last one lands, so there is no honest intermediate value
    to emit -- a half-built call is indistinguishable from a complete one. The
    terminal chunk is therefore where a completed call becomes available, which
    also matches ``usage``.
    """
    parsed: BaseModel | None = None
    """The streamed text validated into the `response_format=` model.

    Terminal chunk only, for the same reason as `tool_calls`: JSON that is
    still arriving is not yet an instance of anything.
    """
    id: str | None = None
    """The provider's identifier for the response, on the terminal chunk.

    On xMagic it arrives in a `metadata` frame before any text, but it rides
    the terminal chunk with `usage`, `tool_calls`, and `parsed` so there is one
    place to look rather than one per provider.
    """


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
    the adapter — an adapter implements `complete`, `stream`, and
    `capabilities`, nothing more. `run_tools` / `arun_tools` are inherited,
    built entirely on `complete`, so every adapter (including third-party
    entry-point ones) gets the execution loop without writing it.
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
        response_format: type[BaseModel] | None = None,
        **params: Any,
    ) -> Completion:
        """Blocking chat completion.

        `response_format` is a pydantic model the answer must conform to. The
        vendor is asked for that schema and the reply is validated into an
        instance on `Completion.parsed`; a reply that does not validate raises
        (DESIGN.md §14). An adapter whose backend takes no schema rejects it
        rather than ignoring it.
        """

    @abstractmethod
    def stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[ToolDef] | None = None,
        response_format: type[BaseModel] | None = None,
        **params: Any,
    ) -> Iterator[CompletionChunk]:
        """Streaming chat completion.

        Text arrives as it is generated; any tool calls arrive whole, on the
        terminal chunk (DESIGN.md §13.6, stage B). An adapter that cannot
        reassemble them raises rather than dropping them -- silently discarding
        the calls a model made is the failure this surface exists to prevent.

        With `response_format`, the JSON streams as text and the validated
        instance rides the terminal chunk as `parsed` (DESIGN.md §14).

        Adapters return a `Stream`, which is an `Iterator` with a `close()`
        that cancels the call and releases its connection now rather than at
        garbage collection, and a context manager that does so on exit.
        """

    def run_tools(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[ToolDef],
        max_turns: int = 10,
        raise_errors: bool = False,
        response_format: type[BaseModel] | None = None,
        **params: Any,
    ) -> ToolRun:
        """Run the tool-calling loop until the model answers in text.

        Calls `complete` with `tools=`, dispatches each returned call to the
        callable its `ToolDef` was built from (`ToolDef.from_callable`), sends
        the results back, and repeats until a turn answers in text or
        `max_turns` model calls have been made — at which point it raises
        :class:`~xmagic.errors.ToolTurnsExceeded` rather than returning what
        would look like an answer (DESIGN.md §13.8).

        A raising tool, an unknown tool name, and arguments that fail
        validation are reported back to the model as the tool result, so it
        can correct itself; with ``raise_errors=True`` they raise instead (a
        tool's own exception propagates unwrapped). Arguments are validated
        through the tool's argument model, so a nested pydantic parameter
        arrives as an instance, not a dict.

        Nothing else is configurable here by design: handoffs, memory,
        planners and retry policy stay out (DESIGN.md §13.8 Q1). ``params``
        pass through to `complete`; ``response_format`` applies to the turn
        that answers in text.
        """
        from xmagic.providers.tool_loop import run_tools

        return run_tools(
            self,
            messages,
            model=model,
            tools=tools,
            max_turns=max_turns,
            raise_errors=raise_errors,
            response_format=response_format,
            **params,
        )

    async def arun_tools(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        tools: list[ToolDef],
        max_turns: int = 10,
        raise_errors: bool = False,
        response_format: type[BaseModel] | None = None,
        **params: Any,
    ) -> ToolRun:
        """`run_tools` for an event loop: `async def` tools are awaited.

        The model call itself runs in a worker thread (`asyncio.to_thread`)
        over the same blocking `complete` — there is no async provider API
        yet, and when one lands this method's internals change, not its
        shape. Sync tools run inline; keep them quick or wrap them yourself.
        """
        from xmagic.providers.tool_loop import arun_tools

        return await arun_tools(
            self,
            messages,
            model=model,
            tools=tools,
            max_turns=max_turns,
            raise_errors=raise_errors,
            response_format=response_format,
            **params,
        )

    def capabilities(self) -> dict[str, bool]:
        """Feature flags callers may branch on (streaming, tools, vision...).

        ``tools`` means **per-call tool definitions** — whether this adapter
        accepts `tools=` (DESIGN.md §13.4, D4). An agent with tools registered
        platform-side is a real capability, and a different one; it does not
        make this flag true. ``structured_output`` means `response_format=` is
        accepted (DESIGN.md §14).
        """
        return {"streaming": True, "tools": False, "vision": False, "structured_output": False}
