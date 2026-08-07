"""The Anthropic and Google adapters are reserved extension points.

They keep their classes and `xmagic.providers` entry points so a native adapter
can be dropped in later, but they ship no implementation and no extra. Two things
are worth locking down: the message a user gets is the same whether or not the
vendor SDK happens to be installed, and nobody re-adds a vendor extra without
noticing. The first matters because a transitive dependency can install a vendor
SDK we never asked for, silently flipping which error path an adapter takes.

OpenAI is deliberately absent here -- it is implemented, and has `[openai]`.
See `test_openai_provider.py`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from xmagic.providers.anthropic import AnthropicProvider
from xmagic.providers.google import GoogleProvider

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

RESERVED = [
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


def test_only_implemented_vendors_get_an_extra() -> None:
    """An extra exists for OpenAI because OpenAIProvider works. Adding one for a
    reserved adapter would install an SDK nothing imports."""
    extras = tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]
    assert set(extras) == {"openai", "litellm", "serve", "mcp", "all"}


def test_all_extra_pulls_no_reserved_vendor_sdk() -> None:
    extras = tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]
    joined = " ".join(extras["all"])
    for vendor in ("anthropic", "google"):
        assert vendor not in joined
