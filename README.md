# xmagic-sdk

[![PyPI](https://img.shields.io/pypi/v/xmagic-sdk.svg)](https://pypi.org/project/xmagic-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/xmagic-sdk.svg)](https://pypi.org/project/xmagic-sdk/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![CI](https://github.com/stochasticai/xmagic-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/stochasticai/xmagic-sdk/actions/workflows/ci.yml)

Python SDK and CLI for [xMagic](https://xmagic.ai), Stochastic's AI agent platform.

> Status: alpha scaffold. See [DESIGN.md](DESIGN.md) for the full design plan and roadmap.

## What it does

1. **MCP servers** — scaffold containerized (Dockerfile included) MCP servers you can
   register as xMagic custom tools.
2. **xMagic API** — chat (sync/streaming/async), file uploads, Drive (knowledge base),
   skills packaging.
3. **Multi-provider** — one interface across xMagic, OpenAI, Anthropic, Google, and
   (via LiteLLM) 100+ more.
4. **Bring your own model** — `provider:model` refs with your own API keys.
5. **Local web app** — `xmagic serve` runs the xMagic web app locally via proxy.

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
xmagic chat -m anthropic:claude-sonnet-4-5 "Hello!"   # your own keys
xmagic mcp init my-tool                   # containerized MCP server scaffold
xmagic skills new my-skill && xmagic skills pack my-skill
```

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
```

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org)
(`feat:`, `fix:`, `docs:`, `test:`, `chore:`, ...; optional scope, e.g. `feat(mcp): ...`).

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup and
the PR workflow, and [ISSUES.md](ISSUES.md) for filing bugs, feature requests,
and security reports. All participants are expected to follow our
[Code of Conduct](CODE_OF_CONDUCT.md).

## License

[Apache-2.0](LICENSE) © Stochastic
