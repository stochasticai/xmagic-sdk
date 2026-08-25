# Progress Log

Reverse-chronological log of work on xmagic-sdk. See [DESIGN.md](DESIGN.md) for
the plan and [TODO.md](TODO.md) for what's next.

---

## 2026-08-25 — Recovering two tests from a closed PR, and branch cleanup

Deleted 22 merged branches. One would not go: `fix/client-robustness`, the
branch behind **#25 — closed, not merged**. Issue #35 recorded that a review of
its replacement (#26) "invalidated the reasoning behind closing #25", and nobody
had gone back to check what that meant.

Diffed it against `main`. The verdict on the source is clean: every change was
superseded by #26, and by better versions — `stream_timeout` is configurable
where the closed branch hardcoded `read=None`, and the error hierarchy gained
`APITimeoutError` on top of what the branch had. Main's tests are broader too on
four of six areas, including pinning the jitter *spread* rather than only its
band.

Two assertions went down with it, though, and both are now recovered:

- **The async transport's connection-error wrapping had no test at all.**
  `AsyncHttpTransport._send` duplicates the sync `except httpx.HTTPError` rather
  than sharing it, and nothing executed that branch. Verified by deleting the
  wrapping: all four parametrized cases fail, so the test guards what it claims.
  Both transports now run off one shared failure list.
- **Nothing asserted that unary requests keep their ordinary read deadline.**
  Only the streaming half of the invariant was pinned. Verified the same way, by
  making `_stream_timeout` leak onto the unary path.

The closed branch can go once this lands. Its tip was `904bc4c`.

## 2026-08-24 — Tool calling as a typed surface (stages A and C)

The provider layer could not express the one capability that makes an agent an
agent: `capabilities()` advertised `tools: True` while `complete` had no `tools`
parameter, and `ChatMessage` could not represent a tool result at all.

- **Stage A** — `ToolDef` / `ToolCall`, `ChatMessage.tool_calls` and
  `tool_call_id`, `content` widened to `str | list[ContentPart] | None`, and
  `Completion.tool_calls`. One mapping in `providers/_openai_wire.py` serves both
  the `openai:` and `litellm:` adapters, which is the bet in §13.2 paying off:
  LiteLLM normalizes every vendor onto the OpenAI shape, so this is one mapping
  rather than one vendor's.
- **Stage C** — `ToolDef.from_callable` builds the schema from a typed signature
  and the description from the docstring.
- **D4 implemented as designed**: `XMagicProvider` reports `tools: False` and
  *rejects* `tools=` instead of ignoring it. So does `stream()` on every adapter,
  because stage B is not built and silently dropping the calls a model made is
  the exact failure this surface exists to prevent.
- **Two things the design did not settle, found while building:**
  - `strict` cannot be claimed for a schema with defaults or nested models —
    strict mode requires every property required and additional ones forbidden at
    every level, so `from_callable` turns it off rather than sending something
    the vendor rejects outright.
  - `get_type_hints` raises a bare `NameError` when a tool refers to a class
    defined inside a function under postponed annotations. It now raises a
    `ValueError` that says what to do about it.
- **`_flatten` was quietly wrong the moment `content` widened** — it would have
  interpolated the string "None" into an xMagic query. mypy caught it on the
  first run, which is the second time in a week the type gate has found a real
  defect rather than a style one.
- 27 new tests. Stages B and D remain, and §13.8 Q1 (is the execution loop ours
  to ship?) and Q3 (`capabilities()` has no vocabulary) are still open.

## 2026-08-23 — `xmagic models`, and the last missing example

Phase 3 is closed and `examples/` is complete.

- **`xmagic models list` / `xmagic models providers`**, over a new
  `providers/catalogue.py` that reads `litellm.model_cost` — chosen over
  `model_list` because it also carries mode, capability flags, context window,
  and prices. Chat models only by default (that is all `Provider` does); an
  unflagged model shows `?` rather than `no`, since ~700 of the 2,390 carry no
  flags and "unsupported" would be invented; truncation is announced, on stderr
  under `--json` so a piped stdout stays valid JSON. The command says in its own
  output that this is LiteLLM's catalogue and not xMagic's — xMagic publishes no
  model list, and a command called `xmagic models` implying otherwise is exactly
  the misreading worth heading off (DESIGN.md §10.6).
- **`examples/06_provider_model.py`** — the last unwritten example. Any
  `provider:model` ref, no xMagic key, and no key at all against
  `litellm:ollama/<model>`.
- **Verified live**, not only mocked: the example ran against OpenAI on both the
  `openai:` and `litellm:` paths, streaming and reporting 258 tokens off the
  terminal chunk. That is the gap the #37 review notes said only a live vendor
  could close.
- **Found in passing:** `examples/README.md` documented
  `06_worklist_outputs_to_drive.py` — a table row and two Notes paragraphs, in
  the shipped 0.3.0 — for a script that was never written. The false entries are
  removed and the script is filed in TODO.md.
- 20 new tests, driving a fake catalogue for everything that would otherwise
  break on LiteLLM's release schedule, plus a short section on the real one.

## 2026-08-23 — LiteLLMProvider

The last stubbed adapter is implemented, which closes the largest unblocked gap
in the SDK surface: one adapter, roughly 150 vendors, over the `Provider`
interface that already carried `xmagic:` and `openai:`.

- **`complete` and `stream`**, with reasoning deltas (LiteLLM normalizes every
  vendor's thinking channel onto `reasoning_content`), token usage, and vendor
  errors translated into this SDK's hierarchy. `done` is emitted at the end of
  the stream rather than on `finish_reason`, unlike the OpenAI adapter: the
  usage frame arrives *after* the finish reason, so closing early would drop the
  counts every time.
- **`capabilities()` reads LiteLLM's model metadata** instead of a hand-kept
  table (`supports_function_calling` / `supports_vision`), off the model the ref
  names.
- **Three behaviours found by testing rather than assumed**, each pinned:
  LiteLLM attaches a zero-filled `Usage` to a response that carried none (now
  treated as absent, not as three measured zeros); it validates parameters
  against the model before sending, so `temperature=0.2` on gpt-5 fails locally;
  and it classifies a dead socket on the OpenAI path as `InternalServerError`,
  so that surfaces as `ServerError` rather than `APIConnectionError`. The last
  one is documented rather than re-classified — undoing it would mean
  string-matching LiteLLM's messages.
- **22 tests**, driving real LiteLLM through respx — no vendor double — plus the
  registry and CLI paths (`xmagic chat -m litellm:openai/gpt-5`), which is what
  proves credential resolution from the vendor's own environment variable works
  end to end.

## 2026-08-22 — Test coverage for the authenticated tools path, and typed tests

Closes the two mechanical gaps left open at 0.3.0.

- **`xmagic tools --url` with a key is exercised over a real socket** (#32). The
  suite scaffolds a project, imports the server `mcp init` generates — middleware
  included — and serves it with uvicorn on an ephemeral loopback port, then drives
  it through `list_tools`/`call_tool` and through the CLI. Wrong key and no key
  both assert the error reads as an auth problem rather than an SSE content-type
  complaint. A separate unit test pins that `_target` hands the transport an
  `httpx2` client: verified by reintroducing the #28 defect, and it is the *only*
  check that catches it — the seven socket tests stay green with an `httpx`
  client, because that path never opens a standalone SSE stream.
- **`mypy --strict` covers `tests/`** (#33), `files = ["src", "tests"]`, 58 errors
  fixed. The four substantive ones: `StreamEvent(type=...)` built with a `str`
  outside its `Literal` — fixed by naming the `Literal` `StreamEventType` in
  `client/models.py` and annotating the test helper against it, so the list is
  stated once; `ChatType | None` dereferenced with `.value` in the sync and async
  contract tests, now `is ChatType.STANDARD` (the wire spelling was already
  pinned by the request assertion next to it); `ModuleSpec | None` passed to
  `module_from_spec`; and `.text` read off the five-member MCP content union
  without an `isinstance` narrow.
- **`tests/_helpers.py`** — the scaffold-import dance existed in two places and
  the new file would have made three, so it is one typed helper now.

Verification: 214 passed, ruff clean, `mypy --strict` clean over 67 files, on
both ends of the matrix (3.11 and 3.14).

## 2026-08-13 — Agent deployment review hardening

- **Deployment no longer changes workspace state while validating an agent.**
  `xmagic agents deploy` now requires a known current workspace, fetches the
  agent directly, and compares its `organization_id` with the current workspace
  instead of switching through every accessible workspace.
- **Optional phone association is safer and scriptable.** `--phone <id>` and
  `--no-phone` make the deployment path deterministic for CI and other
  non-interactive callers. Phone discovery skips only known unavailable-service
  errors and prints a warning; prompt EOF or invalid input skips the optional
  association rather than aborting deployment.
- **Client response handling is consistent.** Response-shape and editor failures
  now use the `XMagicError` hierarchy, `unwrap_data` is shared by client
  resources, and temporary config responses require the verified string `id`
  field.
- **Composer invocation uses a plain chat runner.** The `--composer/-C` path
  calls the same concrete chat implementation as the CLI without passing
  Typer option objects through the call boundary.
- `PhonesAPI` / `AsyncPhonesAPI` are included in the async signature-parity test. 

## 2026-08-13 — Workspace switching and agent config/deploy CLI

- **`xmagic workspaces`** — lists all accessible workspaces with current-workspace
  marker, switches by exact name (`xmagic workspaces "Name"`) or by id
  (`xmagic workspaces --id <id>`). Backed by `WorkspacesAPI`/`AsyncWorkspacesAPI`
  wrapping `GET /users/workspaces` and `POST /users/workspaces/switch`.
- **`xmagic agents`** — default invocation lists agents in the current workspace
  context (`GET /agents`). Two subcommands:
  - **`xmagic agents config [--agent <id>]`** — fetches the agent's temporary
    config (`GET /agents/{id}/configs/temporary` then `…/{cfg_id}/config`),
    serialises it to YAML, opens `$VISUAL`/`$EDITOR`/`nano` for editing, and
    pushes the diff back with `PATCH /agents/{id}/configs/temporary`.
    No-op if the file is saved without changes. `--composer/-C "<prompt>"` is
    an alias that delegates to `xmagic chat --chat-type configuration` instead
    of opening an editor.
  - **`xmagic agents deploy [--agent <id>] [--version "…"]`** — saves the
    current temporary config as a named version (`POST /agents/{id}/configs`),
    optionally attaches a phone number (with optional subagent scope) via
    interactive selection, then deploys (`POST /agents/{id}/configs/{cfg}/deploy`).
    Default version name mirrors the frontend's dayjs format
    (`"August 6, 2:30:45 PM"`). Phone step is silently skipped if `/phones`
    returns an error (voice not enabled on the account).
- **`config_codec.py`** — `json_to_yaml` / `yaml_to_json` / `validate_config_json`
  helpers (backed by `PyYAML>=6.0`, added to `pyproject.toml`). Normalises the
  wire-shape quirk where the backend may return `jobs` instead of `subagents`.
  Required top-level keys (`config_values`, `subagents`, `agent_level_tools`,
  `agent_level_quick_actions`) are validated before any PATCH.
- **New client modules**: `client/agents.py` (`AgentsAPI`/`AsyncAgentsAPI` —
  list, get/export temporary config, update, save, deploy, list subagents),
  `client/phones.py` (`PhonesAPI`/`AsyncPhonesAPI` — list, associate),
  `client/workspaces.py` (`WorkspacesAPI`/`AsyncWorkspacesAPI` — list, switch).
  All three are wired into both `XMagicClient` and `AsyncXMagicClient` in
  `client/__init__.py`.
- **New Pydantic models** in `client/models.py`: `Workspace`, `WorkspaceState`,
  `AgentSummary`, `SavedConfig`, `PhoneSummary`, `SubagentSummary`.
- **README quickstart** renumbered and expanded: workspace listing/switching and
  agent config/deploy steps (formerly steps 3 and 4) are now steps 3–6, with
  the original "Talk to your agent" step bumped to 6.
- **Tests**: `test_cli_agent.py` (12 tests covering agent list, config no-op,
  config edit-and-patch, default agent from config, deploy with/without phones,
  subagent selection, phone skip on 501), `test_cli_workspace.py` (4 tests),
  `test_config_codec.py` (round-trip + missing-key validation). `AgentsAPI` /
  `AsyncAgentsAPI` and `WorkspacesAPI` / `AsyncWorkspacesAPI` added to the
  async-parity parametrize in `test_async_client.py`.

## 2026-08-12 — Worklist SDK and CLI

- Added sync/async Worklist task and recurring-schedule resources covering list,
  get, create, update, delete, trigger, rerun, stop, and schedule pause/resume
  operations. List requests expose explicit single-page `skip`/`limit` controls.
- Added `xmagic worklists` commands for task lifecycle management and YAML-based
  create/edit flows, plus `schedules get|edit|pause|resume|delete`. Task lookup
  fetches the latest related chat message with downloadable output URLs when a
  run is available.
- Added Pydantic models, YAML validation/diff codecs, shared editor handling,
  API/CLI tests, async parity coverage, and documentation. Direct local-file
  upload for `input_s3_file_paths` remains deferred; current inputs must be
  pre-existing S3 paths.
- Worklist review now has two API outcomes: mark a `needs_review` task
  `completed` without another agent action, or send guidance in the existing
  run chat. The CLI shows tasks one at a time: blank completes, `/skip` leaves
  the task in `needs_review`, and any other input sends guidance.


## 2026-08-07 — Client hygiene: typing, timeouts, and the error contract

The five audit findings that were listed as "ready now, nothing blocks them" and
had sat unclaimed for two days. Cheap individually; together they are most of
what a consumer notices when something goes wrong.

- **`py.typed`.** Every module here is annotated and none of it reached
  consumers — PEP 561 treats an installed package without the marker as untyped,
  so `xmagic` resolved to `Any` in every downstream mypy and pyright run.
  Nothing local notices, since we test the source. It needed no
  `pyproject.toml` change, contrary to how it was filed: hatchling picks the
  marker up from the package directory. Verified by building both artifacts and
  looking inside, not by reading the docs.
- **Streams no longer inherit the 60s request timeout.** On a stream the read
  timeout bounds the gap *between events*, not the whole exchange, so an agent
  that thought for longer than `timeout` raised `ReadTimeout` mid-answer.
  Separate `stream_timeout`, default 300s.
- **Error hierarchy filled in**: 403, any 5xx, and wrapped transport failures, so
  `except XMagicError` now actually contains the SDK — previously a DNS failure
  or timeout meant also catching httpx. `XMagicAPIError` carries the response,
  headers, body, and a best-effort request id.
- **Jittered backoff.** The old `min(2**attempt, 30)` was deterministic, so
  clients that failed together retried in lockstep and rebuilt the spike that
  caused the failure. `Retry-After` is left verbatim — the server named a time.
- **Root exports** for `ConfigurationError` and `ChatType`. The first is what
  `XMagicClient()` raises on a missing API key, the likeliest first-run failure
  of all, and catching it meant importing from a path that looks private.

**A defect found by doing the work, not by the audit.** A 401 on `chats.stream`
raised `SSEError("Expected response header Content-Type to contain
'text/event-stream', got 'application/json'")` — the symptom, from httpx_sse's
exception tree, for what was really an auth failure. `connect_sse` validates the
content type and nothing validated the status. Wrapping transport errors made it
briefly worse, since `SSEError` subclasses `httpx.TransportError`: the auth
failure started reporting as "Could not reach <base_url>". Both transports now
check the status before decoding frames and raise what the equivalent unary call
would. Caught by probing a mocked 401 rather than by the test suite, which had no
case for a stream that fails before it starts.

Two things this surfaced and did **not** fix, now in TODO.md: streaming calls are
never retried at all (`sse()` has no retry loop, so a 429 on `stream` fails
immediately while the same status on `query` gets the full schedule), and a
typechecker in CI is now the most valuable item on that list rather than the
least — we are publishing annotations that nothing verifies.

Tests: 105 → 142. Also reconciled TODO.md, which was underselling itself: token
usage and all three addressed release-hygiene items were still listed as pending.

**Note for anyone whose local suite is red on `main`:** a stale `uv.lock` pinning
`mcp` 1.28.1 against the `>=2.0` requirement fails six tests in
`test_tool_invocation.py` while CI stays green. `uv lock --upgrade` clears it.
Third time this trap has cost someone time; it is documented in PLAN.md's notes.

## 2026-08-06/07 — MCP repair, OpenAI provider, release hygiene

A long session. The through-line is that several things believed to be working
were not, and were only found by running them rather than reading them.

**Live defect: `xmagic mcp init` generated projects that could not start.** The
template imported `mcp.server.fastmcp.FastMCP`; mcp 2.0 moved that class, and both
the template and this package declared an unbounded `mcp>=1.0`, so a fresh install
resolved to 2.x and every scaffolded server died at import. **This is still true of
the published 0.1.0** — the fix is on main, unreleased. The scaffold test could not
have caught it: it used `py_compile`, which parses without resolving imports.
Ported to `MCPServer`, bounded to `>=2.0,<3`, and the test now imports the rendered
module for real and drives it over MCP's in-memory transport (#11).

**Live defect: streamed errors were silently discarded.** `XMagicProvider.stream`
branched on done/response/reasoning with no `else`, so an `error` frame vanished —
a failed generation was indistinguishable from a short successful one, and
`xmagic chat` exited 0. Now raises (#20). There was no provider-level test file at
all, which is exactly how it went unnoticed.

**Also shipped:** local tool invocation, `xmagic tools list/call --url`, which
closes the deploy → tunnel → register → hope-the-agent-calls-it dev loop and gives
`mcp init` its first real integration test (#14). A weekly drift check that tests
the *published* artifact from PyPI, since CI only ever exercises the working tree
(#13). `OpenAIProvider`, the first non-xMagic model (#9). Four documented Drive
routes (#15). Token usage surfaced (#20). Release gating and a TestPyPI rehearsal
(#19), and one source of version truth (#18).

**PyPI audit** — see the entry below for the full account.

**Platform questions.** Unpacking the 0.0.3 wheel turned up a `/v1/mcp-servers`
deployment API and a **non-MCP REST tool contract**, both bearing on questions #5
marks as blocking. #21 then confirmed the `agents` hierarchy is the old `personas`
tree renamed — response fields still say `persona_id`. Q5 is resolved; Q13 and Q15
narrowed; Q16 added for the auth-dependent `subagents`→`jobs` key transform.

**Corrected along the way:** xMagic documents no model selection anywhere, so
multi-provider was deprioritised to LiteLLM plus one native adapter. Undocumented
behaviour is treated as unsupported rather than built against — a rule this session
broke once and then adopted deliberately.

## 2026-08-05 — PyPI audit: name mismatch, ownership, and a legacy shim

Audited this project's PyPI presence. Findings are written up in
[PYPI_HISTORY.md](PYPI_HISTORY.md); the short version:

- **`xmagic-sdk` carries two unrelated packages.** Releases 0.0.1–0.0.3
  (November 2025, setuptools) installed a top-level `xmagic_sdk` module with a
  different public API; 0.1.0 installs `xmagic`. Same distribution name, so
  `pip install -U` deletes the old package and `import xmagic_sdk` breaks. Gone
  with it: `run_mcp_server`, `fetch_info_from_kb_v1`/`_v3`, and the hosted
  deployment commands (`xmagic mcp run`/`list`/`logs`/`start`/`stop`/`delete`/
  `validate`, ~1,100 lines in `mcp/deploy_mcp.py`). `configure` and `chat`
  survive by name with different flags, which makes the break quieter, not
  smaller. ~275 non-mirror downloads in the six months before 0.1.0, essentially
  all 0.0.3.
- **Added a raising `xmagic_sdk` shim** (`src/xmagic_sdk/__init__.py`) so that
  import fails with the replacement name, the version boundary, the specific
  dead APIs, and `pip install 'xmagic-sdk==0.0.3'` as the escape hatch. A
  re-export shim was impossible — nothing in the 0.0.x API has a counterpart
  today, so the choice was a pointed error or silence. Pinned by
  `tests/test_legacy_shim.py`, removable at 1.0. Verified by installing a built
  wheel into a clean venv.
- **`xmagic` on PyPI is owned by someone else**, and always was: account
  `XOne_Team` (Amr Elmenyawy), which registered it alongside `XMagics` and
  `XOne-Magic` in **August 2022** — three years before xMagic. Their published
  code is an SMS helper. So the install/import mismatch is permanent, not an
  oversight, and renaming the distribution would need a PEP 541 transfer. The
  ownership is not visible via the JSON API or the project page (JS challenge);
  PyPI's XML-RPC `package_roles` still answers it, and the recipe is in the
  write-up.
- **`xmagic-sdk` has a single role holder**, `internal_apis`, which owns no other
  packages. Trusted publishing means routine releases don't depend on it, but
  yank/delete/maintainer rights do.
- **0.0.3 was a burned version number** — 44 minutes after 0.0.2, for a single
  `logger.warning` → `logger.debug` line. 0.0.1 was a 1,225-byte name
  reservation whose only module read `version = "0.0.1"`. Filed the release
  guards that would prevent a repeat under Phase 6 in [TODO.md](TODO.md); the
  sharpest is that `release.yml` runs no tests before publishing.

Suite 50 → 53 passing.

## 2026-08-05 — Phase 1 complete: async client, chat polish, retry coverage

- **`AsyncXMagicClient` implemented**, closing the last Phase 1 gap and the only
  `NotImplementedError` in the package that wasn't honestly deferred to a later
  phase — it was exported from the package root and raised on construction.
  Sync and async transports now sit side by side in `client/http.py` and share
  auth, retry, and SSE decoding; each resource module holds both classes over
  shared path/payload helpers, so the two cannot drift on the wire. The async
  tests replay the *same* recorded fixtures as the sync contract tests, plus a
  structural parity test that fails if either side gains a method or renames an
  argument.
- **Found and fixed a real bug while writing the retry tests**: `Retry-After` is
  allowed by RFC 9110 to carry an HTTP-date, and `float(retry_after)` raised
  `ValueError` mid-retry rather than retrying. Unparseable or non-positive values
  now fall back to exponential backoff. The README had advertised this retry
  behavior since 0.1.0 with no test covering it.
- **`xmagic chat`**: `-f/--file` (repeatable) uploads and references files on the
  query, `--chat-type` selects the UI context, and reasoning renders dimmed above
  the answer. `CompletionChunk` gained a `kind` field to carry that distinction
  through the provider interface without forcing other adapters to care.
  *Session reuse across interactive turns was already working* — the provider is
  constructed once and `_ensure_chat` caches the chat id — so that item needed a
  test, not an implementation.
- Suite went 18 → 50 passing (3 live tests still deselected): 9 retry, 13 async,
  10 CLI.
- Added `examples/05_skills.py`; `examples/` is now 5 scripts, 2 of which need no
  API key. Only the multi-provider example is left, still blocked on Phase 3.
- Dev dependency: `pytest-asyncio` (bounded `>=1.0,<2`) with `asyncio_mode =
  "auto"`.

## 2026-08-03 — 0.1.0 released to PyPI

- **`xmagic-sdk` 0.1.0 is on PyPI**, published from tag `v0.1.0` via the
  trusted-publishing workflow. The one-time setup PLAN.md §7 flagged as blocking
  (PyPI trusted publisher + a GitHub `pypi` environment) is done, so the release
  path is proven end to end rather than only written. The README's PyPI badges
  now resolve against a real release.
- Added **CHANGELOG.md** covering 0.1.0. Note that PyPI also carries 0.0.1–0.0.3
  from November 2025; those predate this repository's history, so 0.1.0 is the
  first release cut from this codebase and the changelog starts there.
- `CITATION.cff` gained `date-released: 2026-08-03`, which it had been carrying a
  TODO comment for since Phase 1 of PLAN.md.

## 2026-07-31 — Live API validation (#2 closed)

- **Request/response shapes are confirmed against a live agent** and locked
  down, closing [#2](https://github.com/stochasticai/xmagic-sdk/issues/2) —
  the item TODO.md had listed as blocking the rest of Phase 1. Verified chat,
  stream, upload, and Drive endpoints; replaced defensive `.get` chains with the
  confirmed shapes; fixed `StreamEvent`'s `Literal` and `Message.output_assets`.
- Added `tests/test_client_contracts.py` (324 lines) with respx-mocked tests over
  9 recorded fixtures, including SSE frames, plus opt-in live tests that resolve
  an API key from the environment, `.env`, or `xmagic configure`'s config.toml.
  Suite is now 18 passing with the 3 live tests deselected by default.
- Landed via PR #6 (`e0e39c2`), merged to main in `f932e6f`.
- **Phase 1 is unblocked.** `AsyncXMagicClient` is next: it mirrors a now-verified
  sync client, and it is the only `NotImplementedError` left in the package that
  belongs to Phase 1 rather than a later phase.

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
