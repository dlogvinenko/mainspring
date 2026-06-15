# SPDX-License-Identifier: Apache-2.0
"""Tests for changelog source hygiene."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
PRD = REPO_ROOT / "docs" / "prd.md"


# Scenario: The release checklist says the GitHub release description comes from
# CHANGELOG.md.
# Expected: A changelog source exists, names the requirements-first release frame, and
# keeps maintainer publication work visible instead of implying every gate is closed.
def test_changelog_is_honest_about_maintainer_work() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")

    assert text.startswith("# Changelog")
    assert "## v1.0.0 - Public Source Release" in text
    assert "## Unreleased" not in text
    assert (
        "Product Requirements Document (PRD)-first AI coding agent orchestration"
        in text
    )
    assert "production-grade software delivery" in text
    assert "unstructured vibe coding" in text
    assert "### Publication Checklist" in text
    assert "repository visibility to public" in text
    assert "workflow files" in text
    assert "public-source " + "blocker" not in text
    assert "GitHub repository metadata now uses" in text
    assert "signed `v1.0.0` tag" in text
    assert "publish package-manager distribution" in text
    assert "Visibility is the only public-source " + "blocker" not in text
    assert "specialized release-" + "proof commands" not in text
    assert "old monolith " + "audit" not in text
    assert "internal audit scaffolding" not in text
    assert "Set the GitHub repository description" not in text
    stale_migration_window = "migration " + "window"
    assert stale_migration_window not in text


# Scenario: The canonical PRD remains the gate, not the changelog.
# Expected: GitHub release copy can be published from CHANGELOG.md after the
# final tag is signed.
def test_prd_changelog_gate_is_a_maintainer_release_step() -> None:
    text = PRD.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert (
        "- [ ] Signed annotated `v1.0.0` tag exists on the final clean release commit"
        in text
    )
    assert "- [x] GitHub release notes pulled from `CHANGELOG.md`" in text
    assert "import or unlock the maintainer GPG key" in text
    assert "GitHub repository page shows public Apache-2.0 status" in text
    assert "GitHub credential that has `workflow` scope" in normalized
    assert "do not block the source-install repository" in normalized
    assert "sanitized release ref" not in normalized
    assert "`git tag v1.0.0`" not in text
    assert "gh repo view" not in text
