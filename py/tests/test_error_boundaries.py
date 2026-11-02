# SPDX-License-Identifier: Apache-2.0
"""Regression controls for malformed external data and process failures."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from datetime import UTC, datetime

import coverage_gate
import fnm_env
import hud
import limits
import metrics
import notify_telegram
import pytest
import replay
import runtime_state
import taskmaster
import team_dispatch
import wave_log


@pytest.mark.parametrize(
    "reader", [metrics.read_ledger, replay.read_ledger, wave_log.read_ledger]
)
def test_malformed_nested_json_row_preserves_later_valid_ledger_entry(tmp_path, reader):
    ledger = tmp_path / "waves.jsonl"
    valid = {"wave": 1, "verdict": "PASS", "exit_code": 0}
    ledger.write_text("[" * 2000 + "}" + "\n" + json.dumps(valid) + "\n")

    assert reader(ledger) == [valid]


def test_unreadable_utf8_runtime_json_remains_unknown(tmp_path):
    path = tmp_path / "state.json"
    path.write_bytes(b'{"state":"\xff"}')

    assert runtime_state._read_json(path) is None


def test_invalid_utf8_fnm_input_emits_no_shell_assignments():
    stdout = io.StringIO()
    with io.TextIOWrapper(io.BytesIO(b'{"FNM_DIR":"\xff"}'), encoding="utf-8") as stdin:
        assert fnm_env.emit_assignments(stdin, stdout) == 1

    assert stdout.getvalue() == ""


@pytest.mark.parametrize(
    "error",
    [
        OSError("process tool unavailable"),
        subprocess.CalledProcessError(1, ["ps"]),
        subprocess.TimeoutExpired(["ps"], 1),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid output"),
    ],
)
def test_hud_process_read_failures_keep_optional_metadata_unknown(monkeypatch, error):
    def fail(*args, **kwargs):
        del args, kwargs
        raise error

    original_exists = hud.Path.exists
    proc_path = hud.Path("/proc") / "123" / "cwd"
    monkeypatch.setattr(
        hud.Path,
        "exists",
        lambda path: False if path == proc_path else original_exists(path),
    )
    monkeypatch.setattr(hud.subprocess, "check_output", fail)
    monkeypatch.setattr(hud.shutil, "which", lambda command: "/owned/lsof")

    assert hud._pid_command(123) == ""
    assert hud._read_process_rows() == []
    assert hud._pid_cwd(123) is None


@pytest.mark.parametrize(
    "exception", ["RuntimeError", "KeyboardInterrupt", "GeneratorExit"]
)
def test_coverage_child_emulation_retains_failed_process_status(tmp_path, exception):
    script = tmp_path / "child.py"
    script.write_text(f"raise {exception}('owned child failure')\n")

    code, stdout, stderr = coverage_gate._run_python_script_in_process(
        [sys.executable, script], env=None, cwd=tmp_path, text_mode=True
    )

    assert code == 1
    assert stdout == ""
    assert f"{exception}: owned child failure" in stderr


def test_z_is_a_timezone_marker_not_an_accepted_date_time_separator():
    malformed = "2026-11-01Z04:00:00"

    # Native ISO parsing accepts any one-character separator, including Z.
    assert datetime.fromisoformat(malformed).hour == 4
    assert hud._parse_timestamp({"timestamp": malformed}) is None
    assert limits._parse_ts(malformed) is None
    assert notify_telegram._parse_ts(malformed) is None
    assert team_dispatch._parse_time(malformed) is None
    assert metrics._parse_timestamp({"timestamp": malformed}) is None
    assert hud._human_time(malformed) == malformed
    with pytest.raises(ValueError, match="ISO timestamp"):
        hud._parse_since(malformed, datetime(2026, 11, 1, tzinfo=UTC))


@pytest.mark.parametrize(
    "command", [taskmaster.cmd_status_summary, taskmaster.cmd_scope_summary]
)
def test_duplicate_later_parent_ids_cannot_hide_behind_a_valid_first_choice(
    tmp_path, command
):
    path = tmp_path / "tasks.json"
    path.write_text(
        json.dumps(
            {
                "master": {
                    "tasks": [
                        {"id": 1, "status": "pending", "title": "first"},
                        {"id": 2, "status": "pending", "title": "second"},
                        {"id": 2, "status": "pending", "title": "ambiguous duplicate"},
                    ]
                }
            }
        )
    )

    with pytest.raises(TypeError):
        command(str(path))


def test_duplicate_later_subtask_ids_cannot_hide_behind_a_valid_first_choice(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(
        json.dumps(
            {
                "master": {
                    "tasks": [
                        {
                            "id": 1,
                            "status": "pending",
                            "subtasks": [
                                {"id": 1, "status": "pending", "title": "first"},
                                {"id": 2, "status": "pending", "title": "second"},
                                {
                                    "id": 2,
                                    "status": "pending",
                                    "title": "ambiguous duplicate",
                                },
                            ],
                        }
                    ]
                }
            }
        )
    )

    with pytest.raises(TypeError):
        taskmaster.cmd_scope_summary(str(path))
