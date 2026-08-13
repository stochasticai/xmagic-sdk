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
   Worklists, skills packaging, with a matching async client. Request/response shapes are
   verified against the live API and locked with recorded-fixture tests.
3. **Bring your own model** — `provider:model` refs backed by your own key.
   `xmagic:<agent_id>` and `openai:<model>` work today, over one `Provider`
   interface.

Planned:

4. **More providers** *(Phase 3)* — `litellm:` for the ~150 vendors LiteLLM
   reaches, including Anthropic and Google. Their native adapters
   (`anthropic:`, `google:`) are reserved but unimplemented.
5. **Local web app** *(Phase 5)* — `xmagic serve` runs the xMagic web app locally
   via proxy.

## Install

Requires **Python 3.11–3.14**.

```bash
uv pip install xmagic-sdk            # core
uv pip install "xmagic-sdk[all]"     # + all provider/serve/mcp extras
```

Extras are granular if you don't want everything — `[mcp]` for the server
scaffold, `[serve]` for the local web app, `[openai]` for the OpenAI provider,
and `[litellm]` for the long tail. There is no `[anthropic]` or `[google]`:
those adapters aren't implemented, and LiteLLM already reaches both. `pip` works
too if you don't use `uv`.

> **You install `xmagic-sdk` but import `xmagic`.** The two names differ because
> `xmagic` on PyPI belongs to an unrelated project registered in 2022, so it was
> never available to us.
>
> If you used this package **before 0.1.0**, note that releases 0.0.1–0.0.3
> installed a `xmagic_sdk` module with a completely different API. Upgrading
> removes it, so `import xmagic_sdk` will now raise an error explaining the
> change. Pin `xmagic-sdk==0.0.3` if you still depend on that API — see
> [CHANGELOG.md](CHANGELOG.md) for what moved.

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

[providers.openai]        # used by `-m openai:<model>`
api_key = "sk-..."
```

Provider keys are also read from the usual `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, and `GOOGLE_API_KEY` variables. **Keys are only ever
written to your user config directory, never into a project folder.**

### 3. Select your workspace and list agents

```bash
xmagic workspaces                         # list accessible workspaces
xmagic workspaces "Workspace Name"        # switch by exact name
xmagic workspaces --id <workspace_id>     # switch by id

xmagic agents                             # list agents in current workspace context
```

`xmagic workspaces` prints each workspace's name, id, and access level. 

### 4. Edit temporary agent config in YAML

```bash
xmagic agents config --agent <agent_id>
```

If `--agent` is omitted, the CLI falls back to `default_agent_id` from
`xmagic configure --agent ...`. The command fetches temporary config from
the backend, opens your editor (`VISUAL`, then `EDITOR`,
then OS default), and on save pushes the update.

### 5. Deploy the agent config

```bash
xmagic agents deploy --agent <agent_id>
xmagic agents deploy --agent <agent_id> --version "Q3 rollout"
xmagic agents deploy --agent <agent_id> --phone <phone_id>
xmagic agents deploy --agent <agent_id> --no-phone       # CI/non-interactive use
```

`xmagic agents deploy` saves the current temporary config as a named version
and deploys it. If `--version` is omitted, the CLI uses the current
date/time as the version name. Without `--phone` or `--no-phone`, the command
offers optional phone and subagent association interactively. Use `--no-phone`
when running unattended. If `VISUAL` or `EDITOR` points to a GUI editor such as
VS Code, include its wait flag (for example, `code --wait`) when editing YAML.

### 6. Talk to your agent

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

### 7. Manage Worklists

List one page of background tasks, inspect a task and its latest result, or
control its execution:

```bash
xmagic worklists --agent <agent_id>
xmagic worklists get <task_id> --agent <agent_id>
xmagic worklists cancel <task_id> --agent <agent_id>
xmagic worklists delete <task_id> --agent <agent_id> --yes
xmagic worklists trigger <task_id> --agent <agent_id>
xmagic worklists rerun <task_id> --agent <agent_id>
xmagic worklists review [task_id] --agent <agent_id>
```

