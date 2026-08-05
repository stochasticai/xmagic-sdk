# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versions 0.0.1–0.0.3 exist on PyPI (November 2025) but predate this repository's
history and are not covered below. **0.1.0 is the first release cut from this
codebase.**

## [Unreleased]

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
