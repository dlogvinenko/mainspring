# SPDX-License-Identifier: Apache-2.0
"""Tests for decompose.py - PRD phase to Taskmaster prompt planner."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import decompose  # noqa: E402

SCRIPT = str(HERE.parent / "decompose.py")


def _valid_prd(phase_map: str) -> str:
    return f"""# Example - Product Requirements Document (PRD)

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

{phase_map}

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

### Won't (explicit non-goals - do not propose)

- SaaS hosting.

## Appendix A - Source-of-knowledge recipes

Recipes.

## Appendix B - Verification commands

Commands.

## Acknowledgments / Lineage

Lineage.
"""


def _write_prd(tmp_path: Path, phase_map: str) -> Path:
    path = tmp_path / "prd.md"
    path.write_text(_valid_prd(phase_map), encoding="utf-8")
    return path


def test_parse_phase_map_extracts_unchecked_tasks() -> None:
    phases = decompose.parse_phase_map(
        _valid_prd(
            """### P1 - First phase (ACTIVE)

**Goal:** Ship it.

- [x] **P1-1 Completed task.** Already done.
- [ ] **P1-2 Render status panel.** Touch `py/hud.py`.
  Add status output.

### P2 - Last phase

- [ ] **P2-1 Manual release sign-off.** Requires sign-off.
"""
        )
    )

    assert [phase.phase_id for phase in phases] == ["P1", "P2"]
    assert phases[0].active is True
    assert phases[0].tasks[1].task_id == "P1-2"
    assert phases[0].tasks[1].checked is False


def test_select_phase_defaults_to_active_marker() -> None:
    phases = decompose.parse_phase_map(
        _valid_prd(
            """### P1 - First phase (DONE)

- [x] **P1-1 Done.** Done.

### P2 - Current phase (ACTIVE)

- [ ] **P2-1 Build command.** Touch `mainspring.sh`.
"""
        )
    )

    assert decompose.select_phase(phases).phase_id == "P2"


def test_select_phase_uses_active_prd_state(tmp_path: Path) -> None:
    phases = decompose.parse_phase_map(
        _valid_prd(
            """### P1 - First phase

- [ ] **P1-1 Build command.** Touch `mainspring.sh`.

### P2 - Current phase

- [ ] **P2-1 Build docs.** Touch `docs/guide.md`.
"""
        )
    )
    active_prd = tmp_path / "active.json"
    active_prd.write_text(json.dumps({"current_phase": "P2"}), encoding="utf-8")

    assert decompose.select_phase(phases, active_prd_file=active_prd).phase_id == "P2"


def test_select_phase_reports_missing_phase_and_empty_phase_map() -> None:
    with pytest.raises(ValueError, match="no parseable Phase map"):
        decompose.select_phase([])

    phases = decompose.parse_phase_map(
        _valid_prd(
            """### P1 - First phase

- [ ] **P1-1 Build command.** Touch `mainspring.sh`.
"""
        )
    )
    with pytest.raises(ValueError, match="Phase not found"):
        decompose.select_phase(phases, requested="P9")


def test_parse_phase_map_preserves_audit_phase_and_lettered_task_ids() -> None:
    phases = decompose.parse_phase_map(
        _valid_prd(
            """### P-Audit - Release audit remediation (ACTIVE)

- [ ] **P-Audit-1f Make canonical PRD validate clean.** Touch `docs/prd.md`.
"""
        )
    )

    assert phases[0].phase_id == "P-Audit"
    assert phases[0].tasks[0].task_id == "P-Audit-1f"
    assert decompose.select_phase(phases, "P-Audit").phase_id == "P-Audit"


def test_helper_fallbacks_for_sparse_prd_task_text(tmp_path: Path) -> None:
    assert decompose._section_text("# Title\n\nNo phase map here", "Phase map") == ""
    assert (
        decompose._task_title("Plain `docs/prd.md` task.") == "Plain docs/prd.md task"
    )

    active_prd = tmp_path / "active-prd.json"
    active_prd.write_text("{bad json", encoding="utf-8")
    assert decompose._read_active_phase(active_prd) == ""
    assert decompose._read_active_phase(tmp_path / "missing.json") == ""

    phase = decompose.PrdPhase(
        phase_id="P1",
        title="Current",
        body="",
        tasks=[],
        active=False,
    )
    sparse_task = decompose.PrdTask(
        task_id="P1-1",
        title="Sparse",
        checked=False,
        raw="**P1-1 Sparse.**",
        body="",
    )

    assert decompose._summary_text(phase, sparse_task) == (
        "Implement the PRD task from P1: Sparse."
    )
    assert "`TBD`" in decompose._render_scope([])
    assert decompose._prompt_section("## Present\nvalue", "Missing") == ""


def test_build_plan_moves_manual_blockers_to_last_phase(tmp_path: Path) -> None:
    prd = _write_prd(
        tmp_path,
        """### P1 - Current phase

