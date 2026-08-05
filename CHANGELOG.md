# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versions 0.0.1–0.0.3 exist on PyPI (November 2025) but predate this repository's
history and are not covered below. **0.1.0 is the first release cut from this
codebase.**

## [Unreleased]

Phase 1 (core client) is complete as of these changes.

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
- **An `xmagic_sdk` compatibility shim.** Importing it now raises an `ImportError`
  naming the replacement (`xmagic`), the version the change happened in, and
  `pip install 'xmagic-sdk==0.0.3'` for anyone who needs the old API. Scheduled
  for removal in 1.0. See Compatibility below.

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

### Fixed

- **`Retry-After` carrying an HTTP-date crashed the retry loop** with
  `ValueError` instead of retrying. RFC 9110 permits a date as well as a delay in
  seconds; an unparseable or non-positive value now degrades to the normal
  exponential backoff.

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
[Unreleased]: https://github.com/stochasticai/xmagic-sdk/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/stochasticai/xmagic-sdk/releases/tag/v0.1.0
