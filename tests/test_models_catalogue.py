"""`xmagic models` and the catalogue behind it.

Most of this drives a *fake* LiteLLM catalogue: the real one is 2,390 chat
models that change with every LiteLLM release, so asserting against it would
make this suite fail on upstream's schedule rather than on ours. A short section
at the end does check the real thing, for the properties that must hold whatever
LiteLLM ships.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from xmagic.cli.main import app
from xmagic.providers.base import ModelRef
from xmagic.providers.catalogue import list_models, list_providers

pytest.importorskip("litellm")

runner = CliRunner()

# Every awkward shape LiteLLM's real catalogue contains, in one fixture.
FAKE_CATALOGUE: dict[str, Any] = {
    # Key carries the provider prefix already.
    "groq/llama-3.3-70b": {
        "litellm_provider": "groq",
        "mode": "chat",
        "max_input_tokens": 131072,
        "input_cost_per_token": 5.9e-07,
        "output_cost_per_token": 7.9e-07,
        "supports_function_calling": True,
        "supports_vision": False,
    },
    # Key does not.
    "claude-sonnet-5": {
        "litellm_provider": "anthropic",
        "mode": "chat",
        "max_input_tokens": 200000,
        "supports_function_calling": True,
        "supports_vision": True,
    },
    # No capability flags at all -- roughly a third of the real catalogue.
    "tinyprovider/mystery-model": {"litellm_provider": "tinyprovider", "mode": "chat"},
    # Not a chat model.
    "text-embedding-3-large": {"litellm_provider": "openai", "mode": "embedding"},
    # LiteLLM's documentation placeholder, shipped in the same mapping.
    "sample_spec": {"litellm_provider": "openai", "mode": "chat"},
    # Shapes that should be skipped rather than crash the listing.
    "broken/no-provider": {"mode": "chat"},
    "broken/not-a-dict": "nonsense",
}


@pytest.fixture
def catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    import litellm

    monkeypatch.setattr(litellm, "model_cost", FAKE_CATALOGUE)


@pytest.mark.usefixtures("catalogue")
class TestListing:
    def test_chat_models_only_by_default(self) -> None:
        # The Provider interface does chat. Listing embedding or image models
        # beside them would advertise something complete/stream cannot do.
        assert [m.name for m in list_models()] == [
            "claude-sonnet-5",
            "groq/llama-3.3-70b",
            "tinyprovider/mystery-model",
        ]

    def test_mode_none_includes_everything_else(self) -> None:
        assert "text-embedding-3-large" in {m.name for m in list_models(mode=None)}

    def test_the_provider_prefix_is_never_doubled(self) -> None:
        (groq,) = list_models(provider="groq")

        # The key already read `groq/llama-3.3-70b`; naive concatenation gives
        # `litellm:groq/groq/llama-3.3-70b`, which resolves to nothing.
        assert groq.ref == "litellm:groq/llama-3.3-70b"

    def test_a_ref_without_a_prefix_gains_one(self) -> None:
        (claude,) = list_models(provider="anthropic")

        assert claude.ref == "litellm:anthropic/claude-sonnet-5"

    def test_every_ref_parses_back_into_a_usable_model_ref(self) -> None:
        for model in list_models():
            parsed = ModelRef.parse(model.ref)
            assert parsed.provider == "litellm"
            assert parsed.model.startswith(f"{model.provider}/")

    def test_costs_are_reported_per_million_tokens(self) -> None:
        (groq,) = list_models(provider="groq")

        assert groq.input_cost_per_1m == pytest.approx(0.59)
        assert groq.output_cost_per_1m == pytest.approx(0.79)

    def test_an_unflagged_model_is_unknown_not_unsupported(self) -> None:
        (mystery,) = list_models(provider="tinyprovider")

        # None, not False: LiteLLM has no flag for this model, and saying "no"
        # would invent a fact about it.
        assert mystery.tools is None
        assert mystery.vision is None
        assert mystery.context_window is None

    def test_the_documentation_placeholder_is_not_a_model(self) -> None:
        assert "sample_spec" not in {m.name for m in list_models()}

    def test_unusable_entries_are_skipped_rather_than_raising(self) -> None:
        names = {m.name for m in list_models(mode=None)}

        assert "broken/no-provider" not in names
        assert "broken/not-a-dict" not in names

    def test_search_matches_the_ref_case_insensitively(self) -> None:
        assert [m.name for m in list_models(search="LLAMA")] == ["groq/llama-3.3-70b"]

    def test_providers_are_counted_and_ranked(self) -> None:
        assert list_providers() == [("anthropic", 1), ("groq", 1), ("tinyprovider", 1)]


@pytest.mark.usefixtures("catalogue")
class TestCLI:
    def test_list_renders_refs_and_capabilities(self) -> None:
        result = runner.invoke(app, ["models", "list"])

        assert result.exit_code == 0, result.output
        assert "litellm:groq/llama-3.3-70b" in result.output.replace("\n", "")
        # Unknown flags render as `?`, distinct from `no`.
        assert "?" in result.output

    def test_list_json_is_machine_readable(self) -> None:
        result = runner.invoke(app, ["models", "list", "--json"])

        payload = json.loads(result.output)
        assert {m["ref"] for m in payload} == {
            "litellm:anthropic/claude-sonnet-5",
            "litellm:groq/llama-3.3-70b",
            "litellm:tinyprovider/mystery-model",
        }
        assert payload[0]["tools"] is True

    def test_truncation_is_announced_rather_than_silent(self) -> None:
        result = runner.invoke(app, ["models", "list", "--limit", "1"])

        assert "Showing 1 of 3" in result.output

    def test_json_truncation_warns_without_corrupting_stdout(self) -> None:
        result = runner.invoke(app, ["models", "list", "--limit", "1", "--json"])

        # The warning goes to stderr, so a script piping stdout into jq still
        # gets valid JSON -- and still finds out it did not get everything.
        assert len(json.loads(result.stdout)) == 1
        assert "showing 1 of 3" in result.stderr

    def test_no_matches_says_so(self) -> None:
        result = runner.invoke(app, ["models", "list", "-p", "nobody"])

        assert result.exit_code == 0
        assert "No models match" in result.output

    def test_providers_lists_counts(self) -> None:
        result = runner.invoke(app, ["models", "providers", "--json"])

        assert json.loads(result.output) == [
            {"provider": "anthropic", "models": 1},
            {"provider": "groq", "models": 1},
            {"provider": "tinyprovider", "models": 1},
        ]

    def test_the_output_says_whose_catalogue_this_is(self) -> None:
        # xMagic publishes no model list (DESIGN.md §10.6), and a command named
        # `xmagic models` implying otherwise is the misreading worth preventing.
        result = runner.invoke(app, ["models", "list"])

        assert "xMagic publishes no model list" in result.output.replace("\n", " ")


class TestAgainstTheRealCatalogue:
    """Properties that must hold whatever LiteLLM ships."""

    def test_the_catalogue_is_not_empty_and_every_ref_resolves(self) -> None:
        found = list_models()

        assert len(found) > 100
        for model in found:
            assert ModelRef.parse(model.ref).provider == "litellm"
            assert model.mode == "chat"

    def test_the_big_three_vendors_are_reachable(self) -> None:
        providers = {p for p, _ in list_providers()}

        assert {"openai", "anthropic"} <= providers