- [ ] **P1-1 Prepare release submission.** Requires Plugin Hub submission.

### P2 - Manual lane

- [ ] **P2-1 Final manual sign-off.** Requires human review.
""",
    )
    phases = decompose.parse_phase_map(prd.read_text(encoding="utf-8"))
    plan = decompose.build_plan(prd, phases[0], phases)

    assert len(plan) == 1
    assert plan[0].manual_blocker is True
    assert plan[0].status == "blocked"
    assert plan[0].target_phase == "P2"
    assert "GeneratedBy: decompose" in plan[0].prompt


def test_build_plan_include_done_and_text_format_empty_phase(tmp_path: Path) -> None:
    prd = _write_prd(
        tmp_path,
        """### P1 - Current phase

- [x] **P1-1 Completed task.** Touch `docs/prd.md`.
""",
    )
    phases = decompose.parse_phase_map(prd.read_text(encoding="utf-8"))

    skipped = decompose.build_plan(prd, phases[0], phases)
    included = decompose.build_plan(prd, phases[0], phases, include_done=True)

    assert skipped == []
    assert included[0].task_id == "P1-1"
    assert "No unchecked tasks found" in decompose._format_text(prd, phases[0], skipped)


def test_cli_json_dry_run_outputs_taskmaster_prompt(tmp_path: Path) -> None:
    prd = _write_prd(
        tmp_path,
        """### P1 - Current phase

- [ ] **P1-1 Add decompose dispatch.** Touch `mainspring.sh`.

### P2 - Manual lane

- [ ] **P2-1 Manual publish.** Requires live account.
""",
    )

    result = subprocess.run(
        [sys.executable, SCRIPT, str(prd), "--phase", "P1", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["phase"]["phase_id"] == "P1"
    assert payload["tasks"][0]["task_id"] == "P1-1"
    assert "task-master add-task" not in payload["tasks"][0]["prompt"]
    assert "make all` from the repository root" in payload["tasks"][0]["prompt"]
    assert "cd scripts/" + "mainspring" not in payload["tasks"][0]["prompt"]


def test_apply_creates_backup_and_taskmaster_task(tmp_path: Path) -> None:
    prd = _write_prd(
        tmp_path,
        """### P1 - Current phase

- [ ] **P1-1 Add decompose dispatch.** Touch `mainspring.sh`.

### P2 - Manual lane

- [ ] **P2-1 Manual publish.** Requires live account.
""",
    )
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text('{"master":{"tasks":[]}}\n', encoding="utf-8")
    backup_dir = tmp_path / "backups"
    phases = decompose.parse_phase_map(prd.read_text(encoding="utf-8"))
    plans = decompose.build_plan(prd, phases[0], phases)

    summary = decompose.apply_plans(tasks_file, plans, backup_dir)

    data = json.loads(tasks_file.read_text(encoding="utf-8"))
    task = data["master"]["tasks"][0]
    assert summary.created == [1]
    assert summary.updated == []
    assert Path(summary.backup_file).exists()
    assert task["status"] == "pending"
    assert task["mainspring"]["generatedBy"] == "decompose"
    assert task["mainspring"]["digest"] == plans[0].digest
    assert "GeneratedBy: decompose" in task["details"]


def test_apply_is_idempotent_and_preserves_status(tmp_path: Path) -> None:
    prd = _write_prd(
        tmp_path,
        """### P1 - Current phase

