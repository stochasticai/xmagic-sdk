# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versions 0.0.1–0.0.3 exist on PyPI (November 2025) but predate this repository's
history and are not covered below. **0.1.0 is the first release cut from this
codebase.**

## [Unreleased]

### Added

- **`LiteLLMProvider` is implemented** — `litellm:groq/llama-3.3-70b-versatile`,
  `litellm:anthropic/claude-sonnet-5`, `litellm:ollama/llama3`, and everything
  else in LiteLLM's namespace, through the same `Provider` interface as
  `xmagic:` and `openai:`. Optional extra: `xmagic-sdk[litellm]`. This is why
  `AnthropicProvider` and `GoogleProvider` stay reserved — both are reachable
  here. Two behaviours differ from `OpenAIProvider`, deliberately:
  - **A missing API key is not an error.** LiteLLM resolves credentials per
    vendor from the environment (`ANTHROPIC_API_KEY`, `GROQ_API_KEY`, …) and a
    local runtime needs none, so raising on construction would break the common
    case. An explicit key is forwarded when given.
  - **Parameters are validated before the request is sent.** LiteLLM checks them
    against its model metadata, so an unsupported parameter fails locally as a
    `BadRequestError` rather than at the vendor. Moving a call from `openai:` to
    `litellm:` can therefore surface an error the same arguments did not before.
- **Capability flags are read, not maintained.** `LiteLLMProvider.capabilities()`
  consults `litellm.supports_function_calling` and `supports_vision` for the
  model the ref names. A model LiteLLM has no metadata for reports `False` for
  both — "cannot confirm", which is the honest answer.
- **Token usage on the LiteLLM path.** Non-streaming counts come from the
  provider's response. Streaming counts ride out on the terminal chunk — but
  note that when the upstream sends no usage frame, LiteLLM fills the gap with
  its own tokenizer, and nothing distinguishes the estimate from a measurement
  by the time it reaches us. `Usage.raw` keeps the payload. An all-zero `Usage`
  is treated as absent rather than reported as three measured zeros.

- **`StreamEventType`** in `xmagic.client.models` — the `Literal` of every token
  type a stream can carry, previously spelled inline on `StreamEvent.type`.
  Naming it lets callers that construct events annotate against it instead of
  restating eleven strings; nothing about `StreamEvent` itself changed.
- **The authenticated `xmagic tools --url` path is tested.** The scaffolded
  server now runs under uvicorn on a loopback port in the suite, exercised with
  a key through both the client helpers and the CLI, along with the wrong-key
  and no-key rejections. That branch had no coverage at all, which is how it
  shipped an `httpx` client to a transport that needs `httpx2` — a unit test now
  pins the library too, since a wrong-library client still works for
  request/response tools and would otherwise pass everything else.

### Changed

- **`mypy --strict` now covers `tests/` as well as `src/`.** All 58 errors are
  fixed. Four were real rather than mechanical: a `StreamEvent` built with a
  type outside its own `Literal`, `ChatType | None` dereferenced without a
  guard in two contract tests, `ModuleSpec | None` passed straight to
  `module_from_spec`, and `.text` read off the MCP content union without
  narrowing. No shipped code was affected; several tests were passing for a
  narrower reason than they appeared to.

## [0.3.0] — 2026-08-14

Two platform surfaces landed — Worklists and workspace/agent management — and the
client's failure behaviour became honest: errors are typed all the way down,
streams get their own timeout, and nothing leaks an `httpx` exception any more.

The package is also verifiably typed for the first time. `py.typed` shipped in
0.2.0 with nothing checking the annotations behind it; `mypy --strict` now gates
`src/` on every Python in the matrix. It caught a real defect on its first run —
see the `xmagic tools --url` entry under Fixed.

Read **Changed** before upgrading. Nothing here removes a public name, but four
behaviours differ: `Settings.load` now honours an explicit `None`, transport
failures raise this SDK's own errors instead of `httpx`'s, `max_retries` rejects
negatives at construction, and `pyyaml` is a new runtime dependency.

### Added

- **The package is typed for consumers (`py.typed`).** Every module here is
  annotated, and none of it reached downstream type checkers: PEP 561 treats an
  installed package without the marker as untyped, so `xmagic` resolved to `Any`
  in every consumer's mypy and pyright run. The marker now ships in both the
  wheel and the sdist.
- **`stream_timeout`** (default 300s, `None` waits forever) — streams no longer
  inherit the 60s request timeout. See Fixed.
