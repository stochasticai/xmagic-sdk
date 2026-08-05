"""The OpenAI/Anthropic/Google adapters are reserved extension points.

They keep their classes and `xmagic.providers` entry points so a native adapter
can be dropped in later, but they ship no implementation and no extra. Two things
are worth locking down: the message a user gets is the same whether or not the
vendor SDK happens to be installed, and nobody re-adds a per-vendor extra without
noticing. The first matters because LiteLLM depends on `openai`, so installing
the [litellm] extra flips which error path OpenAIProvider takes.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from xmagic.providers.anthropic import AnthropicProvider
from xmagic.providers.google import GoogleProvider
from xmagic.providers.openai import OpenAIProvider

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

RESERVED = [
    pytest.param(OpenAIProvider, "litellm:openai/", id="openai"),
    pytest.param(AnthropicProvider, "litellm:anthropic/", id="anthropic"),
    pytest.param(GoogleProvider, "litellm:gemini/", id="google"),
]


def _message(cls: type) -> str:
    """Whichever error this adapter raises, installed vendor SDK or not."""
    try:
        provider = cls()
    except ImportError as e:  # vendor SDK absent — the constructor refuses
        return str(e)
    with pytest.raises(NotImplementedError) as excinfo:  # present — the method does
        provider.complete([], model="whatever")
    return str(excinfo.value)


@pytest.mark.parametrize(("cls", "litellm_ref"), RESERVED)
def test_reserved_adapter_points_at_the_litellm_route(cls: type, litellm_ref: str) -> None:
    msg = _message(cls)
    assert "reserved extension point" in msg
    assert litellm_ref in msg


@pytest.mark.parametrize(("cls", "litellm_ref"), RESERVED)
def test_both_error_paths_carry_the_same_guidance(cls: type, litellm_ref: str) -> None:
    # Only one path is reachable in any given environment, so compare each
    # against the shared constant rather than against each other.
    from importlib import import_module

    shared = import_module(cls.__module__)._UNIMPLEMENTED
    assert litellm_ref in shared
    assert shared in _message(cls)


def test_no_per_vendor_extras_are_declared() -> None:
    extras = tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]
    assert set(extras) == {"litellm", "serve", "mcp", "all"}


def test_all_extra_does_not_pull_vendor_sdks() -> None:
    extras = tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]
    joined = " ".join(extras["all"])
    for vendor in ("openai", "anthropic", "google"):
        assert vendor not in joined
