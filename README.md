# xmagic-sdk

[![PyPI](https://img.shields.io/pypi/v/xmagic-sdk.svg)](https://pypi.org/project/xmagic-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/xmagic-sdk.svg)](https://pypi.org/project/xmagic-sdk/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![CI](https://github.com/stochasticai/xmagic-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/stochasticai/xmagic-sdk/actions/workflows/ci.yml)

Python SDK and CLI for [xMagic](https://xmagic.ai), Stochastic's AI agent platform.

> **Status: alpha scaffold.** Parts of the surface below are still stubs that
> raise `NotImplementedError` — each is marked with the roadmap phase that
> implements it. See [DESIGN.md](DESIGN.md) for the design plan,
> [TODO.md](TODO.md) for current work, and [CHANGELOG.md](CHANGELOG.md) for
> what shipped.

## What it does

Working today:

1. **MCP servers** — scaffold containerized (Dockerfile included) MCP servers you can
   register as xMagic custom tools.
2. **xMagic API** — chat (sync + streaming), file uploads, Drive (knowledge base),
   skills packaging, with a matching async client. Request/response shapes are
   verified against the live API and locked with recorded-fixture tests.

Planned:

3. **Multi-provider** *(Phase 3)* — one interface across xMagic, OpenAI, Anthropic,
   Google, and (via LiteLLM) 100+ more. Only the xMagic provider is implemented so
   far; the others are stubs.
4. **Bring your own model** *(Phase 3)* — `provider:model` refs with your own API keys.
5. **Local web app** *(Phase 5)* — `xmagic serve` runs the xMagic web app locally
   via proxy.

## Install

Requires **Python 3.11–3.14**.

```bash
uv pip install xmagic-sdk            # core
uv pip install "xmagic-sdk[all]"     # + all provider/serve/mcp extras
```

Extras are granular if you don't want everything — `[mcp]` for the server
scaffold, `[serve]` for the local web app, and `[openai]` / `[anthropic]` /
`[google]` / `[litellm]` per provider. `pip` works too if you don't use `uv`.

From a checkout:

```bash
uv pip install -e .             # core
uv pip install -e ".[all]"      # + all provider/serve/mcp extras
```

Verify it landed:

```bash
xmagic version
```

## Getting started

### 1. Get an API key

In [xmagic.ai](https://xmagic.ai): **profile → API keys**. You'll also want an
**agent id** — create an agent in Studio, and its id appears in the agent's URL.

### 2. Configure

```bash
xmagic configure                 # prompts for the key, hidden input
```

This writes `~/.config/xmagic/config.toml` with mode `600`. Pass
`--agent <agent_id>` to set a default agent, or `--api-key` to skip the prompt
in a script.

Prefer environment variables? `XMAGIC_API_KEY` and `XMAGIC_BASE_URL` both work
and take precedence over the file:

```bash
export XMAGIC_API_KEY="xm-..."
```

Full precedence is **explicit arguments → environment → config file →
defaults**, so you can keep a config file for everyday use and override it
per-command. `XMAGIC_CONFIG_PATH` relocates the file itself.

The config file looks like this, and you can edit it directly:

```toml
[xmagic]
api_key = "xm-..."
base_url = "https://api.xmagic.ai/xmagic-backend/v1"
default_agent_id = "..."

[providers.openai]        # provider keys, once Phase 3 lands
api_key = "sk-..."
```

Provider keys are also read from the usual `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, and `GOOGLE_API_KEY` variables. **Keys are only ever
written to your user config directory, never into a project folder.**

### 3. Talk to your agent

```bash
xmagic chat --agent <agent_id> "Summarize our Q3 goals"   # one-shot
xmagic chat --agent <agent_id>                            # interactive session
```

Responses stream by default; `--no-stream` waits for the full reply instead.
If you set `default_agent_id` during `configure`, drop the `--agent` flag.
When the agent thinks out loud, its reasoning is printed dimmed, above the
answer.

Attach files with `-f` (repeatable), and pick the chat's UI context with
`--chat-type`:

```bash
xmagic chat --agent <agent_id> -f notes.md -f data.csv "What changed?"
xmagic chat --agent <agent_id> --chat-type playground "Try something"
```

An interactive session reuses a single chat, so the agent keeps its context
across turns.

### 4. Use it from Python

```python
from xmagic import XMagicClient

client = XMagicClient()  # reads env/config; or XMagicClient(api_key="xm-...")
chat = client.chats.create("<agent_id>", title="demo")

# Streaming
for event in client.chats.stream("<agent_id>", chat.id, "Explain xMagic skills"):
    if event.type == "response":
        print(event.text, end="")

# Blocking
resp = client.chats.query("<agent_id>", chat.id, "One-sentence summary?")
```

`XMagicClient` is a context manager, so `with XMagicClient() as client:` closes
the underlying HTTP connection for you. It retries `429` and `5xx` with
exponential backoff, honoring `Retry-After`.

`AsyncXMagicClient` mirrors it 1:1 — same resources, same arguments, same
returns. Await each call, and iterate `stream` with `async for`:

```python
from xmagic import AsyncXMagicClient

async with AsyncXMagicClient() as client:
    chat = await client.chats.create("<agent_id>", title="demo")
    async for event in client.chats.stream("<agent_id>", chat.id, "Explain xMagic skills"):
        if event.type == "response":
            print(event.text, end="")
```

### 5. Build a custom tool (MCP server)

```bash
xmagic mcp init my-tool          # scaffold: Dockerfile, compose, FastMCP server
cd my-tool && docker compose up --build
```

That serves MCP over streamable HTTP at `http://localhost:8000/mcp`. xMagic
needs a *public* HTTPS URL to reach it, so for development expose it with a
tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

Then register the resulting `https://.../mcp` URL in the dashboard under
**Custom tools → Create tool**. `xmagic tools register --name ... --url ...`
prints the full checklist. Set `TOOL_API_KEY` in your `.env` to require a
shared secret — the generated server rejects unauthenticated calls with `401`.

### 6. Package a skill

```bash
xmagic skills new my-skill       # scaffold SKILL.md
xmagic skills validate my-skill  # check frontmatter and layout
xmagic skills pack my-skill      # -> my-skill.zip, ready to upload
```

Upload the zip in the dashboard under **Skills**.

### Next steps

Runnable scripts for each of the flows above live in
[`examples/`](examples/) — chat, streaming, files and Drive, and the MCP
scaffold walkthrough (that one needs no API key).

`xmagic --help` lists every command, and each subcommand takes `--help` too.
See [DESIGN.md](DESIGN.md) for how the pieces fit together.

Once the provider adapters land (Phase 3), `chat` will accept a
`provider:model` ref backed by your own key:

```bash
xmagic chat -m anthropic:claude-sonnet-5 "Hello!"   # not yet implemented
```

Today that path exits with a `NotImplementedError` pointing at the roadmap.

## Troubleshooting

**`No API key configured`** — run `xmagic configure`, or export
`XMAGIC_API_KEY`. Check what's actually being picked up with
`xmagic configure --help` and remember env vars override the config file.

**A command prints `... lands in Phase N (see DESIGN.md)`** — that feature is
scaffolded but not implemented yet. See the status note at the top of this
README.

**`401` from your MCP server** — the generated server requires `TOOL_API_KEY`
when set. Send it as either `x-api-key` or `Authorization: Bearer <key>`.

**xMagic can't reach your MCP server** — it must be public HTTPS. `localhost`
won't work; use a tunnel for development.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

CI runs all four across Python 3.11–3.14, and gates on formatting as well as
linting — run `uv run ruff format .` before pushing.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org)
(`feat:`, `fix:`, `docs:`, `test:`, `chore:`, ...; optional scope, e.g. `feat(mcp): ...`).

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup and
the PR workflow, and [ISSUES.md](ISSUES.md) for filing bugs, feature requests,
and security reports. All participants are expected to follow our
[Code of Conduct](CODE_OF_CONDUCT.md).

## License

[Apache-2.0](LICENSE) © Stochastic