- **`PermissionDeniedError` (403) and `ServerError` (5xx)**, plus
  **`APIConnectionError`** and **`APITimeoutError`** for failures that never
  produced a response. Any unmapped 5xx raises `ServerError`, so a backend fault
  is distinguishable from a client mistake without reading `status_code`.
- **`XMagicAPIError` exposes the response**: `.response`, `.headers`, `.body`,
  `.message`, and a best-effort `.request_id` (`x-request-id`, `request-id`, or
  `x-correlation-id`), so a support thread can quote an id rather than a
  screenshot. All are `None` for streamed error frames, which arrive inside an
  HTTP 200 body and have no error response to attach.
- **`ConfigurationError`, `ChatType`, `BadRequestError`, and the new error types
  are exported from the package root.** `ConfigurationError` is what
  `XMagicClient()` raises on the likeliest first-run failure — a missing API key
  — and catching it previously meant importing from `xmagic.errors`, a path that
  looks private.
- **A type check in CI.** `mypy --strict` over `src/`, on every entry of the
  3.11–3.14 matrix. `py.typed` shipped without anything verifying the
  annotations behind it, which is the one situation where a wrong annotation is
  worse for a consumer than no annotation at all. Clean as of this release;
  `tests/` is not covered yet.
- **Workspace and agent management** — `xmagic workspaces` lists and switches
  workspaces; `xmagic agents` lists agents, edits temporary configuration as
  YAML, and saves/deploys named versions with optional phone and subagent
  association. The sync and async clients expose matching workspace, agent, and
  phone resources.
- **Safer agent deployment** — deployment validates agent ownership without
  switching workspaces, supports `--phone` and `--no-phone` for deterministic
  automation, and reports unavailable phone services instead of hiding the
  optional step.
- **Agent configuration helpers** — JSON/YAML validation, typed response-shape
  and editor errors, shared response unwrapping, and a reusable chat runner for
  Composer-driven configuration updates.
- **Worklists — background tasks and recurring schedules.** `xmagic worklists`
  lists, inspects, creates, edits, cancels, deletes, triggers and reruns tasks,
  and `xmagic worklists schedules` gets, edits, pauses, resumes and deletes the
  recurring ones. `create`/`edit` open a pre-filled YAML template in `VISUAL`,
  then `EDITOR`, then the platform default. `worklists review` walks the tasks in
  `needs_review` one at a time: a message continues the task's existing chat
  thread, an empty one completes it without another agent action, `/skip` leaves
  it for later. `client.worklists` mirrors all of it on both the sync and async
  clients, with `WorklistTask`, `WorklistTaskPage`, `WorklistTaskStatus`,
  `WorklistReviewAction`, `WorklistReviewResult`, and `RecurrencySchedule`.

  Listing is deliberately single-page — `--skip` and `--limit` (1–200) fetch
  another, and the CLI reports page size and total count rather than quietly
  issuing more requests. `input_s3_file_paths` must name paths that already
  exist; uploading local files from this command is deferred.

  Adds `pyyaml` as a runtime dependency.

### Changed

- **`Settings.load` now applies an explicit `None` instead of discarding it.** It
  filtered every `None` override, which conflated "the caller did not pass this"
  with "the caller passed `None` deliberately" — fine for `api_key`, where `None`
  means unset, and wrong for `stream_timeout`, where it means "wait forever".
  `XMagicClient` and `AsyncXMagicClient` omit `api_key` and `base_url` when they
  are not supplied, so the config file and environment still win for those; every
  other keyword now reaches the field as written. Affects anyone who passed
  `default_agent_id=None` (or similar) expecting file/env fallback — omit the
  argument instead.
- **`max_retries` rejects negative values** at construction rather than failing
  with `UnboundLocalError` on the first request. `0` still disables retries.

### Fixed

- **`xmagic tools --url` with an API key passed the wrong kind of HTTP client.**
  `mcp` depends on `httpx2` — a separate distribution, version 2.x — while this
  package uses `httpx` 0.28, and the authenticated code path built an `httpx`
  client and handed it to a transport that calls `.sse()` on it. httpx 0.28 has
  no such method. Listing and calling tools happen to work, because neither
  reaches that call, but any flow that uses the standalone SSE stream would fail
  with `AttributeError`. Now builds the client `mcp` actually expects. Found by
  the new type check, and confirmed against a live server rather than assumed.
