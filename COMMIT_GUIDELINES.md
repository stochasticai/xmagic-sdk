# Commit Guidelines

This project follows [Conventional Commits v1.0.0](https://www.conventionalcommits.org/en/v1.0.0/).

## Format

```
<type>(<scope>)!: <description>

[optional body]

[optional footer(s)]
```

- **type** — required, see list below.
- **scope** — optional, a noun describing the area of the codebase (see suggested scopes).
- **!** — append after type/scope to flag a breaking change.
- **description** — required. Imperative mood ("add", not "added"/"adds"), lowercase, no trailing period, ≤ 72 characters for the whole subject line.
- **body** — optional. Explain *what* and *why*, not *how*. Wrap at 72 characters.
- **footers** — optional. `BREAKING CHANGE: <details>`, `Refs: #123`, `Co-authored-by: ...`, etc.

## Types

| Type       | Use for                                                            |
| ---------- | ------------------------------------------------------------------ |
| `feat`     | A new feature (correlates with a MINOR version bump)               |
| `fix`      | A bug fix (correlates with a PATCH version bump)                   |
| `docs`     | Documentation-only changes                                         |
| `test`     | Adding or correcting tests                                         |
| `refactor` | Code change that neither fixes a bug nor adds a feature            |
| `perf`     | Performance improvement                                            |
| `style`    | Formatting, whitespace, etc. (no code behavior change)             |
| `build`    | Build system or dependency changes (`pyproject.toml`, `uv.lock`)   |
| `ci`       | CI configuration and scripts                                       |
| `chore`    | Maintenance tasks that don't touch src or tests                    |
| `revert`   | Reverting a previous commit                                        |

## Suggested scopes

`client`, `chat`, `mcp`, `skills`, `drive`, `providers`, `cli`, `serve`, `deps`

## Breaking changes

Mark with `!` and/or a `BREAKING CHANGE:` footer:

```
feat(client)!: drop support for legacy v1 chat endpoints

BREAKING CHANGE: XMagicClient.chats.create no longer accepts `model_id`;
pass a `provider:model` ref instead.
```

## Examples

```
feat(mcp): add dockerfile generation to `xmagic mcp init`
fix(chat): handle SSE reconnect on stream timeout
docs: expand quickstart with skills packaging example
test(providers): cover litellm fallback routing
build(deps): bump httpx to 0.28
chore: initial commit
```

## Rules of thumb

1. One logical change per commit; keep commits small and self-contained.
2. The subject line should complete the sentence: "If applied, this commit will _\<subject\>_."
3. Reference issues in footers (`Refs: #42`, `Fixes: #42`), not in the subject.
4. Never commit secrets; `.env` files are gitignored on purpose.
