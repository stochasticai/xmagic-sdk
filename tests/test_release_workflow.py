"""Regression tests for guarded PyPI release workflow configuration.

These locate steps **by name**. The previous version sliced the file on the name
of the *following* step, so inserting or reordering anything raised `IndexError`
rather than failing an assertion -- a test that breaks confusingly the moment the
workflow it guards is edited.
"""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"

STEP_PREFIX = "      - "


def _release_workflow_text() -> str:
    """Read the release workflow exactly as GitHub receives it."""
    return RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8")


def _steps() -> list[str]:
    """Split the workflow into step blocks, in file order."""
    chunks = _release_workflow_text().split(f"\n{STEP_PREFIX}")
    return [STEP_PREFIX + chunk for chunk in chunks[1:]]


def _step(name: str) -> str:
    """One step's text, located by its own name rather than by its neighbours."""
    for step in _steps():
        if step.startswith(f"{STEP_PREFIX}name: {name}"):
            return step
    raise AssertionError(f"release.yml has no step named {name!r}")


def _step_index(name: str) -> int:
    for index, step in enumerate(_steps()):
        if step.startswith(f"{STEP_PREFIX}name: {name}"):
            return index
    raise AssertionError(f"release.yml has no step named {name!r}")


def test_manual_release_requires_version_and_checks_out_matching_tag() -> None:
    """Manual publishing must target an explicit, existing version tag."""
    workflow_text = _release_workflow_text()
    manual_dispatch = workflow_text.split("  workflow_dispatch:", 1)[1].split(
        "\n\npermissions:", 1
    )[0]
    manual_checkout = _step("Check out manually requested release tag")

    assert "version:" in manual_dispatch
    assert "required: true" in manual_dispatch
    assert "type: string" in manual_dispatch
    assert "if: github.event_name == 'workflow_dispatch'" in manual_checkout
    assert "ref: v${{ inputs.version }}" in manual_checkout
    assert "fetch-depth: 0" in manual_checkout


def test_release_version_guard_applies_to_automatic_and_manual_runs() -> None:
    """Both trigger paths must verify the tag, commit, and package version."""
    verification_step = _step("Verify release tag and package version")

    # A step-level release-only condition was the original manual-publish gap.
    assert "\n        if:" not in verification_step
    assert "inputs.version || github.ref_name" in verification_step
    assert 'git rev-parse --verify --quiet "refs/tags/${expected_tag}"' in verification_step
    assert 'git rev-list -n 1 "${expected_tag}"' in verification_step
    assert 'if [ "${tag_commit}" != "${head_commit}" ]' in verification_step
    assert 'if [ "${project_version}" != "${release_version}" ]' in verification_step


def test_release_runs_the_test_suite_before_building() -> None:
    """A tag must not be able to publish a red commit.

    CI passing on the tagged commit has only ever been incidental -- it happened
    to hold for v0.1.0, but nothing in this workflow consulted it. These steps
    make it a precondition.
    """
    lint = _step("Lint and format")
    tests = _step("Test")

    assert "uv run ruff check ." in lint
    assert "uv run ruff format --check ." in lint
    assert "uv run pytest" in tests
    # Order is the whole point: gating after the build would still publish.
    assert _step_index("Test") < _step_index("Build sdist and wheel")


def test_testpypi_rehearsal_uses_the_same_artifact_and_never_blocks() -> None:
    """The rehearsal must publish the bytes that PyPI will get.

    The one historical rehearsal (0.0.2, Nov 2025) built its own sdist -- 28,934
    bytes against PyPI's 28,947 -- so it never rehearsed what shipped. And it must
    not fail the release when no TestPyPI publisher is configured.
    """
    rehearsal = _step("Publish to TestPyPI (rehearsal)")

    assert "repository-url: https://test.pypi.org/legacy/" in rehearsal
    assert "continue-on-error: true" in rehearsal
    # Downloaded, not rebuilt: same bytes as the PyPI upload.
    assert _step_index("Publish to TestPyPI (rehearsal)") > _step_index("Download built dist")