- **Streaming inherited the 60s request timeout**, so an agent that paused longer
  than `timeout` between two events raised `ReadTimeout` mid-answer. On a stream
  the read timeout bounds the *gap between events*, not the whole exchange, so
  the two cannot share a number. Streams now use `stream_timeout` (default 300s)
  for reads while connect/write/pool keep the normal bound. Thinking-heavy agents
  were the ones hitting this.
- **A failed streaming call reported the wrong thing entirely.** `connect_sse`
  validates only the content type, so a 401 on `chats.stream` raised
  `httpx_sse.SSEError("Expected response header Content-Type to contain
  'text/event-stream', got 'application/json'")` — the symptom rather than the
  cause, from a third-party exception tree, for what was really an auth failure.
  Error statuses on a stream now raise the same typed error the equivalent unary
  call would (`AuthenticationError`, `RateLimitError`, `ServerError`, …), body
  and all. A 2xx response that genuinely isn't an event stream raises
  `XMagicError` naming that, rather than being mistaken for a network fault.
- **Transport failures leaked `httpx` exceptions.** A DNS failure, refused
  connection, or timeout raised `httpx.ConnectError` / `httpx.ReadTimeout`
  straight through, so catching everything this SDK can raise meant catching
  `XMagicError` *and* importing httpx. They now raise `APIConnectionError` /
  `APITimeoutError`, with the original as `__cause__` and a message naming which
  timeout setting to raise. **Visible behaviour change** for anyone who caught
  the httpx types directly.

  The wrapping covers `httpx.RequestError` rather than only
  `httpx.TransportError`: `DecodingError` (a corrupt compressed body) and
  `TooManyRedirects` belong to the former but not the latter, and would
  otherwise have kept escaping while every connection-level failure looked
  correctly handled.
- **A timeout while opening a stream named the wrong setting.** Only the read
  deadline comes from `stream_timeout`; connect, write and pool stay on
  `timeout`. A `ConnectTimeout` on a streaming call nonetheless advised raising
  `stream_timeout`, which cannot affect it. The message now names the setting
  that actually governs the phase that timed out.
- **Retry backoff was deterministic**, so clients that failed together retried in
  lockstep and re-synchronized the load spike that caused the failure. Backoff
  now carries equal jitter: each delay is drawn from `[ceiling/2, ceiling]`, so
  it still grows and still respects the 30s cap. `Retry-After` is deliberately
  left un-jittered — the server named a time.

## [0.2.0] — 2026-08-07

Phase 1 (core client) completed, the MCP toolkit gained a working dev loop, and
the first non-xMagic model became callable.

Two fixes here were live defects rather than latent ones: `xmagic mcp init`
generated projects that could not start, and streamed errors were discarded so
that a failed generation looked like a short successful one. Both were found by
running the code rather than reading it, and both are covered by tests now.

Read **Changed** and **Compatibility** before upgrading — two extras were removed
and one streaming behaviour changed.

### Added

- **`AsyncXMagicClient`** — a full 1:1 async mirror of the sync client, replacing
  the placeholder that raised `NotImplementedError`. Same resources, arguments,
  and return types; `stream` is an async iterator. Backoff uses `asyncio.sleep`,
  so waiting on a rate limit does not block the event loop.
- **`xmagic chat` gains `-f/--file`** (repeatable) to attach files to a prompt,
  and **`--chat-type`** to choose the chat's UI context.
- **Reasoning is rendered dimmed** above the answer when an agent emits it.
  `CompletionChunk` gained a `kind` field (`"response"` / `"reasoning"`) so
  callers can distinguish the two; adapters with no reasoning channel emit the
  default and callers need not branch.
- `examples/` — runnable scripts for basic chat, streaming, files + Drive, the
  MCP server scaffold, and skills packaging. The last two need no API key.
- Test coverage for the retry/backoff contract and for the `chat` CLI, plus a
  structural test asserting the async API mirrors the sync one method for method.
- **Token usage is surfaced.** `token_usage` events reached the client and were
  then dropped by the provider. `Completion` and the terminal `CompletionChunk`
  now carry a `Usage` (input/output/total tokens, plus the raw payload). The
  shape is unconfirmed — it comes from the backend's private `TokenType` enum
  rather than the API reference — so parsing degrades to `None` rather than
  raising, and never reports zeros it did not measure.