- [ ] **P1-1 Add decompose dispatch.** Touch `mainspring.sh`.
""",
    )
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text('{"master":{"tasks":[]}}\n', encoding="utf-8")
    backup_dir = tmp_path / "backups"
    phases = decompose.parse_phase_map(prd.read_text(encoding="utf-8"))
    plans = decompose.build_plan(prd, phases[0], phases)

    first = decompose.apply_plans(tasks_file, plans, backup_dir)
    data = json.loads(tasks_file.read_text(encoding="utf-8"))
    data["master"]["tasks"][0]["status"] = "review"
    tasks_file.write_text(json.dumps(data), encoding="utf-8")

    second = decompose.apply_plans(tasks_file, plans, backup_dir)
    data = json.loads(tasks_file.read_text(encoding="utf-8"))

    assert first.created == [1]
    assert second.created == []
    assert second.updated == []
    assert second.unchanged == [1]
    assert len(data["master"]["tasks"]) == 1
    assert data["master"]["tasks"][0]["status"] == "review"
    assert len(list(backup_dir.glob("*.bak"))) == 2


def test_apply_updates_legacy_generated_task(tmp_path: Path) -> None:
    prd = _write_prd(
        tmp_path,
        """### P1 - Current phase

- [ ] **P1-1 Add decompose dispatch.** Touch `mainspring.sh`.
""",
    )
    phases = decompose.parse_phase_map(prd.read_text(encoding="utf-8"))
    plans = decompose.build_plan(prd, phases[0], phases)
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(
        json.dumps(
            {
                "master": {
                    "tasks": [
                        {
                            "id": 2,
                            "title": "Old",
                            "details": (
                                f"GeneratedBy: decompose\nSource: {prd}\n"
                                f"Digest: {plans[0].digest}\n"
                            ),
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    summary = decompose.apply_plans(tasks_file, plans, tmp_path / "backups")
    data = json.loads(tasks_file.read_text(encoding="utf-8"))

    assert summary.updated == [2]
    assert data["master"]["tasks"][0]["title"] == "P1-1 Add decompose dispatch"
    assert data["master"]["tasks"][0]["mainspring"]["digest"] == plans[0].digest


def test_next_task_id_ignores_non_integer_ids() -> None:
    assert decompose._next_task_id([{"id": "not-int"}, {"id": 3}]) == 4


def test_cli_apply_writes_tasks_file(tmp_path: Path) -> None:
    prd = _write_prd(
        tmp_path,
        """### P1 - Current phase

- [ ] **P1-1 Add decompose dispatch.** Touch `mainspring.sh`.
""",
    )
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text('{"master":{"tasks":[]}}\n', encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            str(prd),
            "--phase",
            "P1",
            "--apply",
            "--tasks-file",
            str(tasks_file),
            "--backup-dir",
            str(tmp_path / "backups"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    data = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert result.returncode == 0
    assert "created: 1 [1]" in result.stdout
    assert data["master"]["tasks"][0]["mainspring"]["taskId"] == "P1-1"


def test_cli_rejects_invalid_prd(tmp_path: Path) -> None:
    prd = tmp_path / "bad.md"
    prd.write_text("# Missing Method shape\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, SCRIPT, str(prd)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "PRD validation failed" in result.stderr


def test_cli_rejects_unknown_flag_and_format(tmp_path: Path) -> None:
    prd = _write_prd(
        tmp_path,
        """### P1 - Current phase

- [ ] **P1-1 Build docs.** Touch `docs/guide.md`.
""",
    )

    unknown = subprocess.run(
        [sys.executable, SCRIPT, str(prd), "--phase"],
        capture_output=True,
        text=True,
        check=False,
    )
    bad_format = subprocess.run(
        [sys.executable, SCRIPT, str(prd), "--format", "yaml"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert unknown.returncode == 2
    assert "Unknown or incomplete flag: --phase" in unknown.stderr
    assert bad_format.returncode == 2
    assert "Unknown format: yaml" in bad_format.stderr


def test_cli_apply_reports_missing_taskmaster_file(tmp_path: Path) -> None:
    prd = _write_prd(
        tmp_path,
        """### P1 - Current phase

- [ ] **P1-1 Build docs.** Touch `docs/guide.md`.
""",
    )

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            str(prd),
            "--apply",
            "--tasks-file",
            str(tmp_path / "missing.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Taskmaster file not found" in result.stderr


def test_cli_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Usage: mainspring decompose" in result.stdout
    assert "mainspring decompose docs/prd.md --phase P1 --apply" in result.stdout
    assert "Add --apply" not in result.stdout
