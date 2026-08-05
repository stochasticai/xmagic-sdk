# Open-Source Readiness Plan

Plan for addressing initial feedback: common OSS doc files, PyPI publishing, examples,
and hosted docs.

## Phase 1 — Open-source doc files ✅ done

1. ✅ **LICENSE** — Apache-2.0 full text, "Copyright 2026 Stochastic".
2. ✅ **CONTRIBUTING.md** — dev setup (`uv sync --all-extras`), checks, project
   layout, Conventional Commits, PR workflow.
3. ✅ **ISSUES.md** + `.github/ISSUE_TEMPLATE/` (bug report, feature request,
   config with contact links) and `.github/PULL_REQUEST_TEMPLATE.md`.
4. ✅ **CODE_OF_CONDUCT.md** — Contributor Covenant v2.1, with
   support@xmagic.ai as the enforcement contact.
5. ✅ **CITATION.cff** — validates against schema 1.2.0 (`uvx cffconvert --validate`).
   Add `date-released` when 0.1.0 is actually published.

## Phase 2 — PyPI packaging & release ✅ done

6. ✅ `pyproject.toml`: moved to PEP 639 (`license = "Apache-2.0"`,
   `license-files = ["LICENSE"]`, `hatchling>=1.27`) and added an explicit
   `[tool.hatch.build.targets.sdist]` include list. Verified with `uv build` —
   LICENSE lands in `dist-info/licenses/`, `twine check` passes.
7. ✅ **`.github/workflows/release.yml`** — PyPI trusted publishing (OIDC) on
   GitHub Release, with a tag-vs-version guard. **`.github/workflows/ci.yml`** —
   ruff + pytest on Python 3.11/3.12/3.13, plus a build/twine-check job.
   The one-time setup this needed — a PyPI trusted publisher for
   `stochasticai/xmagic-sdk` (`release.yml`, environment `pypi`) and a GitHub
   environment named `pypi` — is **done**, and the path is proven end to end:
   **0.1.0 published to PyPI 2026-08-03** from tag `v0.1.0`.
8. ✅ **README badges** — PyPI version, Python versions, license, CI status.
   The PyPI badges now resolve against a real release. Also added Contributing
   and License sections.

## Phase 3 — Examples & docs (not started — now the only phase left)

9. **`examples/`** — small runnable scripts:
   - basic chat
   - streaming
   - multi-provider (`provider:model`) — needs Phase 3 of the DESIGN.md roadmap
     first; the adapters are stubs today
   - file / Drive upload
   - MCP server scaffold walkthrough
10. **Docs for docs.xmagic.ai** — draft SDK/CLI reference + quickstart pages.
    The site is live and runs **Docusaurus v3.8.1** (served from S3), so pages
    are Markdown/MDX with frontmatter plus a sidebar entry. Still blocked on
    where the source lives — see below.

## Open questions

- Where does the docs.xmagic.ai Docusaurus source live? It is not in this repo,
  so the SDK reference pages either go to that separate repo or ship from here
  with a publish step. Decide before writing Phase 3 pages.

## Notes

- ✅ Formatting is enforced: a one-time `ruff format .` normalized 7 files and
  CI now gates on `ruff format --check .` alongside `ruff check .`.
- **`uv.lock` stays gitignored** (decided 2026-07-28). Standard for a library:
  consumers resolve their own dependencies, and CI resolving fresh means we
  find out early when an upstream release breaks us. Trade-off accepted — a
  green build can go red with no code change on our side.

  Sharper than it first looked, though: a developer's local lock still exists
  and ages silently. A stale one pinning litellm 1.92.0 made Python 3.14 look
  broken locally and held local ruff at 0.15 while CI moved to 0.16 — which is
  what let CI stay red unnoticed. If a dev environment disagrees with CI, run
  `uv lock --upgrade` first.
