"""The version is declared in more than one place. They must agree.

`pyproject.toml` is the source of truth: the release workflow's guard compares it
against the git tag via `uv version --short`, and it is what ends up in the built
distribution's metadata.

`xmagic.__version__` no longer repeats it -- it reads the installed distribution
metadata -- so the assertion here is really "the installed distribution matches
this working tree", which catches a stale editable install as well as a broken
fallback.

`CITATION.cff` genuinely cannot be derived, so it is checked rather than removed.
It drifted silently before: it carried a "add date-released when 0.1.0 ships"
TODO for weeks after 0.1.0 had shipped.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import xmagic

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CITATION = ROOT / "CITATION.cff"


def _pyproject_version() -> str:
    return tomllib.loads(PYPROJECT.read_text())["project"]["version"]


def _citation_version() -> str:
    # Deliberately not a YAML parse: pyyaml is not a dependency, and the field is
    # a plain scalar on its own line.
    for line in CITATION.read_text().splitlines():
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    pytest.fail("CITATION.cff has no `version:` line")


def test_runtime_version_matches_pyproject() -> None:
    """A mismatch means the installed distribution is stale -- `uv sync` fixes it.

    This is what `xmagic version` prints, so drift here is what users would see.
    """
    assert xmagic.__version__ == _pyproject_version()


def test_citation_version_matches_pyproject() -> None:
    assert _citation_version() == _pyproject_version()


def test_version_is_not_the_uninstalled_fallback() -> None:
    # The fallback exists so importing from a bare checkout does not explode. If
    # it shows up in a test run, the package is not installed and every other
    # assertion in this file is meaningless.
    assert xmagic.__version__ != "0.0.0+unknown"
