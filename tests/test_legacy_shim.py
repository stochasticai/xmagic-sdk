"""The `xmagic_sdk` shim must fail loudly and usefully.

Releases 0.0.1-0.0.3 shipped a top-level `xmagic_sdk` package under this same
distribution name. Upgrading removes it, so the shim's whole job is to replace a
bare ModuleNotFoundError with a message that names the boundary and the escape
hatch. These tests pin that message, because a shim with a vague message is
worth roughly nothing.
"""

from __future__ import annotations

import importlib

import pytest


def _import_error() -> str:
    with pytest.raises(ImportError) as excinfo:
        importlib.import_module("xmagic_sdk")
    return str(excinfo.value)


def test_importing_the_legacy_package_raises_importerror() -> None:
    # ImportError specifically, so `try: import xmagic_sdk / except ImportError`
    # in downstream code still does the right thing.
    assert _import_error()


def test_message_names_the_replacement_and_the_version_boundary() -> None:
    msg = _import_error()
    assert "xmagic_sdk" in msg
    assert "import xmagic" in msg
    assert "0.1.0" in msg


def test_message_offers_the_pin_for_users_who_need_the_old_api() -> None:
    # The 0.0.x deploy commands have no equivalent today, so "pin 0.0.3" is the
    # only honest advice we can give. If that stops being true, update this test.
    msg = _import_error()
    assert "xmagic-sdk==0.0.3" in msg
