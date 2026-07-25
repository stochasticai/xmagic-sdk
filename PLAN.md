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
   ⚠️ Requires one-time setup: a PyPI trusted publisher for `stochasticai/xmagic-sdk`
   (`release.yml`, environment `pypi`) and a GitHub environment named `pypi`.
8. ✅ **README badges** — PyPI version, Python versions, license, CI status
   (PyPI badges render as "unknown" until the first publish). Also added
   Contributing and License sections.

## Phase 3 — Examples & docs (not started)

9. **`examples/`** — small runnable scripts:
   - basic chat
   - streaming
   - multi-provider (`provider:model`)
   - file / Drive upload
   - MCP server scaffold walkthrough
10. **Docs for docs.xmagic.ai** — draft SDK/CLI reference + quickstart pages.
    Blocked on the open question below.

## Open questions

- What platform powers docs.xmagic.ai (determines docs source format)?
- `uv.lock` is currently gitignored, so CI resolves dependencies fresh on every
  run. Fine for a library; commit the lock if reproducible CI is preferred.

## Notes

- `ruff format` currently reports 7 unformatted files, so CI gates on
  `ruff check` only. Worth a one-time `ruff format .` commit if we want to
  enforce formatting.
