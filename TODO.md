# TODO

Working task list, organized by DESIGN.md roadmap phase. Move completed items
to [PROGRESS.md](PROGRESS.md) with a date.

## Phase 1 — Core client ✅ complete

Live validation ([#2](https://github.com/stochasticai/xmagic-sdk/issues/2))
unblocked the rest of the phase, and it is now finished.

- [x] Implement `AsyncXMagicClient` (1:1 mirror of sync client)
- [x] `xmagic chat` polish: render `reasoning` events dimmed; `--chat-type`
      flag; reuse a session across interactive turns
- [x] File-upload flow end-to-end (`-f` flag → `/uploaded-files` → query ref)
- [x] Retry/backoff behavior test for 429 with `Retry-After`

## Phase 2 — MCP toolkit

- [ ] `xmagic mcp dev`: docker compose wrapper with `--tunnel`
      (cloudflared/ngrok) instead of printed instructions
- [ ] Run a real `docker build` of the generated project in CI (structure is
      verified; base-image layer build is not). Matters more if DESIGN.md §11
      and §12 land — more templates through the same scaffold, same blind spot
- [ ] Decide how tools get exercised without a full deploy — see "Local tool
      invocation" below and DESIGN.md §6
- [ ] Confirm which header xMagic actually sends the custom-tool API key in
      (`x-api-key` vs `Authorization: Bearer`) — template accepts both for now
- [ ] Optional SSE (legacy transport) flag for the template if xMagic requires it

### Local tool invocation

The dev loop for a custom tool today is: `docker compose up` → tunnel →
register in the dashboard → open a chat → hope the agent decides to call it.
That is minutes per iteration and the agent's choice is not under our control,
so a failing tool and a tool the agent simply declined to use look identical.

Two halves, and they are independent:

- [ ] **Local** — `xmagic tools list --url` and `xmagic tools call NAME --url`,
      speaking MCP streamable HTTP directly to a running server. No xMagic
      account, no tunnel, no registration. Fully within our control; unblocks
      iterating on the §11/§12 templates
- [ ] **Remote** — can a *registered* tool be invoked through the xMagic API
      rather than only as a side effect of an agent chat? Would make tools
      testable against the real platform and scriptable in CI. Platform
      question, not ours to decide — see Open questions
- [ ] Decide whether these belong under `xmagic tools` (alongside `register`)
      or `xmagic mcp` (alongside `init`/`dev`). The local one is really an MCP
      client; the remote one is an xMagic API call. They may not want to share
      a command group

## Phase 3 — Providers

- [ ] Implement `OpenAIProvider` (complete + stream)
- [ ] Implement `AnthropicProvider`
- [ ] Implement `GoogleProvider`
- [ ] Implement `LiteLLMProvider` (long-tail escape hatch)
- [ ] `xmagic models list` across configured providers
- [ ] Provider capability flags (tools, vision) wired into CLI errors

## Phase 4 — Skills & Drive

- [ ] Verify Drive endpoint paths against docs.xmagic.ai/api-drive
      (current paths in `client/drive.py` are unverified — see docstring)
- [ ] `xmagic drive download` (ZIP export) and recursive listing
- [ ] Richer SKILL.md validation (proper YAML parsing vs current line-based)
- [ ] Wire skills upload / tool registration APIs if xMagic publishes them
      (open question §10.1)

## Phase 5 — Local web app (`xmagic serve`)

- [ ] Implement the reverse proxy (Starlette): streaming bodies, Host/cookie
      rewrite allowlist, config injection, `--upstream` for self-hosted
- [ ] Validate proxy viability against hosted app early (CSP/auth cookies —
      open question §10.3)
- [ ] Minimal fallback chat UI backed by the SDK (`/api/*` routes)

## Phase 6 — Polish & release

Largely delivered by the open-source readiness work (see [PLAN.md](PLAN.md)).

- [x] `git init` + initial commit
- [x] CI: ruff check + ruff format + pytest on Python 3.11–3.14, plus a
      build/`twine check` job
- [x] README badges
- [x] CHANGELOG
- [x] PyPI release (`xmagic-sdk`) — **0.1.0 published 2026-08-03**; tag `v0.1.0`,
      trusted publishing via `release.yml`
- [x] Examples directory — `examples/` with basic chat, streaming, files+Drive,
      and the MCP scaffold walkthrough (the last needs no API key)
- [x] Skills packaging example (`examples/05_skills.py`)
- [ ] Multi-provider example (`provider:model`) — blocked on Phase 3 adapters

### Release hygiene (from the PyPI audit — see [PYPI_HISTORY.md](PYPI_HISTORY.md))

Nothing here blocks a release; each one makes a burned version number less
likely. 0.0.3 was spent on a one-line log change because PyPI won't accept a
re-upload.

- [ ] `release.yml` runs no tests or lint — it goes from checkout straight to
      `uv build` + `twine check`, so a green tag can publish a red commit
- [ ] Two version sources with no guard: `pyproject.toml` and
      `src/xmagic/__init__.py`. Derive `__version__` from
      `importlib.metadata.version("xmagic-sdk")`, or assert they agree in a test
- [ ] Publish to TestPyPI from the *same* artifact that goes to PyPI, so the
      rehearsal is a real one (the 0.0.2 rehearsal shipped a different sdist)
- [ ] Add a second owner to the `xmagic-sdk` PyPI project — `internal_apis` is
      currently the only role holder, so yank/delete/maintainer rights are
      single-homed
- [x] Document the install-vs-import name mismatch (`xmagic-sdk` / `xmagic`) and
      the 0.0.x → 0.1.0 break, and ship a shim that explains it on import

## Open questions (blockers noted in DESIGN.md §10)

- [ ] Public API for custom-tool registration / skill upload? (dashboard-only today)
- [ ] Can a registered custom tool be **invoked** directly through the API,
      independently of an agent chat? (see "Local tool invocation", Phase 2)
- [ ] Exact MCP transport xMagic's runtime speaks (streamable HTTP assumed)
- [ ] Are agent list/management endpoints public? (needed for `xmagic agents list`)
- [ ] Behavioral differences between chat types beyond UI context (guardrails,
      history, tool availability)?
