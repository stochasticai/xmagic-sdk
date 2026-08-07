# PyPI: `xmagic-sdk` and `xmagic`

Findings from an audit of this project's PyPI presence on 2026-08-05. Everything
below is from the PyPI JSON/simple APIs and from unpacking the published
artifacts — no inference from repository history except where marked.

Short version: the `xmagic-sdk` name carries **two unrelated packages** under one
distribution, one version number was burned on a one-line change, and the
`xmagic` name is registered but empty.

---

## 1. Release history

| Version | Uploaded (UTC) | Wheel | What it actually is |
|---|---|---|---|
| 0.0.1 | 2025-11-10 18:48 | 1,225 B | Placeholder — no code |
| 0.0.2 | 2025-11-11 10:26 | 35,937 B | First real upload |
| 0.0.3 | 2025-11-11 11:10 | 35,935 B | 0.0.2 + a one-line log change |
| 0.1.0 | 2026-08-03 19:23 | 40,249 B | Different package entirely (this repo) |

Nothing is yanked. Authors on the 0.0.x line: Marcos Rivera Martínez, Glenn Ko,
Subhash G N, Jatin Sarda.

### 0.0.1 was a name reservation, not a release

The sdist contains one module, `xmagic_sdk/__init__.py`, whose entire content is:

```python
version = "0.0.1"
```

### 0.0.3 was a burned version number

0.0.2 and 0.0.3 shipped **44 minutes apart**. The complete content diff between
the two sdists, excluding version strings in `setup.py` and `PKG-INFO`:

```diff
--- xmagic_sdk-0.0.2/src/xmagic_sdk/mcp/deploy_mcp.py
+++ xmagic_sdk-0.0.3/src/xmagic_sdk/mcp/deploy_mcp.py
@@ -1138,7 +1138,7 @@
              except Exception as e:
-                logger.warning(f"Could not delete custom tool configuration: {e}")
+                logger.debug("No custom tool configuration found for this deployment.")
```

That is the whole release. PyPI does not permit re-uploading a filename, so
fixing a log level after publishing costs a version number. This is the pattern
worth guarding against — see §5.

### TestPyPI was used once, and not as a true rehearsal

TestPyPI holds only `0.0.2`, uploaded 2025-11-10 22:46 — about 12 hours *before*
PyPI's 0.0.2. The sdists differ in size (28,934 B on TestPyPI vs 28,947 B on
PyPI), so the artifact that was rehearsed is not the artifact that shipped.

---

## 2. The real problem: one distribution, two packages

`pip install xmagic-sdk` installs a different top-level module depending on which
version resolves.

| | 0.0.1 – 0.0.3 | 0.1.0 |
|---|---|---|
| Import name | `xmagic_sdk` | `xmagic` |
| Console script | `xmagic_sdk.cli:xmagic` (click) | `xmagic.cli.main:app` (typer) |
| Build backend | setuptools / `setup.py` | hatchling |
| Public API | `registry`, `run_mcp_server`, `fetch_info_from_kb_v1`, `fetch_info_from_kb_v3` | `XMagicClient`, `AsyncXMagicClient`, `Settings`, error types |

Because the distribution name is unchanged, `pip install -U xmagic-sdk` uninstalls
the old files and installs the new ones. `import xmagic_sdk` then fails.

**Modules that disappeared in 0.1.0**, with no equivalent in the current codebase:

```
xmagic_sdk/agents/agents.py
xmagic_sdk/chatting/chatting.py
xmagic_sdk/mcp/deploy_mcp.py         (~1,100 lines — hosted deploy flow)
xmagic_sdk/mcp/artifacts.py
xmagic_sdk/mcp/download_files.py
xmagic_sdk/mcp/fetch_info_from_kb.py
xmagic_sdk/mcp/mcp_api.py
xmagic_sdk/mcp/registry.py
```

**CLI surface that disappeared.** The `xmagic` command still exists after upgrade,
which makes the break quieter rather than louder:

- 0.0.3: `configure`, `chat`, `mcp run|list|delete|logs|stop|start|validate`
- 0.1.0: `configure`, `chat`, `mcp init|dev`, `skills`, `tools`, `drive`, `serve`, `version`

`xmagic mcp list`, `logs`, `start`, `stop`, `delete`, `run` and `validate` are all
gone. `configure` and `chat` survive by name with different flags.

`CHANGELOG.md` describes the 0.0.x line as predating this repository's history,
which is true as provenance but reads as bookkeeping. It is a hard fork of both
the import path and the feature set under a shared name.

### How much this matters

Download figures via pypistats, 2026-02-05 to 2026-08-04 (130 days):

