# TODO

Working task list, organized by DESIGN.md roadmap phase. Move completed items
to [PROGRESS.md](PROGRESS.md) with a date.

## Phase 1 — Core client (next up)

- [ ] Validate `xmagic chat --agent <id>` against a real agent with a live
      `XMAGIC_API_KEY`; confirm request/response shapes for create-chat, query,
      and SSE events (`reasoning`/`response`/`live_update`/`[DONE]`)
- [ ] Lock in verified shapes with respx-mocked tests + recorded SSE fixtures
- [ ] Implement `AsyncXMagicClient` (1:1 mirror of sync client)
- [ ] `xmagic chat` polish: render `reasoning` events dimmed; `--chat-type`
      flag; reuse a session across interactive turns
- [ ] File-upload flow end-to-end (`-f` flag → `/uploaded-files` → query ref)
- [ ] Retry/backoff behavior test for 429 with `Retry-After`

## Phase 2 — MCP toolkit

- [ ] `xmagic mcp dev`: docker compose wrapper with `--tunnel`
      (cloudflared/ngrok) instead of printed instructions
- [ ] Run a real `docker build` of the generated project in CI (structure is
      verified; base-image layer build is not)
- [ ] Confirm which header xMagic actually sends the custom-tool API key in
      (`x-api-key` vs `Authorization: Bearer`) — template accepts both for now
- [ ] Optional SSE (legacy transport) flag for the template if xMagic requires it

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

- [ ] `git init` + initial commit; CI (pytest + ruff + template docker build)
- [ ] Examples directory (SDK usage, MCP tool, skill)
- [ ] README badges, CHANGELOG, PyPI release (`xmagic-sdk`)

## Open questions (blockers noted in DESIGN.md §10)

- [ ] Public API for custom-tool registration / skill upload? (dashboard-only today)
- [ ] Exact MCP transport xMagic's runtime speaks (streamable HTTP assumed)
- [ ] Are agent list/management endpoints public? (needed for `xmagic agents list`)
- [ ] Behavioral differences between chat types beyond UI context (guardrails,
      history, tool availability)?