- **`xmagic tools list` and `xmagic tools call`** — an MCP client that talks
  straight to a running custom-tool server. No xMagic account, no tunnel, no
  dashboard registration, and no waiting for an agent to decide to call the
  tool. `--arg key=value` (repeatable, JSON-coerced so numbers reach a typed
  tool as numbers), `--json-args` for a whole object, `--json` for scriptable
  output, and a non-zero exit when the tool reports an error so it works in CI.
  Requires `xmagic-sdk[mcp]`.

  This also gives `xmagic mcp init` its first real integration test: the suite
  scaffolds a project, imports it, and drives it over MCP's in-memory transport
  — no container, no port.
- **Four Drive routes** from the published API reference that the client lacked:
  `get_folder` (with optional `include_counts`), `update_folder` (partial — it
  sends only what you ask to change), `delete_files`, and `download_files`,
  which returns the ZIP export as bytes. Both sync and async.
  `HttpTransport`/`AsyncHttpTransport` gained `request_bytes` for the one
  documented endpoint that answers `application/zip` rather than JSON; the retry
  loop is now shared between both response shapes rather than duplicated.

- **`OpenAIProvider` is implemented** — the first non-xMagic model you can
  actually call: `xmagic chat -m openai:gpt-5`, or `get_provider("openai:gpt-5")`
  from Python, over the same `Provider` interface the xMagic path uses. Blocking
  and streaming, extra request params passed through, and OpenAI's exceptions
  translated into this SDK's own hierarchy, so a 429 from OpenAI raises the same
  `RateLimitError` a 429 from xMagic would. Unlike the xMagic adapter, `model` is
  a real model name rather than an agent id: there is no chat to create and no
  server-side session, so multi-turn context is whatever the caller passes.
  Optional extra: `xmagic-sdk[openai]`.

### Changed

- **Dropped the `[anthropic]` and `[google]` extras.** They installed vendor SDKs
  that nothing imports — both `complete` and `stream` on those adapters raise
  `NotImplementedError`, and LiteLLM already reaches both vendors (and ~150 more)
  through one dependency. `[all]` is now `[openai,litellm,serve,mcp]`;
  `anthropic` and the `google-genai` tree (google-auth, protobuf, grpcio) no
  longer install at all. The two adapter classes and their `xmagic.providers`
  entry points are unchanged and remain reserved extension points; an extra comes
  back alongside whichever one is actually implemented. Their error messages now
  point at `litellm:<vendor>/<model>` rather than at an extra that no longer
  exists.
- **An `xmagic_sdk` compatibility shim.** Importing it now raises an `ImportError`
  naming the replacement (`xmagic`), the version the change happened in, and
  `pip install 'xmagic-sdk==0.0.3'` for anyone who needs the old API. Scheduled
  for removal in 1.0. See Compatibility below.

### Fixed

- **Streamed errors were silently discarded.** `XMagicProvider.stream` branched
  on `done`/`response`/`reasoning` with no `else`, so an `error` frame fell
  through and vanished: the caller received whatever text arrived before the
  failure and a clean end of stream, indistinguishable from a short successful
  answer. `xmagic chat` printed the partial text and exited `0`. An `error` event
  now raises `XMagicAPIError`. **This is a visible behaviour change** — calls that
  previously returned truncated text now raise.

- **`xmagic mcp init` generated projects that could not start.** The template
  imported `mcp.server.fastmcp.FastMCP`; mcp 2.0 moved that class to
  `mcp.server.mcpserver.MCPServer`, and both the generated project and this
  package declared an unbounded `mcp>=1.0` — so a fresh install resolved to 2.x
  and every scaffolded server failed at import with `ModuleNotFoundError`. The
  template is ported, and both dependency declarations are now bounded to
  `>=2.0,<3`.

  The scaffold test could not have caught this: it used `py_compile`, which
  parses without resolving imports. It now imports the rendered module for real
  and drives it over MCP's in-memory transport — scaffold, `list_tools`, call
  `ping`, assert the response — so a broken generated server fails CI rather
  than reaching users.
- **`Retry-After` carrying an HTTP-date crashed the retry loop** with
  `ValueError` instead of retrying. RFC 9110 permits a date as well as a delay in
  seconds; an unparseable or non-positive value now degrades to the normal
  exponential backoff.
- **`xmagic chat` silently swallowed bracketed text in error messages.** Rich
  read `[providers.openai]` as a style tag and dropped it, turning "add
  `[providers.openai]` api_key to ..." into advice pointing at nothing. Error
  text is now escaped before rendering.

### Compatibility

