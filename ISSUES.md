# Reporting Issues

Bug reports and feature requests go to the
[GitHub issue tracker](https://github.com/stochasticai/xmagic-sdk/issues).

Before opening one, please
[search existing issues](https://github.com/stochasticai/xmagic-sdk/issues?q=is%3Aissue)
— including closed ones — to see if it has already been reported or answered.

## Bug reports

Open a [bug report](https://github.com/stochasticai/xmagic-sdk/issues/new?template=bug_report.yml)
and include:

- **What happened vs. what you expected.**
- **Steps to reproduce** — the smallest CLI command or Python snippet that
  triggers it. A reproduction we can run is the single most useful thing you can
  provide.
- **Versions** — `xmagic --version`, `python --version`, and your OS.
- **Traceback or output**, with any API keys, tokens, agent IDs, or other
  secrets redacted.

If the problem involves a specific provider (`openai:`, `anthropic:`,
`google:`, `litellm:`), say which one and which model ref you used.

## Feature requests

Open a [feature request](https://github.com/stochasticai/xmagic-sdk/issues/new?template=feature_request.yml)
describing the problem you are trying to solve, not only the solution you have
in mind. Include what you tried with the current API and why it fell short.

We are especially interested in requests that fit the SDK's scope: xMagic API
coverage, CLI ergonomics, MCP scaffolding, skills packaging, and provider
adapters.

## Questions and usage help

For "how do I ...?" questions, check the [README](README.md), the
[design notes](DESIGN.md), and the docs at <https://docs.xmagic.ai> first. If
those don't cover it, open an issue — a question that needed asking usually
means a documentation gap worth fixing.

## Security vulnerabilities

**Do not open a public issue for a security vulnerability.**

Report it privately through GitHub's
[private vulnerability reporting](https://github.com/stochasticai/xmagic-sdk/security/advisories/new)
on the repository's Security tab. Include a description, reproduction steps, and
the impact you believe it has. We will acknowledge the report and keep you
updated on the fix and disclosure timeline.

## Contributing a fix

If you'd like to fix the issue yourself, say so in the issue and see
[CONTRIBUTING.md](CONTRIBUTING.md) for setup and the PR workflow.
