# TODO

Working task list, organized by DESIGN.md roadmap phase. Move completed items
to [PROGRESS.md](PROGRESS.md) with a date.

## Release plan

Each version introduces one capability, named in its heading. A version is
ready when that capability is complete, not when the Unreleased section is
long (RELEASING.md). Items keep their checkboxes in the phase sections below;
this is the map, not a second list.

### 0.5.0 — Drive it from a script, debug it, test against it

**Shipped 2026-09-14** as [v0.5.0](https://github.com/stochasticai/xmagic-sdk/releases/tag/v0.5.0).

The SDK and CLI become something you can run unattended. Every command yields
output a program can parse, every call can be inspected when it fails, every
stream can be released, and a consumer can test against the SDK without the
network. All but the last item landed in #45–#52.

- **Machine-readable output.** `--json` on every command that produces data,
  and `chat --schema FILE` for a validated structured reply from the shell.
- **Structured output in the SDK.** `response_format=` takes a pydantic model,
  `Completion.parsed` carries the validated instance or the call raises, and
  `capabilities()["structured_output"]` says whether a ref supports it.
- **Inspectable calls.** `xmagic` / `xmagic.http` loggers with `xmagic -v`,
  a `User-Agent` on every request, and `Completion.id` /
  `CompletionChunk.id` to tie a reply to the message the platform recorded.
- **Deterministic streams.** `Stream` / `AsyncStream` with `close()` and
  context-manager exit, on every streaming call.
- [x] **A test double for consumers** — done 2026-09-14 (DESIGN.md §15).
      `xmagic.testing.FakeXMagic` fakes the backend behind the real client;
      the recorded fixtures ship in the package. 0.5.0 is complete.

Also in the release, outside the theme: `mcp init` emits the hosted layout and
`/health`; SKILL.md frontmatter is read as YAML. Minor bump, per the Changed
entries in CHANGELOG.md.

### 0.6.0 — Files in, results out: Drive and Worklists complete

Everything a worklist consumes or produces is reachable from the SDK and CLI
without opening the web app. The client already speaks every Drive route the
platform documents; this release puts them on the command line and closes the
loop from local file to worklist input to output back in Drive.

- [ ] **Drive on the command line** — `xmagic drive download`, `rm`, `rename`,
      and recursive listing, for the routes implemented on 2026-08-06.
- [x] **Worklist inputs from local files** — done 2026-09-14. `--input FILE`
      on `worklists create|edit`, an `input_files` list in the YAML, and
      `worklists.upload_inputs()` in the SDK; files go through a Drive folder,
      the one route that yields a storage path.
- [ ] **Worklist outputs to Drive** — the `examples/` walkthrough (completed
      outputs → presigned download → Drive upload) that 0.3.0 documented and
      never shipped.
- [ ] **Complete listings** — `list_folders` / `list_files` paginate instead
      of truncating at 20. Needs the request parameter names from
      [#5]; if they have not arrived, the release ships with the cap
      documented and this item moves to the next version.

Pagination changes what a listing returns, which is the Changed entry that
makes this a minor bump.

### After 0.6.0 — Tools, end to end

The next capability, not yet a version: the tool-calling execution loop
(stage D, pending the DESIGN.md §13.8 Q1 decision), a `capabilities()`
vocabulary that can say "tools registered platform-side", remote invocation of
a registered tool, and `mcp deploy|list|logs|stop|delete` once hosting is
offered. Named here so the two decisions and the [#5] answers have somewhere
to land; it gets a number when enough of it is unblocked to be one release.

### Kept out of the plan

- **Hygiene, not features**, done whenever: a second owner on the PyPI project;
  the `httpx`/`httpx2` boundary decision ([#34]).
- **Not scheduled:** Phase 5 (`xmagic serve`), the redactor and coding-agent
  bridge templates (§11, §12), and the larger surface items (observability,
  middleware, human-in-the-loop, multimodal, caching). Each wants its own
  design pass before it gets a version.

[#5]: https://github.com/stochasticai/xmagic-sdk/issues/5
[#34]: https://github.com/stochasticai/xmagic-sdk/issues/34

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
- [x] **Check `/v1/mcp-servers` before building `mcp dev --tunnel`.** Checked
      2026-09-12 with a live key. **Hosting is on the platform roadmap but not
      offered yet**: the deployment routes from the 0.0.x SDK are still
      reachable (`GET /v1/mcp-servers` lists, `POST` requires `name` +
      `code_zip_upload_file_id`, `POST .../validate-code` unzips the upload,
      requires `mcp_server.py` at the root, and returns an AI review), but
      every deployment is rejected ~1 s after submission — `status: failed`,
      `url: null`, `service_account_name: null`, `{}` from `/logs` — before a
      container is scheduled. That is the feature being gated, not a bug in
      the upload. What the runtime *will* do, from its returned startup
      script: `pip install -r requirements.txt` then `python mcp_server.py`,
      found up to two levels deep under `/code`, with `MCP_RUN_LOCALLY=true`
      set; `command`/`args` in the request are ignored. `mcp init` now
      generates both files, so scaffolded projects pass validation today.
      `/v1/custom-tool-configs` (registration) is reachable too — DESIGN.md
      §10.1 assumed it was not. Probe deployment ids, if anyone wants them:
      `6aa4f114af2a6e6aa27259e7`, `6aa4f1f316c3d6dd08c8296a`
- [ ] `xmagic mcp deploy|list|logs|stop|delete` on `/v1/mcp-servers`, and a
      real `xmagic tools register` on `/v1/custom-tool-configs` — build when
      hosting ships. The 0.0.3 wheel's `mcp/deploy_mcp.py` is the reference
      for payloads and status values (`deploying` → `running` | `failed`;
      note the server's `cpu_milllicores` spelling)

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
- [x] Implement `LiteLLMProvider` (complete + stream) — done 2026-08-23. Covers
      the remaining ~150 vendors, Anthropic and Google among them. Two behaviours
      differ from `OpenAIProvider` and are documented rather than papered over: a
      missing API key is not an error (LiteLLM resolves per-vendor credentials
      from the environment, and a local runtime needs none), and streamed token
      counts may be LiteLLM's own estimate when the upstream sends no usage frame
- [x] `xmagic models list` — done 2026-08-23, plus `xmagic models providers`.
      Reads `litellm.model_cost` (2,390 chat models across 85 providers as of
      litellm 1.95) rather than `model_list`, because that mapping also carries
      the mode, capability flags, context window, and prices. Three decisions
      worth knowing: chat models only by default, since that is all the
      `Provider` interface does; a missing capability flag renders `?` rather
      than `no`, because ~700 models carry none and "unsupported" would be
      invented; and truncation is announced, on stderr under `--json` so stdout
      stays valid
- [x] Provider capability flags — done 2026-08-23. `LiteLLMProvider.capabilities()`
      reads `litellm.supports_function_calling` / `supports_vision` for the model
      the ref names, rather than hand-maintaining a table. Both report `False` for
      a model LiteLLM has no metadata for, so an unmapped model reads as "cannot
      confirm"
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
- [x] Richer SKILL.md validation — done 2026-09-11. Frontmatter goes through
      `yaml.safe_load`, so folded descriptions and quoted colons read as
      written; a non-mapping block or a non-string `name`/`description` is
      refused with the reason rather than coerced
- [ ] Wire skills upload / tool registration APIs if xMagic publishes them
      (open question §10.1)

## Worklists

- [x] Sync/async task and recurring-schedule client resources
- [x] `xmagic worklists` list/get/create/edit/delete/cancel/trigger/rerun commands
- [x] Sync/async review: complete a needs-review task or send agent guidance;
      CLI review uses blank=complete and `/skip`=leave in needs_review, with no
      approve/retrigger path
- [x] Single-page `--skip`/`--limit` pagination and latest chat-result retrieval
- [ ] **`examples/06_worklist_outputs_to_drive.py` was documented but never
      written.** `examples/README.md` described it in the table and in two Notes
      paragraphs as though it shipped — it went out that way in 0.3.0. The false
      entries were removed 2026-08-23 and slot 06 went to the provider example;
      the script itself (completed worklist outputs → presigned download → Drive
      upload) is still worth writing, and the README text describing it is in
      this file's git history
- [x] Upload local files for `input_s3_file_paths` directly from Worklist YAML/CLI
      — done 2026-09-14 via Drive: upload, attach, take the data source's
      `value`. Probe finding worth keeping: the API accepts *any* string in
      `input_s3_file_paths` (a bare upload id was echoed back too), so a wrong
      path fails at run time, not at creation; what the run does with the
      path is unverified until a real task is executed with one

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
- [x] Multi-provider example — done 2026-08-23 as
      `examples/06_provider_model.py`. Takes any `provider:model` ref, needs no
      xMagic key, and runs with no key at all against `litellm:ollama/<model>`.
      Verified live against OpenAI on both the `openai:` and `litellm:` paths

## SDK surface — surveyed, not yet scoped

From a survey of what agent-platform SDKs commonly expose (2026-08-05). These are
ours to build — nothing external blocks them. Deliberately not assigned to a
phase; listed so they stop being invisible.

Ready now, roughly in order of value per unit of work:

- [x] **Token usage** on `Completion` / `CompletionChunk` — landed in
      [#20](https://github.com/stochasticai/xmagic-sdk/pull/20). The xMagic shape
      is still unconfirmed, so parsing degrades to `None` rather than reporting
      zeros it did not measure
- [x] **Tool calling as a typed surface** — stages A and C done 2026-08-24
      ([#16](https://github.com/stochasticai/xmagic-sdk/issues/16), DESIGN.md
      §13). `ToolDef`/`ToolCall`, `ChatMessage.tool_calls`/`tool_call_id`,
      `Completion.tool_calls`, `ToolDef.from_callable`, and one OpenAI-shape
      mapping shared by the `openai:` and `litellm:` adapters. D1-D5 accepted as
      designed. Still open:
- [ ] **Tool calling, stage D — execution loop.** Blocked on a decision, not on
      code: DESIGN.md §1 lists agent orchestration as a non-goal, and §13.8 Q1
      asks whether a call/execute/feed-back loop crosses that line. Every peer
      SDK ships one
- [ ] **`capabilities()` is a `dict[str, bool]` with no defined vocabulary.**
      D4 made the `tools` flag honest, but there is now no word for "has tools
      registered platform-side", which is what xMagic actually offers. §13.8 Q3
- [x] **Structured output** — done 2026-09-10 (DESIGN.md §14). `response_format=`
      takes a pydantic model, `Completion.parsed` carries the validated instance
      or the call raises. No `json_object` mode. The CLI flag followed on
      2026-09-11: `chat --schema FILE` builds the model from a JSON Schema file
      (DESIGN.md §14.3) and `--json` output gained `parsed`
- [x] **Logging, and a `User-Agent` header** — done 2026-09-10 (DESIGN.md §8).
      `xmagic` / `xmagic.http` loggers, `NullHandler` at the root, `DEBUG` for
      request/response lines and `INFO` for retries, never headers or bodies;
      `xmagic -v` for the CLI. `User-Agent: xmagic-sdk/<v> python/<v> httpx/<v>`
      on every xMagic request. Provider adapters keep their vendors' user agents
- [x] **`--json` output for the CLI** — done 2026-09-10 (DESIGN.md §5). Every
      data-producing command; JSON on stdout via `json.dumps`, errors on stderr,
      exit code as the verdict. `chat --schema` followed on 2026-09-11
- [x] **Stream cancellation and deterministic close** — done 2026-09-10
      (DESIGN.md §8). `Stream` / `AsyncStream` wrap every streaming call:
      `close()` cancels and releases now, `with` does it on exit
- [x] **A test double for consumers** — done 2026-09-14 (DESIGN.md §15).
      `xmagic.testing.FakeXMagic`: an `httpx` transport the real client talks
      to, state in memory, replies scripted per agent, every body rendered from
      the recorded fixtures, which moved into the package as
      `xmagic.testing.load_fixture`. Unrecorded routes answer `400 not_faked`

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
- [x] **Add a typechecker to CI** — done 2026-08-12. `mypy` in `strict` mode over
      `src/`, as a step in the existing matrix job so the required status checks
      already cover it. Found 13 errors, all fixed; one of them was a real defect
      (see below). `mypy>=2.3,<2.4`, bounded for the same reason ruff is
- [x] **Type-check `tests/` too** — done 2026-08-22
      ([#33](https://github.com/stochasticai/xmagic-sdk/issues/33)).
      `files = ["src", "tests"]`, with all 58 errors fixed. Four were real: a
      `StreamEvent` built with a `str` outside its own `Literal` (fixed by naming
      that `Literal` `StreamEventType` and annotating against it), `ChatType | None`
      dereferenced without a guard in two contract tests, `ModuleSpec | None`
      passed straight to `module_from_spec`, and `.text` read off the MCP content
      union without narrowing. The rest were missing annotations
- [ ] **`mcp` pulls in a second HTTP library.** It depends on `httpx2` (a separate
      distribution, 2.x) while this package uses `httpx` 0.28, so anything handing
      a client across that boundary is passing the wrong type. Fixed at the one
      call site we own (`mcp/client.py`), but the two coexisting in the same
      environment is worth a decision rather than a patch
      ([#34](https://github.com/stochasticai/xmagic-sdk/issues/34))
- [x] **Cover the authenticated `xmagic tools --url` path** — done 2026-08-22
      ([#32](https://github.com/stochasticai/xmagic-sdk/issues/32)). The scaffolded
      server now runs under uvicorn on a loopback port in the suite, driven with a
      key through both the client helpers and the CLI, plus a unit test pinning
      that `_target` hands the transport an `httpx2` client. That last one is the
      only check that fails if the #28 defect returns: a wrong-library client
      still works for request/response tools, which is why it survived
- [x] **`metadata` stream events are dropped** — done 2026-09-10. The
      `message_id` they carry is now `CompletionChunk.id` on the terminal chunk
      and `Completion.id` on the blocking path, with OpenAI's and LiteLLM's ids
      in the same field
- [ ] **Streaming calls are never retried** — decided 2026-09-10 to leave it
      that way until the platform answers one question (DESIGN.md §8): is a
      partially-delivered query safe to re-send, or does the agent see it
      twice? Retrying before the connection is established is safe on any
      reading and is the one piece worth building without the answer; ask on
      [#5](https://github.com/stochasticai/xmagic-sdk/issues/5) first
- [x] **No stream cancellation, and no deterministic close** — done 2026-09-10,
      see "Ready now" above

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
