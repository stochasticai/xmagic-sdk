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

Start with `04_mcp_server.py` if you don't have credentials yet — it only writes
files locally.

## Setup

The three API examples need a key and an agent id:

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

Each script resolves the agent as `XMAGIC_AGENT_ID` first, then the
`default_agent_id` in `~/.config/xmagic/config.toml`, and exits with a hint if
it finds neither.

## Notes

- `03_files_and_drive.py` creates a Drive folder named `xmagic-sdk-example` and
  **deletes it on the way out**. Pass `--keep` to inspect it in the dashboard
  instead.
- Examples call the live API, which counts against your plan's rate limit
  (Free 20 rpm / Pro 100 / Business 500). The client retries `429` with backoff
  automatically.
- A **multi-provider** example (`provider:model` refs backed by your own key) is
  planned but not written yet: only the xMagic provider is implemented today, and
  the OpenAI/Anthropic/Google/LiteLLM adapters raise `NotImplementedError` until
  Phase 3 of the [roadmap](../DESIGN.md) lands.
