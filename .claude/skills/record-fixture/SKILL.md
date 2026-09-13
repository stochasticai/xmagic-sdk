---
name: record-fixture
description: Record a live xMagic API response into tests/fixtures and wire a respx replay test, following tests/fixtures/README.md. Use when adding an endpoint to the client, when a response shape is suspected to have drifted, or when a test needs a real payload. Fixtures are recorded from the live API, never invented.
---

Read `tests/fixtures/README.md` and follow it. It covers credential
resolution, raw-httpx capture, naming, the `_comment` header, redaction
placeholders, and how the replay test is wired.

Notes for running it from a session:

- Live tests are selected with `-m live`, not `-k live`; the default
  `-m 'not live'` in pyproject.toml deselects them otherwise.
- The capture script goes in the scratchpad, never in the repo. Print the raw
  body and copy it into the fixture file by hand, redacting as you go.
- Never write a real API key, agent id, chat id, or file id anywhere under
  the repo, including in a commit message or a test name.
- Delete every server-side resource the capture created before finishing.
- Commit only the fixture and the test that replays it.
