"""Test your own code against a fake xMagic, with no key and no network.

`xmagic.testing.FakeXMagic` stands in for the backend. The real client talks to
it through an httpx transport, it keeps state (chats, uploads, Drive folders),
and it answers in the shapes recorded from the live API. Script what an agent
replies, run the code under test, then assert on what it sent.

This file is both an example and a runnable check: it defines a small function
that uses the SDK, then tests it the way a consumer's pytest suite would.

Run:
    uv run python examples/08_offline_tests.py
    uv run pytest examples/08_offline_tests.py      # the same file, as tests
"""

from __future__ import annotations

from xmagic import XMagicClient
from xmagic.testing import FakeXMagic

# --- the code under test: something a consumer might write ------------------------


def ask_for_summary(client: XMagicClient, agent_id: str, text: str) -> str:
    """Open a chat, ask the agent for a one-line summary, return it stripped."""
    chat = client.chats.create(agent_id, title="summary")
    reply = client.chats.query(agent_id, chat.id, f"Summarize in one line:\n{text}")
    return reply.text.strip()


# --- the tests -------------------------------------------------------------------------


def test_summary_is_the_agents_reply() -> None:
    fake = FakeXMagic()
    fake.agent("agent-1").replies("  Three bullet points about Q3.  ")

    result = ask_for_summary(fake.client(), "agent-1", "long notes...")

    assert result == "Three bullet points about Q3."


def test_summary_sends_the_text_and_opens_one_chat() -> None:
    fake = FakeXMagic()

    ask_for_summary(fake.client(), "agent-1", "long notes...")

    create, query = fake.calls
    assert create.path == "/agents/agent-1/chats"
    assert create.json == {"chat_type": "standard", "title": "summary"}
    assert query.json == {"query": "Summarize in one line:\nlong notes...", "is_stream": False}
    assert len(fake.chats) == 1


def test_a_reply_can_depend_on_the_question() -> None:
    fake = FakeXMagic()
    fake.agent("agent-1").replies(lambda q: f"{len(q.splitlines())} lines seen")

    assert ask_for_summary(fake.client(), "agent-1", "a\nb\nc") == "4 lines seen"


if __name__ == "__main__":
    for test in (
        test_summary_is_the_agents_reply,
        test_summary_sends_the_text_and_opens_one_chat,
        test_a_reply_can_depend_on_the_question,
    ):
        test()
        print(f"ok  {test.__name__}")
