# SPDX-License-Identifier: Apache-2.0
"""Synthetic status and supervision controls without a real team backend."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "py/team_status.py"


def cli(field, payload):
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--field", field],
        input=json.dumps(payload),
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )


@pytest.mark.parametrize(
    "workers",
    [
        {"total": True, "dead": 0},
        {"total": 2, "dead": False},
        {"total": 1.9, "dead": 0},
        {"total": 2, "dead": 1.9},
        {"total": 2, "dead": -1},
        {"total": 2},
        {"total": 2, "dead": None},
        {"total": 2, "dead": ""},
        None,
        [],
        "bad",
    ],
)
def test_unproved_or_non_integer_workers_never_usable(workers):
    result = cli("usable-check", {"status": "ok", "workers": workers})
    assert (result.returncode, result.stdout.strip(), result.stderr) == (0, "bad", "")


@pytest.mark.parametrize(
    "workers,expected",
    [
        ({"total": 2, "dead": 0}, "usable"),
        ({"total": "2", "dead": "0"}, "usable"),
        ({"total": 2, "dead": 2}, "bad"),
        ({"total": 0, "dead": 0}, "bad"),
    ],
)
def test_existing_integer_and_decimal_string_controls(workers, expected):
    result = cli("usable-check", {"status": "ok", "workers": workers})
    assert (result.returncode, result.stdout.strip(), result.stderr) == (
        0,
        expected,
        "",
    )


@pytest.mark.parametrize("payload", [None, [], 1])
@pytest.mark.parametrize(
    "field,expected",
    [("status", ""), ("phase", ""), ("dead-workers", "0"), ("usable-check", "bad")],
)
def test_wrong_top_level_shape_uses_documented_error_defaults(payload, field, expected):
    result = cli(field, payload)
    assert (result.returncode, result.stdout.strip(), result.stderr) == (
        0,
        expected,
        "",
    )


@pytest.mark.parametrize("field", ["status", "phase"])
@pytest.mark.parametrize("value", [True, ["running"]])
def test_status_and_phase_do_not_fabricate_scalar_text(field, value):
    result = cli(field, {field: value})
    assert (result.returncode, result.stdout.strip(), result.stderr) == (0, "", "")


@pytest.mark.parametrize("value", [True, 1.9, -1, []])
def test_invalid_dead_count_keeps_legacy_zero_default(value):
    result = cli("dead-workers", {"workers": {"dead": value}})
    assert (result.returncode, result.stdout.strip(), result.stderr) == (0, "0", "")


SHELL = r"""
set -euo pipefail
source "$1"
source "${1%/*}/team_supervision.sh"
MAINSPRING_PY_DIR="$2"; NATIVE_PYTHON="$3"; NATIVE_INPUT="$4"; NATIVE_CALLS="$5"; LOG_FILE="$6"; STATE_DIR="$7"
NATIVE_FALLBACK="${10}"; NATIVE_COUNTS="${11}"; NATIVE_NEXT="${12}"; NATIVE_SKIP="${13}"; NATIVE_COUNTS_EXIT="${14}"
team_python() { printf '%s\n' "$NATIVE_PYTHON"; }
omx() { cat "$NATIVE_INPUT"; }
requeue_stale_team_tasks() { printf 'requeue\n' >> "$NATIVE_CALLS"; }
nudge_pending_team_tasks() { printf 'nudge\n' >> "$NATIVE_CALLS"; }
team_task_counts() { printf '%s\n' "$NATIVE_COUNTS"; return "$NATIVE_COUNTS_EXIT"; }
collect_parallel_taskmaster_items() { printf '%s' "$NATIVE_NEXT"; }
taskmaster_team_skip_reason() { printf '%s' "$NATIVE_SKIP"; }
dispatch_parallel_team_tasks() { printf 'dispatch\n' >> "$NATIVE_CALLS"; }
TEAM_SUPERVISE=true; TEAM_POLL_SECONDS=0; TEAM_FALLBACK_TO_SOLO="$NATIVE_FALLBACK"
if [ "$8" = supervise-direct ]; then
  supervise_team_run synthetic-team "$9"
  result=$?
elif [ "$8" = supervise ]; then
  if supervise_team_run synthetic-team "$9"; then result=0; else result=$?; fi
else
  if find_active_team_name; then result=0; else result=$?; fi
