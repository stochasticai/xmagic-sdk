"""A minimal MCP client, for exercising a custom tool without deploying it.

The dev loop for an xMagic custom tool is otherwise: ``docker compose up`` ->
tunnel -> register in the dashboard -> open a chat -> hope the agent decides to
call the tool. That is minutes per iteration, and the last step is not under the
developer's control, so a broken tool and a tool the agent simply declined to
invoke look identical.

These helpers speak MCP straight to a running server: no xMagic account, no
tunnel, no registration. They also let the test suite drive a scaffolded server
directly, which is how ``mcp init`` gets an integration test rather than a
syntax check.

Note what this does and does not prove. It verifies the server answers MCP
correctly; it does **not** verify that xMagic can call it, since the transport
xMagic's runtime actually speaks is still an open question (DESIGN.md §10.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xmagic.errors import XMagicError


@dataclass
class ToolInfo:
    """One tool as advertised by a server."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolResult:
    """The outcome of a tool call, flattened for display."""

    is_error: bool
    text: str
    structured: dict[str, Any] | None = None


def _import_client() -> Any:
    try:
        from mcp import Client
    except ImportError as e:  # pragma: no cover - exercised by the extra being absent
        raise ImportError(
            "MCP client support requires the extra: pip install 'xmagic-sdk[mcp]'"
        ) from e
    return Client


def _target(url_or_server: Any, api_key: str | None) -> Any:
    """Resolve what to hand `Client`.

    A server object (or anything non-string) is passed straight through, which is
    what lets tests drive a scaffolded server over MCP's in-memory transport. A
    URL becomes a streamable-HTTP transport; an API key rides on a preconfigured
    httpx client, since `Client` itself takes no headers.
    """
    if not isinstance(url_or_server, str):
        return url_or_server
    if not api_key:
        return url_or_server

    # `httpx2`, not the `httpx` the rest of this package uses: mcp depends on
    # httpx2 (a separate distribution, 2.x) and calls `.sse()` on whatever client
    # it is handed, which httpx 0.28 has no equivalent for. Passing our own
    # client happens to work for request/response tools -- that path never
    # reaches `.sse` -- but breaks the moment a server uses the standalone SSE
    # stream. Both arrive with the [mcp] extra, so importing it here is safe.
    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    # Both header styles, because which one xMagic sends is unconfirmed and the
    # generated template accepts either (TODO.md, Phase 2).
    headers = {"x-api-key": api_key, "Authorization": f"Bearer {api_key}"}
    return streamable_http_client(url_or_server, http_client=httpx2.AsyncClient(headers=headers))


async def list_tools(url_or_server: Any, api_key: str | None = None) -> list[ToolInfo]:
    """Ask a server what it can do."""
    client_cls = _import_client()
    try:
        async with client_cls(_target(url_or_server, api_key)) as client:
            listed = await client.list_tools()
    except Exception as e:
        raise _wrap(e, url_or_server) from e
    return [
        ToolInfo(
            name=tool.name,
            description=tool.description or "",
            # mcp 2.0 names this `input_schema`; 1.x used the wire spelling
            # `inputSchema`. We pin to 2.x, but reading both costs nothing and
            # this attribute is exactly the kind that gets renamed back.
            input_schema=getattr(tool, "input_schema", None)
            or getattr(tool, "inputSchema", None)
            or {},
        )
        for tool in listed.tools
    ]


async def call_tool(
    url_or_server: Any,
    name: str,
    arguments: dict[str, Any] | None = None,
    api_key: str | None = None,
) -> ToolResult:
    """Invoke one tool and flatten the response for display."""
    client_cls = _import_client()
    try:
        async with client_cls(_target(url_or_server, api_key)) as client:
            result = await client.call_tool(name, arguments or {})
    except Exception as e:
        raise _wrap(e, url_or_server) from e

    blocks = getattr(result, "content", None) or []
    text = "\n".join(getattr(b, "text", "") for b in blocks if getattr(b, "text", None))
    return ToolResult(
        is_error=bool(getattr(result, "isError", False)),
        text=text,
        structured=getattr(result, "structuredContent", None),
    )


def _innermost(exc: BaseException) -> BaseException:
    """Dig the real failure out of anyio's nested ExceptionGroups.

    Without this, a plain 401 surfaces as "ExceptionGroup: unhandled errors in a
    TaskGroup (1 sub-exception)", which tells a developer nothing about the tool
    they are trying to reach.
    """
    seen = 0
    while (subs := getattr(exc, "exceptions", None)) and seen < 10:
        exc = subs[0]
        seen += 1
    return exc


def _wrap(exc: Exception, target: Any) -> Exception:
    """Turn transport failures into this SDK's error type.

    A tool that is not running, or is rejecting the key, are the two most common
    outcomes while developing one. Both should read as such.
    """
    if isinstance(exc, XMagicError):
        return exc
    where = target if isinstance(target, str) else "the server"
    cause = _innermost(exc)
    detail = f"{type(cause).__name__}: {cause}"

    # A rejected key is the most likely reason a *reachable* server refuses, but
    # the HTTP status does not survive: mcp collapses it into a generic MCPError
    # with code -32603. So hint rather than assert a status we never saw.
    if getattr(cause, "error", None) is not None:
        return XMagicError(
            f"MCP request to {where} failed: {detail}. If the server requires an "
            "API key, pass --api-key — the generated template rejects "
            "unauthenticated calls with 401."
        )
    return XMagicError(f"MCP request to {where} failed: {detail}")
