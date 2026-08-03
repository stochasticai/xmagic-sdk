# Progress Log

Reverse-chronological log of work on xmagic-sdk. See [DESIGN.md](DESIGN.md) for
the plan and [TODO.md](TODO.md) for what's next.

---

## 2026-07-29 — Docs accuracy pass

- **README no longer advertises unimplemented features as working.** It pitched
  multi-provider chat, BYO models, the async client, and `xmagic serve` as
  capabilities; all four raise `NotImplementedError`. The Quickstart's second
  command (`xmagic chat -m anthropic:...`) printed "Phase 3 (see DESIGN.md)"
  rather than talking to a model. Split into working-today vs planned, each
  planned item tagged with its phase.
- Added `ruff format --check .` to the documented checks in README and
  CONTRIBUTING — CI had started gating on it, so contributors would pass locally
  and get a red PR. CONTRIBUTING also still claimed formatting was "not yet
  enforced repo-wide".
- Reconciled `TODO.md` Phase 6 (CI, badges, and git init were done but listed as
  pending) and refreshed this log.

## 2026-07-28 — CI repair, Python 3.14, open-source readiness

**CI had been failing on every run since the workflows landed**, while
`ruff check` passed locally. Cause: `ruff>=0.5` unbounded with no explicit
`select`. CI resolved ruff 0.16.0, whose default rule set is wider than 0.15's,
so it enforced 15 rules the local 0.15.21 never checked.

- Declared `[tool.ruff.lint] select` explicitly and bounded the dev dependency
  to `ruff>=0.16,<0.17`, so a ruff upgrade can change fix behavior but never
  silently change which rules are enforced. `B008` ignored under `cli/` —
  Typer's API requires callables as parameter defaults.
- Cleared what the wider set legitimately found: `B904` (10 CLI handlers now
  `raise ... from None`), `BLE001` (narrowed a blind `except Exception` in
  `_parse_error` to `(ValueError, AttributeError)`), `PYI034` (`__enter__`
  returns `Self`), `UP042` (`ChatType` → `StrEnum`; wire format unchanged since
  the payload reads `.value`), plus `RUF022`/`UP037` autofixes.
- **Python 3.14 added to the CI matrix** and `requires-python` bounded to
  `">=3.11,<3.15"`. The previous open-ended `">=3.11"` asked resolvers to
  satisfy *all* future Pythons; every litellm release caps out, so nothing
  qualified and resolution degraded to an old pin. litellm ships cp314 wheels
  as of 1.93.0.
- Root cause of the local/CI drift was a stale gitignored `uv.lock` pinning
  litellm 1.92.0 (declares `<3.14`, no macOS wheel) and holding ruff at 0.15.
  `uv lock --upgrade` clears it — worth knowing "no committed lock" in practice
  means an invisible per-developer lock that ages silently.
- Open-source readiness (PLAN.md Phases 1–2): LICENSE, CoC, CONTRIBUTING,
  ISSUES, CITATION.cff, issue/PR templates, PEP 639 metadata, sdist include
  list, CI matrix, and a PyPI trusted-publishing release workflow.
- Filed [#2](https://github.com/stochasticai/xmagic-sdk/issues/2) for Phase 1
  live API validation.

## 2026-07-20

- Added `PROGRESS.md` (this file) and `TODO.md` for ongoing tracking.

## 2026-07-12 — Review, fixes, and end-to-end verification

Full code review of the scaffold; **5 bugs found and fixed**:

1. `cli/chat.py` — `-m <ref>` without a colon produced an empty model name
   (`ref.partition(":")[2]`); now resolved via `ModelRef.parse()`.
2. `mcp/templates/Dockerfile.tmpl` — `uv pip install .` ran before `COPY src/`,
   so image builds could never succeed; switched to deps-only install
   (`uv pip install -r pyproject.toml`).
3. `mcp/templates/Dockerfile.tmpl` — healthcheck shell-quoting bug made
   containers permanently unhealthy; replaced HTTP probe with a TCP socket check.
4. `mcp/templates/server.py.tmpl` — `TOOL_API_KEY` was read but never enforced
   (contradicted DESIGN.md's "auth-on-by-default"); added `ApiKeyMiddleware`
   accepting `x-api-key` or `Authorization: Bearer`, 401 on mismatch, and a loud
   warning when no key is set. Generated project now lists `starlette`/`uvicorn`
   explicitly.
5. `client/files.py`, `client/drive.py` — uploads passed open file handles
   through the retry loop (retries would send empty bodies); now read bytes
   up front.

Verification:

- pytest **10/10** (4 new tests: rendered server compiles + contains auth
  middleware, Dockerfile regression checks, CLI error paths, ModelRef regression)
- ruff clean
- Live e2e: `xmagic mcp init my-tool` → installed deps → booted generated
  server → probed `/mcp`: no key **401**, wrong key **401**, `x-api-key` **200**
  (full MCP `initialize` handshake over SSE), `Bearer` **200**
- Skills flow: `skills new` → `validate` → `pack` produced an upload-ready zip

Also this session (earlier):

- **Changed CLI provider path default chat type** from `playground` to
  `standard` (`XMagicProvider._ensure_chat`); SDK and CLI now consistently
  default to `standard`.

## 2026-07-09 — Design plan + scaffold (Phase 0)

- Researched xMagic docs: API base `https://api.xmagic.ai/xmagic-backend/v1`,
  `x-api-key` auth, chat/query/SSE/async endpoints, Drive API, custom tools
  (public HTTPS MCP URL + optional key, dashboard-registered), skills
  (`SKILL.md` zip), rate limits.
- Wrote **DESIGN.md**: goals (MCP scaffolding, API access, multi-provider,
  BYO models, local web app), architecture, package layout, roadmap
  (Phases 0–6), open questions.
- Decisions (with user): local web app = **proxy of hosted app** (+ fallback
  UI), providers = **hybrid** (own interface + optional LiteLLM), stack =
  **uv + Typer + httpx**, deliverable = design + scaffold.
- Scaffolded the repo:
  - Working sync client: chats (create/query/stream/async), files, Drive;
    httpx transport with retries/backoff and SSE; typed error hierarchy;
    config precedence (env > `~/.config/xmagic/config.toml` > defaults)
  - Provider layer: `Provider` ABC, registry with entry-point plugins,
    functional `XMagicProvider`; OpenAI/Anthropic/Google/LiteLLM as
    optional-extra stubs (Phase 3)
  - MCP toolkit: `xmagic mcp init` generating Dockerfile, compose, FastMCP
    streamable-HTTP server, `.env.example`, registration README
  - Skills tooling: `new` / `validate` / `pack` (fully working)
  - CLI: `configure`, `chat`, `mcp`, `skills`, `tools`, `drive`, `serve`,
    `version`
  - 6 smoke tests, ruff clean, `requires-python >= 3.11`
