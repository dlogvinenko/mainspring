# SPDX-License-Identifier: Apache-2.0
"""Actual malformed Taskmaster reads refuse terminal Team completion."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENV = {
    key: os.environ[key] for key in ("HOME", "home", "CODEX_HOME") if key in os.environ
}
ENV.update(PATH="/usr/bin:/bin:/opt/homebrew/bin", PYTHONDONTWRITEBYTECODE="1")
SHELL = r"""
set -euo pipefail
source "$1/lib/team.sh"
source "$1/lib/team_supervision.sh"
source "$1/lib/taskmaster_helpers.sh"
MAINSPRING_PY_DIR="$1/py"; PY="$2"; ROOT_DIR="$3"
LOG_FILE="$3/log"; CALLS="$3/calls"; FAIL_READ="$4"; TEAM_FALLBACK_TO_SOLO="$5"
team_python() { printf '%s\n' "$PY"; }
mainspring_python() { printf '%s\n' "$PY"; }
omx() { printf '%s\n' '{"status":"ok","phase":"complete","workers":{"total":2,"dead":0}}'; }
team_task_counts() { printf '%s\n' '0 0 0 0'; }
requeue_stale_team_tasks() { printf 'requeue\n' >> "$CALLS"; }
nudge_pending_team_tasks() { printf 'nudge\n' >> "$CALLS"; }
dispatch_parallel_team_tasks() { printf 'dispatch\n' >> "$CALLS"; }
if [ "$FAIL_READ" = skip ]; then
  collect_parallel_taskmaster_items() {
    local rc
    "$PY" "$MAINSPRING_PY_DIR/taskmaster.py" collect-parallel "$ROOT_DIR/.taskmaster/tasks/tasks.json" --limit "$1"
    rc=$?
    printf '{' > "$ROOT_DIR/.taskmaster/tasks/tasks.json"
    return "$rc"
  }
fi
TEAM_SUPERVISE=true; TEAM_POLL_SECONDS=0
if supervise_team_run synthetic-team 2; then rc=0; else rc=$?; fi
printf 'PEER_RETURN:%s\nPEER_REASON:%s\n' "$rc" "${TEAM_FALLBACK_REASON-unset}"
"""


@pytest.mark.parametrize("failed_read", ["collect", "skip"])
@pytest.mark.parametrize("fallback", ["false", "true"])
def test_actual_unknown_ready_read_is_refused(tmp_path, failed_read, fallback):
    path = tmp_path / ".taskmaster/tasks/tasks.json"
    path.parent.mkdir(parents=True)
    initial = "{" if failed_read == "collect" else '{"master":{"tasks":[]}}'
    path.write_text(initial)
    calls = tmp_path / "calls"
    calls.write_text("")
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            SHELL,
            "synthetic",
            str(ROOT),
            sys.executable,
            str(tmp_path),
            failed_read,
            fallback,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env=ENV,
        cwd=tmp_path,
    )
    proof = {
        "failed_read": failed_read,
        "fallback": fallback,
        "initial_tasks_text": initial,
        "final_tasks_text": path.read_text(),
        "process_returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "calls": calls.read_text().splitlines(),
    }
    (tmp_path / "result.json").write_text(json.dumps(proof, indent=2) + "\n")
    assert result.returncode == 0, result.stderr
    assert calls.read_text() == ""
    assert "JSONDecodeError" in result.stderr
    assert (
        "cmd_collect_parallel" in result.stderr
        if failed_read == "collect"
        else "cmd_team_skip_reason" in result.stderr
    )
    assert "PEER_RETURN:2\n" in result.stdout
    assert "No more parallel-safe Taskmaster work" not in result.stdout
    assert "PEER_REASON:unset\n" in result.stdout
    assert "--restart-team" in result.stdout
    expected = (
        "could not read ready Taskmaster work"
        if failed_read == "collect"
        else "could not read Taskmaster team skip reason"
    )
    assert expected in result.stdout
