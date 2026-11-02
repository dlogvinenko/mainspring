# SPDX-License-Identifier: Apache-2.0
"""Synthetic Team read failures and maintenance ordering through real helpers."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EMPTY = '{"master":{"tasks":[]}}'
READY = {
    "id": 1,
    "title": "Synthetic task",
    "status": "pending",
    "details": "Touch src/a.py",
    "dependencies": [],
    "subtasks": [],
}


def environment(tag=None):
    values = {
        key: os.environ[key]
        for key in ("HOME", "home", "CODEX_HOME")
        if key in os.environ
    }
    values.update(PATH="/usr/bin:/bin", PYTHONDONTWRITEBYTECODE="1")
    if tag is not None:
        values["MAINSPRING_TASKMASTER_TAG"] = tag
    return values


def prepare_project(project, raw, state_tag=None):
    path = project / ".taskmaster/tasks/tasks.json"
    path.parent.mkdir(parents=True)
    if raw is not None:
        path.write_text(raw)
    if state_tag is not None:
        (project / ".taskmaster/state.json").write_text(
            json.dumps({"currentTag": state_tag})
        )
    return path


def run_helper(project, command, tag=None):
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "py/taskmaster.py"),
            command,
            str(project / ".taskmaster/tasks/tasks.json"),
        ],
        cwd=project,
        env=environment(tag),
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )


SHELL = r"""
set -euo pipefail
source "$1/lib/team.sh"
source "$1/lib/team_supervision.sh"
source "$1/lib/taskmaster_helpers.sh"
MAINSPRING_PY_DIR="$1/py"; PY="$2"; ROOT_DIR="$3"
LOG_FILE="$3/log"; CALLS="$3/calls"; FAIL_READ="$4"
TEAM_FALLBACK_TO_SOLO="$5"; PHASE="$6"
TASKS="$ROOT_DIR/.taskmaster/tasks/tasks.json"
team_python() { printf '%s\n' "$PY"; }
mainspring_python() { printf '%s\n' "$PY"; }
omx() {
  printf '{"status":"ok","phase":"%s","workers":{"total":2,"dead":0}}\n' "$PHASE"
}
team_task_counts() { printf 'counts\n' >> "$CALLS"; printf '0 0 0 0\n'; }
requeue_stale_team_tasks() { printf 'requeue\n' >> "$CALLS"; }
nudge_pending_team_tasks() { printf 'nudge\n' >> "$CALLS"; }
dispatch_parallel_team_tasks() { printf 'dispatch\n' >> "$CALLS"; }
sleep() { printf 'unexpected polling in bounded fixture\n' >&2; exit 98; }
collect_parallel_taskmaster_items() {
  printf 'collect\n' >> "$CALLS"
  if [ "$FAIL_READ" = collect_partial ]; then
    printf '%s\n' '{"id":1}'
    return 7
  fi
  local rc
  "$PY" "$MAINSPRING_PY_DIR/taskmaster.py" collect-parallel "$TASKS" --limit "$1"
  rc=$?
  case "$FAIL_READ" in
    skip_json) printf '{' > "$TASKS" ;;
    skip_utf8) printf '\377' > "$TASKS" ;;
  esac
  return "$rc"
}
taskmaster_team_skip_reason() {
  printf 'skip\n' >> "$CALLS"
  if [ "$FAIL_READ" = skip_partial ]; then
    printf 'routing:synthetic_partial\n'
    return 8
  fi
  "$PY" "$MAINSPRING_PY_DIR/taskmaster.py" team-skip-reason "$TASKS"
}
TEAM_SUPERVISE=true; TEAM_POLL_SECONDS=0
if supervise_team_run synthetic-team 2; then rc=0; else rc=$?; fi
printf 'GUARD_RETURN:%s\nGUARD_REASON:%s\n' "$rc" "${TEAM_FALLBACK_REASON-unset}"
"""


def run_supervisor(
    project, *, phase="complete", fallback="false", failure="none", tag=None
):
    calls = project / "calls"
    calls.write_text("")
    result = subprocess.run(
        [
            "/bin/bash",
            "--noprofile",
            "--norc",
            "-c",
            SHELL,
            "synthetic-team",
            str(ROOT),
            sys.executable,
            str(project),
            failure,
            fallback,
            phase,
        ],
        cwd=project,
        env=environment(tag),
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    code = int(re.search(r"GUARD_RETURN:(\d+)", result.stdout).group(1))
    reason = re.search(r"GUARD_REASON:([^\n]+)", result.stdout).group(1)
    actions = calls.read_text().splitlines()
    return code, reason, actions, result


@pytest.mark.parametrize(
    "case,fallback",
    [
        ("collect_json", "false"),
        ("collect_json", "true"),
        ("collect_null_rows", "false"),
        ("collect_scalar_row", "false"),
        ("collect_missing", "false"),
        ("collect_partial", "false"),
        ("skip_json", "false"),
        ("skip_utf8", "true"),
        ("skip_partial", "false"),
        ("ordinary_complete", "false"),
        ("ordinary_complete", "true"),
        ("ordinary_running", "false"),
        ("active_collect_error", "false"),
        ("complete_ready", "false"),
    ],
)
def test_read_failure_and_maintenance_order(tmp_path, case, fallback):
    raw = EMPTY
    if case in {"collect_json", "active_collect_error"}:
        raw = "{"
    elif case == "collect_null_rows":
        raw = '{"master":{"tasks":null}}'
    elif case == "collect_scalar_row":
        raw = '{"master":{"tasks":[1]}}'
    elif case == "collect_missing":
        raw = None
    elif case == "complete_ready":
        raw = json.dumps({"master": {"tasks": [READY]}})
    prepare_project(tmp_path, raw)
    phase = (
        "running"
        if case in {"ordinary_running", "active_collect_error"}
        else "complete"
    )
    code, reason, actions, result = run_supervisor(
        tmp_path,
        phase=phase,
        fallback=fallback,
        failure=case,
    )
    ordinary = case.startswith("ordinary_")
    assert code == (2 if fallback == "true" else 0) if ordinary else code == 2
    assert reason == ("team:no_parallel_safe_work" if ordinary else "unset")
    prefix = ["requeue", "nudge"] if phase == "running" else []
    suffix = ["counts", "collect"]
    if case.startswith("skip_") or ordinary:
        suffix.append("skip")
    assert actions == prefix + suffix
    assert "dispatch" not in actions
    assert ("No more parallel-safe Taskmaster work" in result.stdout) == ordinary
    assert "--restart-team" in result.stdout
    if ordinary:
        assert result.stderr == ""
