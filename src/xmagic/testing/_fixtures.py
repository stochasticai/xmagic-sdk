"""Access to the recorded API fixtures that ship with the package.

Every file under ``xmagic/testing/fixtures/`` was captured from the live xMagic
API and redacted (see the README there). The SDK's own contract tests replay
them, and :class:`xmagic.testing.FakeXMagic` renders its responses from them,
so a consumer's tests and this package's tests pin the same shapes.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def fixture_path(name: str) -> Path:
    """The on-disk path of a recorded fixture, for callers that want the raw file."""
    path = FIXTURES_DIR / name
    if not path.is_file():
        available = ", ".join(sorted(p.name for p in FIXTURES_DIR.iterdir() if p.suffix != ".md"))
        raise FileNotFoundError(f"No recorded fixture named {name!r}. Available: {available}")
    return path


@cache
def _load_json(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(fixture_path(name).read_text())
    loaded.pop("_comment", None)
    return loaded


def load_fixture(name: str) -> dict[str, Any]:
    """A recorded JSON response body, as the client would parse it.

    The recording's ``_comment`` key (provenance, not payload) is dropped. The
    result is a fresh copy each time, so a caller may edit it freely.
    """
    copy: dict[str, Any] = json.loads(json.dumps(_load_json(name)))
    return copy


def load_text_fixture(name: str) -> str:
    """A recorded text fixture verbatim, annotations included."""
    return fixture_path(name).read_text()


def sse_frames(name: str) -> str:
    """The raw ``data:`` frames of a recorded SSE fixture, ready to serve as a body.

    The recording is annotated prose above the frames; only lines starting
    with ``data: `` are wire content, joined with the blank line SSE requires.
    """
    lines = [line for line in load_text_fixture(name).splitlines() if line.startswith("data: ")]
    return "\n\n".join(lines) + "\n\n"