- **275** downloads excluding mirrors (1,110 including mirrors)
- **125** excluding mirrors in the last 30 days

0.1.0 landed 2026-08-03, so essentially all of that is 0.0.3 — roughly two
non-mirror downloads a day, much of which is likely CI rather than people. Small,
but not zero, and the failure it produces is a bare `ModuleNotFoundError`.

---

## 3. The `xmagic` name on PyPI — taken, by someone else

**Registered, active, empty, and not ours.**

```
https://pypi.org/simple/xmagic/      -> 200, zero files, project-status: active
https://pypi.org/pypi/xmagic/json    -> 404 (no releases, so no "latest")
https://test.pypi.org/simple/xmagic/ -> 404 (not registered there)
```

The HTML project page is behind a JS challenge, and the JSON API returns nothing
for a release-less project, so ownership is not visible the obvious ways. PyPI's
XML-RPC API still answers it:

```bash
curl -s -X POST https://pypi.org/pypi -H 'Content-Type: text/xml' --data '
<?xml version="1.0"?>
<methodCall><methodName>package_roles</methodName>
<params><param><value><string>xmagic</string></value></param></params>
</methodCall>'
```

| Distribution | Owner account |
|---|---|
| `xmagic` | **`XOne_Team`** |
| `xmagic-sdk` | **`internal_apis`** |

`user_packages` shows `XOne_Team` also holds **`XMagics`** and **`XOne-Magic`**,
both published August 2022 by *Amr Elmenyawy* (`xone.conect@gmail.com`,
`XOne_support@gmail.com`), summary "XOne_Team library". `XMagics` 1.0.4 installs a
top-level `XMagics` package containing `Xsms.py` — an SMS helper. Unrelated to
Stochastic, and it **predates xMagic**, so `xmagic` is not a squat aimed at this
project; it's one of three variant names that account registered around its own
library four years ago and then abandoned.

What follows from that:

- **The distribution can never simply be renamed to `xmagic`.** That option is
  closed without a [PEP 541](https://peps.python.org/pep-0541/) name-transfer
  request. The case would rest on the name being registered-but-unused since
  2022; it's a plausible request but not a strong one, since the owner registered
  it deliberately as part of a cluster. Not worth pursuing unless the naming
  mismatch starts costing something real.
- **Collision risk today is low.** Their published packages install `XMagics`,
  not `xmagic`, so nothing currently shadows our import name. The residual risk
  is a dormant account publishing a top-level `xmagic` module later.
- **The `xmagic-sdk` / `xmagic` distribution-vs-import mismatch is permanent.**
  Worth stating plainly in the README rather than leaving users to infer it.

Related names `xmagic-cli` and `xmagicai` are unregistered.

### A governance note on `internal_apis`

`xmagic-sdk` has exactly one role holder — an account named `internal_apis`, which
owns no other packages. Trusted publishing means routine releases don't depend on
that account's credentials, but **ownership rights do**: yanking, deleting,
adding maintainers, and configuring the trusted publisher all sit with it alone.
Worth adding a second owner, and worth knowing whose account it actually is.

---

## 4. What was done about it

A compatibility shim now ships in the wheel (`src/xmagic_sdk/__init__.py`).
Importing it raises `ImportError` with the replacement name, the version
boundary, the specific APIs that no longer exist, and `pip install
'xmagic-sdk==0.0.3'` as the escape hatch. Pinned by `tests/test_legacy_shim.py`
and documented under Compatibility in `CHANGELOG.md`. Scheduled for removal in
1.0.

A re-export shim was not an option: nothing in the 0.0.x API has a counterpart in
the current SDK, so there is nothing to forward to. The choice was between a
pointed error and silence.

---

## 5. Guards worth adding before the next release

None of these are in `TODO.md` today.

1. **`release.yml` never runs tests or lint.** It goes from checkout straight to
   `uv build` + `twine check`, so a green tag can publish a red commit. This is
   the most likely way to burn another version number.
2. **Two version sources, no guard.** `pyproject.toml` and
   `src/xmagic/__init__.py:23` each declare `0.1.0` independently; the release
   workflow only checks the tag against `uv version --short`. Derive
   `__version__` from `importlib.metadata.version("xmagic-sdk")` and delete the
   literal, or assert they match in a test.
3. **Publish to TestPyPI from the same artifact** that will go to PyPI, rather
   than a separately-built one, so the rehearsal is actually a rehearsal.
4. **Add a second owner to `xmagic-sdk`.** One account, `internal_apis`, holds
   every ownership right over the published package (see §3).
5. **Say in the README that the install name and the import name differ** —
   `pip install xmagic-sdk`, `import xmagic` — since `xmagic` belongs to an
   unrelated account and the mismatch is now permanent.
