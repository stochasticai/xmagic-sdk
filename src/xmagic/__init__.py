"""xmagic-sdk: Python SDK and CLI for xMagic, Stochastic's AI agent platform.

Quickstart::

    from xmagic import XMagicClient

    client = XMagicClient()  # reads XMAGIC_API_KEY from env/config
    chat = client.chats.create(agent_id="...", title="demo")
    resp = client.chats.query(agent_id="...", chat_id=chat.id, query="Hello!")
    print(resp.text)
"""

from importlib.metadata import PackageNotFoundError, version as _installed_version

from xmagic.client import AsyncXMagicClient, XMagicClient
from xmagic.client.models import ChatType
from xmagic.config import Settings
from xmagic.errors import (
    APIConnectionError,
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

try:
    __version__ = _installed_version("xmagic-sdk")
except PackageNotFoundError:  # running from a source checkout, not installed
    __version__ = "0.0.0+unknown"

__all__ = [
    "APIConnectionError",
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
    "XMagicAPIError",
    "XMagicClient",
    "XMagicError",
    "__version__",
]
