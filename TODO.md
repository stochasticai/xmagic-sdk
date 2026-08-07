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
- [ ] Run a real `docker build` of the generated project in CI (the Python
      side is now covered — the suite imports the generated server and drives it
      over MCP — but the base-image layer build is not). Matters more if DESIGN.md §11
      and §12 land — more templates through the same scaffold, same blind spot
- [ ] Decide how tools get exercised without a full deploy — see "Local tool
      invocation" below and DESIGN.md §6
- [ ] Confirm which header xMagic actually sends the custom-tool API key in
      (`x-api-key` vs `Authorization: Bearer`) — template accepts both for now
- [ ] Optional SSE (legacy transport) flag for the template if xMagic requires it
- [ ] **Check `/v1/mcp-servers` before building `mcp dev --tunnel`.** The 0.0.x
      SDK (PyPI, Nov 2025) drove a platform deployment API — create, list, status,
      update, delete, logs, stop, `validate-code` — and read a live endpoint URL
      off the finished deployment. If any of that is still public, tunnelling to a
      local container solves a problem the platform already solved, and `mcp init`
      should scaffold *for* it. Asked as Q2 follow-up in
      [#5](https://github.com/stochasticai/xmagic-sdk/issues/5)

### Local tool invocation

The dev loop for a custom tool today is: `docker compose up` → tunnel →
register in the dashboard → open a chat → hope the agent decides to call it.
That is minutes per iteration and the agent's choice is not under our control,
so a failing tool and a tool the agent simply declined to use look identical.

Two halves, and they are independent:

- [x] **Local** — `xmagic tools list --url` and `xmagic tools call NAME --url`,
      speaking MCP streamable HTTP directly to a running server. No xMagic
      account, no tunnel, no registration. Landed under `xmagic tools`; also
      gives `mcp init` a real integration test via MCP's in-memory transport
- [ ] **Remote** — can a *registered* tool be invoked through the xMagic API
      rather than only as a side effect of an agent chat? Would make tools
      testable against the real platform and scriptable in CI. Platform
      question, not ours to decide — see Open questions
- [x] Decided: both live under `xmagic tools`. Users reach for this wanting to
      *test a tool*, not to speak a protocol, so grouping by intent beats
      grouping by what each one talks to

## Phase 3 — Providers (deprioritized 2026-08-05)

Worth knowing before picking this up: **xMagic documents no model selection at
all.** `model` in `XMagicProvider` is an agent id, and `_query_payload` carries no
model field. Checked against the live docs on 2026-08-05: none of the 15 endpoints
in the API reference takes a `model` parameter, no endpoint lists models, and none
of the 103 documented pages covers choosing one — the agent-config page's only
mention is an "Allow Model's Knowledge" toggle, which is about pretrained
knowledge, not model choice.

How xMagic picks a model is therefore not a supported, documented surface, and we
should not build against it or assume one exists. What follows for us: per-call
model choice comes from LiteLLM alone, and one adapter covers every vendor the
three native ones would have. The native adapters are now reserved extension
points with no extra (DESIGN.md §4).

- [x] Implement `OpenAIProvider` (complete + stream) — the worked example of a
      vendor-native adapter, and the pattern to copy for any other. Keeps its
      `[openai]` extra
- [ ] Implement `LiteLLMProvider` (complete + stream) — covers the remaining
      ~150 vendors, Anthropic and Google among them
- [ ] `xmagic models list` — near-trivial off `litellm.model_list` (~1,900 models
      across 149 providers as of litellm 1.95)
- [ ] Provider capability flags — read `litellm.supports_function_calling` /
      `supports_vision` rather than hand-maintaining a table
- [ ] ~~`AnthropicProvider` / `GoogleProvider`~~ — reserved, not planned. Build
      one only if a vendor-specific need (parameters, auth, transport) makes
      routing through LiteLLM wrong, and add its extra back at that point

## Phase 4 — Skills & Drive

- [x] Verify Drive endpoint paths against the published API reference — done
      2026-08-06; the existing paths are correct, and four documented routes we
      lacked are now implemented (folder details, folder update, file deletion,
      ZIP export)
- [ ] **`list_folders` / `list_files` silently truncate at 20 items.** The live
      response carries `data.pagination` (`page`, `page_size`, `total_count`)
      and we return only `data.results`. The request-side parameter names are
      undocumented, so this needs an answer before it can be fixed correctly —
      raised on [#5](https://github.com/stochasticai/xmagic-sdk/issues/5)
- [ ] CLI surface for the new Drive routes (`xmagic drive download`, `rm`,
      `rename`) and recursive listing
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
- [ ] Multi-provider example (`provider:model`) — blocked on `LiteLLMProvider`

## SDK surface — surveyed, not yet scoped

From a survey of what agent-platform SDKs commonly expose (2026-08-05). These are
ours to build — nothing external blocks them. Deliberately not assigned to a
phase; listed so they stop being invisible.

Ready now, roughly in order of value per unit of work:

- [x] **Token usage** on `Completion` / `CompletionChunk` — landed in
      [#20](https://github.com/stochasticai/xmagic-sdk/pull/20). The xMagic shape
      is still unconfirmed, so parsing degrades to `None` rather than reporting
      zeros it did not measure
- [ ] **Tool calling as a typed surface.** `capabilities()` advertises
      `tools: True`, but `Provider.complete` has no `tools` parameter, and
      `ChatMessage` has no `tool_call_id` so it cannot represent a tool result
      at all. Designed in DESIGN.md §13; review thread
      [#16](https://github.com/stochasticai/xmagic-sdk/issues/16). Stage A
      (types + blocking path) and C (schemas from typed callables) are the
      milestone that matters
- [ ] **Structured output** — `response_format` passthrough plus a "parse into
      this pydantic model" helper. Table stakes across every peer SDK
- [ ] **Logging, and a `User-Agent` header.** There is no logging anywhere in the
      package, so a failing call cannot be inspected; and the client identifies
      itself to no one, which rules out server-side version telemetry
- [ ] **`--json` output for the CLI.** Nothing is scriptable today without
      parsing Rich-formatted text
- [ ] **Stream cancellation and deterministic close.** `sse()` yields from inside
      a `with connect_sse(...)`, so a caller who breaks out of the loop leaves the
      response open until GC; there is no way to cancel an in-flight query
- [ ] **A test double for consumers** — export the recorded fixtures or a fake
      client, so downstream users can test against this SDK without network

Correctness and packaging gaps found in an audit on 2026-08-05. The first five
landed together on 2026-08-07; the rest were re-verified against the tree that
day and are still open.

- [x] **Ship a `py.typed` marker** — done 2026-08-07. Needed no
      `pyproject.toml` change after all: hatchling picks the marker up from the
      package directory, verified by building both artifacts
- [x] **SSE inherits the 60s read timeout** — done 2026-08-07. Streams now read
      with `stream_timeout` (default 300s, `None` waits forever) while
      connect/write/pool keep the normal bound
- [x] **Export `ConfigurationError` and `ChatType` at the package root** — done
      2026-08-07, along with `BadRequestError` and the new error types
- [x] **Fill the error hierarchy** — done 2026-08-07. `PermissionDeniedError`
      (403), `ServerError` (any 5xx), `APIConnectionError` / `APITimeoutError`
      wrapping httpx transport failures, and `.response` / `.headers` / `.body` /
      `.message` / `.request_id` on `XMagicAPIError`
- [x] **Add jitter to retry backoff** — done 2026-08-07. Equal jitter: each delay
      drawn from `[ceiling/2, ceiling]`. `Retry-After` stays verbatim
- [ ] **Add a typechecker to CI.** No mypy or pyright anywhere. This is now the
      most valuable item in this list rather than the least: `py.typed` ships as
      of 2026-08-07, so we are publishing annotations that nothing verifies, and a
      wrong one is worse for a consumer than none at all
- [ ] **`metadata` stream events are dropped**, and they carry `message_id` — so
      a streaming caller cannot learn the id of the message it just received.
      Named in a comment in `providers/xmagic.py:157`; filed here so it is not
      only a comment
- [ ] **Streaming calls are never retried.** `sse()` has no retry loop, so a 429
      or 503 on `chats.stream` fails on the first attempt while the same status on
      `chats.query` gets the full backoff schedule. Found 2026-08-07 while fixing
      the status handling below; retrying a stream needs a decision about whether
      a partially-consumed stream can be safely restarted, so it is not a
      one-liner
- [ ] **No stream cancellation, and no deterministic close** — listed under
      "Ready now" above; noting here that the two touch the same code

Larger, and worth their own design pass:

- [ ] Observability: OpenTelemetry spans, request-id capture, callbacks/hooks
- [ ] Middleware / request interceptors
- [ ] Human-in-the-loop: interrupt a run, approve, resume
- [ ] Multimodal input (images, audio). `Message.output_assets` already hints at
      artifacts coming back the other way
- [ ] Pagination — nothing paginates; Drive listings return whole result sets
- [ ] Prompt caching, batch APIs, idempotency keys

Blocked on the platform, tracked in
[#5](https://github.com/stochasticai/xmagic-sdk/issues/5) rather than here:
conversation history and chat listing (Q10), a usage/cost API (Q11), feedback
capture (Q12), and whether guardrails / agent versioning / scheduling / threads /
worklists / forms / evaluation / integrations are reachable by API at all (Q13).

### Release hygiene (from the PyPI audit — see [PYPI_HISTORY.md](PYPI_HISTORY.md))

Nothing here blocks a release; each one makes a burned version number less
likely. 0.0.3 was spent on a one-line log change because PyPI won't accept a
re-upload.

- [x] `release.yml` runs no tests or lint — it went from checkout straight to
      `uv build` + `twine check`, so a green tag could publish a red commit.
      Fixed in [#19](https://github.com/stochasticai/xmagic-sdk/pull/19) (merged);
      the workflow now runs `ruff check`, `ruff format --check`, and `pytest`
      before it publishes
- [x] Two version sources with no guard: `pyproject.toml` and
      `src/xmagic/__init__.py`. Fixed in
      [#18](https://github.com/stochasticai/xmagic-sdk/pull/18) (merged) —
      `__version__` now derives from `importlib.metadata`, with
      `tests/test_version_consistency.py` guarding it
- [x] Publish to TestPyPI from the *same* artifact that goes to PyPI, so the
      rehearsal is a real one (the 0.0.2 rehearsal shipped a different sdist).
      Fixed in [#19](https://github.com/stochasticai/xmagic-sdk/pull/19) (merged)
- [ ] Add a second owner to the `xmagic-sdk` PyPI project — `internal_apis` is
      currently the only role holder, so yank/delete/maintainer rights are
      single-homed
- [x] Document the install-vs-import name mismatch (`xmagic-sdk` / `xmagic`) and
      the 0.0.x → 0.1.0 break, and ship a shim that explains it on import

## Open questions (blockers noted in DESIGN.md §10)

Consolidated for the platform team in
[#5](https://github.com/stochasticai/xmagic-sdk/issues/5), which now also carries
Q9–Q14 from the 2026-08-05 audit — including evidence that the 0.0.x SDK called a
`/v1/mcp-servers` deployment API and spoke a **non-MCP** REST tool contract, which
bears on the two questions there marked blocking.

- [ ] Public API for custom-tool registration / skill upload? (dashboard-only today)
- [ ] Can a registered custom tool be **invoked** directly through the API,
      independently of an agent chat? (see "Local tool invocation", Phase 2)
- [ ] Exact MCP transport xMagic's runtime speaks (streamable HTTP assumed)
- [x] Are agent list/management endpoints public? (`xmagic agents` and its
      `config`/`deploy` subcommands are implemented)
- [ ] Behavioral differences between chat types beyond UI context (guardrails,
      history, tool availability)?
