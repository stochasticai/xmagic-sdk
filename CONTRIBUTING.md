# Contributing to xmagic-sdk

Thanks for your interest in improving the xMagic Python SDK and CLI. This guide
covers local setup, the checks we run, and how to get a change merged.

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

The project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
git clone https://github.com/stochasticai/xmagic-sdk.git
cd xmagic-sdk
uv sync --all-extras            # installs the package, all extras, and dev tools
git config core.hooksPath .githooks   # enable the pre-commit hook
```

That creates a `.venv/` with the package installed in editable mode, so
`uv run xmagic --help` reflects your working tree.

The hook config is per-clone — git cannot commit it for you, so run that line
once. See [Pre-commit hook](#pre-commit-hook) for what it does.

## Running the checks

```bash
uv run pytest             # test suite
uv run ruff check .       # lint
uv run ruff format .      # format
uv run mypy               # types (strict, src/ only)
```

All four must pass before a pull request can be merged; CI runs the same
commands across Python 3.11–3.14, checking formatting with `ruff format
--check .`. `mypy` is strict and covers `src/` only — the package ships
`py.typed`, so those annotations are a promise to consumers' type checkers.
`tests/` is not type-checked yet; see TODO.md. The repo is fully formatted, so run `ruff format .` before pushing
rather than hand-matching style. Tests live in `tests/`
and use
[respx](https://lundberg.github.io/respx/) to mock HTTP — no network calls and
no real API key should be required to run the suite.

## Pre-commit hook

`.githooks/pre-commit` runs the two ruff gates against your **staged** content,
so CI does not tell you about a formatting slip minutes later. Enable it with
the `git config` line in [Development setup](#development-setup).

Worth knowing: **ruff formats Python code blocks inside Markdown**, so `.md`
files are format-checked too. A hand-aligned snippet in a design document will
fail CI exactly like a `.py` file would — which is why this hook exists.

Details, in case it behaves in a way that surprises you:

- It checks the staged blobs, not the working tree, so unstaged edits neither
  mask a real failure nor cause a spurious one.
- It runs ruff through `uv run`, so the version is the one `pyproject.toml`
  pins and local matches CI by construction.
- It does **not** run pytest — pytest works against the working tree rather
  than the index, so it would report on code you are not committing. CI covers
  the tests.
- `git commit --no-verify` bypasses it.

## Project layout

```
src/xmagic/
  client/      # XMagicClient, HTTP transport, chats/files/drive resources
  cli/         # typer commands (chat, configure, drive, mcp, serve, skills, tools)
  providers/   # provider adapters + registry (xmagic, openai, anthropic, google, litellm)
  mcp/         # MCP server scaffolding
  skills/      # skill packaging
  webapp/      # local web app proxy for `xmagic serve`
tests/
```

New providers are registered through the `xmagic.providers` entry points in
`pyproject.toml` and should subclass the base in `src/xmagic/providers/base.py`.

## Commit messages

We follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).
See [COMMIT_GUIDELINES.md](COMMIT_GUIDELINES.md) for the full spec, allowed
types, and suggested scopes. Short version:

```
feat(mcp): add dockerfile generation to `xmagic mcp init`
fix(chat): handle SSE reconnect on stream timeout
docs: expand quickstart with skills packaging example
```

## Pull request workflow

1. **Open an issue first** for anything larger than a small fix, so we can agree
   on the approach before you invest time. See [ISSUES.md](ISSUES.md).
2. Fork the repo and branch from `main` (e.g. `feat/streaming-retries`).
3. Make your change, and add or update tests to cover it.
4. Update the README or other docs if you changed user-facing behavior.
5. Run the checks above.
6. Open a pull request against `main`, fill in the template, and link the issue
   it addresses (`Fixes #42`).
7. Keep the PR focused — one logical change. Rebase or push follow-up commits in
   response to review; we squash on merge.

## Reporting security issues

Please do **not** open a public issue for a security vulnerability. See the
reporting instructions in [ISSUES.md](ISSUES.md#security-vulnerabilities).

## Never commit secrets

API keys belong in your environment or in `xmagic configure` output, never in
the repo. `.env` files are gitignored on purpose.
