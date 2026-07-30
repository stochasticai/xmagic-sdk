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
   using your own API keys (`provider:model` notation, e.g. `anthropic:claude-sonnet-5`).
5. **Local web app** — `xmagic serve` runs a local reverse proxy for the hosted xMagic
   web app with local config injection, plus a minimal built-in status/chat fallback UI.
6. **Coding-agent bridge** *(proposed, §11)* — an MCP server template that lets an xMagic
   chat agent delegate repo work to an open-weights coding agent running on your infra.
7. **Document redactor** *(proposed, §12)* — a reference MCP tool that redacts PII using
   local models, and the first template to validate `mcp init --template`.

### Non-goals (v0.x)

- Re-implementing the full xMagic web frontend.
- Agent orchestration frameworks (we expose primitives, not a graph runtime). §11 wraps
  an existing harness; it does not build one.
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

client = XMagicClient()  # key from env/config
chat = client.chats.create(agent_id, title="demo", chat_type="standard")

# Blocking
resp = client.chats.query(agent_id, chat.id, "Summarize this file", uploaded_files=[file_id])

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

llm = get_provider("anthropic:claude-sonnet-5")  # or "xmagic:<agent_id>",
result = llm.complete(messages=[...])  # "openai:gpt-4o", "google:gemini-2.5-pro",
for chunk in llm.stream(messages=[...]):
    ...  # "litellm:<anything>"
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
| **7 — Document redactor** *(proposed)* | `mcp init --template redactor`; see §12 |
| **8 — Coding-agent bridge** *(proposed)* | `mcp init --template coding-agent`; see §11 |

## 10. Open questions

These, plus the platform-facing questions in §11.9 and §12.11, are consolidated for the
platform team in [#5](https://github.com/stochasticai/xmagic-sdk/issues/5).

1. Does xMagic expose (or plan) APIs for custom-tool registration and skill upload?
   (CLI currently stops at "packaged + validated, register in dashboard".)
2. Exact MCP transport xMagic's agent runtime speaks (streamable HTTP assumed; SSE
   legacy transport kept available behind a template flag).
3. Web-app proxy viability against the hosted app's CSP/auth — validate early in
   Phase 5; fallback UI is the hedge.
4. Are agent listing/management endpoints public? (Needed for `xmagic agents list`.)

---

## 11. Coding-agent bridge (proposed)

