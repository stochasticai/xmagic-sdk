# xmagic-sdk — Design Plan

A Python SDK and CLI for [xMagic](https://xmagic.ai), Stochastic's AI agent platform.

Status: **Draft v0.1** · Target: Python >= 3.10 · License: Apache-2.0

---

## 1. Goals

1. **MCP server scaffolding** — `xmagic mcp init` generates a containerized MCP server
   (Dockerfile included) that satisfies xMagic's custom-tool contract: a public HTTPS
   MCP endpoint returning well-structured JSON.
2. **xMagic API access** — first-class Python client + CLI for chat (sync, streaming,
   async/webhook), tools, skills, agents, and Drive (knowledge base).
3. **Multi-provider extensibility** — a thin `Provider` interface with first-party
   adapters for xMagic, OpenAI, Anthropic, and Google; optional LiteLLM adapter for
   the long tail of providers.
4. **Bring-your-own-model** — select any provider/model at call time or via config
   using your own API keys (`provider:model` notation, e.g. `anthropic:claude-sonnet-4-5`).
5. **Local web app** — `xmagic serve` runs a local reverse proxy for the hosted xMagic
   web app with local config injection, plus a minimal built-in status/chat fallback UI.

### Non-goals (v0.x)

- Re-implementing the full xMagic web frontend.
- Agent orchestration frameworks (we expose primitives, not a graph runtime).
- Hosting/deployment of MCP servers beyond templates and docs (no built-in PaaS).

---

## 2. xMagic platform facts (from docs.xmagic.ai)

These constrain the design:

| Aspect | Detail |
|---|---|
| Base URL | `https://api.xmagic.ai/xmagic-backend/v1` |
| Auth | API key via `x-api-key` header (dashboard → Settings → API Keys) |
| Entities | Agent (`agent_id`) → Chat (`chat_id`) → Message (`message_id`); Jobs = workflows |
| Chat types | `playground`, `configuration`, `interact`, `standard` |
| Chat | `POST /agents/{agent_id}/chats` |
| Query | `POST /agents/{agent_id}/chats/{chat_id}/query` (`is_stream` → SSE) |
| Async query | `POST /agents/{agent_id}/chats/{chat_id}/async_query` (webhook delivery) |
| SSE events | `reasoning`, `response`, `live_update`, `[DONE]` |
| Files | `POST /uploaded-files` → file id referenced in queries |
| Drive API | Folder/file CRUD, upload w/ auto-indexing, ZIP download |
| Custom tools | Registered in dashboard: name, description, **public HTTPS MCP server URL**, optional API key |
| Skills | `.zip` with `SKILL.md` (YAML frontmatter: `name`, `description`) + supporting files; attached at agent/subagent scope |
| Rate limits | Free 20 rpm · Pro 100 rpm · Business 500 rpm · Enterprise custom |
| Errors | `{error_code, message}`; 400/401/404/429 |

### Known documentation gaps (tracked as open questions, §10)

- No published Dockerfile/container spec for MCP servers — we define a sane default
  (streamable-HTTP MCP on `/mcp`) and keep the template configurable.
- No public API documented for registering custom tools or uploading skills — the CLI
  packages/validates locally and (for now) hands off to the dashboard; API wiring is
  isolated behind interfaces so it can be added without breaking changes.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI (Typer)                          │
│  xmagic chat · mcp · skills · tools · drive · serve · cfg   │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
┌──────────────▼───────────┐   ┌──────────────▼───────────────┐
│   Provider layer          │   │  Web app proxy (`serve`)     │
│   base.Provider (ABC)     │   │  Starlette/FastAPI reverse   │
│   ├─ XMagicProvider ──┐   │   │  proxy → app.xmagic.ai       │
│   ├─ OpenAIProvider   │   │   │  + header/config injection   │
│   ├─ AnthropicProvider│   │   │  + fallback local UI         │
│   ├─ GoogleProvider   │   │   └──────────────────────────────┘
│   └─ LiteLLMProvider  │   │
└───────────────────────┼───┘   ┌──────────────────────────────┐
                        │       │  MCP toolkit                 │
┌───────────────────────▼───┐   │  scaffold templates:         │
│   xMagic API client        │   │  server.py (FastMCP,         │
│   httpx sync+async, SSE,   │   │  streamable-http) +          │
│   retries, pydantic models │   │  Dockerfile + compose        │
└────────────────────────────┘   └──────────────────────────────┘
```

### Package layout

```
src/xmagic/
├── __init__.py            # XMagicClient, AsyncXMagicClient, __version__
├── config.py              # Settings: env > file (~/.config/xmagic/config.toml) > defaults
├── errors.py              # XMagicError hierarchy (Auth, RateLimit, NotFound, ...)
├── client/
│   ├── http.py            # httpx transport, x-api-key, retries/backoff, SSE
│   ├── models.py          # Pydantic v2 models (Chat, Message, StreamEvent, ...)
│   ├── chats.py           # create chat, query (sync/stream/async), messages
│   ├── files.py           # uploaded-files
│   └── drive.py           # knowledge-base folders/files
├── providers/
│   ├── base.py            # Provider ABC: complete(), stream(); ModelRef parsing
│   ├── registry.py        # "provider:model" resolution, entry-point plugins
│   ├── xmagic.py          # maps chat completion semantics onto agent chats
│   ├── openai.py          # optional extra [openai]
│   ├── anthropic.py       # optional extra [anthropic]
│   ├── google.py          # optional extra [google]
│   └── litellm.py         # optional extra [litellm] — long-tail escape hatch
├── skills/
│   └── packaging.py       # validate SKILL.md frontmatter, build/inspect zips
├── mcp/
│   ├── scaffold.py        # `xmagic mcp init` project generator
│   └── templates/         # server.py, Dockerfile, compose, pyproject, README
├── webapp/
│   └── proxy.py           # reverse proxy + fallback UI (extra: [serve])
└── cli/
    ├── main.py            # Typer app, sub-app mounting
    └── ...                # chat.py, mcp.py, skills.py, tools.py, drive.py, serve.py, configure.py
```

---

## 4. SDK surface (Python)

```python
from xmagic import XMagicClient

client = XMagicClient()                       # key from env/config
chat = client.chats.create(agent_id, title="demo", chat_type="standard")

# Blocking
resp = client.chats.query(agent_id, chat.id, "Summarize this file",
                          uploaded_files=[file_id])

# Streaming (SSE)
for event in client.chats.stream(agent_id, chat.id, "Explain step by step"):
    if event.type == "response":
        print(event.text, end="")

# Async client mirrors the sync API 1:1
from xmagic import AsyncXMagicClient
```

Provider layer (BYO model):

```python
from xmagic.providers import get_provider

llm = get_provider("anthropic:claude-sonnet-4-5")   # or "xmagic:<agent_id>",
result = llm.complete(messages=[...])               # "openai:gpt-4o", "google:gemini-2.5-pro",
for chunk in llm.stream(messages=[...]): ...        # "litellm:<anything>"
```

Design rules:

- `Provider` is intentionally minimal (`complete`, `stream`, `capabilities`) —
  normalization lives in adapters, not callers.
- `XMagicProvider` adapts agent-chat semantics to the message interface (creates an
  ephemeral `standard` chat per session unless given a `chat_id`).
- Third parties register providers via the `xmagic.providers` entry-point group.
- Provider SDKs are **optional extras**; importing an uninstalled adapter raises a
  helpful `pip install "xmagic-sdk[openai]"` message.

---

## 5. CLI surface

```
xmagic configure                      # interactive setup; writes config.toml
xmagic chat [--agent ID | --model provider:model] [--stream/--no-stream] [-f FILE]
xmagic agents list                    # as API coverage allows
xmagic drive ls|upload|download ...
xmagic skills new NAME                # scaffold SKILL.md + layout
xmagic skills validate PATH           # frontmatter/zip lint
xmagic skills pack PATH               # build upload-ready zip
xmagic tools register --dry-run       # emits dashboard checklist until an API exists
xmagic mcp init NAME                  # scaffold containerized MCP server
xmagic mcp dev [--tunnel]             # run locally; hint ngrok/cloudflared for HTTPS
xmagic serve [--port 8377]            # local web app proxy
xmagic models list                    # models across configured providers
```

Config precedence: CLI flags > env (`XMAGIC_API_KEY`, `XMAGIC_BASE_URL`,
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, ...) >
`~/.config/xmagic/config.toml` > defaults. Keys are never written to project dirs.

---

## 6. MCP server toolkit (Goal 1)

`xmagic mcp init my-tool` generates:

```
my-tool/
├── Dockerfile              # python:3.12-slim + uv, non-root, HEALTHCHECK
├── compose.yaml            # local run on :8000
├── pyproject.toml          # deps: mcp (FastMCP)
├── src/my_tool/server.py   # FastMCP app, streamable-http transport at /mcp
├── .env.example            # TOOL_API_KEY for xMagic's optional key field
└── README.md               # register-with-xMagic walkthrough
```

Contract targeted (per xMagic custom-tools guide):

- **Transport**: MCP streamable HTTP mounted at `/mcp` (works behind any HTTPS LB).
- **Auth**: optional shared secret; template validates the API key xMagic sends.
- **Responses**: tools return structured JSON; template includes error envelopes,
  timeouts, and request logging (docs explicitly recommend all three).
- **Deploy**: container is platform-agnostic (Cloud Run, Fly.io, ECS, k8s). Dev flow:
  `xmagic mcp dev --tunnel` prints a cloudflared/ngrok command to get a temporary
  public HTTPS URL for dashboard registration.

If/when xMagic publishes an official container spec, only `mcp/templates/` changes.

---

## 7. Local web app (Goal 5)

Chosen approach: **local proxy of the hosted xMagic web app**.

- `xmagic serve` starts a Starlette reverse proxy on `localhost:8377` forwarding to
  the hosted app, streaming bodies, rewriting `Host`/cookies as needed, and injecting
  local configuration (e.g., default agent, API base override for self-hosted xMagic
  deployments — the platform supports own-cloud installs).
- **Known risks** (documented, not hidden): CSP headers, third-party auth cookies, and
  frontend changes on xMagic's side can break proxying. Mitigations: header rewrite
  allowlist, `--passthrough` mode, and a built-in minimal chat UI (single HTML page
  talking to our own `/api/*` endpoints backed by the SDK) as a graceful fallback.
- For self-hosted/enterprise xMagic deployments, `--upstream URL` points the proxy at
  the customer's own instance — this is the strongest use case for the proxy design.

---

## 8. Cross-cutting concerns

- **HTTP**: httpx with retries + exponential backoff on 429/5xx honoring
  `Retry-After`; client-side rate-limit awareness per plan tier.
- **Errors**: typed hierarchy mapping `{error_code, message}`; never swallow bodies.
- **Streaming**: one SSE parser (httpx-sse) shared by SDK and CLI; events typed as
  `Reasoning | Response | LiveUpdate | Done`.
- **Security**: keys via env/keyring-style config only; redact `x-api-key` in logs;
  MCP template ships auth-on-by-default.
- **Testing**: pytest + respx (httpx mocking); recorded SSE fixtures; template
  golden-file tests for `mcp init`; CLI tests via Typer's runner.
- **Packaging**: uv + hatchling; extras: `[openai] [anthropic] [google] [litellm]
  [serve] [mcp] [all]`; single console script `xmagic`.
- **Git conventions**: [Conventional Commits](https://www.conventionalcommits.org)
  for all commit messages (`feat:`, `fix:`, `docs:`, `test:`, `chore:`,
  `refactor:`; scope optional, e.g. `feat(mcp): ...`). Enables changelog
  generation and semantic-version bumps at release time.

---

## 9. Roadmap

| Phase | Scope |
|---|---|
| **0 — Scaffold** (this session) | Repo layout, pyproject, config, CLI skeleton, MCP templates |
| **1 — Core client** | chats/query/stream/files, errors, retries; `xmagic chat` end-to-end |
| **2 — MCP toolkit** | `mcp init/dev`, template hardening, register walkthrough |
| **3 — Providers** | base + xmagic/openai/anthropic/google adapters, `models list`, litellm extra |
| **4 — Skills & Drive** | skills new/validate/pack, drive CRUD |
| **5 — Serve** | proxy + fallback UI, `--upstream` for self-hosted |
| **6 — Polish** | docs, examples, CI, PyPI release |

## 10. Open questions

1. Does xMagic expose (or plan) APIs for custom-tool registration and skill upload?
   (CLI currently stops at "packaged + validated, register in dashboard".)
2. Exact MCP transport xMagic's agent runtime speaks (streamable HTTP assumed; SSE
   legacy transport kept available behind a template flag).
3. Web-app proxy viability against the hosted app's CSP/auth — validate early in
   Phase 5; fallback UI is the hedge.
4. Are agent listing/management endpoints public? (Needed for `xmagic agents list`.)
