# Releasing xmagic-sdk

How a version gets from `main` to PyPI. The mechanics live in
`.github/workflows/release.yml`; this document is the checklist around it.

PyPI version numbers are permanent. A bad upload cannot be replaced, only
superseded (0.0.3 was burned on a one-line change, see PYPI_HISTORY.md), so
the tag, the package metadata, and the changelog are checked against each
other before anything is published.

## When to release

When there is a reason to. Unreleased work accumulating under `[Unreleased]`
in CHANGELOG.md is the normal state of `main`, not a prompt to ship.

## Preconditions

- On `main`, clean tree, latest CI run green.
- No AI attribution in any commit, PR body, or release note (CONTRIBUTING.md).

## 1. Pick the version

`pyproject.toml` is the source of truth; the release workflow compares it to
the git tag with `uv version --short`. The project is 0.x, so:

- Any entry under `### Changed` that alters behaviour for existing callers
  means a **minor** bump (0.4.0 to 0.5.0).
- Only additions and fixes means a **patch** bump.

## 2. Prepare on a branch `release/X.Y.Z`

Edit exactly these files:

1. `pyproject.toml`: `version = "X.Y.Z"`.
2. `CITATION.cff`: `version: "X.Y.Z"` and `date-released: "YYYY-MM-DD"`.
   Use today; step 5 corrects it if the tag lands on another day.
3. `CHANGELOG.md`:
   - Rename `## [Unreleased]` to `## [X.Y.Z] — YYYY-MM-DD` (em dash, matching
     the existing headings) and add a fresh empty `## [Unreleased]` above it.
   - Write a two or three paragraph intro under the new heading: what the
     release adds up to, what to read under Changed before upgrading, and the
     test count. This text becomes the GitHub Release notes verbatim.
   - Tidy duplicate `### Added` / `### Changed` headings that accumulated
     across PRs. Entry text stays as written; only headings and order move.
   - Update the link references at the bottom: `[Unreleased]` compares from
     `vX.Y.Z...HEAD`, and add `[X.Y.Z]: .../releases/tag/vX.Y.Z`.
   - Every older section stays byte-identical to its tag.

## 3. Verify locally

```bash
uv sync --all-extras            # refresh the editable install so the version test sees X.Y.Z
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest
rm -rf dist && uv build && uvx twine check dist/*
uv version --short && uv run xmagic version   # both print X.Y.Z
```

All of it must pass. Note the test count for the changelog intro.

## 4. Commit and merge

Commit as `chore(release): prepare X.Y.Z`. The body states the bump rationale
(which Changed entries made it minor), lists the PRs since the last tag, and
records what was verified. Open a pull request against `main` and merge it.

## 5. Tag and publish

On `main`, after the merge:

1. If the date drifted, commit `chore(release): date X.Y.Z to the tag day`
   touching CHANGELOG.md and CITATION.cff, and merge that too.
2. Tag the merge commit and push the tag:

   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

3. Put the CHANGELOG intro paragraphs in a notes file outside the repo and
   publish the release:

   ```bash
   gh release create vX.Y.Z --title vX.Y.Z --notes-file /path/to/notes.md
   ```

Publishing the release triggers `release.yml`, which re-checks tag against
version, runs the full suite, builds, rehearses on TestPyPI, and publishes to
PyPI through trusted publishing. Nothing is uploaded by hand.

## 6. Confirm and record

```bash
gh run list --workflow=release.yml --limit 1   # then: gh run watch <id>
curl -s https://pypi.org/pypi/xmagic-sdk/json | jq -r .info.version
```

When PyPI shows X.Y.Z, update PROGRESS.md and commit
`docs(progress): note that vX.Y.Z shipped` through a pull request.

## If the workflow fails after the tag exists

Fix on `main`, then run the workflow manually (`workflow_dispatch`) with the
version and no leading `v`; it checks out the existing tag. If the fix has to
be in the tagged content, that version is spent: move to the next patch number.
