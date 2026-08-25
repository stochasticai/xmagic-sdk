# Open-Source Readiness Plan

Plan for addressing initial feedback: common OSS doc files, PyPI publishing, examples,
and hosted docs.

**Scope note.** This plan covers open-source readiness only. Feature work lives in the
[DESIGN.md](DESIGN.md) roadmap and [TODO.md](TODO.md); its phase numbers are unrelated to
the ones here. Reconciled against the repository on 2026-08-06 — every claim below was
re-checked rather than carried forward.

## Phase 1 — Open-source doc files ✅ done

1. ✅ **LICENSE** — Apache-2.0 full text, "Copyright 2026 Stochastic".
2. ✅ **CONTRIBUTING.md** — dev setup (`uv sync --all-extras`), checks, project
   layout, Conventional Commits, PR workflow.
3. ✅ **ISSUES.md** + `.github/ISSUE_TEMPLATE/` (bug report, feature request,
   config with contact links) and `.github/PULL_REQUEST_TEMPLATE.md`.
4. ✅ **CODE_OF_CONDUCT.md** — Contributor Covenant v2.1, with
   support@xmagic.ai as the enforcement contact.
5. ✅ **CITATION.cff** — validates against schema 1.2.0 (`uvx cffconvert --validate`),
   and carries `date-released: "2026-08-03"`.

## Phase 2 — PyPI packaging & release ✅ done

6. ✅ `pyproject.toml`: PEP 639 (`license = "Apache-2.0"`,
   `license-files = ["LICENSE"]`, `hatchling>=1.27`) plus an explicit
   `[tool.hatch.build.targets.sdist]` include list. Verified with `uv build` —
   LICENSE lands in `dist-info/licenses/`, `twine check` passes.
7. ✅ **`.github/workflows/release.yml`** — PyPI trusted publishing (OIDC) on
   GitHub Release, with a tag-vs-version guard. **`.github/workflows/ci.yml`** —
   ruff check, ruff format, and pytest on **Python 3.11–3.14**, plus a
   build/twine-check job. The one-time setup — a PyPI trusted publisher for
   `stochasticai/xmagic-sdk` (`release.yml`, environment `pypi`) and a GitHub
   environment named `pypi` — is **done**, and the path is proven end to end:
   **0.1.0 published to PyPI 2026-08-03** from tag `v0.1.0`.
8. ✅ **README badges** — PyPI version, Python versions, license, CI status, all
   resolving against a real release. Contributing and License sections added.

## Phase 3 — Examples & docs (the only phase left)

9. ✅ **`examples/`** — six runnable scripts, and the directory is complete:
   - ✅ basic chat (`01_basic_chat.py`)
   - ✅ streaming (`02_streaming.py`)
   - ✅ file / Drive upload (`03_files_and_drive.py`)
   - ✅ MCP server scaffold walkthrough (`04_mcp_server.py`) — needs no API key,
     so it doubles as the zero-credential entry point
   - ✅ skills packaging walkthrough (`05_skills.py`) — also needs no API key
   - ✅ **non-xMagic model** (`06_provider_model.py`) — written 2026-08-23, once
     `LiteLLMProvider` landed. Takes any `provider:model` ref over the same
     `Provider` interface as `xmagic:<agent_id>`, and needs no xMagic key

   The API examples exit cleanly with a pointed message when the key or agent id
   is missing, rather than surfacing a traceback.
10. ⬜ **Docs for docs.xmagic.ai** — draft SDK/CLI reference + quickstart pages.
    The site is live and runs **Docusaurus v3.8.1** (served from S3), so pages
    are Markdown/MDX with frontmatter plus a sidebar entry. Blocked on the open
    question below.

## Open questions

- **Where does the docs.xmagic.ai Docusaurus source live?** It is not in this
  repo, so the SDK reference pages either go to that separate repo or ship from
  here with a publish step. Decide before writing item 10.

## Notes

- ✅ Formatting is enforced: a one-time `ruff format .` normalized 7 files, and CI
  gates on `ruff format --check .` alongside `ruff check .`.
- **`uv.lock` stays gitignored** (decided 2026-07-28, still true — the file is
  untracked). Standard for a library: consumers resolve their own dependencies,
  and CI resolving fresh means we find out early when an upstream release breaks
  us. Trade-off accepted: a green build can go red with no code change on our side.

  Sharper than it first looked. A developer's local lock still exists and ages
  silently. A stale one pinning litellm 1.92.0 made Python 3.14 look broken
  locally and held local ruff at 0.15 while CI moved to 0.16 — which is what let
  CI stay red unnoticed. If a dev environment disagrees with CI, run
  `uv lock --upgrade` first.

  **This cuts both ways, and the other edge drew blood.** Resolving fresh also
  means published artifacts decay: an unbounded `mcp>=1.0` in the MCP template
  was correct at 0.1.0 and broke when mcp 2.0 relocated `FastMCP`, leaving
  `xmagic mcp init` generating projects that could not start (PR #11). No lock
  file would have prevented that — the template ships to users who resolve their
  own dependencies. **Upper bounds on anything whose API we import are the
  actual mitigation**, and the ruff and mcp incidents are the same lesson twice.

## Not covered here

Release *hygiene* — `release.yml` running no tests before publishing, and the
version being declared independently in `pyproject.toml` and
`src/xmagic/__init__.py` with nothing enforcing agreement — is tracked in
[TODO.md](TODO.md) under Phase 6, not in this plan. Neither affected the 0.1.0
release: CI ran on the tagged commit `b81bd32` and passed before the release
workflow ran. The gap is that nothing *requires* it to.
