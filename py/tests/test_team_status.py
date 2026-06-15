# SPDX-License-Identifier: Apache-2.0
"""Tests for team_status.py — team backend status JSON field extraction."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import team_status  # noqa: E402

SCRIPT = str(HERE.parent / "team_status.py")


def _run(field: str, input_json: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, SCRIPT, "--field", field],
        input=input_json,
        capture_output=True,
        text=True,
    )


# ── status field ────────────────────────────────────────────────────────


# Scenario: Valid JSON with status="ok".
# Expected: prints "ok".
def test_status_ok() -> None:
    result = _run("status", '{"status": "ok"}')
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


# Scenario: Valid JSON with status="missing".
# Expected: prints "missing".
def test_status_missing() -> None:
    result = _run("status", '{"status": "missing"}')
    assert result.returncode == 0
    assert result.stdout.strip() == "missing"


# Scenario: Valid JSON with no status key.
# Expected: prints empty string.
def test_status_absent() -> None:
    result = _run("status", '{"phase": "running"}')
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# Scenario: Invalid JSON.
# Expected: prints empty string.
def test_status_invalid_json() -> None:
    result = _run("status", "not json")
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# ── phase field ─────────────────────────────────────────────────────────


# Scenario: Valid JSON with phase="complete".
# Expected: prints "complete".
def test_phase_complete() -> None:
    result = _run("phase", '{"phase": "complete"}')
    assert result.returncode == 0
    assert result.stdout.strip() == "complete"


# Scenario: Valid JSON with no phase.
# Expected: prints empty string.
def test_phase_absent() -> None:
    result = _run("phase", '{"status": "ok"}')
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# ── dead-workers field ──────────────────────────────────────────────────


# Scenario: Valid JSON with workers.dead=3.
# Expected: prints "3".
def test_dead_workers() -> None:
    result = _run("dead-workers", '{"workers": {"dead": 3, "total": 5}}')
    assert result.returncode == 0
    assert result.stdout.strip() == "3"


# Scenario: No workers key.
# Expected: prints "0".
def test_dead_workers_absent() -> None:
    result = _run("dead-workers", '{"status": "ok"}')
    assert result.returncode == 0
    assert result.stdout.strip() == "0"


# Scenario: Invalid JSON.
# Expected: prints "0".
def test_dead_workers_invalid_json() -> None:
    result = _run("dead-workers", "bad")
    assert result.returncode == 0
    assert result.stdout.strip() == "0"


# ── usable-check field ─────────────────────────────────────────────────


# Scenario: Notification health JSON reports pending lines.
# Expected: pending-lines extracts the integer value for shell drain checks.
def test_pending_lines() -> None:
    result = _run("pending-lines", '{"pending_lines": 3}')
    assert result.returncode == 0
    assert result.stdout.strip() == "3"


# Scenario: Notification health JSON has no pending_lines field.
# Expected: pending-lines defaults to zero.
def test_pending_lines_absent() -> None:
    result = _run("pending-lines", '{"status": "healthy"}')
    assert result.returncode == 0
    assert result.stdout.strip() == "0"


# Scenario: Invalid JSON for notification health.
# Expected: pending-lines defaults to zero.
def test_pending_lines_invalid_json() -> None:
    result = _run("pending-lines", "bad")
    assert result.returncode == 0
    assert result.stdout.strip() == "0"


# Scenario: status=ok, total=3, dead=1.
# Expected: "usable".
def test_usable_check_usable() -> None:
    result = _run(
        "usable-check", '{"status": "ok", "workers": {"total": 3, "dead": 1}}'
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "usable"


# Scenario: status=ok, total=3, dead=3.
# Expected: "bad" (all dead).
def test_usable_check_all_dead() -> None:
    result = _run(
        "usable-check", '{"status": "ok", "workers": {"total": 3, "dead": 3}}'
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "bad"


# Scenario: status=missing.
# Expected: "bad".
def test_usable_check_missing() -> None:
    result = _run(
        "usable-check", '{"status": "missing", "workers": {"total": 3, "dead": 0}}'
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "bad"


# Scenario: Invalid JSON.
# Expected: "bad".
def test_usable_check_invalid_json() -> None:
    result = _run("usable-check", "bad")
    assert result.returncode == 0
    assert result.stdout.strip() == "bad"


# Scenario: status=ok, total=0.
# Expected: "bad" (no workers).
def test_usable_check_zero_total() -> None:
    result = _run(
        "usable-check", '{"status": "ok", "workers": {"total": 0, "dead": 0}}'
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "bad"


# ── parse_field unit tests ──────────────────────────────────────────────


def test_parse_field_status_direct() -> None:
    assert team_status.parse_field('{"status": "ok"}', "status") == "ok"


def test_parse_field_phase_direct() -> None:
    assert team_status.parse_field('{"phase": "running"}', "phase") == "running"


def test_parse_field_dead_workers_direct() -> None:
    assert team_status.parse_field('{"workers": {"dead": 5}}', "dead-workers") == "5"


def test_parse_field_usable_direct() -> None:
    assert (
        team_status.parse_field(
            '{"status": "ok", "workers": {"total": 2, "dead": 0}}', "usable-check"
        )
        == "usable"
    )


def test_parse_field_invalid_json_defaults_direct() -> None:
    assert team_status.parse_field("not json", "status") == ""
    assert team_status.parse_field("not json", "phase") == ""
    assert team_status.parse_field("not json", "dead-workers") == "0"
    assert team_status.parse_field("not json", "pending-lines") == "0"
    assert team_status.parse_field("not json", "usable-check") == "bad"


def test_parse_field_invalid_worker_counts_direct() -> None:
    assert (
        team_status.parse_field('{"workers": {"dead": "many"}}', "dead-workers") == "0"
    )
    assert (
        team_status.parse_field(
            '{"status": "ok", "workers": {"total": "many", "dead": 0}}',
            "usable-check",
        )
        == "bad"
    )


def test_parse_field_unknown_field_direct(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        team_status.parse_field("{}", "bogus")
    assert exc.value.code == 2
    assert "Unknown field: bogus" in capsys.readouterr().err


# ── CLI error handling ──────────────────────────────────────────────────


# Scenario: No arguments.
# Expected: exit code 2.
def test_cli_no_args() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


# Scenario: Unknown field.
# Expected: exit code 2.
def test_cli_unknown_field() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "--field", "bogus"],
        input="{}",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
