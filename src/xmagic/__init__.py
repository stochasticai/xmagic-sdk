"""xmagic-sdk: Python SDK and CLI for xMagic, Stochastic's AI agent platform.

Quickstart::

    from xmagic import XMagicClient

    client = XMagicClient()  # reads XMAGIC_API_KEY from env/config
    chat = client.chats.create(agent_id="...", title="demo")
    resp = client.chats.query(agent_id="...", chat_id=chat.id, query="Hello!")
    print(resp.text)
"""

from xmagic.client import AsyncXMagicClient, XMagicClient
from xmagic.config import Settings
from xmagic.errors import (
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    XMagicAPIError,
    XMagicError,
)

__version__ = "0.1.0"

__all__ = [
    "AsyncXMagicClient",
    "AuthenticationError",
    "NotFoundError",
    "RateLimitError",
    "Settings",
    "XMagicAPIError",
    "XMagicClient",
    "XMagicError",
    "__version__",
]
