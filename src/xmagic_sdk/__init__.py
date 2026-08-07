"""Compatibility shim for the pre-0.1.0 ``xmagic_sdk`` package.

Releases 0.0.1-0.0.3 of the ``xmagic-sdk`` distribution installed a top-level
``xmagic_sdk`` package. From 0.1.0 the same distribution installs ``xmagic``
instead, with a different public API. Upgrading in place therefore deletes
``xmagic_sdk`` from the environment, and ``import xmagic_sdk`` would fail with a
bare ``ModuleNotFoundError`` that says nothing about why.

This module exists only to make that boundary legible. It ships no
functionality and is scheduled for removal in 1.0.
"""

from __future__ import annotations

_MESSAGE = """\
The `xmagic_sdk` package was replaced by `xmagic` in xmagic-sdk 0.1.0.

    import xmagic_sdk           ->  import xmagic
    from xmagic_sdk import ...  ->  from xmagic import ...

This is not a straight rename: the public API changed too. The 0.0.x helpers
(`run_mcp_server`, `fetch_info_from_kb_v1`, `fetch_info_from_kb_v3`, `registry`)
and the hosted deployment commands (`xmagic mcp run` / `list` / `logs` / `start`
/ `stop` / `delete` / `validate`) have no equivalent in the current release.

If you depend on those, pin the old line until they are reimplemented:

    pip install 'xmagic-sdk==0.0.3'

See https://github.com/stochasticai/xmagic-sdk/blob/main/CHANGELOG.md
"""

raise ImportError(_MESSAGE)
