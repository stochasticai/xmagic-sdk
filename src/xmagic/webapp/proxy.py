"""Reverse proxy serving the xMagic web app locally (``xmagic serve``).

Design (see DESIGN.md §7):

- Starlette app on localhost forwarding requests to the upstream xMagic web
  app (hosted, or a self-hosted instance via ``--upstream``).
- Streams request/response bodies; rewrites Host/cookie headers via an
  allowlist; injects local configuration.
- Known risks: CSP headers, third-party auth cookies, upstream frontend
  changes. Fallback: a minimal built-in chat page backed by the SDK.

Full implementation lands in Phase 5. Requires extra: ``xmagic-sdk[serve]``.
"""

from __future__ import annotations

DEFAULT_PORT = 8377
DEFAULT_UPSTREAM = "https://xmagic.ai"


def run_proxy(port: int = DEFAULT_PORT, upstream: str = DEFAULT_UPSTREAM) -> None:
    """Start the local proxy server (blocking)."""
    try:
        import starlette  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "The local web app requires the extra: pip install 'xmagic-sdk[serve]'"
        ) from e
    raise NotImplementedError("The local web app proxy lands in Phase 5 (see DESIGN.md roadmap).")
