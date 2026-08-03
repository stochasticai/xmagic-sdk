"""Regression tests for guarded PyPI release workflow configuration."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"


def _release_workflow_text() -> str:
    """Read the release workflow exactly as GitHub receives it."""
    return RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8")


def test_manual_release_requires_version_and_checks_out_matching_tag() -> None:
    """Manual publishing must target an explicit, existing version tag."""
    workflow_text = _release_workflow_text()
    manual_dispatch = workflow_text.split("  workflow_dispatch:", 1)[1].split(
        "\n\npermissions:", 1
    )[0]
    manual_checkout = workflow_text.split(
        "      - name: Check out manually requested release tag", 1
    )[1].split("\n\n      - name: Install uv", 1)[0]

    assert "version:" in manual_dispatch
    assert "required: true" in manual_dispatch
    assert "type: string" in manual_dispatch
    assert "if: github.event_name == 'workflow_dispatch'" in manual_checkout
    assert "ref: v${{ inputs.version }}" in manual_checkout
    assert "fetch-depth: 0" in manual_checkout


def test_release_version_guard_applies_to_automatic_and_manual_runs() -> None:
    """Both trigger paths must verify the tag, commit, and package version."""
    workflow_text = _release_workflow_text()
    verification_step = workflow_text.split(
        "      - name: Verify release tag and package version", 1
    )[1].split("\n\n      - name: Build sdist and wheel", 1)[0]

    # A step-level release-only condition was the original manual-publish gap.
    assert "\n        if:" not in verification_step
    assert "inputs.version || github.ref_name" in verification_step
    assert 'git rev-parse --verify --quiet "refs/tags/${expected_tag}"' in verification_step
    assert 'git rev-list -n 1 "${expected_tag}"' in verification_step
    assert 'if [ "${tag_commit}" != "${head_commit}" ]' in verification_step
    assert 'if [ "${project_version}" != "${release_version}" ]' in verification_step
