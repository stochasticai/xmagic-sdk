"""The installed version, in a module with no imports from the rest of the package.

`xmagic/__init__.py` imports the client, and the client's transport needs the
version for its `User-Agent`; reading it here keeps that from being a cycle.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _installed_version

try:
    __version__ = _installed_version("xmagic-sdk")
except PackageNotFoundError:  # running from a source checkout, not installed
    __version__ = "0.0.0+unknown"