> **Status: proposed, not accepted.** Nothing here is implemented. This section exists
> to be reviewed and either adopted into the roadmap or dropped. Review thread:
> [#3](https://github.com/stochasticai/xmagic-sdk/issues/3).

### 11.1 Motivation

Drive a coding agent from the xMagic chat interface — "fix the flaky test in
`payments/`" typed into a chat, executed by a real coding harness against a real
checkout — with the model being open weights on infrastructure you control.

### 11.2 Why wrap `pi` rather than build a harness

[`earendil-works/pi`](https://github.com/earendil-works/pi) (formerly `badlogic/pi-mono`)
is a minimal terminal coding harness: a four-tool core (Read, Write, Edit, Bash),
extensible via TypeScript extensions, skills, and prompt templates rather than by
forking. It ships an **RPC mode** (JSON protocol over stdio) intended for exactly this
— being driven by another process — and the monorepo already includes vLLM pods for
serving open weights.

Building our own harness would mean re-deriving the agent loop, tool dispatch, and
session state that pi already has, and would land squarely on our stated non-goal (§1).
Wrapping it does not. **pi is TypeScript**, so the harness itself cannot live in this
Python package regardless; only the bridge can.

### 11.3 Controlling constraint

xMagic reaches custom tools **only at public HTTPS MCP URLs** (§2). Therefore pi runs
**server-side**, in a container we deploy. The developer's machine is never exposed.

**Rejected alternative — local pi behind a tunnel.** Exposing an exec-capable MCP server
from a developer machine means a public internet URL granting arbitrary code execution
on that machine, gated on one shared secret. Workable for a local demo with eyes open;
it must not become the documented path.

### 11.4 Architecture

```
                        Developer
                            │  "fix the flaky test in payments/"
                            ▼
                 ┌──────────────────────┐
                 │  xMagic chat         │   agent (+ optional "coder"
                 │  hosted UI/runtime   │    subagent) with skills attached
                 └──────────┬───────────┘
                            │  custom tool call, public HTTPS
                            ▼
┌───────────────────────────────────────────────────────────┐
│  coding-agent MCP server            (you deploy)          │
│  FastMCP · streamable-HTTP /mcp · TOOL_API_KEY enforced   │
│                                                           │
│    code_task_start   ──▶ job store ──┐                    │
│    code_task_status  ◀───────────────┤                    │
│    code_task_result  ◀───────────────┤                    │
│    code_task_cancel  ──▶─────────────┘                    │
│                          │                                │
│                          ▼  spawn; JSON over stdio        │
│                 ┌────────────────────┐                    │
│                 │  pi  (RPC mode)    │                    │
│                 │  Read Write Edit   │                    │
│                 │  Bash              │                    │
│                 └─────────┬──────────┘                    │
│                           │                               │
│              ephemeral git worktree, one per job          │
│                           │                               │
└───────────────────────────┼───────────────────────────────┘
                            │  OpenAI-compatible
                            ▼
                 ┌──────────────────────┐
                 │  vLLM — open weights │
                 │  your GPU            │
                 └──────────────────────┘

  output: branch + patch (+ PR url), never a push to a protected ref
```

Nothing leaves your infrastructure except the chat text itself.

### 11.5 Tool surface — job-shaped, not blocking

MCP tool calls are request/response; a pi run takes minutes. A single blocking
`code_task` would time out. So the surface is a job:

```
code_task_start(repo, instruction, base_ref="main", timeout_s=1800)
    -> {job_id, state}

code_task_status(job_id)
    -> {state, elapsed_s, log_tail, turns, tokens}

code_task_result(job_id)
    -> {state, summary, patch, files_changed, branch, pr_url, error}

code_task_cancel(job_id)                      # optional but cheap
    -> {state}
```

`state` ∈ `queued | running | succeeded | failed | timeout | cancelled`.

The agent polls `code_task_status` between turns; `log_tail` is what makes the chat feel
live. MCP progress notifications over streamable HTTP are the more elegant option, but
agent-side support is unverified — polling is the version that works today.

Note `async_query` (§2) does **not** help here: it is chat-side delivery, not tool-side.

### 11.6 pi driver

The MCP server is Python (FastMCP, consistent with the existing template in §6), so the
driver is a subprocess wrapper over pi's RPC mode:

```python
async def run_pi(workdir: Path, instruction: str, on_event) -> PiResult:
    proc = await asyncio.create_subprocess_exec(
        "pi", "--rpc",                    # exact invocation TBD — see 11.8 Q3
        cwd=workdir,
        stdin=PIPE, stdout=PIPE, stderr=PIPE,
    )
    proc.stdin.write(json.dumps({"type": "prompt", "text": instruction}).encode() + b"\n")
    await proc.stdin.drain()

    async for line in proc.stdout:
        event = json.loads(line)
        on_event(event)                   # appended to the job's log_tail
        if event.get("type") == "done":
            break
    ...
```

pi's **print mode** (single-shot) would be simpler, but yields no incremental events and
so no `log_tail`. RPC is the right choice given 11.5.

### 11.7 Isolation

The server executes model-authored shell commands. The existing template's non-root user
and healthcheck (§6) are a floor, not sufficient:

- **No ambient cloud credentials** in the job container — no instance metadata access, no
  mounted service-account keys.
- **Scoped per-repo token**, not an org-wide one. Least privilege that still allows a
  branch push.
- **Ephemeral worktree per job**, destroyed on completion; no state shared between jobs.
- **Egress restrictions** — the model endpoint and the git host, not the open internet.
- **Wall-clock and turn caps**, enforced by the server rather than trusted to the prompt.
- Output is a **branch or patch**. Never a push to a protected ref, never a deploy.

### 11.8 What lands where

| Piece | Home | Rough size |
|---|---|---|
| `coding-agent` template set | **this repo**, `mcp/templates/coding-agent/` | ~500 lines |
| `--template` flag on `mcp init` | **this repo**, `mcp/scaffold.py` | ~30 lines |
| Deployed bridge service | **separate repo**, generated from the template | — |
| pi extensions / skills | **separate repo** (TypeScript) | — |

Shipping MCP server templates is already this package's job (§6), and `scaffold.py` is a
56-line dict-driven generator — a second template set is a small, natural extension. The
running service is not our artifact; the scaffold for it is.

**Sequencing:** the `--template` machinery should be proven by the document redactor
(§12) first. It needs the same scaffold change and the same xMagic tool contract, but
carries none of the arbitrary-code-execution risk — a cheaper way to find out whether
the multi-template approach is right.

Template breakdown (~500 lines): `server.py` four tools + job store (~200), `pi_driver.py`
(~120), `jobs.py` asyncio job registry (~80), `Dockerfile` python + node + pi + git (~40),
compose/pyproject/README/.env (~60).

### 11.9 Open questions for review

1. **Is this in scope for xmagic-sdk at all?** The counter-argument: it is a product
   feature wearing an SDK costume, and templates for it could live in their own repo.
   The argument for: §6 already establishes template-shipping as our job.
2. **Tool or subagent?** These are not alternatives. It is a *tool* at the implementation
   layer; "subagent" is packaging — an xMagic subagent scoped to this tool plus coding
   skills (§2). Decide the packaging separately from the build.
3. **pi's exact RPC contract** — flag name, message schema, and event types in 11.6 are
   assumed, not verified against the pi source. Must be confirmed before implementation.
4. **Do xMagic skills and pi skills share a format?** We already package `SKILL.md` + zip
   (§4, `skills/packaging.py`) and pi has its own skills concept. If the frontmatter and
   layout align, xMagic skills run in pi unchanged — cheap to check, decides how much
   integration is free.
5. **Who hosts the reference deployment**, and does the vLLM pod ship with it or is BYO
   endpoint the only supported story?
6. **Multi-tenancy** — is one job per container acceptable, or does the job store need to
   survive restarts (i.e. Redis/Postgres rather than in-memory)?

---

## 12. Document redactor (proposed)

> **Status: proposed, not accepted.** Nothing here is implemented. Review thread:
> [#4](https://github.com/stochasticai/xmagic-sdk/issues/4).

A reference MCP tool: redact PII from documents using models that run on your own
infrastructure, exposed to xMagic chat as a custom tool. Proposed as the **first**
`mcp init --template` (see §11.8 sequencing).

### 12.1 Why this one, and why local models

Redaction is the rare case where local inference is a *requirement*, not a preference:
you cannot send an unredacted document to a third-party API in order to discover what is
sensitive in it. The constraint is what makes this worth building as the reference
example — it exercises the full MCP + open-weights path against a real need, with a
narrow tool surface and no arbitrary code execution.

### 12.2 Core decision: spans, not text

**The model returns spans. Code applies the redaction from character offsets.**

```json
{"start": 142, "end": 153, "type": "US_SSN", "score": 0.99, "detector": "regex+luhn"}
```

If an LLM emits redacted *text* instead, it will silently paraphrase, reorder, and drop
content, and the result cannot be unit-tested or audited. Span-based output makes the
transformation deterministic, diffable, and reviewable. Every design choice below assumes
this.

### 12.3 Layered detection

An LLM alone is the wrong engine: a miss is a leak, so recall must be near-perfect and
behavior must be reproducible.

| Layer | Catches | Tech |
|---|---|---|
| **L1** deterministic | SSN, credit card (Luhn), email, phone, IBAN, IP, MRN, dates | regex + validators |
| **L2** statistical NER | names, organizations, locations | spaCy / transformer NER |
| **L3** local LLM | quasi-identifiers, context-dependent references ("the patient's daughter"), narrative free text | Qwen / Llama 8B-class |

L1+L2 are essentially [Microsoft Presidio](https://github.com/microsoft/presidio)
(Apache-2.0, ~50 recognizers, pluggable). Reimplementing that is months of work for a
worse result — adopt it and spend our effort on L3, the merge logic, and evaluation.

The LLM's job is escalation and the long tail. It must not be load-bearing for structured
identifiers, which L1 already catches deterministically.

### 12.4 Architecture

```
   Document owner
        │  uploads contract.pdf
        ▼
┌────────────────────┐
│   xMagic chat      │   agent decides to call the tool
└─────────┬──────────┘
          │  redact_document(file_ref, policy="hipaa_safe_harbor")
          │  ─── a reference, never the document text (see 12.5) ───
          ▼
┌──────────────────────────────────────────────────────┐
│  redactor MCP server            (your infra)         │
│  FastMCP · streamable-HTTP /mcp · TOOL_API_KEY       │
│                                                      │
│   1. fetch bytes by ref                              │
│   2. extract text + offset/bbox map                  │
│   3. detect ──┬── L1  regex + validators             │
│               ├── L2  NER (spaCy / Presidio)         │
│               └── L3  local LLM ────────────┐        │
│   4. merge spans, resolve overlaps          │        │
│   5. apply operator by offset               │        │
│      (mask | replace | hash | pseudonym)    │        │
│                                             │        │
└──────────┬──────────────────────────────────┼────────┘
           │                                  │  OpenAI-compatible
           ▼                                  ▼
   redacted document                 ┌──────────────────┐
   + span audit record               │  vLLM / Ollama   │
                                     │  open weights    │
   unredacted bytes never egress     └──────────────────┘
```

### 12.5 Document transport — the self-defeat trap

If the xMagic agent passes document **text** inline in the tool call, the unredacted
document has already passed through the platform and the model context. The redactor has
defeated itself before it runs.

So how bytes reach the tool is load-bearing, not an implementation detail:

| Option | Verdict |
|---|---|
| (a) Inline text in the tool call | **Self-defeating.** Demo only. |
| (b) Tool fetches by xMagic file id | Preferred. `POST /uploaded-files` returns an id (§2, `client/files.py`). Requires the tool to hold an xMagic key and a documented fetch endpoint — **unverified**, see 12.9 Q1. |
| (c) Presigned URL passed to the tool | Good if available. |
| (d) Direct upload to the tool's own endpoint | Fallback that always works; costs a separate upload step. |

Design for (b)/(c); build (d) as the guaranteed path.

### 12.6 Tool surface

```
analyze_document(file_ref, policy="hipaa_safe_harbor")
    -> {ok, findings: [{type, count, samples_masked}], spans_total}

redact_document(file_ref, policy, operator="replace", dry_run=false)
    -> {ok, output_ref, entity_counts: {US_SSN: 3, PERSON: 12}, spans_redacted: 47}
```

`analyze_document` matters more than it looks: it lets a human approve before anything is
destroyed, and it is how reviewers build trust in the tool. Large documents move to the
job-shaped pattern from §11.5 — MCP is request/response and OCR is slow.

### 12.7 Formats, and the PDF trap

Scope grows fastest here, so it is phased (12.8):

- **Text / Markdown** — offsets are trivial.
- **PDF, text layer** — PyMuPDF. **Must use `add_redact_annot()` + `apply_redactions()`,
  which remove content.** Drawing black rectangles over selectable text is the classic
  redaction failure that leaks the original on copy-paste.
- **Scanned PDF / images** — OCR, spans map to bounding boxes rather than offsets.
- **DOCX** — entities routinely split across XML runs; naive offset replacement corrupts
  the file.

### 12.8 Evaluation

The part that separates a demo from a product, and the reason R0 starts with the eval set
rather than the engine.

- **Recall per entity type is the headline metric** — a miss is a leak. Precision is
  secondary: over-redaction destroys utility but does not disclose.
- Eval corpus: synthetic (Faker) plus a public de-identification corpus.
- **CI gate:** recall must not regress below a per-type threshold.
- **Definition of done: HIPAA Safe Harbor's 18 identifiers.** Without a named standard,
  "done" is unfalsifiable.

### 12.9 Roadmap

| Phase | Scope | Exit criteria |
|---|---|---|
| **R0 — Spike** | Presidio + local LLM on plain text, CLI only, no MCP | Spans from a text file; measured recall on ~50 synthetic docs |
| **R1 — Engine** | Policy config, operators, span merge, pseudonym vault | HIPAA 18 covered; recall ≥ 0.98 structured, ≥ 0.90 names |
| **R2 — MCP tool** | Wrap in the §6 scaffold, structured errors, auth | Registered in the xMagic dashboard, end-to-end on text |
| **R3 — PDF** | Text-layer PDFs, true redaction | Extracted text of the output contains zero known entities |
| **R4 — Async** | Job-shaped tools, large documents, concurrency | 200-page PDF without timeout |
| **R5 — OCR + DOCX** | Scanned documents, Office formats | Bounding-box redaction verified on scans |
| **R6 — Productize** | Eval in CI, audit log, template extraction | `xmagic mcp init --template redactor` |

**R0–R2 is the milestone that matters** — a working xMagic tool. R3+ is where document
formats consume the schedule.

### 12.10 What lands where

| Piece | Home |
|---|---|
| `redactor` template set | **this repo**, `mcp/templates/redactor/` (R6) |
| `--template` flag on `mcp init` | **this repo**, `mcp/scaffold.py` (R6) |
| Redaction engine + eval corpus | **separate repo** — it is a product, not SDK surface |
| Deployed service | **separate repo**, generated from the template |

Note the ordering: the engine is built and proven standalone (R0–R5), and only the
*shape* of it becomes a template at R6. Extracting a template from a working service is
tractable; designing one up front is not.

### 12.11 Open questions for review

1. **Can a custom tool fetch an xMagic uploaded file by id?** (12.5) This decides the tool
   signature and whether the design is coherent at all. Blocking — needs an answer from
   the platform team, not a decision from us.
2. **Does xMagic host custom-tool containers**, or is BYO deployment the only story?
   "Hosted on xMagic" has two readings: *registered as a custom tool* (documented, we
   deploy) versus *xMagic runs the container* (undocumented). Related to §10.1.
3. **Reversible or one-way?** A pseudonym vault mapping fake→real is a materially
   different security artifact from one-way masking, with its own storage and access
   requirements. Decide before R1.
4. **Which standard for v1** — HIPAA Safe Harbor is proposed; GDPR pseudonymization has
   different requirements and would change the entity list.
5. **Does L3 (local LLM) actually earn its place?** R0 should measure recall with and
   without it. If it does not move the number, the tool is simpler and faster without it,
   and "local models" becomes an L2-only story.
6. **Is a redaction product in scope for this repo at all,** even as a template? Same
   question as §11.9 Q1, and the answers should probably agree.
