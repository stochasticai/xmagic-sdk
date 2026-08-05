"""Basic chat: create a chat, ask one question, read the answer.

Run:
    export XMAGIC_API_KEY="xm-..."
    export XMAGIC_AGENT_ID="<agent_id>"     # or: xmagic configure --agent <id>
    uv run python examples/01_basic_chat.py
"""

from __future__ import annotations

import os
import sys

from xmagic import XMagicClient
from xmagic.errors import (
    AuthenticationError,
    ConfigurationError,
    NotFoundError,
    RateLimitError,
    XMagicAPIError,
)


def main() -> int:
    # XMagicClient() resolves credentials from, in order: explicit arguments,
    # environment variables, ~/.config/xmagic/config.toml, defaults. It raises
    # ConfigurationError up front if no key turns up.
    try:
        client = XMagicClient()
    except ConfigurationError as e:
        print(e, file=sys.stderr)
        return 2

    with client:
        agent_id = os.environ.get("XMAGIC_AGENT_ID") or client.settings.default_agent_id
        if not agent_id:
            print(
                "No agent id. Set XMAGIC_AGENT_ID, or run `xmagic configure --agent <id>`.",
                file=sys.stderr,
            )
            return 2

        try:
            chat = client.chats.create(agent_id, title="SDK example: basic chat")
            print(f"chat id: {chat.id}")

            response = client.chats.query(agent_id, chat.id, "In one sentence, what is xMagic?")
            print(f"\n{response.text}")

            # message_id lets you fetch the stored message later, including any
            # files the agent produced (output_assets maps output id -> S3 path).
            if response.message_id:
                message = client.chats.get_message(agent_id, chat.id, response.message_id)
                if message.output_assets:
                    print(f"\noutputs: {list(message.output_assets)}")

        except AuthenticationError:
            print("Invalid or missing API key. Run `xmagic configure`.", file=sys.stderr)
            return 1
        except NotFoundError:
            print(
                f"Agent {agent_id!r} not found — check the id in the agent's URL.", file=sys.stderr
            )
            return 1
        except RateLimitError:
            # The client already retries 429 with backoff, honoring Retry-After.
            # Reaching here means the retries were exhausted.
            print("Rate limited, and retries were exhausted.", file=sys.stderr)
            return 1
        except XMagicAPIError as e:
            print(f"API error: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
