"""Test support for code that uses this SDK.

Two things live here: :class:`FakeXMagic`, an in-process fake of the xMagic
backend that the real client talks to through an ``httpx`` transport, and the
recorded API fixtures it renders from, exposed through :func:`load_fixture`
and friends for tests that would rather mock a route themselves.

Neither needs a key or the network. See ``fixtures/README.md`` in this
package for how the recordings are made.
"""

from xmagic.testing._fake import (
    AgentScript,
    FakeChat,
    FakeFile,
    FakeFolder,
    FakeMessage,
    FakeUpload,
    FakeXMagic,
    RecordedCall,
)
from xmagic.testing._fixtures import (
    FIXTURES_DIR,
    fixture_path,
    load_fixture,
    load_text_fixture,
    sse_frames,
)

__all__ = [
    "FIXTURES_DIR",
    "AgentScript",
    "FakeChat",
    "FakeFile",
    "FakeFolder",
    "FakeMessage",
    "FakeUpload",
    "FakeXMagic",
    "RecordedCall",
    "fixture_path",
    "load_fixture",
    "load_text_fixture",
    "sse_frames",
]
