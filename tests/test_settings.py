"""How explicit arguments, the environment, and the config file combine.

`Settings.load` used to drop every `None` override, which conflated "the caller
did not supply this" with "the caller supplied None deliberately". That is fine
for `api_key`, where None means unset, and wrong for `stream_timeout`, where None
means "wait forever" -- it made the documented value unreachable through the
constructor and silently substituted the 300s default.

The rule these tests pin: `Settings.load` applies whatever it is given, and the
client omits its two named arguments when they are not supplied.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from xmagic import AsyncXMagicClient, XMagicClient
from xmagic.client.http import _stream_timeout
from xmagic.config import ENV_API_KEY, ENV_BASE_URL, ENV_CONFIG_PATH, Settings

CLIENTS = [XMagicClient, AsyncXMagicClient]


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point config resolution at a scratch path, never the developer's own."""
    config = tmp_path / "config.toml"
    monkeypatch.setenv(ENV_CONFIG_PATH, str(config))
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    monkeypatch.delenv(ENV_BASE_URL, raising=False)
    return config


@pytest.mark.parametrize("client_cls", CLIENTS, ids=lambda c: c.__name__)
def test_stream_timeout_none_reaches_the_settings(client_cls: type) -> None:
    """`None` is the documented way to wait forever, so it has to survive."""
    settings = client_cls(api_key="k", stream_timeout=None).settings

    assert settings.stream_timeout is None
    assert _stream_timeout(settings).read is None


@pytest.mark.parametrize("client_cls", CLIENTS, ids=lambda c: c.__name__)
def test_an_explicit_stream_timeout_still_wins(client_cls: type) -> None:
    assert client_cls(api_key="k", stream_timeout=900.0).settings.stream_timeout == 900.0


@pytest.mark.parametrize("client_cls", CLIENTS, ids=lambda c: c.__name__)
def test_the_default_stream_timeout_survives_an_untouched_constructor(client_cls: type) -> None:
    assert client_cls(api_key="k").settings.stream_timeout == 300.0


def test_an_omitted_api_key_still_falls_back_to_the_config_file(isolated_config: Path) -> None:
    """The regression risk in letting None through: it must not clobber the file."""
    isolated_config.write_text('[xmagic]\napi_key = "from-file"\n', encoding="utf-8")

    assert XMagicClient().settings.api_key == "from-file"
    assert XMagicClient(api_key=None).settings.api_key == "from-file"
    assert XMagicClient(api_key="explicit").settings.api_key == "explicit"


def test_an_omitted_base_url_still_falls_back_to_the_config_file(isolated_config: Path) -> None:
    isolated_config.write_text('[xmagic]\nbase_url = "https://file.example/v1"\n', encoding="utf-8")

    assert XMagicClient(api_key="k").settings.base_url == "https://file.example/v1"
    assert XMagicClient(api_key="k", base_url=None).settings.base_url == "https://file.example/v1"


def test_the_environment_still_beats_the_config_file(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_config.write_text('[xmagic]\napi_key = "from-file"\n', encoding="utf-8")
    monkeypatch.setenv(ENV_API_KEY, "from-env")

    assert XMagicClient().settings.api_key == "from-env"
    assert XMagicClient(api_key="explicit").settings.api_key == "explicit"


@pytest.mark.parametrize("client_cls", CLIENTS, ids=lambda c: c.__name__)
def test_a_negative_max_retries_is_rejected_up_front(client_cls: type) -> None:
    """`range(max_retries + 1)` is empty below zero, so the retry loop would fall
    off the end and raise `UnboundLocalError` at request time instead."""
    with pytest.raises(ValidationError):
        client_cls(api_key="k", max_retries=-1)


def test_zero_max_retries_is_still_allowed() -> None:
    assert XMagicClient(api_key="k", max_retries=0).settings.max_retries == 0


def test_load_applies_none_but_the_client_omits_what_was_not_passed() -> None:
    """The two halves of the fix, stated directly."""
    assert Settings.load(stream_timeout=None).stream_timeout is None
    assert Settings.load(api_key=None).api_key is None
    assert XMagicClient(api_key="k").settings.stream_timeout == 300.0
