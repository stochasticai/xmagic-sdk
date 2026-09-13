---
name: release
description: Cut an xmagic-sdk release by following RELEASING.md end to end - version bump, CHANGELOG close-out, CITATION date, local verification, tag, GitHub Release (which publishes to PyPI), and the post-ship PROGRESS note. Use only when the user explicitly asks to release or ship a version. Never propose a release unprompted; unreleased work accumulating on main is the normal state.
---

Read `RELEASING.md` and follow it step by step. It is the single procedure for
humans and agents; do not improvise around it.

Notes for running it from a session:

- Confirm the user actually asked for a release before touching anything. A
  full `[Unreleased]` section is not a request.
- The release-notes file for `gh release create --notes-file` goes in the
  scratchpad, never in the repo.
- Pushing `main` is blocked by the project hook; open pull requests for the
  prepare commit and the PROGRESS note. Pushing the `vX.Y.Z` tag is allowed.
- No AI attribution anywhere: commits, PR body, release notes.
- Report each verification result as it happens (test count, `twine check`,
  workflow run id, PyPI version), not as a summary at the end.
