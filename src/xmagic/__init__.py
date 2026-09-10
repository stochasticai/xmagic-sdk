"""xmagic-sdk: Python SDK and CLI for xMagic, Stochastic's AI agent platform.

Quickstart::

    from xmagic import XMagicClient

    client = XMagicClient()  # reads XMAGIC_API_KEY from env/config
    chat = client.chats.create(agent_id="...", title="demo")
    resp = client.chats.query(agent_id="...", chat_id=chat.id, query="Hello!")
    print(resp.text)
"""

import logging

from xmagic._version import __version__
from xmagic.client import AsyncXMagicClient, XMagicClient
from xmagic.client.models import ChatType
from xmagic.client.streaming import AsyncStream, Stream
from xmagic.config import Settings
from xmagic.errors import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConfigurationError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    XMagicAPIError,
    XMagicError,
)

# The package logs under "xmagic" (transport under "xmagic.http") and, like any
# library, says nothing unless the application asks: attach a handler or call
# `logging.basicConfig()` to see it. Request and response lines are DEBUG,
# retries are INFO; headers and bodies are never logged, so the API key cannot
# leak through here.
logging.getLogger("xmagic").addHandler(logging.NullHandler())

__all__ = [
    "APIConnectionError",
    "APITimeoutError",
    "AsyncStream",
    "AsyncXMagicClient",
    "AuthenticationError",
    "BadRequestError",
    "ChatType",
    "ConfigurationError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "ServerError",
    "Settings",
    "Stream",
    "XMagicAPIError",
    "XMagicClient",
    "XMagicError",
    "__version__",
]
