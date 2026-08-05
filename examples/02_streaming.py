"""Streaming: consume Server-Sent Events from a query as they arrive.

Shows the event types a live agent actually emits, and how to tell the agent's
thinking (`reasoning`) apart from its answer (`response`).

Run:
    export XMAGIC_API_KEY="xm-..."
    export XMAGIC_AGENT_ID="<agent_id>"     # or: xmagic configure --agent <id>
    uv run python examples/02_streaming.py
"""

from __future__ import annotations

import os
import sys

from xmagic import XMagicClient
from xmagic.errors import ConfigurationError, XMagicAPIError

DIM = "\033[2m"
RESET = "\033[0m"


def main() -> int:
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

        # Only dim reasoning when stdout is a terminal, so piping to a file or
        # another program does not pick up escape codes.
        color = sys.stdout.isatty()
        message_id = None

        try:
            chat = client.chats.create(agent_id, title="SDK example: streaming")
            stream = client.chats.stream(
                agent_id, chat.id, "Explain xMagic skills in two short paragraphs."
            )

            for event in stream:
                if event.type == "response":
                    # Incremental answer text. Flush so it appears token by token.
                    print(event.text, end="", flush=True)
                elif event.type == "reasoning":
                    text = f"{DIM}{event.text}{RESET}" if color else event.text
                    print(text, end="", flush=True)
                elif event.type == "metadata":
                    # Carries the message_id for the turn, under raw["data"].
                    data = event.raw.get("data")
                    if isinstance(data, dict):
                        message_id = data.get("message_id")
                elif event.type == "error":
                    print(f"\nstream error: {event.text}", file=sys.stderr)
                    return 1
                elif event.type == "done":
                    # Synthetic event for the `data: [DONE]` sentinel frame.
                    print()

        except XMagicAPIError as e:
            print(f"\nAPI error: {e}", file=sys.stderr)
            return 1

        if message_id:
            print(f"\nmessage id: {message_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
