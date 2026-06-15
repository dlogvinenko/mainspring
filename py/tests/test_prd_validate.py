# SPDX-License-Identifier: Apache-2.0
"""Tests for prd_validate.py — Method-shaped PRD validator."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import prd_validate  # noqa: E402

SCRIPT = str(HERE.parent / "prd_validate.py")
REPO_ROOT = HERE.parents[1]


def _valid_prd() -> str:
    return """# Example — Product Requirements Document (PRD)

## Contents

1. [Mission](#mission)

## Mission

Do the work.

## Durability principles

1. **Truth first.** Verify before claiming completion.

## Current truth snapshot (verified)

| Metric | Value | Source |
| --- | --- | --- |
| Main LOC | 10 | `wc -l scripts/main.sh` |

## Naming and brand boundary

Names are explicit.

## Target architecture

Architecture goes here.

## Phase map

Phase map goes here.

## Architecture decisions (ADRs)

### ADR-01: Pick a license

**Context:** A decision is needed.

**Options considered:** MIT; Apache-2.0.

**Decision:** Apache-2.0.

**Rationale:** Patent grant.

**Consequences:** SPDX headers.

**Reversal cost:** high.

## Operational doctrine

Use the tool carefully.

## Health rituals

Run checks weekly.

## Disaster recovery

Recover with documented commands.

## Versioning and migration

SemVer.

## Definition of Done (release checklist)

- [ ] Tests pass.

## Explicit non-goals

- Not a SaaS.

## Backlog (Must / Should / Could / Won't)

### Must (blocks this release or scope)

1. Build it.

### Should (v1.x post-release)

1. Polish it.

### Could (v2 candidates, only if data justifies)

1. Maybe later.

### Won't (explicit non-goals — do not propose)

- SaaS hosting.

## Appendix A — Source-of-knowledge recipes

Recipes.

## Appendix B — Verification commands

Commands.

## Acknowledgments / Lineage

Lineage.
"""


# Scenario: a complete Method-shaped PRD.
# Expected: no validation issues.
def test_valid_prd_passes() -> None:
    assert prd_validate.validate_text(_valid_prd()) == []


# Scenario: required sections are absent.
# Expected: validation reports a missing section.
def test_missing_section_fails() -> None:
    text = _valid_prd().replace("## Mission\n\nDo the work.\n\n", "")
    issues = prd_validate.validate_text(text)
    assert any(issue.code == "section:missing" for issue in issues)
    assert any("Mission" in issue.message for issue in issues)


# Scenario: a template placeholder remains.
# Expected: validation reports the line with unresolved placeholder text.
def test_unresolved_placeholder_fails() -> None:
    issues = prd_validate.validate_text(_valid_prd() + "\n{{replace me}}\n")
    assert any(issue.code == "placeholder:unresolved" for issue in issues)
    assert any(issue.line for issue in issues)


# Scenario: the truth table has an empty Source cell.
# Expected: validation rejects the PRD.
def test_empty_truth_source_fails() -> None:
    text = _valid_prd().replace(
        "| Main LOC | 10 | `wc -l scripts/main.sh` |",
        "| Main LOC | 10 |  |",
    )
    issues = prd_validate.validate_text(text)
    assert any(issue.code == "truth:source_missing" for issue in issues)


def test_truth_snapshot_requires_source_table_and_data_rows() -> None:
    no_source_table = _valid_prd().replace(
        "| Metric | Value | Source |\n| --- | --- | --- |\n| Main LOC | 10 | `wc -l scripts/main.sh` |",
        "| Metric | Value |\n| --- | --- |\n| Main LOC | 10 |",
    )
    no_rows = _valid_prd().replace(
        "| Main LOC | 10 | `wc -l scripts/main.sh` |",
        "",
    )

    assert any(
        issue.code == "truth:source_table_missing"
        for issue in prd_validate.validate_text(no_source_table)
    )
    assert any(
        issue.code == "truth:no_rows" for issue in prd_validate.validate_text(no_rows)
    )


# Scenario: an ADR omits required decision-record fields.
# Expected: validation names the missing field.
def test_adr_missing_required_field_fails() -> None:
    text = _valid_prd().replace("**Options considered:** MIT; Apache-2.0.\n\n", "")
    issues = prd_validate.validate_text(text)
    assert any(issue.code == "adr:missing_fields" for issue in issues)
    assert any("Options considered" in issue.message for issue in issues)


def test_missing_or_empty_adr_section_fails() -> None:
    missing = _valid_prd().replace(
        """## Architecture decisions (ADRs)

### ADR-01: Pick a license

**Context:** A decision is needed.

**Options considered:** MIT; Apache-2.0.

**Decision:** Apache-2.0.

**Rationale:** Patent grant.

**Consequences:** SPDX headers.

**Reversal cost:** high.

""",
        "",
    )
    empty = _valid_prd().replace("### ADR-01: Pick a license", "Decision notes only")

    assert any(
        issue.code == "adr:missing" for issue in prd_validate.validate_text(missing)
    )
    assert any(issue.code == "adr:none" for issue in prd_validate.validate_text(empty))


# Scenario: the Backlog omits the Won't lane.
# Expected: validation reports the missing explicit non-goal backlog lane.
def test_backlog_without_wont_lane_fails() -> None:
    text = _valid_prd().replace(
        "### Won't (explicit non-goals — do not propose)\n\n- SaaS hosting.\n",
        "",
    )
    issues = prd_validate.validate_text(text)
    assert any(issue.code == "backlog:wont_missing" for issue in issues)


# Scenario: Mainspring's canonical PRD is the validator's reference target.
# Expected: the real PRD validates cleanly.
def test_canonical_mainspring_prd_validates() -> None:
    prd = REPO_ROOT / "docs/prd.md"
    assert prd_validate.validate_prd(prd) == []


# Scenario: P-Comp acceptance depends on explicit roadmap metadata.
# Expected: the canonical PRD records completed roadmap work, hosted docs
# publication status, and re-evaluation triggers.
def test_canonical_prd_pcomp_roadmap_metadata() -> None:
    prd = REPO_ROOT / "docs/prd.md"
    text = prd.read_text(encoding="utf-8")

    assert "**v1.x roadmap ownership:**" in text
    assert "P-Comp-7 local implementation" in text
    assert "P-Comp-7 local implementation and hosted publication" in text
    assert "Future hosted-docs work is limited to optional custom-domain polish" in text
    assert "Next public " + "proof" not in text
    assert "proof-" + "ledger" not in text
    assert "**Could-lane re-evaluation triggers:**" in text
    assert "P-Comp-9's core interface is complete" in text
    assert "P-Comp-13 becomes eligible" in text
    assert "- [x] Should items (P-Comp-6 through P-Comp-8) on the v1.x roadmap" in text
    assert (
        "- [x] Could items documented in Backlog with re-evaluation triggers." in text
    )


# Scenario: CLI validates a complete PRD file.
# Expected: exit 0 and success text.
def test_cli_valid_file(tmp_path: Path) -> None:
    prd = tmp_path / "prd.md"
    prd.write_text(_valid_prd())
    result = subprocess.run(
        [sys.executable, SCRIPT, str(prd)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "validation passed" in result.stdout


# Scenario: CLI JSON output on a bad PRD.
# Expected: exit 1 and machine-readable issue codes.
def test_cli_json_failure(tmp_path: Path) -> None:
    prd = tmp_path / "prd.md"
    prd.write_text(_valid_prd() + "\n{{missing}}\n")
    result = subprocess.run(
        [sys.executable, SCRIPT, str(prd), "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "placeholder:unresolved" in result.stdout


def test_validate_prd_missing_file_reports_file_issue(tmp_path: Path) -> None:
    issues = prd_validate.validate_prd(tmp_path / "missing-prd.md")

    assert [issue.code for issue in issues] == ["file:missing"]


@pytest.mark.parametrize(
    ("args", "returncode", "stream", "snippet"),
    [
        ([], 2, "stderr", "Usage: mainspring validate-prd"),
        (["--help"], 0, "stdout", "Usage: mainspring validate-prd"),
        (["missing.md", "--unknown"], 2, "stderr", "Unknown flag"),
        (["missing.md", "--format", "yaml"], 2, "stderr", "Unknown format"),
    ],
)
def test_cli_usage_and_error_paths(
    tmp_path: Path, args: list[str], returncode: int, stream: str, snippet: str
) -> None:
    resolved_args = [
        str(tmp_path / item) if item.endswith(".md") else item for item in args
    ]

    result = subprocess.run(
        [sys.executable, SCRIPT, *resolved_args],
        capture_output=True,
        text=True,
    )

    assert result.returncode == returncode
    output = result.stderr if stream == "stderr" else result.stdout
    assert snippet in output
