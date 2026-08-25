# Examples

Small runnable scripts, each covering one thing. Run them from the repo root.

```bash
uv sync --all-extras
uv run python examples/01_basic_chat.py
```

| Example | What it shows | Needs an API key |
|---|---|---|
| [`01_basic_chat.py`](01_basic_chat.py) | Create a chat, send a blocking query, fetch the stored message and its output assets. Typed error handling. | yes |
| [`02_streaming.py`](02_streaming.py) | Consume SSE events as they arrive; separate `reasoning` from `response`, capture `message_id` from `metadata`. | yes |
| [`03_files_and_drive.py`](03_files_and_drive.py) | Upload a file and reference it in a query, then index one into a Drive knowledge-base folder. | yes |
| [`04_mcp_server.py`](04_mcp_server.py) | Scaffold a containerized MCP server (a custom tool) and walk through registering it. | **no** |
| [`05_skills.py`](05_skills.py) | Scaffold, validate, and pack a skill into an upload-ready zip. | **no** |
| [`06_provider_model.py`](06_provider_model.py) | Bring your own model: resolve a `provider:model` ref, read its capabilities, stream the answer. Works with OpenAI, any LiteLLM vendor, or a local model. | **no** (needs a *vendor* key, or none at all for Ollama) |

Start with `04_mcp_server.py` or `05_skills.py` if you don't have credentials
yet — they only write files locally. `06_provider_model.py` needs no xMagic key
either, and runs against a local model with no key at all.

## Setup

The API examples need a key and an agent id:

```bash
export XMAGIC_API_KEY="xm-..."
export XMAGIC_AGENT_ID="<agent_id>"
```

Or persist both, so the examples pick them up with no environment variables at all:

```bash
xmagic configure --agent <agent_id>
```

Get a key from [xmagic.ai](https://xmagic.ai) under **profile → API keys**. The
agent id is in the agent's URL in Studio.

The first three scripts resolve the agent as `XMAGIC_AGENT_ID` first, then the
`default_agent_id` in `~/.config/xmagic/config.toml`.

## Notes

- `03_files_and_drive.py` creates a Drive folder named `xmagic-sdk-example` and
  **deletes it on the way out**. Pass `--keep` to inspect it in the dashboard
  instead.
- Examples call the live API, which counts against your plan's rate limit
  (Free 20 rpm / Pro 100 / Business 500). The client retries `429` with backoff
  automatically.
- `01`–`03` use the sync client. Everything they do is also available on
  `AsyncXMagicClient`, which mirrors it 1:1 — `await` each call and iterate
  `stream` with `async for`.
- `06_provider_model.py` takes an optional `provider:model` ref as its one
  argument and defaults to `openai:gpt-5`. It calls a third-party vendor, not
  xMagic, so it spends that vendor's credits rather than your xMagic quota.
  `AnthropicProvider` and `GoogleProvider` remain unimplemented on purpose —
  reach both through `litellm:` (see [DESIGN.md](../DESIGN.md) §4).
