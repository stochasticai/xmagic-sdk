"""Packaging invariants that fail silently if broken.

The `py.typed` marker is the case that motivated this file: without it PEP 561
tells every downstream type checker to treat this package as untyped, so all our
annotations resolve to `Any` in consumers' code. Nothing in the test suite or at
runtime notices, because the annotations are still there in the source we run.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPOSITORY_ROOT / "src" / "xmagic"


def _pyproject() -> dict[str, object]:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def test_py_typed_marker_exists() -> None:
    """PEP 561: no marker, no types for consumers.

    That it reaches the built wheel is checked by building one -- CI's `build
    distributions` job -- since hatchling picks it up implicitly from the package
    directory rather than from an entry in pyproject.toml.
    """
    assert (PACKAGE_ROOT / "py.typed").is_file()


def test_py_typed_is_not_excluded_from_version_control() -> None:
    """Hatchling's default file selection skips VCS-ignored files.

    An ignore rule broad enough to cover the marker would drop it from the wheel
    while leaving every local test green.
    """
    ignore_rules = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").split()

    assert "py.typed" not in ignore_rules
    assert "*.typed" not in ignore_rules


def test_sdist_still_ships_the_sources() -> None:
    """`include` is an allowlist: dropping "src" would ship an empty sdist."""
    sdist = _pyproject()["tool"]["hatch"]["build"]["targets"]["sdist"]  # type: ignore[index]

    assert "src" in sdist["include"]