`xmagic worklists create` opens a pre-filled YAML template, while `edit` and
`schedules edit` open the current editable fields in the configured editor
(`VISUAL`, then `EDITOR`, then the platform default). Save the file to submit
the changes. List pagination is deliberately single-page: use `--skip` and
`--limit` (1–200) when fetching another page; the CLI reports the page size and
total count instead of silently making additional requests.

`worklists review` displays the latest result for each task in `needs_review`,
one at a time. Enter a message to send guidance to the agent in the task's
existing chat thread. Press Enter without a message to complete the task
without another agent action, or type `/skip` to leave it in `needs_review` for
later. Pass a task ID to review one task.

Recurring schedules can also be inspected and controlled with
`xmagic worklists schedules get|edit|pause|resume|delete`. Worklist
`input_s3_file_paths` values must currently be existing S3 paths. Direct upload
of local files from the Worklist CLI is deferred future work; use the existing
file/Drive upload APIs first.

### 8. Use it from Python

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

# Non-interactive worklist review. No message completes the task without
# another agent action; a message continues the existing worklist run chat.
review = client.worklists.review("<agent_id>", "<task_id>", message="Approved")
print(review.action, review.task.id)
```

`XMagicClient` is a context manager, so `with XMagicClient() as client:` closes
the underlying HTTP connection for you. It retries `429` and `5xx` with
jittered exponential backoff, honoring `Retry-After`.

Timeouts come in two flavours, because streams need a looser bound than unary
calls — `timeout` (default 60s) bounds a whole request, while `stream_timeout`
(default 300s, `None` waits forever) bounds the *gap between two stream events*,
so an agent that thinks for a while is not mistaken for a dead connection:

```python
client = XMagicClient(timeout=30.0, stream_timeout=600.0, max_retries=5)
```

Everything that can go wrong raises a subclass of `XMagicError`, so one `except`
contains the SDK — including connection failures, which are wrapped rather than
leaked as `httpx` exceptions:

```python
from xmagic import APIConnectionError, RateLimitError, XMagicAPIError, XMagicError

try:
    resp = client.chats.query("<agent_id>", chat.id, "Hello!")
except RateLimitError:
    ...  # 429, after the retries were exhausted
except APIConnectionError:
    ...  # never got a response at all; APITimeoutError is a subclass
except XMagicAPIError as e:
    print(e.status_code, e.request_id)  # also .error_code, .response, .headers, .body
except XMagicError:
    ...  # everything else, e.g. ConfigurationError
```

The status-specific classes are `BadRequestError` (400), `AuthenticationError`
(401), `PermissionDeniedError` (403), `NotFoundError` (404), `RateLimitError`
(429), and `ServerError` (any 5xx).

The package ships a `py.typed` marker, so mypy and pyright see its annotations
rather than `Any`.

`AsyncXMagicClient` mirrors it 1:1 — same resources, same arguments, same
returns. Await each call, and iterate `stream` with `async for`:

```python
from xmagic import AsyncXMagicClient

async with AsyncXMagicClient() as client:
    chat = await client.chats.create("<agent_id>", title="demo")
    async for event in client.chats.stream("<agent_id>", chat.id, "Explain xMagic skills"):
        if event.type == "response":
            print(event.text, end="")

      review = await client.worklists.review("<agent_id>", "<task_id>")
      print(review.action, review.task.id)
```

### 9. Build a custom tool (MCP server)

```bash
xmagic mcp init my-tool          # scaffold: Dockerfile, compose, MCP server
cd my-tool && docker compose up --build
```

That serves MCP over streamable HTTP at `http://localhost:8000/mcp`. xMagic
needs a *public* HTTPS URL to reach it, so for development expose it with a
tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

Before going anywhere near a tunnel, exercise it locally — `tools list` and
`tools call` speak MCP straight to the server:

```bash
xmagic tools list --url http://localhost:8000/mcp --api-key "$TOOL_API_KEY"
xmagic tools call ping --url http://localhost:8000/mcp --api-key "$TOOL_API_KEY" -a message=hi
```

