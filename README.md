# xmagic-sdk

[![PyPI](https://img.shields.io/pypi/v/xmagic-sdk.svg)](https://pypi.org/project/xmagic-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/xmagic-sdk.svg)](https://pypi.org/project/xmagic-sdk/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![CI](https://github.com/stochasticai/xmagic-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/stochasticai/xmagic-sdk/actions/workflows/ci.yml)

Python SDK and CLI for [xMagic](https://xmagic.ai), Stochastic's AI agent platform.

> **Status: alpha scaffold.** Parts of the surface below are still stubs that
> raise `NotImplementedError` — each is marked with the roadmap phase that
> implements it. See [DESIGN.md](DESIGN.md) for the design plan and
> [TODO.md](TODO.md) for current work.

## What it does

Working today:

1. **MCP servers** — scaffold containerized (Dockerfile included) MCP servers you can
   register as xMagic custom tools.
2. **xMagic API** — chat (sync + streaming), file uploads, Drive (knowledge base),
   skills packaging. The client is implemented but its request/response shapes
   have not yet been verified against the live API
   ([#2](https://github.com/stochasticai/xmagic-sdk/issues/2)).

Planned:

3. **Multi-provider** *(Phase 3)* — one interface across xMagic, OpenAI, Anthropic,
   Google, and (via LiteLLM) 100+ more. Only the xMagic provider is implemented so
   far; the others are stubs.
4. **Bring your own model** *(Phase 3)* — `provider:model` refs with your own API keys.
5. **Async client** *(Phase 1)* — `AsyncXMagicClient`, a 1:1 mirror of the sync client.
6. **Local web app** *(Phase 5)* — `xmagic serve` runs the xMagic web app locally
   via proxy.

## Install

```bash
uv pip install xmagic-sdk            # core
uv pip install "xmagic-sdk[all]"     # + all provider/serve/mcp extras
```

From a checkout:

```bash
uv pip install -e .              # core
uv pip install -e ".[all]"      # + all provider/serve/mcp extras
```

## Quickstart

```bash
xmagic configure                          # store your xMagic API key
xmagic chat --agent <agent_id> "Hello!"   # talk to your agent
xmagic mcp init my-tool                   # containerized MCP server scaffold
xmagic skills new my-skill && xmagic skills pack my-skill
```

Once the provider adapters land in Phase 3, the same command will accept a
`provider:model` ref backed by your own key:

```bash
xmagic chat -m anthropic:claude-sonnet-5 "Hello!"   # not yet implemented
```

Today that path exits with a `NotImplementedError` pointing at the roadmap.

```python
from xmagic import XMagicClient

client = XMagicClient()
chat = client.chats.create("<agent_id>", title="demo")
for event in client.chats.stream("<agent_id>", chat.id, "Explain xMagic skills"):
    if event.type == "response":
        print(event.text, end="")
```

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

CI runs all four across Python 3.11–3.14, and gates on formatting as well as
linting — run `uv run ruff format .` before pushing.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org)
(`feat:`, `fix:`, `docs:`, `test:`, `chore:`, ...; optional scope, e.g. `feat(mcp): ...`).

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup and
the PR workflow, and [ISSUES.md](ISSUES.md) for filing bugs, feature requests,
and security reports. All participants are expected to follow our
[Code of Conduct](CODE_OF_CONDUCT.md).

## License

[Apache-2.0](LICENSE) © Stochastic
