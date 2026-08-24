"""Bring your own model: one interface, any provider.

`get_provider` resolves a `provider:model` ref to an adapter, and every adapter
exposes the same three methods — so the code below does not change when the ref
does. Errors arrive as this SDK's own types whichever vendor produced them.

Run:
    # any one of these
    export OPENAI_API_KEY="sk-..."      # openai:gpt-5
    export ANTHROPIC_API_KEY="sk-..."   # litellm:anthropic/claude-sonnet-5
    export GROQ_API_KEY="gsk-..."       # litellm:groq/llama-3.3-70b-versatile

    uv run python examples/06_provider_model.py
    uv run python examples/06_provider_model.py litellm:groq/llama-3.3-70b-versatile

    # or, with no API key at all, against a model running on your machine:
    uv run python examples/06_provider_model.py litellm:ollama/llama3

Needs no xMagic key: nothing here touches the xMagic API. The `xmagic:<agent_id>`
ref goes through the same interface — see 01_basic_chat.py for that side.
"""

from __future__ import annotations

import sys

from xmagic.errors import (
    AuthenticationError,
    ConfigurationError,
    RateLimitError,
    XMagicError,
)
from xmagic.providers import ChatMessage, ModelRef, get_provider

DEFAULT_REF = "openai:gpt-5"

MESSAGES = [
    ChatMessage(role="system", content="Answer in one short sentence."),
    ChatMessage(role="user", content="What is a Model Context Protocol server?"),
]


def discover(needle: str) -> None:
    """Refs are discoverable, not something to guess at.

    The same listing backs `xmagic models list --search <needle>`. It reads
    LiteLLM's catalogue, which is the only model list available -- xMagic
    publishes none, since a `xmagic:` ref names an agent rather than a model.
    """
    try:
        from xmagic.providers.catalogue import list_models
    except ImportError as e:  # the [litellm] extra is not installed
        print(f"(skipping model discovery: {e})")
        return

    matches = list_models(search=needle)[:3]
    print(f"refs matching {needle!r}: {', '.join(m.ref for m in matches) or 'none'}\n")


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REF
    parsed = ModelRef.parse(ref)

    discover("llama-3.3-70b")

    try:
        provider = get_provider(ref)
    except ConfigurationError as e:
        # The OpenAI adapter needs a key up front. The LiteLLM one does not:
        # it resolves credentials per vendor from the environment, and a local
        # runtime like Ollama needs none at all.
        print(e, file=sys.stderr)
        return 2
    except ImportError as e:
        # The adapter's extra is not installed, e.g. `pip install 'xmagic-sdk[litellm]'`.
        print(e, file=sys.stderr)
        return 2

    # Capabilities are advertised, not assumed. On the LiteLLM path they are read
    # from its model metadata; `tools: False` there can mean "no flag for this
    # model" rather than "not supported".
    print(f"{ref} -> {provider.name} adapter, capabilities: {provider.capabilities()}\n")

    try:
        for chunk in provider.stream(MESSAGES, model=parsed.model):
            if chunk.kind == "reasoning":
                continue  # thinking, not the answer -- render it dimmed if you want it
            print(chunk.text, end="", flush=True)
            if chunk.done and chunk.usage:
                print(f"\n\ntokens: {chunk.usage.total_tokens}")
    except AuthenticationError:
        print(f"\nThe key for {parsed.provider!r} was rejected.", file=sys.stderr)
        return 1
    except RateLimitError:
        print("\nRate limited by the provider.", file=sys.stderr)
        return 1
    except XMagicError as e:
        # One exception hierarchy regardless of vendor: a 429 from Groq raises
        # the same RateLimitError a 429 from xMagic would.
        print(f"\n{type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