That skips the whole tunnel → register → open a chat → hope-the-agent-calls-it
loop, which otherwise makes a broken tool and a tool the agent declined to use
look identical. Pass `--json` for scriptable output; `call` exits non-zero when
the tool reports an error, so it works in CI. Repeat `-a key=value` for multiple
arguments, or pass `--json-args '{"k": "v"}'`.

Then register the resulting public `https://.../mcp` URL in the dashboard under
**Custom tools → Create tool**. `xmagic tools register --name ... --url ...`
prints the full checklist. Set `TOOL_API_KEY` in your `.env` to require a
shared secret — the generated server rejects unauthenticated calls with `401`.

### 10. Package a skill

```bash
xmagic skills new my-skill       # scaffold SKILL.md
xmagic skills validate my-skill  # check frontmatter and layout
xmagic skills pack my-skill      # -> my-skill.zip, ready to upload
```

Upload the zip in the dashboard under **Skills**.

### 11. Use a non-xMagic model

`chat` takes a `provider:model` ref backed by your own key. OpenAI is
implemented:

```bash
export OPENAI_API_KEY="sk-..."
xmagic chat -m openai:gpt-5 "Hello!"
```

Or from Python, through the same `Provider` interface the xMagic path uses:

```python
from xmagic.providers import ChatMessage, get_provider

provider = get_provider("openai:gpt-5")  # reads OPENAI_API_KEY
for chunk in provider.stream([ChatMessage(role="user", content="Hello!")], model="gpt-5"):
    print(chunk.text, end="")
```

Two differences from the xMagic path are worth knowing. `model` is a real model
name here, not an agent id — OpenAI picks per call, so there's no agent and no
server-side session, and multi-turn context is whatever you pass in `messages`.
And `-f/--file` is xMagic-only, since uploads are an xMagic feature.

Errors arrive as this SDK's own types, so you catch `XMagicError` regardless of
which vendor failed — a 429 from OpenAI raises the same `RateLimitError` a 429
from xMagic would.

`anthropic:` and `google:` are not implemented; use `litellm:` for those once
that adapter lands (Phase 3).

### Next steps

Runnable scripts for each of the flows above live in
[`examples/`](examples/) — chat, streaming, files and Drive, and the MCP
scaffold walkthrough (that one needs no API key).

`xmagic --help` lists every command, and each subcommand takes `--help` too.
See [DESIGN.md](DESIGN.md) for how the pieces fit together.

## Troubleshooting

**`No API key configured`** — run `xmagic configure`, or export
`XMAGIC_API_KEY`. Check what's actually being picked up with
`xmagic configure --help` and remember env vars override the config file.

**A command prints `... lands in Phase N (see DESIGN.md)`** — that feature is
scaffolded but not implemented yet. See the status note at the top of this
README.

**`ModuleNotFoundError: No module named 'xmagic'`** — the import name is
`xmagic`, but the package to install is `xmagic-sdk`. See the note under
[Install](#install).

**`ImportError` mentioning `xmagic_sdk`** — you upgraded from 0.0.x, where the
module was called `xmagic_sdk`. It is `xmagic` from 0.1.0 on, with a different
API; the error text names what changed.

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
uv run mypy
```

CI runs all five across Python 3.11–3.14, and gates on formatting and types as
well as linting — run `uv run ruff format .` before pushing.

`mypy` runs in `strict` mode over `src/`. The package ships a `py.typed` marker,
so its annotations are what downstream type checkers believe about it; a wrong
one is worse for a consumer than none at all. `tests/` is not checked yet.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org)
(`feat:`, `fix:`, `docs:`, `test:`, `chore:`, ...; optional scope, e.g. `feat(mcp): ...`).

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup and
the PR workflow, and [ISSUES.md](ISSUES.md) for filing bugs, feature requests,
and security reports. All participants are expected to follow our
[Code of Conduct](CODE_OF_CONDUCT.md).

## License

[Apache-2.0](LICENSE) © Stochastic
