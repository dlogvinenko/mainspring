# SPDX-License-Identifier: Apache-2.0
"""Tests for runtime_state.py — Mainspring runtime state operations."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import runtime_state  # noqa: E402

SCRIPT = str(HERE.parent / "runtime_state.py")


# ── team-status ────────────────────────────────────────────────────────


def test_team_status_valid() -> None:
    payload = {
        "status": "running",
        "phase": "active",
        "workers": {"total": 3, "dead": 0},
        "tasks": {"pending": 1, "in_progress": 2, "completed": 5, "failed": 0},
    }
    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_team_status("my-team", json.dumps(payload))
    out = buf.getvalue()
    assert "my-team: status=running" in out
    assert "dead=0" in out


def test_team_status_invalid_json() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_team_status("bad-team", "not json")
    assert "bad-team: status unreadable" in buf.getvalue()


def test_pid_and_runtime_pid_helpers_cover_edge_shapes(tmp_path: Path) -> None:
    state_dir = tmp_path / ".mainspring" / "state"
    state_dir.mkdir(parents=True)
    lock_file = state_dir / "mainspring.lock"
    lock_file.write_text("0", encoding="utf-8")

    assert not runtime_state._pid_alive(None)
    assert not runtime_state._pid_alive("not-a-pid")
    assert not runtime_state._pid_alive(0)
    assert runtime_state._pid_alive(os.getpid())
    assert runtime_state._runtime_pid_files(state_dir) == [lock_file]


# ── runtime-summary ───────────────────────────────────────────────────


def test_runtime_summary_missing_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()
    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_runtime_summary(str(state_dir))
    out = buf.getvalue()
    assert "session:" in out
    assert "skill-active: missing" in out
    assert "warnings: none" in out


def test_runtime_summary_with_session(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()
    (state_dir / "session.json").write_text(
        json.dumps({"session_id": "s-1", "pid": 99999, "cwd": "/tmp"})
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_runtime_summary(str(state_dir))
    assert "id=s-1" in buf.getvalue()


def test_runtime_summary_checks_post_p7_lock_file(tmp_path: Path) -> None:
    state_dir = tmp_path / ".mainspring/state"
    state_dir.mkdir(parents=True)
    (state_dir / "team").mkdir()
    (state_dir / "mainspring.lock").write_text("99999", encoding="utf-8")

    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_runtime_summary(str(state_dir))

    assert "stale pid file: mainspring.lock -> 99999" in buf.getvalue()


def test_runtime_summary_reports_completed_mode_mismatch(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()
    mode_path = state_dir / "ultrawork-state.json"
    (state_dir / "session.json").write_text(
        json.dumps({"session_id": "s-1", "pid": 99999, "cwd": "/tmp"})
    )
    (state_dir / "skill-active-state.json").write_text(
        json.dumps(
            {
                "active": True,
                "skill": "ultrawork",
                "phase": "running",
                "initialized_state_path": str(mode_path),
            }
        )
    )
    mode_path.write_text(json.dumps({"active": False, "current_phase": "completed"}))

    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_runtime_summary(str(state_dir))

    out = buf.getvalue()
    assert "skill-active: active=True skill=ultrawork phase=running" in out
    assert "mode-state:" in out
    assert "stale skill-active state" in out


def test_runtime_summary_reports_dead_active_session_without_team_state(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()
    (state_dir / "session.json").write_text(
        json.dumps({"session_id": "s-1", "pid": 99999, "cwd": "/tmp"})
    )
    (state_dir / "skill-active-state.json").write_text(
        json.dumps({"active": True, "skill": "ralph", "phase": "running"})
    )
    (state_dir / "ralph-state.json").write_text(
        json.dumps({"active": True, "phase": "working"})
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_runtime_summary(str(state_dir))

    assert "stale active mode state" in buf.getvalue()


def test_runtime_summary_resolves_relative_initialized_mode_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()
    (state_dir / "session.json").write_text(
        json.dumps({"session_id": "s-1", "pid": os.getpid(), "cwd": str(tmp_path)})
    )
    (state_dir / "skill-active-state.json").write_text(
        json.dumps(
            {
                "active": True,
                "skill": "ultrawork",
                "phase": "planning",
                "initialized_state_path": "state/custom-mode.json",
            }
        )
    )
    (state_dir / "custom-mode.json").write_text(
        json.dumps({"active": True, "current_phase": "planning"})
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_runtime_summary(str(state_dir))

    output = buf.getvalue()
    assert (
        "mode-state: path=state/custom-mode.json active=True phase=planning" in output
    )
    assert "warnings: none" in output


def test_runtime_summary_reports_missing_mode_and_unreadable_pid_file(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / ".mainspring" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "team").mkdir()
    (state_dir / "session.json").write_text(
        json.dumps({"session_id": "s-1", "pid": os.getpid(), "cwd": str(tmp_path)})
    )
    (state_dir / "skill-active-state.json").write_text(
        json.dumps({"active": True, "skill": "missing-mode", "phase": "running"})
    )
    (state_dir / "mainspring.lock").write_text("not-a-pid", encoding="utf-8")

    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_runtime_summary(str(state_dir))

    output = buf.getvalue()
    assert "mode-state: path=" in output
    assert "missing-mode-state.json missing/unreadable" in output
    assert "stale pid file candidate: mainspring.lock unreadable" in output


# ── repair ─────────────────────────────────────────────────────────────


def test_repair_no_skill_file(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()
    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_repair(str(state_dir))
    assert "nothing to repair" in buf.getvalue()


def test_repair_missing_mode_state_refuses_without_force(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "skill-active-state.json").write_text(
        json.dumps({"active": True, "skill": "missing"})
    )

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit) as exc:
        runtime_state.cmd_repair(str(state_dir))

    assert exc.value.code == 0
    assert "Mode state is missing/unreadable" in buf.getvalue()


def test_repair_missing_mode_state_with_force_exits_one(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "skill-active-state.json").write_text(
        json.dumps({"active": True, "skill": "missing"})
    )

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit) as exc:
        runtime_state.cmd_repair(str(state_dir), force=True)

    assert exc.value.code == 1
    assert "Mode state is missing/unreadable" in buf.getvalue()


def test_repair_dry_run_stale(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()
    (state_dir / "session.json").write_text(json.dumps({"pid": 1, "session_id": "s-1"}))
    (state_dir / "skill-active-state.json").write_text(
        json.dumps({"active": True, "skill": "test", "phase": "running"})
    )
    (state_dir / "test-state.json").write_text(
        json.dumps({"active": False, "phase": "completed"})
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_repair(str(state_dir), dry_run=True)
    out = buf.getvalue()
    assert "DRY_RUN" in out
    # Verify file was NOT modified
    skill = json.loads((state_dir / "skill-active-state.json").read_text())
    assert skill["active"] is True


def test_repair_dry_run_dead_session_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()
    (state_dir / "session.json").write_text(
        json.dumps({"pid": 99999, "session_id": "s-1"})
    )
    (state_dir / "skill-active-state.json").write_text(
        json.dumps({"active": True, "skill": "test", "phase": "running"})
    )
    (state_dir / "test-state.json").write_text(
        json.dumps({"active": True, "phase": "running"})
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_repair(str(state_dir), dry_run=True)

    assert "active mode state has no live session pid" in buf.getvalue()
    assert "DRY_RUN: would mark skill-active" in buf.getvalue()


def test_repair_dry_run_stale_pid_files(tmp_path: Path) -> None:
    state_dir = tmp_path / ".mainspring/state"
    state_dir.mkdir(parents=True)
    (state_dir / "team").mkdir()
    (state_dir / "skill-active-state.json").write_text(
        json.dumps({"active": False, "skill": "test"})
    )
    (state_dir / "test-state.json").write_text(json.dumps({"active": False}))
    (state_dir / "mainspring.lock").write_text("not-a-pid", encoding="utf-8")

    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_repair(str(state_dir), dry_run=True)

    out = buf.getvalue()
    assert "stale Mainspring pid files" in out
    assert "unreadable" in out
    assert "DRY_RUN: would remove stale Mainspring pid files." in out


def test_repair_requires_force_before_mutating_stale_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()
    (state_dir / "session.json").write_text(json.dumps({"pid": 1, "session_id": "s-1"}))
    (state_dir / "skill-active-state.json").write_text(
        json.dumps({"active": True, "skill": "test", "phase": "running"})
    )
    (state_dir / "test-state.json").write_text(
        json.dumps({"active": False, "phase": "completed"})
    )

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit) as exc:
        runtime_state.cmd_repair(str(state_dir))

    assert exc.value.code == 2
    assert "Refusing repair without --force" in buf.getvalue()
    skill = json.loads((state_dir / "skill-active-state.json").read_text())
    mode = json.loads((state_dir / "test-state.json").read_text())
    assert skill["active"] is True
    assert mode["active"] is False


def test_repair_force_mutates_stale_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()
    (state_dir / "session.json").write_text(json.dumps({"pid": 1, "session_id": "s-1"}))
    (state_dir / "skill-active-state.json").write_text(
        json.dumps({"active": True, "skill": "test", "phase": "running"})
    )
    (state_dir / "test-state.json").write_text(
        json.dumps({"active": False, "phase": "completed"})
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_repair(str(state_dir), force=True)

    assert "Repaired skill-active-state.json and mode state." in buf.getvalue()
    skill = json.loads((state_dir / "skill-active-state.json").read_text())
    mode = json.loads((state_dir / "test-state.json").read_text())
    assert skill["active"] is False
    assert skill["phase"] == "completed"
    assert mode["active"] is False
    assert mode["current_phase"] == "completed"


def test_repair_force_mutates_active_skills_and_relative_mode_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()
    (state_dir / "session.json").write_text(
        json.dumps({"pid": 99999, "session_id": "s-1"})
    )
    (state_dir / "skill-active-state.json").write_text(
        json.dumps(
            {
                "active": True,
                "skill": "test",
                "phase": "running",
                "initialized_state_path": "state/custom-state.json",
                "active_skills": [
                    {"name": "test", "active": True, "phase": "running"},
                    "legacy-shape",
                ],
            }
        )
    )
    mode_path = state_dir / "custom-state.json"
    mode_path.write_text(json.dumps({"active": True, "phase": "running"}))

    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_repair(str(state_dir), force=True)

    skill = json.loads((state_dir / "skill-active-state.json").read_text())
    mode = json.loads(mode_path.read_text())
    assert skill["active"] is False
    assert skill["active_skills"][0]["active"] is False
    assert skill["active_skills"][0]["completed_at"]
    assert skill["active_skills"][1] == "legacy-shape"
    assert mode["current_phase"] == "completed"


def test_repair_rejects_mode_path_outside_state_dir_even_with_force(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()
    outside = tmp_path / "outside-state.json"
    outside.write_text(json.dumps({"active": True, "phase": "running"}))
    (state_dir / "skill-active-state.json").write_text(
        json.dumps(
            {
                "active": True,
                "skill": "test",
                "phase": "running",
                "initialized_state_path": "../outside-state.json",
            }
        )
    )

    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit) as exc:
        runtime_state.cmd_repair(str(state_dir), force=True)

    assert exc.value.code == 2
    assert "outside runtime state dir" in buf.getvalue()
    assert json.loads(outside.read_text()) == {"active": True, "phase": "running"}


def test_repair_force_removes_stale_pid_file(tmp_path: Path) -> None:
    state_dir = tmp_path / ".mainspring/state"
    state_dir.mkdir(parents=True)
    (state_dir / "team").mkdir()
    lock_file = state_dir / "mainspring.lock"
    lock_file.write_text("99999", encoding="utf-8")
    (state_dir / "skill-active-state.json").write_text(
        json.dumps({"active": False, "skill": "test"})
    )
    (state_dir / "test-state.json").write_text(json.dumps({"active": False}))

    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_repair(str(state_dir), force=True)

    assert "Removed stale pid file" in buf.getvalue()
    assert not lock_file.exists()


def test_repair_reports_unlink_failure_for_stale_pid_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / ".mainspring" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "team").mkdir()
    lock_file = state_dir / "mainspring.lock"
    lock_file.write_text("99999", encoding="utf-8")
    (state_dir / "skill-active-state.json").write_text(
        json.dumps({"active": False, "skill": "test"})
    )
    (state_dir / "test-state.json").write_text(json.dumps({"active": False}))

    original_unlink = Path.unlink

    def fail_unlink(self: Path) -> None:
        if self == lock_file:
            raise OSError("denied")
        original_unlink(self)

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    buf = io.StringIO()

    with redirect_stdout(buf):
        runtime_state.cmd_repair(str(state_dir), force=True)

    assert "Could not remove stale pid file" in buf.getvalue()
    assert "denied" in buf.getvalue()


# ── cleanup-stale ─────────────────────────────────────────────────────


def test_cleanup_stale_requires_force_before_process_cleanup() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_cleanup_stale(12345, 60)

    assert "Refusing stale process cleanup without --force" in buf.getvalue()


def test_cleanup_stale_force_stops_only_old_matching_processes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ps_output = "\n".join(
        [
            "111 00:10:00 /bin/bash ./mainspring.sh --last-run",
            f"{os.getpid()} 2-00:00:00 /bin/bash ./mainspring.sh --last-run",
            "222 00:01:00 /bin/bash ./mainspring.sh --last-run",
            "333 00:20:00 python unrelated.py",
            "bad-row",
        ]
    )
    killed: list[int] = []

    def fake_check_output(args: list[str], *, text: bool) -> str:
        assert args == ["ps", "-axo", "pid=,etime=,command="]
        assert text is True
        return ps_output

    def fake_kill(pid: int, sig: int) -> None:
        assert sig == runtime_state.signal.SIGTERM
        killed.append(pid)

    monkeypatch.setattr(runtime_state.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(runtime_state.os, "kill", fake_kill)

    runtime_state.cmd_cleanup_stale(os.getpid(), 5, force=True)

    assert killed == [111]
    out = capsys.readouterr().out
    assert "Stopped stale process 111" in out
    assert "Stopped stale process 444" not in out


def test_cleanup_stale_reports_process_listing_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_check_output(args: list[str], *, text: bool) -> str:
        raise subprocess.CalledProcessError(1, args, output="no ps")

    monkeypatch.setattr(runtime_state.subprocess, "check_output", fail_check_output)

    runtime_state.cmd_cleanup_stale(os.getpid(), 5, force=True)

    assert capsys.readouterr().out == ""


# ── stop-processes ─────────────────────────────────────────────────────


def test_stop_processes_requires_force(capsys: pytest.CaptureFixture[str]) -> None:
    runtime_state.cmd_stop_processes("state", os.getpid())

    assert "Refusing to stop processes without --force" in capsys.readouterr().out


def test_stop_processes_cli_rejects_unknown_flags_before_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def fail_if_called(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(runtime_state, "cmd_stop_processes", fail_if_called)

    with pytest.raises(SystemExit) as exc:
        runtime_state.main(
            [
                "stop-processes",
                str(tmp_path / "state"),
                str(os.getpid()),
                "--force",
                "--all",
                "--dry-run",
            ]
        )

    assert exc.value.code == 2
    assert called is False
    err = capsys.readouterr().err
    assert "Unknown option: --dry-run" in err
    assert "Usage: runtime_state.py stop-processes" in err


def test_stop_processes_stops_recorded_project_pids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "mainspring.lock").write_text("111", encoding="utf-8")
    (state_dir / "notifier.pid").write_text("222", encoding="utf-8")
    killed: list[int] = []

    monkeypatch.setattr(runtime_state, "_pid_alive", lambda pid: pid in {111, 222})
    monkeypatch.setattr(
        runtime_state,
        "_pid_command",
        lambda pid: {
            111: "/bin/bash ./mainspring.sh taskmaster",
            222: (
                "python /repo/mainspring/py/notify_telegram.py watch "
                f"{state_dir.parent}/logs/waves.jsonl --state-dir {state_dir}"
            ),
        }.get(pid, ""),
    )
    monkeypatch.setattr(
        runtime_state.os,
        "kill",
        lambda pid, sig: killed.append(pid),
    )

    runtime_state.cmd_stop_processes(str(state_dir), os.getpid(), force=True)

    assert killed == [111, 222]
    out = capsys.readouterr().out
    assert "Stopped" in out


def test_stop_processes_stops_recorded_team_backends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "state"
    team_dir = state_dir / "team" / "demo"
    team_dir.mkdir(parents=True)
    (team_dir / "config.json").write_text(json.dumps({"name": "demo"}))
    calls: list[list[str]] = []

    def fake_run(
        args: list[str],
        *,
        check: bool,
        stdout: object,
        stderr: object,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(runtime_state.subprocess, "run", fake_run)

    runtime_state.cmd_stop_processes(str(state_dir), os.getpid(), force=True)

    assert calls == [["omx", "team", "shutdown", "demo", "--force"]]
    out = capsys.readouterr().out
    assert "Stopped team backend demo" in out


def test_stop_processes_refuses_foreign_recorded_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "mainspring.lock").write_text("111", encoding="utf-8")
    killed: list[int] = []

    monkeypatch.setattr(runtime_state, "_pid_alive", lambda pid: pid == 111)
    monkeypatch.setattr(
        runtime_state, "_pid_command", lambda pid: "python unrelated.py"
    )
    monkeypatch.setattr(runtime_state.os, "kill", lambda pid, sig: killed.append(pid))

    runtime_state.cmd_stop_processes(str(state_dir), os.getpid(), force=True)

    assert killed == []
    assert "Refusing to stop non-Mainspring" in capsys.readouterr().out


def test_stop_processes_refuses_foreign_notifier_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "project" / ".mainspring" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "notifier.pid").write_text("222", encoding="utf-8")
    other_runtime = tmp_path / "other" / ".mainspring"
    killed: list[int] = []

    monkeypatch.setattr(runtime_state, "_pid_alive", lambda pid: pid == 222)
    monkeypatch.setattr(
        runtime_state,
        "_pid_command",
        lambda pid: (
            "python /repo/mainspring/py/notify_telegram.py watch "
            f"{other_runtime}/logs/waves.jsonl --state-dir {other_runtime}/state"
        ),
    )
    monkeypatch.setattr(runtime_state.os, "kill", lambda pid, sig: killed.append(pid))

    runtime_state.cmd_stop_processes(str(state_dir), os.getpid(), force=True)

    assert killed == []
    out = capsys.readouterr().out
    assert "Refusing to stop notifier pid 222 outside" in out
    assert "No recorded live Mainspring process found" in out


def test_stop_processes_refuses_ambiguous_relative_notifier_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "project" / ".mainspring" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "notifier.pid").write_text("222", encoding="utf-8")
    killed: list[int] = []

    monkeypatch.setattr(runtime_state, "_pid_alive", lambda pid: pid == 222)
    monkeypatch.setattr(
        runtime_state,
        "_pid_command",
        lambda pid: (
            "python /repo/mainspring/py/notify_telegram.py watch "
            ".mainspring/logs/waves.jsonl --state-dir .mainspring/state"
        ),
    )
    monkeypatch.setattr(runtime_state.os, "kill", lambda pid, sig: killed.append(pid))

    runtime_state.cmd_stop_processes(str(state_dir), os.getpid(), force=True)

    assert killed == []
    out = capsys.readouterr().out
    assert "Refusing to stop notifier pid 222 outside" in out
    assert "No recorded live Mainspring process found" in out


def test_stop_processes_all_stops_matching_mainspring_processes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ps_output = "\n".join(
        [
            "111 /bin/bash ./mainspring.sh taskmaster",
            "222 python unrelated.py",
            "333 python /opt/mainspring/bin/mainspring hud",
            "444 vim /tmp/mainspring.sh",
            "555 python /tmp/hud.py",
            "666 /usr/bin/env python3 /repo/mainspring/py/notify_telegram.py watch .mainspring/logs/waves.jsonl",
        ]
    )
    killed: list[int] = []

    monkeypatch.setattr(
        runtime_state.subprocess,
        "check_output",
        lambda args, *, text: ps_output,
    )
    monkeypatch.setattr(
        runtime_state,
        "_pid_alive",
        lambda pid: pid in {111, 222, 333, 444, 555, 666},
    )
    monkeypatch.setattr(
        runtime_state.os,
        "kill",
        lambda pid, sig: killed.append(pid),
    )

    runtime_state.cmd_stop_processes(
        "state",
        os.getpid(),
        force=True,
        all_projects=True,
    )

    assert killed == [111, 333, 666]
    assert "Stopped mainspring pid 111" in capsys.readouterr().out


# ── find-latest-team ───────────────────────────────────────────────────


def test_find_latest_team_empty(tmp_path: Path) -> None:
    team_dir = tmp_path / "team"
    team_dir.mkdir()
    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_find_latest_team(str(team_dir))
    assert buf.getvalue().strip() == ""


def test_find_latest_team_with_config(tmp_path: Path) -> None:
    team_dir = tmp_path / "team"
    t1 = team_dir / "alpha"
    t1.mkdir(parents=True)
    (t1 / "config.json").write_text(json.dumps({"name": "alpha-team"}))
    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_find_latest_team(str(team_dir))
    assert buf.getvalue().strip() == "alpha-team"


def test_find_latest_team_skips_unreadable_json(tmp_path: Path) -> None:
    team_dir = tmp_path / "team"
    bad = team_dir / "bad"
    good = team_dir / "good"
    bad.mkdir(parents=True)
    good.mkdir()
    (bad / "config.json").write_text("{not json", encoding="utf-8")
    (good / "config.json").write_text(json.dumps({}), encoding="utf-8")

    buf = io.StringIO()
    with redirect_stdout(buf):
        runtime_state.cmd_find_latest_team(str(team_dir))

    assert buf.getvalue().strip() == "good"


# ── CLI error handling ─────────────────────────────────────────────────


def test_cli_no_args() -> None:
    result = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True)
    assert result.returncode == 2


def test_cli_unknown_subcommand() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "bogus"], capture_output=True, text=True
    )
    assert result.returncode == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["team-status"],
        ["runtime-summary"],
        ["repair"],
        ["cleanup-stale"],
        ["stop-processes"],
        ["find-latest-team"],
    ],
)
def test_cli_usage_for_missing_subcommand_args(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        runtime_state.main(argv)
    assert exc.value.code == 2
    assert "Usage: runtime_state.py" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["cleanup-stale", "not-a-pid", "5"], "current_pid must be an integer"),
        (["cleanup-stale", "123", "soon"], "ttl_minutes must be an integer"),
        (
            ["stop-processes", "/tmp/state", "not-a-pid", "--force"],
            "current_pid must be an integer",
        ),
    ],
)
def test_cli_rejects_malformed_numeric_args_without_traceback(
    argv: list[str],
    message: str,
) -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, *argv],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert message in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_dispatches_runtime_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()

    runtime_state.main(["runtime-summary", str(state_dir)])

    assert "session:" in capsys.readouterr().out


def test_cli_dispatches_repair_cleanup_and_find_latest_team(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "team").mkdir()
    (state_dir / "skill-active-state.json").write_text(
        json.dumps({"active": False, "skill": "test"})
    )
    (state_dir / "test-state.json").write_text(json.dumps({"active": False}))

    runtime_state.main(["repair", str(state_dir), "--dry-run"])
    assert "No stale" in capsys.readouterr().out

    monkeypatch.setattr(
        runtime_state.subprocess,
        "check_output",
        lambda args, *, text: "",
    )
    runtime_state.main(["cleanup-stale", str(os.getpid()), "5", "--force"])
    assert capsys.readouterr().out == ""

    runtime_state.main(["stop-processes", str(state_dir), str(os.getpid()), "--force"])
    assert "No recorded live" in capsys.readouterr().out

    team = state_dir / "team" / "beta"
    team.mkdir()
    (team / "config.json").write_text(json.dumps({"name": "beta-team"}))
    runtime_state.main(["find-latest-team", str(state_dir / "team")])
    assert capsys.readouterr().out.strip() == "beta-team"


def _attribution_synthetic_process(monkeypatch, command):
    killed = []
    monkeypatch.setattr(runtime_state, "_pid_alive", lambda pid: pid == 222)
    monkeypatch.setattr(runtime_state, "_pid_command", lambda _pid: command)
    monkeypatch.setattr(
        runtime_state.os, "kill", lambda pid, sig: killed.append((pid, sig))
    )
    monkeypatch.setattr(runtime_state, "_stop_team_backend", lambda _name: False)
    return killed


def _attribution_state(tmp_path, filename):
    state_dir = tmp_path / "project-p" / ".mainspring" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / filename).write_text("222", encoding="utf-8")
    return state_dir


def test_lock_pid_refuses_explicit_foreign_notifier_command(
    tmp_path, monkeypatch, capsys
):
    state_dir = _attribution_state(tmp_path, "mainspring.lock")
    command = (
        "python /repo/mainspring/py/notify_telegram.py watch "
        "/project-q/.mainspring/logs/waves.jsonl --state-dir /project-q/.mainspring/state"
    )
    killed = _attribution_synthetic_process(monkeypatch, command)
    runtime_state.cmd_stop_processes(str(state_dir), 999, force=True)
    assert killed == []
    assert "Refusing to stop notifier pid 222 outside" in capsys.readouterr().out


def test_relative_state_argument_refuses_unattributed_relative_notifier_command(
    tmp_path, monkeypatch, capsys
):
    state_dir = _attribution_state(tmp_path, "notifier.pid")
    monkeypatch.chdir(state_dir.parent.parent)
    command = (
        "python /repo/mainspring/py/notify_telegram.py watch "
        ".mainspring/logs/waves.jsonl --state-dir .mainspring/state"
    )
    killed = _attribution_synthetic_process(monkeypatch, command)
    runtime_state.cmd_stop_processes(".mainspring/state", 999, force=True)
    assert killed == []
    assert "Refusing to stop notifier pid 222 outside" in capsys.readouterr().out


@pytest.mark.parametrize("pid_file", ["mainspring.lock", "notifier.pid"])
def test_project_absolute_notifier_remains_stoppable_from_either_pid_file(
    tmp_path, monkeypatch, pid_file
):
    state_dir = _attribution_state(tmp_path, pid_file)
    command = (
        f"python /repo/mainspring/py/notify_telegram.py watch {state_dir.parent}/logs/waves.jsonl "
        f"--state-dir {state_dir}"
    )
    killed = _attribution_synthetic_process(monkeypatch, command)
    runtime_state.cmd_stop_processes(str(state_dir), 999, force=True)
    assert killed == [(222, runtime_state.signal.SIGTERM)]


def test_relative_caller_with_absolute_project_notifier_evidence_remains_stoppable(
    tmp_path, monkeypatch
):
    state_dir = _attribution_state(tmp_path, "notifier.pid")
    monkeypatch.chdir(state_dir.parent.parent)
    command = (
        f"python /repo/mainspring/py/notify_telegram.py watch {state_dir.parent}/logs/waves.jsonl "
        f"--state-dir {state_dir}"
    )
    killed = _attribution_synthetic_process(monkeypatch, command)
    runtime_state.cmd_stop_processes(".mainspring/state", 999, force=True)
    assert killed == [(222, runtime_state.signal.SIGTERM)]


def test_absolute_caller_still_refuses_relative_notifier_without_process_cwd(
    tmp_path, monkeypatch
):
    state_dir = _attribution_state(tmp_path, "notifier.pid")
    command = (
        "python /repo/mainspring/py/notify_telegram.py watch "
        ".mainspring/logs/waves.jsonl --state-dir .mainspring/state"
    )
    killed = _attribution_synthetic_process(monkeypatch, command)
    runtime_state.cmd_stop_processes(str(state_dir), 999, force=True)
    assert killed == []


def test_recorded_generic_mainspring_launcher_behavior_is_preserved(
    tmp_path, monkeypatch
):
    state_dir = _attribution_state(tmp_path, "mainspring.lock")
    killed = _attribution_synthetic_process(
        monkeypatch, "/bin/bash ./mainspring.sh taskmaster"
    )
    runtime_state.cmd_stop_processes(str(state_dir), 999, force=True)
    assert killed == [(222, runtime_state.signal.SIGTERM)]


def test_unknown_recorded_command_is_refused_without_claiming_foreign_identity(
    tmp_path, monkeypatch
):
    state_dir = _attribution_state(tmp_path, "mainspring.lock")
    killed = _attribution_synthetic_process(monkeypatch, "")
    runtime_state.cmd_stop_processes(str(state_dir), 999, force=True)
    assert killed == []


def test_explicit_all_projects_override_still_accepts_foreign_notifier(
    tmp_path, monkeypatch
):
    state_dir = _attribution_state(tmp_path, "mainspring.lock")
    command = (
        "python /repo/mainspring/py/notify_telegram.py watch "
        "/project-q/.mainspring/logs/waves.jsonl --state-dir /project-q/.mainspring/state"
    )
    killed = _attribution_synthetic_process(monkeypatch, command)
    monkeypatch.setattr(
        runtime_state.subprocess,
        "check_output",
        lambda *_args, **_kwargs: "222 " + command,
    )
    runtime_state.cmd_stop_processes(str(state_dir), 999, force=True, all_projects=True)
    assert killed == [(222, runtime_state.signal.SIGTERM)]


def test_notifier_attribution_never_signals_the_current_process(tmp_path, monkeypatch):
    state_dir = _attribution_state(tmp_path, "mainspring.lock")
    command = f"python /repo/mainspring/py/notify_telegram.py watch {state_dir.parent}/logs/waves.jsonl"
    killed = _attribution_synthetic_process(monkeypatch, command)
    runtime_state.cmd_stop_processes(str(state_dir), 222, force=True)
    assert killed == []


def test_lock_pid_does_not_expand_generic_command_admission(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_state, "_is_mainspring_command", lambda _command: False)
    state_dir = tmp_path / "custom-state"
    state_dir.mkdir()
    (state_dir / "mainspring.lock").write_text("222", encoding="utf-8")
    command = f"python /repo/notify_telegram.py watch /other/ledger.jsonl --state-dir {state_dir}"
    killed = _attribution_synthetic_process(monkeypatch, command)
    runtime_state.cmd_stop_processes(str(state_dir), 999, force=True)
    assert killed == []