- **0.1.0 changed this distribution's import name from `xmagic_sdk` to `xmagic`,
  and replaced its public API.** Releases 0.0.1-0.0.3 (November 2025) installed a
  top-level `xmagic_sdk` package built with setuptools; 0.1.0 installs `xmagic`.
  Because both ship under the distribution name `xmagic-sdk`, `pip install -U`
  deletes the old package, so `import xmagic_sdk` breaks. The 0.0.x helpers
  (`run_mcp_server`, `fetch_info_from_kb_v1` / `_v3`, `registry`) and the hosted
  deployment commands (`xmagic mcp run` / `list` / `logs` / `start` / `stop` /
  `delete` / `validate`, ~1,100 lines in `mcp/deploy_mcp.py`) have no equivalent
  in the current release. `xmagic configure` and `xmagic chat` survive by name but
  changed flags. Pin `xmagic-sdk==0.0.3` if you depend on any of it.

Work in progress is tracked in [TODO.md](TODO.md).

## [0.1.0] — 2026-08-03

First release from this codebase. Alpha: several surfaces are scaffolded and
raise `NotImplementedError`, each tagged with the roadmap phase that implements
it (see [DESIGN.md](DESIGN.md)).

### Added

- **xMagic API client** (sync) — chats (create / query / stream / async),
  file uploads, and Drive (knowledge base) operations. httpx transport with
  retries and exponential backoff honoring `Retry-After`, SSE streaming, and a
  typed error hierarchy.
- **CLI** (`xmagic`) — `configure`, `chat`, `mcp`, `skills`, `tools`, `drive`,
  `serve`, and `version`. Config precedence is explicit arguments → environment
  → `~/.config/xmagic/config.toml` (written mode `600`) → defaults.
- **MCP toolkit** — `xmagic mcp init` scaffolds a containerized FastMCP server
  over streamable HTTP, with Dockerfile, compose file, `.env.example`, and a
  registration walkthrough. The generated server enforces `TOOL_API_KEY` when
  set, accepting either `x-api-key` or `Authorization: Bearer`, and returns
  `401` otherwise.
- **Skills tooling** — `xmagic skills new` / `validate` / `pack`, producing an
  upload-ready zip.
- **Provider layer** — `Provider` ABC, a registry with entry-point plugin
  support, and a working `XMagicProvider`. OpenAI, Anthropic, Google, and
  LiteLLM ship as optional-extra stubs (Phase 3).
- Packaging: PEP 639 license metadata, granular extras (`[mcp]`, `[serve]`,
  `[openai]`, `[anthropic]`, `[google]`, `[litellm]`, `[all]`), and PyPI
  trusted publishing via GitHub OIDC with a tag-vs-version guard.
- Open-source docs: LICENSE (Apache-2.0), CONTRIBUTING, CODE_OF_CONDUCT,
  ISSUES, CITATION.cff, and issue/PR templates.

### Fixed

- Live request/response shapes verified against a real agent and locked with
  respx-mocked tests plus recorded SSE fixtures; defensive `.get` chains
  replaced with confirmed shapes, and `StreamEvent`'s `Literal` and
  `Message.output_assets` corrected ([#2]).
- `xmagic chat -m <ref>` without a colon produced an empty model name; model
  refs now resolve through `ModelRef.parse()`.
- Generated `Dockerfile` installed the project before copying `src/`, so image
  builds could never succeed; switched to a deps-only install.
- Generated `Dockerfile` healthcheck had a shell-quoting bug that left
  containers permanently unhealthy; replaced with a TCP socket check.
- `TOOL_API_KEY` was read but never enforced in the generated server,
  contradicting the auth-on-by-default design.
- File uploads passed open file handles through the retry loop, so a retry
  would send an empty body; bytes are now read up front.
- CLI provider path defaulted to the `playground` chat type while the SDK
  defaulted to `standard`; both now default to `standard`.

### Known limitations

- `AsyncXMagicClient` is exported but raises `NotImplementedError` (Phase 1).
- Provider adapters other than xMagic are stubs (Phase 3).
- `xmagic serve` (local web app proxy) is not implemented (Phase 5).
- Drive endpoint paths beyond those covered by the live validation remain
  unverified against docs.xmagic.ai/api-drive (Phase 4).

[#2]: https://github.com/stochasticai/xmagic-sdk/issues/2
[Unreleased]: https://github.com/stochasticai/xmagic-sdk/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/stochasticai/xmagic-sdk/releases/tag/v0.2.0
[0.1.0]: https://github.com/stochasticai/xmagic-sdk/releases/tag/v0.1.0