fi
printf 'NATIVE_RETURN:%s\n' "$result"
printf 'NATIVE_FALLBACK:%s\n' "${TEAM_FALLBACK_REASON-unset}"
"""


def shell(
    tmp_path,
    payload,
    mode="supervise",
    team_size=2,
    *,
    fallback="false",
    counts="0 0 0 0",
    next_items="",
    skip_reason="",
    counts_exit=0,
):
    source = tmp_path / "status.json"
    source.write_text(json.dumps(payload))
    calls = tmp_path / "calls.txt"
    calls.write_text("")
    state = tmp_path / "state"
    team = state / "team/synthetic-team"
    team.mkdir(parents=True)
    (team / "config.json").write_text('{"name":"synthetic-team"}\n')
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            SHELL,
            "synthetic-native",
            str(ROOT / "lib/team.sh"),
            str(ROOT / "py"),
            sys.executable,
            str(source),
            str(calls),
            str(tmp_path / "log.txt"),
            str(state),
            mode,
            str(team_size),
            fallback,
            counts,
            next_items,
            skip_reason,
            str(counts_exit),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if mode == "supervise-direct" and result.returncode:
        code = result.returncode
    else:
        assert result.returncode == 0, result.stderr
        code = int(re.search(r"NATIVE_RETURN:(\d+)", result.stdout).group(1))
    return code, result, calls.read_text().splitlines()


@pytest.mark.parametrize(
    "workers",
    [
        None,
        {"total": 2, "dead": "many"},
        {"total": 2, "dead": -1},
        {"total": True, "dead": 0},
    ],
)
def test_actual_supervisor_never_acts_on_unproved_worker_evidence(tmp_path, workers):
    code, result, calls = shell(
        tmp_path, {"status": "ok", "phase": "running", "workers": workers}
    )
    assert code == 2 and not calls and not result.stderr


@pytest.mark.parametrize(
    "payload,expected,calls_expected",
    [
        (
            {"status": "ok", "phase": "running", "workers": {"total": 2, "dead": 0}},
            0,
            ["requeue", "nudge"],
        ),
        (
            {"status": "ok", "phase": "running", "workers": {"total": 2, "dead": 2}},
            2,
            [],
        ),
        ({"status": "missing"}, 2, []),
    ],
)
def test_actual_supervisor_preserves_valid_and_existing_terminal_controls(
    tmp_path, payload, expected, calls_expected
):
    code, result, calls = shell(tmp_path, payload)
    assert code == expected and calls == calls_expected and not result.stderr


@pytest.mark.parametrize("status", [True, ["ok"]])
def test_actual_active_team_scan_does_not_select_non_scalar_status(tmp_path, status):
    code, result, calls = shell(
        tmp_path,
        {"status": status, "phase": "running", "workers": {"total": 2, "dead": 0}},
        "active",
    )
    assert code == 1 and not calls
    assert result.stdout.split("NATIVE_RETURN:", 1)[0].splitlines() == []


@pytest.mark.parametrize(
    "phase,expected", [("running", 0), ("complete", 1), ("cancelled", 1), ("failed", 1)]
)
def test_actual_active_team_scan_preserves_named_phases(tmp_path, phase, expected):
    code, result, calls = shell(
        tmp_path,
        {"status": "ok", "phase": phase, "workers": {"total": 2, "dead": 0}},
        "active",
    )
    assert code == expected and not calls
    expected_names = ["synthetic-team"] if phase == "running" else []
    assert result.stdout.split("NATIVE_RETURN:", 1)[0].splitlines() == expected_names


@pytest.mark.parametrize(
    "total,dead,local_size,expected,calls_expected",
    [
        (2, 2, 6, 2, []),
        (6, 2, 2, 0, ["requeue", "nudge"]),
    ],
)
def test_actual_supervisor_uses_reported_worker_total(
    tmp_path, total, dead, local_size, expected, calls_expected
):
    code, result, calls = shell(
        tmp_path,
        {"status": "ok", "phase": "running", "workers": {"total": total, "dead": dead}},
        team_size=local_size,
    )
    assert code == expected and calls == calls_expected and not result.stderr


@pytest.mark.parametrize("phase", ["cancelled", "failed"])
def test_actual_supervisor_preserves_terminal_phase_boundaries(tmp_path, phase):
    code, result, calls = shell(
        tmp_path, {"status": "ok", "phase": phase, "workers": {"total": 2, "dead": 0}}
    )
    assert code == 2 and not calls and not result.stderr


def test_actual_supervisor_refuses_backend_error_status(tmp_path):
    code, result, calls = shell(
        tmp_path,
        {"status": "error", "phase": "running", "workers": {"total": 2, "dead": 0}},
    )
    assert code == 2 and not calls and not result.stderr


@pytest.mark.parametrize(
    "value,expected", [(6, "6"), ("6", "6"), (True, "0"), (1.9, "0")]
)
def test_additive_total_counter_has_same_safe_integer_contract(value, expected):
    result = cli("total-workers", {"workers": {"total": value}})
    assert (result.returncode, result.stdout.strip(), result.stderr) == (
        0,
        expected,
        "",
    )


@pytest.mark.parametrize("workers", [None, {"total": 2, "dead": "many"}])
def test_errexit_consumer_returns_restart_guidance_without_parser_crash(
    tmp_path, workers
):
    code, result, calls = shell(
        tmp_path,
        {"status": "ok", "phase": "running", "workers": workers},
        "supervise-direct",
    )
    assert code == 2 and not calls and not result.stderr
    assert "explicit restart" in result.stdout or "--restart-team" in result.stdout


@pytest.mark.parametrize(
    "fallback,skip_reason,expected",
    [
        ("false", "", 0),
        ("true", "", 2),
        ("false", "routing:plugin_invisible", 0),
        ("true", "routing:plugin_invisible", 2),
    ],
)
def test_complete_no_more_work_preserves_existing_fallback_policy_without_actions(
    tmp_path, fallback, skip_reason, expected
):
    payload = {"status": "ok", "phase": "complete", "workers": {"total": 2, "dead": 0}}
    code, result, calls = shell(
        tmp_path, payload, fallback=fallback, skip_reason=skip_reason
    )
    assert code == expected and not calls and not result.stderr
    assert (
        "NATIVE_FALLBACK:" + (skip_reason or "team:no_parallel_safe_work")
        in result.stdout
    )
    assert "No more parallel-safe Taskmaster work" in result.stdout
    assert "--restart-team" in result.stdout


@pytest.mark.parametrize(
    "kwargs",
    [
        {"counts": "1 0 0 0"},
        {"counts": "0 1 0 0"},
        {"next_items": "synthetic-ready-item"},
        {"counts_exit": 1},
    ],
)
def test_complete_with_unfinished_or_unknown_work_refuses_without_backend_actions(
    tmp_path, kwargs
):
    payload = {"status": "ok", "phase": "complete", "workers": {"total": 2, "dead": 0}}
    code, result, calls = shell(tmp_path, payload, **kwargs)
    assert code == 2 and not calls and not result.stderr
