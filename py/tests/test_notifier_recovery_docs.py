# SPDX-License-Identifier: Apache-2.0
"""Regression tests for safe Telegram notifier recovery guidance."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDE = REPO_ROOT / "docs" / "guide.md"
PLAYBOOK = REPO_ROOT / "docs" / "playbook.md"
PRD = REPO_ROOT / "docs" / "prd.md"
DOCTOR = REPO_ROOT / "lib" / "doctor.sh"
PROCESS_NAME_KILL = "pkill -f " + "notify_" + "telegram.py"


def _line_containing(path: Path, needle: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if needle in line:
            return line
    raise AssertionError(f"{needle!r} not found in {path.relative_to(REPO_ROOT)}")


# Scenario: The quick disaster-recovery table is the first operator surface
# for a stuck Telegram daemon.
# Expected: It routes to the safe recorded-PID restart flow, not broad pkill.
def test_playbook_telegram_stuck_recovery_uses_safe_restart() -> None:
    row = _line_containing(PLAYBOOK, "| Telegram daemon stuck")

    assert "notify-health --format json" in row
    assert "notify-restart" in row
    assert "notify-test" in row
    assert PROCESS_NAME_KILL not in row
    assert "relaunch with next wave" not in row


# Scenario: The guide's detailed Telegram recovery procedure is copied during
# incidents, so it must not drift back to process-name kills.
# Expected: It names the health probe and recorded-PID restart flow.
def test_guide_telegram_recovery_uses_safe_restart() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    recovery = text.split("**Recovery:**", 1)[1]

    assert "mainspring notify-health --format json" in recovery
    assert "mainspring notify-restart" in recovery
    assert "mainspring notify-test" in recovery
    assert PROCESS_NAME_KILL not in recovery


# Scenario: The PRD is the canonical recovery source for night-worker routing.
# Expected: The Telegram stuck section preserves the safe notifier restart path.
def test_prd_telegram_stuck_recovery_uses_safe_restart() -> None:
    text = PRD.read_text(encoding="utf-8")
    section = text.split("### Telegram daemon stuck", 1)[1].split("---", 1)[0]

    assert "mainspring notify-health --format json" in section
    assert "mainspring notify-restart" in section
    assert "mainspring notify-test" in section
    assert PROCESS_NAME_KILL not in section


# Scenario: Doctor is the standard launch-readiness probe when the notifier
# daemon is missing or dead.
# Expected: Its warning names the same immediate recovery flow as the runbook.
def test_doctor_missing_notifier_pid_guidance_names_safe_restart() -> None:
    warning = _line_containing(DOCTOR, "Telegram notifier pid missing")

    assert "mainspring notify-restart" in warning
    assert "mainspring notify-test" in warning
    assert "start the next enabled wave" not in warning
