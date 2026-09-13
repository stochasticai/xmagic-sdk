# Recorded API fixtures

Every file here was captured from the live xMagic API and replayed by
`tests/test_client_contracts.py` through respx. A hand-written fixture proves
nothing about the backend, so none are invented; a shape that has not been
recorded is a shape the suite does not pin.

## Running the live tests

Live tests are marked `live` and excluded by default (`-m 'not live'` in
pyproject.toml), so select them by marker, not by name:

```bash
XMAGIC_LIVE_TESTS=1 uv run pytest tests/test_client_contracts.py -m live
```

Credentials resolve with the SDK's own precedence: `XMAGIC_API_KEY` from the
environment, then the repo `.env`, then `~/.config/xmagic/config.toml` written
by `xmagic configure`. Chat calls also need `XMAGIC_TEST_AGENT_ID` (environment
or `.env`; falls back to the config file's `default_agent_id`).

## Recording a new fixture

1. **Capture with raw httpx, not the SDK.** The point is the wire shape, so
   bypass the client's parsing. Write a throwaway script outside the repo that
   builds the request the same way `src/xmagic/client/` does and prints the raw
   body.
   - JSON endpoints: `httpx.Client(...).request(...)`, save `response.text`.
   - Streaming endpoints: `with client.stream(...) as r: for line in
     r.iter_lines()` so the exact SSE framing is visible. Do not go through
     `httpx_sse`; it hides whether an `event:` field is sent (it is not, and
     that finding is what `stream_sse_frames.txt` documents).
   - Use disposable server-side resources (a folder named `xmagic-sdk-live-*`,
     a chat titled `sdk live contract test`) and delete them afterwards, as
     the live tests do.

2. **Name the file** `<resource>_<operation>_response.json`, or `.txt` for
   SSE.

3. **Annotate.** JSON fixtures start with a `_comment` key:

   ```json
   {
     "_comment": "Recorded live from GET /knowledge-bases?parent_kb_id={kb_id} on YYYY-MM-DD. Account-identifying ids redacted.",
     "data": {}
   }
   ```

   SSE fixtures are annotated text: a header stating the endpoint, date, and
   how it was captured, a "Key findings" list, then the raw `data:` frames
   separated by blank lines. The loader keeps only lines starting with
   `data: `, so prose above them is safe.

4. **Redact** every account-identifying id with a stable placeholder, the same
   one everywhere it appears in the fixture and in the test:
   `REDACTED_CHAT_ID`, `REDACTED_MESSAGE_ID`, `REDACTED_UPLOADED_FILE_ID`,
   `REDACTED_KB_ID`, `REDACTED_DATA_SOURCE_ID`. Keep everything else
   (timestamps, nulls, nested `_class_id` fields) exactly as received;
   unexpected keys are part of what the fixture pins.

5. **Wire the replay test** in `tests/test_client_contracts.py`:
   - Load with `_load_json_fixture` or `_sse_frames_from_fixture`.
   - Mock the route with respx and capture the outgoing request.
   - Assert the request shape the SDK sends: method, path, query params, JSON
     body or multipart fields.
   - Call the client method and assert the parsed model fields match the
     placeholders.
   - For a new endpoint, also add a `@pytest.mark.live` test under the same
     `XMAGIC_LIVE_TESTS` skip, creating and cleaning up its own resources.
   - Update the recording date in the module docstring if the set was
     re-recorded.

6. **Verify and commit.**

   ```bash
   uv run pytest tests/test_client_contracts.py -q
   uv run ruff format . && uv run ruff check . && uv run mypy
   git diff --stat   # fixture and test only; no keys, no real ids
   ```

   Commit as `test(client): record <endpoint> fixture`, or `fix(client): ...`
   if the recording revealed a mismatch the client had to change for.
