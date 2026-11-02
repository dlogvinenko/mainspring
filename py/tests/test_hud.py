# SPDX-License-Identifier: Apache-2.0
"""Tests for hud.py - read-only Mainspring HUD snapshot."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import hud

SCRIPT = str(HERE.parent / "hud.py")
MAINSPRING_DIR = HERE.parent.parent


@pytest.fixture(autouse=True)
def _clear_operator_notification_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "MAINSPRING_NOTIFY_ENABLED",
        "MAINSPRING_TELEGRAM_BOT_TOKEN",
        "MAINSPRING_TELEGRAM_CHAT_ID",
        "MAINSPRING_NOTIFY_STALE_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)


def _write_ledger(path: Path) -> None:
    entries = [
        {
            "timestamp": "2026-04-29T01:00:00+02:00",
            "wave_id": "old",
            "task_id": "1",
            "verdict": "PASS",
            "exit_code": 0,
            "duration_seconds": 10,
            "engines": {"writer": "claude", "reviewer": "codex"},
        },
        {
            "timestamp": "2026-04-29T04:40:00+02:00",
            "wave_id": "w1",
            "task_id": "42",
            "verdict": "FAIL",
            "exit_code": 1,
            "duration_seconds": 20,
            "engines": {"writer": "codex", "reviewer": "codex"},
            "failure_reason": "review:gate_failed",
            "quota": {"claude": {"short_remaining_pct": 42.5}},
        },
        {
            "timestamp": "2026-04-29T04:50:00+02:00",
            "wave_id": "w2",
            "task_id": "43",
            "verdict": "PASS",
            "exit_code": 0,
            "duration_seconds": 40,
            "engine": "claude",
            "review_engine": "codex",
            "codex_short_delta_pct": 91,
        },
    ]
    path.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n",
        encoding="utf-8",
    )


def _write_taskmaster(
    project: Path, *, tag: str = "release", statuses: list[str] | None = None
) -> None:
    statuses = statuses or ["done", "pending"]
    task_root = project / ".taskmaster"
    task_root.mkdir(parents=True, exist_ok=True)
    (task_root / "tasks").mkdir(parents=True, exist_ok=True)
    (task_root / "state.json").write_text(
        json.dumps({"currentTag": tag}),
        encoding="utf-8",
    )
    (task_root / "tasks" / "tasks.json").write_text(
        json.dumps(
            {
                tag: {
                    "tasks": [
                        {"id": str(index + 1), "status": status, "subtasks": []}
                        for index, status in enumerate(statuses)
                    ]
                }
            }
        ),
        encoding="utf-8",
    )


def _assert_stale_recovery_guidance(snapshot: dict, text: str) -> None:
    message = snapshot["notifications"]["next_step_message"]

    assert "mainspring notify-restart" in message
    assert "mainspring notify-test" in message
    assert "next enabled wave" not in message
    assert "Notifications next: Run mainspring notify-restart" in text


def test_build_snapshot_summarizes_recent_waves_quota_and_team(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    team_dir = state_dir / "team" / "alpha"
    team_dir.mkdir(parents=True)
    (team_dir / "config.json").write_text(
        json.dumps({"status": "running", "team_size": 3}),
        encoding="utf-8",
    )
    (team_dir / "dispatch-ledger.json").write_text(
        json.dumps({"42": {"status": "pending"}}),
        encoding="utf-8",
    )
    _write_ledger(ledger)
    (ledger.parent / "latest.log").write_text(
        "\nolder runtime line\nlatest runtime line\n",
        encoding="utf-8",
    )

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        since="1h",
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    assert snapshot["entry_count"] == 2
    assert snapshot["ledger_state"]["status"] == "ok"
    assert snapshot["ledger_state"]["entries"] == 2
    assert snapshot["ledger_state"]["valid_entries"] == 3
    assert snapshot["current_wave"]["wave_id"] == "w2"
    assert snapshot["current_wave"]["last_log_line"] == "latest runtime line"
    assert snapshot["recent_waves"][0]["wave_id"] == "w2"
    assert snapshot["today"]["total_waves"] == 2
    assert snapshot["today"]["success_rate"] == 50.0
    assert snapshot["quota"]["codex"]["short_used_pct"] == 91.0
    assert snapshot["quota"]["claude"]["short_remaining_pct"] == 42.5
    assert snapshot["quota"]["gemini"]["source"] == "missing"
    assert snapshot["active_teams"] == [
        {
            "name": "alpha",
            "status": "running",
            "workers": 3,
            "pending_dispatches": 1,
        }
    ]
    assert snapshot["notifications"]["status"] == "disabled"
    assert snapshot["notifications"]["enabled"] is False
    assert snapshot["notifications"]["next_step"] == "enable-notifications"


def test_build_snapshot_sorts_recent_waves_by_stopped_time(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    entries = [
        {
            "timestamp": "2026-04-29T04:50:00+02:00",
            "wave_id": "newer",
            "duration_seconds": 30,
            "verdict": "PASS",
        },
        {
            "timestamp": "2026-04-29T04:40:00+02:00",
            "wave_id": "older",
            "duration_seconds": 120,
            "verdict": "FAIL",
        },
    ]
    ledger.write_text(
        "\n".join(json.dumps(entry) for entry in reversed(entries)) + "\n",
        encoding="utf-8",
    )

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    assert snapshot["current_wave"]["wave_id"] == "newer"
    assert [wave["wave_id"] for wave in snapshot["recent_waves"]] == [
        "newer",
        "older",
    ]
    assert snapshot["current_wave"]["started_at"] == "2026-04-29T04:49:30+02:00"
    assert snapshot["current_wave"]["stopped_at"] == "2026-04-29T04:50:00+02:00"


def test_today_entries_use_snapshot_timezone_not_runner_timezone() -> None:
    entries = [
        {
            "timestamp": "2026-01-02T00:30:00+14:00",
            "wave_id": "same-day-in-snapshot-zone",
        },
        {
            "timestamp": "2026-01-01T23:30:00+14:00",
            "wave_id": "previous-day-in-snapshot-zone",
        },
    ]

    today = hud._today_entries(
        entries,
        datetime.fromisoformat("2026-01-02T01:00:00+14:00"),
    )

    assert [entry["wave_id"] for entry in today] == ["same-day-in-snapshot-zone"]


def test_build_snapshot_includes_live_runtime_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hud,
        "_pid_command",
        lambda pid: (
            "/bin/bash ./mainspring.sh --last-run" if pid == os.getpid() else ""
        ),
    )
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)
    (state_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": "session-1",
                "started_at": "2026-04-29T04:55:00+02:00",
                "cwd": "/repo",
                "pid": os.getpid(),
            }
        ),
        encoding="utf-8",
    )
    (state_dir.parent / "last-run.env").write_text(
        (
            "MODE=night\n"
            "TOPOLOGY=solo\n"
            "PAIR_MODE=codex+codex\n"
            "SPEED_PROFILE=max\n"
            "MAX_AGENTS=6\n"
            "PRD_PATH=docs/prd.md"
        ),
        encoding="utf-8",
    )

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot, width=240)

    assert snapshot["runtime"]["session_id"] == "session-1"
    assert snapshot["runtime"]["elapsed_seconds"] == 300
    assert snapshot["runtime"]["pid_alive"] is True
    assert snapshot["runtime"]["mode"] == "night"
    assert snapshot["runtime"]["topology"] == "solo"
    assert snapshot["runtime"]["pair"] == "codex+codex"
    assert snapshot["runtime"]["speed_profile"] == "max"
    assert snapshot["runtime"]["max_agents"] == "6"
    assert snapshot["runtime"]["prd_path"] == "docs/prd.md"
    assert snapshot["project"]["name"] == "repo"
    assert snapshot["project"]["root"] == "/repo"
    assert (
        "Runtime: live night/solo pair=codex+codex speed=max agents=6 elapsed=300s"
    ) in text


def test_build_snapshot_rejects_foreign_live_session_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "mainspring"
    runtime = project / ".mainspring"
    state_dir = runtime / "state"
    ledger = runtime / "logs" / "waves.jsonl"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    _write_ledger(ledger)
    (state_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": "codex-app-session",
                "started_at": "2026-04-29T04:55:00+02:00",
                "cwd": str(project),
                "pid": 12345,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(hud, "_pid_is_running", lambda pid: pid == 12345)
    monkeypatch.setattr(
        hud,
        "_pid_command",
        lambda pid: (
            "/Applications/Codex.app/Contents/Resources/codex app-server"
            if pid == 12345
            else ""
        ),
    )

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    assert snapshot["runtime"]["pid"] is None
    assert snapshot["runtime"]["pid_alive"] is False
    assert snapshot["runtime"]["pid_source"] == ""
    assert snapshot["runtime"]["rejected_session_pid"] == 12345
    assert "codex app-server" in snapshot["runtime"]["rejected_session_pid_command"]


def test_global_snapshot_hides_foreign_session_pid_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "mainspring"
    runtime = project / ".mainspring"
    state_dir = runtime / "state"
    ledger = runtime / "logs" / "waves.jsonl"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    _write_ledger(ledger)
    (state_dir / "last-run.env").write_text(
        "MODE=taskmaster\nTOPOLOGY=team\nPAIR_MODE=codex+codex\n",
        encoding="utf-8",
    )
    (state_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": "codex-app-session",
                "started_at": "2026-04-29T04:55:00+02:00",
                "cwd": str(project),
                "pid": 12345,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(hud, "_pid_is_running", lambda pid: pid == 12345)
    monkeypatch.setattr(
        hud,
        "_pid_command",
        lambda pid: (
            "/Applications/Codex.app/Contents/Resources/codex app-server"
            if pid == 12345
            else ""
        ),
    )

    active_only = hud.build_global_snapshot(
        ledger,
        state_dir,
        search_roots=[tmp_path],
        process_rows=[],
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    all_runtimes = hud.build_global_snapshot(
        ledger,
        state_dir,
        search_roots=[tmp_path],
        process_rows=[],
        include_stale=True,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    assert active_only["run_count"] == 0
    assert all_runtimes["run_count"] == 1
    assert all_runtimes["runs"][0]["operator_state"] == "STALE"
    assert all_runtimes["runs"][0]["pid"] is None


def test_build_snapshot_infers_project_from_runtime_state_dir(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    runtime_dir = project_root / ".mainspring"
    state_dir = runtime_dir / "state"
    ledger = runtime_dir / "logs" / "waves.jsonl"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    _write_ledger(ledger)

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot, width=200)

    assert snapshot["project"]["name"] == "project"
    assert snapshot["project"]["root"] == str(project_root)
    assert f"Folder: {project_root}" in text


def test_build_snapshot_prefers_watched_runtime_root_over_stale_session_cwd(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    runtime_dir = project_root / ".mainspring"
    state_dir = runtime_dir / "state"
    ledger = runtime_dir / "logs" / "waves.jsonl"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    _write_ledger(ledger)
    (state_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": "old-session",
                "started_at": "2026-04-29T04:55:00+02:00",
                "cwd": "/workspace/stale/old-project",
                "pid": 999999999,
            }
        ),
        encoding="utf-8",
    )

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot, width=220)

    assert snapshot["project"]["name"] == "project"
    assert snapshot["project"]["root"] == str(project_root)
    assert "old-project" not in text


def test_build_snapshot_includes_taskmaster_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MAINSPRING_TASKMASTER_TAG", raising=False)
    project_root = tmp_path / "progress-app"
    runtime_dir = project_root / ".mainspring"
    state_dir = runtime_dir / "state"
    ledger = runtime_dir / "logs" / "waves.jsonl"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    _write_ledger(ledger)
    task_root = project_root / ".taskmaster"
    (task_root / "tasks").mkdir(parents=True)
    (task_root / "state.json").write_text(
        json.dumps({"currentTag": "release"}),
        encoding="utf-8",
    )
    (task_root / "tasks" / "tasks.json").write_text(
        json.dumps(
            {
                "release": {
                    "tasks": [
                        {"id": "1", "status": "done", "subtasks": []},
                        {
                            "id": "2",
                            "status": "pending",
                            "subtasks": [
                                {"id": "2.1", "status": "done"},
                                {"id": "2.2", "status": "in-progress"},
                                {"id": "2.3", "status": "blocked"},
                            ],
                        },
                        {"id": "3", "status": "cancelled", "subtasks": []},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot, width=240)

    assert snapshot["progress"]["source"] == "taskmaster"
    assert snapshot["progress"]["tag"] == "release"
    assert snapshot["progress"]["done"] == 2
    assert snapshot["progress"]["total"] == 4
    assert snapshot["progress"]["percent"] == 50
    assert "Progress: 50% (2/4) source=taskmaster tag=release" in text


def test_build_snapshot_falls_back_to_prd_checkbox_progress(tmp_path: Path) -> None:
    project_root = tmp_path / "prd-app"
    runtime_dir = project_root / ".mainspring"
    state_dir = runtime_dir / "state"
    ledger = runtime_dir / "logs" / "waves.jsonl"
    docs = project_root / "docs"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    docs.mkdir(parents=True)
    _write_ledger(ledger)
    (docs / "prd.md").write_text(
        ("# Product Requirements Document (PRD)\n- [x] Shipped\n- [ ] Remaining"),
        encoding="utf-8",
    )

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot, width=240)

    assert snapshot["progress"]["source"] == "prd_checkboxes"
    assert snapshot["progress"]["done"] == 1
    assert snapshot["progress"]["total"] == 2
    assert snapshot["progress"]["percent"] == 50
    assert "Progress: 50% (1/2) source=prd_checkboxes" in text


def test_build_snapshot_uses_live_lock_mtime_as_runtime_start(tmp_path: Path) -> None:
    project_root = tmp_path / "locked-project"
    runtime_dir = project_root / ".mainspring"
    state_dir = runtime_dir / "state"
    ledger = runtime_dir / "logs" / "waves.jsonl"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    _write_ledger(ledger)
    lock = state_dir / "mainspring.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    started = datetime.fromisoformat("2026-04-29T04:55:00+02:00").timestamp()
    os.utime(lock, (started, started))

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    assert snapshot["runtime"]["pid_alive"] is True
    assert snapshot["runtime"]["started_at"] == "2026-04-29T04:55:00+02:00"
    assert snapshot["runtime"]["elapsed_seconds"] == 300


def test_build_snapshot_prefers_live_lock_mtime_over_stale_session_start(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "locked-project"
    runtime_dir = project_root / ".mainspring"
    state_dir = runtime_dir / "state"
    ledger = runtime_dir / "logs" / "waves.jsonl"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    _write_ledger(ledger)
    (state_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": "old-codex-app-session",
                "started_at": "2026-04-25T08:29:50+02:00",
                "cwd": "/workspace/stale/old-project",
                "pid": 999999999,
            }
        ),
        encoding="utf-8",
    )
    lock = state_dir / "mainspring.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    started = datetime.fromisoformat("2026-04-29T04:58:00+02:00").timestamp()
    os.utime(lock, (started, started))

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    assert snapshot["runtime"]["pid_alive"] is True
    assert snapshot["runtime"]["pid_source"] == "lock"
    assert snapshot["runtime"]["started_at"] == "2026-04-29T04:58:00+02:00"
    assert snapshot["runtime"]["elapsed_seconds"] == 120


def test_build_global_snapshot_discovers_runtimes_and_sorts_live_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MAINSPRING_TASKMASTER_TAG", raising=False)
    project_live = tmp_path / "client-app"
    project_stale = tmp_path / "api-app"
    live_runtime = project_live / ".mainspring"
    stale_runtime = project_stale / ".mainspring"
    for runtime in (live_runtime, stale_runtime):
        (runtime / "state").mkdir(parents=True)
        (runtime / "logs").mkdir(parents=True)
        _write_ledger(runtime / "logs" / "waves.jsonl")
        (runtime / "state" / "last-run.env").write_text(
            "PAIR_MODE=codex+codex\nMODE=taskmaster\nTOPOLOGY=team\n",
            encoding="utf-8",
        )
    (live_runtime / "state" / "mainspring.lock").write_text(
        str(os.getpid()),
        encoding="utf-8",
    )
    (stale_runtime / "state" / "mainspring.lock").write_text(
        "999999999",
        encoding="utf-8",
    )
    (project_live / ".taskmaster").mkdir()
    (project_live / ".taskmaster" / "state.json").write_text(
        json.dumps({"currentTag": "release"}),
        encoding="utf-8",
    )

    snapshot = hud.build_global_snapshot(
        live_runtime / "logs" / "waves.jsonl",
        live_runtime / "state",
        search_roots=[tmp_path],
        process_rows=[],
        include_stale=True,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    assert snapshot["scope"] == "global"
    assert snapshot["run_count"] == 2
    assert snapshot["live_count"] == 1
    assert snapshot["runs"][0]["project"] == "client-app"
    assert snapshot["runs"][0]["status"] == "live"
    assert snapshot["runs"][0]["operator_state"] == "OK"
    assert snapshot["runs"][0]["taskmaster_tag"] == "release"
    assert {run["folder"] for run in snapshot["runs"]} == {
        str(project_live),
        str(project_stale),
    }

    active_only = hud.build_global_snapshot(
        live_runtime / "logs" / "waves.jsonl",
        live_runtime / "state",
        search_roots=[tmp_path],
        process_rows=[],
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    assert active_only["run_count"] == 1
    assert active_only["runs"][0]["project"] == "client-app"


def test_global_discovery_uses_process_project_and_cwd(tmp_path: Path) -> None:
    project_from_flag = tmp_path / "flag-project"
    project_from_shell = tmp_path / "shell-project"
    project_from_cwd = tmp_path / "cwd-project"
    for project in (project_from_flag, project_from_shell, project_from_cwd):
        runtime = project / ".mainspring"
        (runtime / "state").mkdir(parents=True)
        (runtime / "logs").mkdir(parents=True)
        _write_ledger(runtime / "logs" / "waves.jsonl")

    refs = hud.discover_runtime_refs(
        project_from_flag / ".mainspring" / "logs" / "waves.jsonl",
        project_from_flag / ".mainspring" / "state",
        search_roots=[],
        process_rows=[
            f"111 /bin/bash mainspring.sh --project {project_from_flag} taskmaster",
            "222 /opt/bin/mainspring taskmaster",
            (
                "333 /bin/bash -lc "
                f"'./mainspring.sh --project {project_from_shell} taskmaster --once'"
            ),
        ],
        cwd_resolver=lambda pid: project_from_cwd if pid == 222 else tmp_path,
    )

    assert {str(Path(ref["runtime_dir"])) for ref in refs} == {
        str(project_from_flag / ".mainspring"),
        str(project_from_shell / ".mainspring"),
        str(project_from_cwd / ".mainspring"),
    }


def test_global_snapshot_marks_repeated_failures_as_needing_action(
    tmp_path: Path,
) -> None:
    project = tmp_path / "stuck-app"
    runtime = project / ".mainspring"
    (runtime / "state").mkdir(parents=True)
    (runtime / "logs").mkdir(parents=True)
    (runtime / "state" / "mainspring.lock").write_text(
        str(os.getpid()),
        encoding="utf-8",
    )
    rows = [
        {
            "timestamp": f"2026-04-29T04:0{index}:00+02:00",
            "wave_id": str(index),
            "task_id": "7",
            "verdict": "FAIL",
            "exit_code": 0,
            "duration_seconds": 20,
            "engines": {"writer": "codex", "reviewer": "codex"},
            "failure_reason_class": "scope:violation",
            "next_action": "Remove forbidden path changes, rerun verification.",
        }
        for index in range(1, 4)
    ]
    (runtime / "logs" / "waves.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    snapshot = hud.build_global_snapshot(
        runtime / "logs" / "waves.jsonl",
        runtime / "state",
        search_roots=[],
        process_rows=[],
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    run = snapshot["runs"][0]
    assert snapshot["needs_action_count"] == 1
    assert "attention_count" not in snapshot
    assert run["operator_state"] == "STUCK"
    assert run["consecutive_failures"] == 3
    assert run["failure_reason_class"] == "scope:violation"
    assert "Remove forbidden path changes" in run["next_action"]


def test_operator_state_labels_are_human_readable() -> None:
    assert hud._operator_state_label("RUNNING") == "Running"
    assert hud._operator_state_label("OK") == "Waiting"
    assert hud._operator_state_label("STUCK") == "Blocked"
    assert hud._operator_state_label("RETRY") == "Failed"
    assert hud._operator_state_label("IDLE") == "Stopped cleanly"
    assert hud._operator_state_label("STALE", "FAIL") == "Failed"
    assert hud._operator_state_label("STALE", "PASS") == "Not running"


def test_global_snapshot_marks_restarted_failure_as_running(
    tmp_path: Path,
) -> None:
    project = tmp_path / "restarted-app"
    runtime = project / ".mainspring"
    (runtime / "state").mkdir(parents=True)
    (runtime / "logs").mkdir(parents=True)
    lock = runtime / "state" / "mainspring.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    restarted_at = datetime.fromisoformat("2026-04-29T04:55:00+02:00").timestamp()
    os.utime(lock, (restarted_at, restarted_at))
    rows = [
        {
            "timestamp": f"2026-04-29T04:0{index}:00+02:00",
            "wave_id": str(index),
            "task_id": "7",
            "verdict": "FAIL",
            "exit_code": 0,
            "duration_seconds": 20,
            "engines": {"writer": "codex", "reviewer": "codex"},
            "failure_reason_class": "scope:violation",
            "next_action": "Remove forbidden path changes, rerun verification.",
        }
        for index in range(1, 4)
    ]
    (runtime / "logs" / "waves.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    snapshot = hud.build_global_snapshot(
        runtime / "logs" / "waves.jsonl",
        runtime / "state",
        search_roots=[],
        process_rows=[],
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    run = snapshot["runs"][0]
    assert snapshot["needs_action_count"] == 0
    assert "attention_count" not in snapshot
    assert run["operator_state"] == "RUNNING"
    assert run["runtime_started_after_last_wave"] is True
    assert run["consecutive_failures"] == 3
    assert "Running now" in run["next_action"]
    assert "Previous wave: FAIL" in run["next_action"]
    assert "Remove forbidden path changes" not in run["next_action"]


def test_global_snapshot_does_not_count_hud_command_as_work_process(
    tmp_path: Path,
) -> None:
    project = tmp_path / "dashboard-only"
    runtime = project / ".mainspring"
    (runtime / "state").mkdir(parents=True)
    (runtime / "logs").mkdir(parents=True)
    _write_ledger(runtime / "logs" / "waves.jsonl")

    snapshot = hud.build_global_snapshot(
        runtime / "logs" / "waves.jsonl",
        runtime / "state",
        search_roots=[],
        process_rows=[
            "111 /opt/bin/mainspring hud --once",
            f"112 /bin/bash -lc './mainspring.sh --project {project} hud'",
        ],
        cwd_resolver=lambda _pid: project,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    assert snapshot["run_count"] == 0
    assert snapshot["live_count"] == 0


def test_global_snapshot_does_not_count_utility_commands_as_work_process(
    tmp_path: Path,
) -> None:
    project = tmp_path / "utility-only"
    runtime = project / ".mainspring"
    (runtime / "state").mkdir(parents=True)
    (runtime / "logs").mkdir(parents=True)
    _write_ledger(runtime / "logs" / "waves.jsonl")

    snapshot = hud.build_global_snapshot(
        runtime / "logs" / "waves.jsonl",
        runtime / "state",
        search_roots=[],
        process_rows=[
            "201 /opt/bin/mainspring limits --format json",
            "202 /opt/bin/mainspring last-run --format json",
            "203 /opt/bin/mainspring help --full",
        ],
        cwd_resolver=lambda _pid: project,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    assert snapshot["run_count"] == 0
    assert snapshot["live_count"] == 0


def test_global_snapshot_ignores_shell_scripts_that_only_mention_mainspring(
    tmp_path: Path,
) -> None:
    real_project = tmp_path / "real-project"
    mentioned_project = tmp_path / "mentioned-project"
    for project in (real_project, mentioned_project):
        runtime = project / ".mainspring"
        (runtime / "state").mkdir(parents=True)
        (runtime / "logs").mkdir(parents=True)
        _write_ledger(runtime / "logs" / "waves.jsonl")

    snapshot = hud.build_global_snapshot(
        real_project / ".mainspring" / "logs" / "waves.jsonl",
        real_project / ".mainspring" / "state",
        search_roots=[],
        process_rows=[
            (
                "301 /bin/bash -lc 'echo preflight; "
                f"mainspring --project {mentioned_project} status; sleep 5'"
            ),
        ],
        cwd_resolver=lambda _pid: real_project,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    assert snapshot["run_count"] == 0
    assert snapshot["live_count"] == 0


def test_build_snapshot_keeps_dispatch_only_team_visible(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    team_dir = state_dir / "team" / "dispatch-only"
    team_dir.mkdir(parents=True)
    (team_dir / "dispatch-ledger.json").write_text(
        json.dumps(
            {
                "42": {"status": "pending"},
                "43": {"status": "in_progress"},
                "44": {"status": "completed"},
            }
        ),
        encoding="utf-8",
    )
    _write_ledger(ledger)

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    assert snapshot["active_teams"] == [
        {
            "name": "dispatch-only",
            "status": "dispatch-only",
            "workers": "",
            "pending_dispatches": 2,
        }
    ]


def test_format_text_contains_operator_snapshot(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)
    (ledger.parent / "latest.log").write_text("runtime ready\n", encoding="utf-8")

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot, width=200)

    assert "Mainspring project snapshot" in text
    assert "Folder:" in text
    assert "Current wave: id=w2 task_id=43" in text
    assert "started=2026-04-29 04:49:20" in text
    assert "stopped=2026-04-29 04:50:00" in text
    assert "Last log:" in text
    assert "Today: 3 waves" in text
    assert "Quota: claude 57.5% used" in text
    assert "Active teams: none" in text
    assert "Notifications: disabled" in text


def test_format_rich_contains_operator_snapshot(tmp_path: Path) -> None:
    from rich.console import Console

    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    team_dir = state_dir / "team" / "alpha"
    team_dir.mkdir(parents=True)
    (team_dir / "config.json").write_text(
        json.dumps({"status": "running", "team_size": 3}),
        encoding="utf-8",
    )
    (team_dir / "dispatch-ledger.json").write_text(
        json.dumps({"42": {"status": "pending"}}),
        encoding="utf-8",
    )
    _write_ledger(ledger)

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    console = Console(record=True, width=100, color_system=None, force_terminal=False)
    console.print(hud.format_rich(snapshot))
    text = console.export_text()

    assert "Mainspring" in text
    assert "Mainspring HUD" not in text
    assert "Folder" in text
    assert "Current" in text
    assert "Runtime" in text
    assert "Progress" in text
    assert "Telegram" in text
    assert "Quota" in text
    assert "Teams" in text
    assert "Started" in text
    assert "Stopped" in text
    assert "codex" in text
    assert "alpha" in text
    assert "running" in text
    assert "w2" in text


def test_format_rich_compacts_long_wave_ids(tmp_path: Path) -> None:
    from rich.console import Console

    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    snapshot["recent_waves"][0]["wave_id"] = "team-preflight-20260504-183429"
    console = Console(record=True, width=120, color_system=None, force_terminal=False)
    console.print(hud.format_rich(snapshot))
    text = console.export_text()

    assert "Wave ID" in text
    assert "Task ID" in text
    assert "team-preflig...260504-183429" in text


def test_format_global_text_contains_all_runtime_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MAINSPRING_TASKMASTER_TAG", raising=False)
    project = tmp_path / "ops-app"
    runtime = project / ".mainspring"
    (runtime / "state").mkdir(parents=True)
    (runtime / "logs").mkdir(parents=True)
    _write_ledger(runtime / "logs" / "waves.jsonl")
    _write_taskmaster(project, statuses=["done", "pending"])
    (runtime / "state" / "mainspring.lock").write_text(
        str(os.getpid()),
        encoding="utf-8",
    )
    snapshot = hud.build_global_snapshot(
        runtime / "logs" / "waves.jsonl",
        runtime / "state",
        search_roots=[tmp_path],
        process_rows=[],
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    text = hud.format_global_text(snapshot, width=220)

    assert "Mainspring" in text
    assert ("Global " + "HUD") not in text
    assert "1 total, 1 live, 0 past" in text
    assert "View: all projects on this machine" in text
    stale_scope = "Scope: global " + "machine view"
    stale_runtimes = "Run" + "times:"
    assert stale_scope not in text
    assert stale_runtimes not in text
    assert "- Waiting | ops-app" in text
    assert f"Folder: {project}" in text
    assert "Task: 43" in text
    assert "Progress: 50% (1/2)" in text
    assert "project=ops-app" not in text
    assert "folder=" not in text


def test_format_global_text_empty_state_is_actionable(tmp_path: Path) -> None:
    runtime = tmp_path / ".mainspring"
    ledger = runtime / "logs" / "waves.jsonl"
    state_dir = runtime / "state"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    snapshot = hud.build_global_snapshot(
        ledger,
        state_dir,
        search_roots=[],
        process_rows=[],
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    text = hud.format_global_text(snapshot, width=120)

    assert "Mainspring" in text
    assert "Mainspring HUD" not in text
    assert "Runs:  0 total, 0 live, 0 past, 0 needs action" in text
    assert "View: all projects on this machine" in text
    stale_scope = "Scope: global " + "machine view"
    stale_runtimes = "Run" + "times:"
    assert stale_scope not in text
    assert stale_runtimes not in text
    assert "State: IDLE - no Mainspring work is running" in text
    assert "This is healthy if you expected no active jobs." in text
    assert "Start / Resume" in text
    assert "new run in a project" in text
    assert "mainspring --last-run" in text
    assert "mainspring notify-health --format json" in text
    assert "mainspring stop --force" in text
    assert "mainspring stop --force --" + "all" not in text
    assert "mainspring doctor" in text
    assert "main..." not in text


def test_format_global_text_separates_running_state_from_previous_failure(
    tmp_path: Path,
) -> None:
    project = tmp_path / "running-app"
    runtime = project / ".mainspring"
    (runtime / "state").mkdir(parents=True)
    (runtime / "logs").mkdir(parents=True)
    lock = runtime / "state" / "mainspring.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    restarted_at = datetime.fromisoformat("2026-04-29T04:55:00+02:00").timestamp()
    os.utime(lock, (restarted_at, restarted_at))
    rows = [
        {
            "timestamp": "2026-04-29T04:03:00+02:00",
            "wave_id": "failed-before-restart",
            "task_id": "7",
            "verdict": "ERROR",
            "exit_code": 1,
            "duration_seconds": 20,
            "engines": {"writer": "codex", "reviewer": "codex"},
            "failure_reason_class": "engine:exit_nonzero",
            "next_action": "Inspect old log.",
        }
    ]
    (runtime / "logs" / "waves.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    snapshot = hud.build_global_snapshot(
        runtime / "logs" / "waves.jsonl",
        runtime / "state",
        search_roots=[],
        process_rows=[],
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_global_text(snapshot, width=1000)

    assert "- Running | running-app" in text
    assert "Now: Running now" in text
    assert "Previous result: ERROR" in text
    assert "result=ERROR" not in text
    assert "reason=engine:exit_nonzero" not in text
    assert "Inspect old log" not in text
    assert "Running now" in text


def test_runtime_session_command_rejects_claude_quota_probe() -> None:
    assert not hud._is_runtime_session_command(
        "claude -p --dangerously-skip-permissions --verbose "
        "--output-format stream-json --include-partial-messages Reply exactly: ok"
    )
    assert hud._is_runtime_session_command(
        "claude -p --dangerously-skip-permissions --verbose "
        "--output-format stream-json --include-partial-messages Implement task 8"
    )


def test_format_global_rich_contains_machine_runtime_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rich.console import Console

    monkeypatch.delenv("MAINSPRING_TASKMASTER_TAG", raising=False)
    project = tmp_path / "rich-app"
    runtime = project / ".mainspring"
    (runtime / "state").mkdir(parents=True)
    (runtime / "logs").mkdir(parents=True)
    _write_ledger(runtime / "logs" / "waves.jsonl")
    _write_taskmaster(project, statuses=["done", "pending"])
    (runtime / "state" / "mainspring.lock").write_text(
        str(os.getpid()),
        encoding="utf-8",
    )
    snapshot = hud.build_global_snapshot(
        runtime / "logs" / "waves.jsonl",
        runtime / "state",
        search_roots=[tmp_path],
        process_rows=[],
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    console = Console(record=True, width=220, color_system=None, force_terminal=False)
    console.print(hud.format_global_rich(snapshot))
    text = console.export_text()

    assert "Mainspring" in text
    assert ("Global " + "HUD") not in text
    assert "Mainspring " + "runtimes" not in text
    assert "State" in text
    assert "Issue" in text
    assert "Next" in text
    assert "Waiting" in text
    assert "rich-app" in text
    assert "Task" in text
    assert "Progress" in text
    assert "50% (1/2)" in text
    assert "Telegram" in text


def test_format_global_rich_empty_state_is_actionable(tmp_path: Path) -> None:
    from rich.console import Console

    runtime = tmp_path / ".mainspring"
    ledger = runtime / "logs" / "waves.jsonl"
    state_dir = runtime / "state"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    snapshot = hud.build_global_snapshot(
        ledger,
        state_dir,
        search_roots=[],
        process_rows=[],
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    console = Console(record=True, width=120, color_system=None, force_terminal=False)
    console.print(hud.format_global_rich(snapshot))
    text = console.export_text()

    assert "Ready To Start" in text
    assert "IDLE - no Mainspring work is running" in text
    assert "cd /path/to/project && mainspring" in text
    assert "mainspring --last-run" in text
    assert "mainspring stop --force" in text
    assert "mainspring stop --force --" + "all" not in text
    assert "State   Project" not in text


def test_format_rich_surfaces_degraded_ledger_reason(tmp_path: Path) -> None:
    from rich.console import Console

    ledger = tmp_path / "missing-waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    console = Console(record=True, width=120, color_system=None, force_terminal=False)
    console.print(hud.format_rich(snapshot))
    text = console.export_text()

    assert "missing entries=0 valid=0" in text
    assert "ledger file is missing" in text


def test_build_snapshot_reports_missing_ledger_state(tmp_path: Path) -> None:
    ledger = tmp_path / "missing-waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot)

    assert snapshot["entry_count"] == 0
    assert snapshot["ledger_state"]["status"] == "missing"
    assert snapshot["ledger_state"]["reason"] == "ledger file is missing"
    assert "Ledger: missing, entries=0, valid=0 (ledger file is missing)" in text


def test_build_snapshot_reports_empty_ledger_state(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    ledger.write_text("", encoding="utf-8")

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot)

    assert snapshot["entry_count"] == 0
    assert snapshot["ledger_state"]["status"] == "empty"
    assert snapshot["ledger_state"]["reason"] == "ledger file has no wave rows"
    assert "Ledger: empty, entries=0, valid=0 (ledger file has no wave rows)" in text


def test_build_snapshot_reports_nonempty_invalid_ledger_state(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    ledger.write_text("not-json\nalso-not-json\n", encoding="utf-8")

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot)

    assert snapshot["entry_count"] == 0
    assert snapshot["ledger_state"]["status"] == "no_valid_entries"
    assert (
        snapshot["ledger_state"]["reason"]
        == "ledger has bytes but no valid JSONL wave rows"
    )
    assert snapshot["ledger_state"]["valid_entries"] == 0
    assert "Ledger: no_valid_entries, entries=0, valid=0" in text


def test_build_snapshot_keeps_valid_ledger_state_when_since_filters_all_rows(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        since="1m",
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot)

    assert snapshot["entry_count"] == 0
    assert snapshot["current_wave"] is None
    assert snapshot["recent_waves"] == []
    assert snapshot["ledger_state"]["status"] == "ok"
    assert snapshot["ledger_state"]["entries"] == 0
    assert snapshot["ledger_state"]["valid_entries"] == 3
    assert "Ledger: ok, entries=0, valid=3" in text
    assert "no_valid_entries" not in text


def test_format_text_clips_to_small_terminal_width(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    team_dir = state_dir / "team" / "very-long-team-name-that-would-wrap"
    team_dir.mkdir(parents=True)
    (team_dir / "config.json").write_text(
        json.dumps({"status": "running-with-a-verbose-status", "team_size": 12}),
        encoding="utf-8",
    )
    _write_ledger(ledger)
    (ledger.parent / "latest.log").write_text(
        "latest runtime line " + ("with extra diagnostic context " * 8) + "\n",
        encoding="utf-8",
    )

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    snapshot["recent_waves"][0]["wave_id"] = "wave-id-" + ("x" * 120)

    for width, height in ((80, 24), (200, 60)):
        text = hud.format_text(snapshot, width=width)
        lines = text.splitlines()

        assert max(len(line) for line in lines) <= width
        assert len(lines) <= height
        assert "..." in text


def test_build_snapshot_reports_notifier_health_when_enabled(
    tmp_path: Path, monkeypatch
) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)
    (state_dir / "notify-state.json").write_text(
        json.dumps({"last_line_count": 3, "last_activity_ts": 1000.0}),
        encoding="utf-8",
    )
    (state_dir / "notifier.pid").write_text(str(os.getpid()), encoding="utf-8")
    (ledger.parent / "notifier.log").write_text(
        "notify: 2026-04-29T04:59:00+02:00 processed 3 new ledger line(s), 3 valid\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAINSPRING_NOTIFY_ENABLED", "1")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_CHAT_ID", "123")

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    assert snapshot["notifications"]["enabled"] is True
    assert snapshot["notifications"]["configured"] is True
    assert snapshot["notifications"]["status"] == "healthy"
    assert snapshot["notifications"]["reason"] == "caught_up"
    assert snapshot["notifications"]["pending_lines"] == 0
    assert snapshot["notifications"]["ledger_lines"] == 3
    assert snapshot["notifications"]["process_running"] is True
    assert snapshot["notifications"]["next_step"] == "none"


def test_build_snapshot_reports_stale_notifier_with_pending_lines(
    tmp_path: Path, monkeypatch
) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)
    (state_dir / "notify-state.json").write_text(
        json.dumps({"last_line_count": 1, "last_activity_ts": 1.0}),
        encoding="utf-8",
    )
    (state_dir / "notifier.pid").write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setenv("MAINSPRING_NOTIFY_ENABLED", "1")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_CHAT_ID", "123")

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot)

    assert snapshot["notifications"]["status"] == "stale"
    assert snapshot["notifications"]["reason"] == "pending_lines_stale"
    assert snapshot["notifications"]["next_step"] == "restart-notifier-daemon"
    assert snapshot["notifications"]["pending_lines"] == 2
    assert "Notifications: stale (pending_lines_stale, pending=2)" in text
    _assert_stale_recovery_guidance(snapshot, text)


def test_build_snapshot_reports_corrupt_notifier_state_as_stale(
    tmp_path: Path, monkeypatch
) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)
    state_path = state_dir / "notify-state.json"
    state_path.write_text(
        json.dumps(
            {
                "last_line_count": "not-a-count",
                "last_activity_ts": "not-a-timestamp",
            }
        ),
        encoding="utf-8",
    )
    os.utime(state_path, (1000.0, 1000.0))
    (state_dir / "notifier.pid").write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setenv("MAINSPRING_NOTIFY_ENABLED", "1")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_CHAT_ID", "123")

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("1970-01-01T01:23:20+00:00"),
    )
    text = hud.format_text(snapshot)

    assert snapshot["notifications"]["status"] == "stale"
    assert snapshot["notifications"]["reason"] == "pending_without_activity_stale"
    assert snapshot["notifications"]["last_line_count"] == 0
    assert snapshot["notifications"]["pending_lines"] == 3
    assert "Notifications: stale (pending_without_activity_stale, pending=3)" in text
    _assert_stale_recovery_guidance(snapshot, text)


def test_build_snapshot_reports_stale_notifier_log(tmp_path: Path, monkeypatch) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)
    os.utime(ledger, (5000.0, 5000.0))
    (state_dir / "notify-state.json").write_text(
        json.dumps({"last_line_count": 3, "last_activity_ts": 5000.0}),
        encoding="utf-8",
    )
    (state_dir / "notifier.pid").write_text(str(os.getpid()), encoding="utf-8")
    (ledger.parent / "notifier.log").write_text(
        "notify: 1970-01-01T00:16:40Z processed 3 new ledger line(s), 3 valid\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAINSPRING_NOTIFY_ENABLED", "1")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_CHAT_ID", "123")

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("1970-01-01T01:23:20+00:00"),
    )
    text = hud.format_text(snapshot)

    assert snapshot["notifications"]["status"] == "stale"
    assert snapshot["notifications"]["reason"] == "notifier_log_stale"
    assert snapshot["notifications"]["watch_status"] == "stale"
    assert snapshot["notifications"]["next_step"] == "restart-notifier-daemon"
    assert "Notifications: stale (notifier_log_stale, pending=0)" in text
    _assert_stale_recovery_guidance(snapshot, text)


def test_build_snapshot_reports_notifier_log_warmup(
    tmp_path: Path, monkeypatch
) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)
    (state_dir / "notify-state.json").write_text(
        json.dumps({"last_line_count": 3, "last_activity_ts": 1000.0}),
        encoding="utf-8",
    )
    (state_dir / "notifier.pid").write_text(str(os.getpid()), encoding="utf-8")
    (ledger.parent / "notifier.log").write_text(
        "notify: watching waves.jsonl\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAINSPRING_NOTIFY_ENABLED", "1")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_CHAT_ID", "123")

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("1970-01-01T00:18:20+00:00"),
    )
    text = hud.format_text(snapshot)

    assert snapshot["notifications"]["status"] == "starting"
    assert snapshot["notifications"]["reason"] == "notifier_log_warming_up"
    assert snapshot["notifications"]["watch_status"] == "starting"
    assert snapshot["notifications"]["next_step"] == "wait-for-heartbeat"
    assert "Notifications: starting (notifier_log_warming_up, pending=0)" in text
    assert "Notifications next: Wait for the notifier heartbeat" in text


def test_build_snapshot_reports_stale_notifier_when_pid_missing(
    tmp_path: Path, monkeypatch
) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)
    (state_dir / "notify-state.json").write_text(
        json.dumps({"last_line_count": 3, "last_activity_ts": 1000.0}),
        encoding="utf-8",
    )
    (ledger.parent / "notifier.log").write_text(
        "notify: 2026-04-29T04:59:00+02:00 processed 3 new ledger line(s), 3 valid\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAINSPRING_NOTIFY_ENABLED", "1")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_CHAT_ID", "123")

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot)

    assert snapshot["notifications"]["status"] == "stale"
    assert snapshot["notifications"]["reason"] == "daemon_pid_missing"
    assert snapshot["notifications"]["watch_status"] == "healthy"
    assert snapshot["notifications"]["pending_lines"] == 0
    assert snapshot["notifications"]["next_step"] == "restart-notifier-daemon"
    assert "Notifications: stale (daemon_pid_missing, pending=0)" in text
    _assert_stale_recovery_guidance(snapshot, text)


def test_build_snapshot_reports_stale_notifier_when_pid_dead(
    tmp_path: Path, monkeypatch
) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)
    (state_dir / "notify-state.json").write_text(
        json.dumps({"last_line_count": 3, "last_activity_ts": 1000.0}),
        encoding="utf-8",
    )
    (state_dir / "notifier.pid").write_text("999999999", encoding="utf-8")
    (ledger.parent / "notifier.log").write_text(
        "notify: 2026-04-29T04:59:00+02:00 processed 3 new ledger line(s), 3 valid\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAINSPRING_NOTIFY_ENABLED", "1")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_CHAT_ID", "123")

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )

    assert snapshot["notifications"]["status"] == "stale"
    assert snapshot["notifications"]["reason"] == "daemon_pid_not_running"
    assert snapshot["notifications"]["pid"] == 999999999
    assert snapshot["notifications"]["process_running"] is False
    assert snapshot["notifications"]["watch_status"] == "healthy"
    assert snapshot["notifications"]["next_step"] == "restart-notifier-daemon"


def test_build_snapshot_honors_notifier_stale_seconds_env(
    tmp_path: Path, monkeypatch
) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)
    (state_dir / "notify-state.json").write_text(
        json.dumps({"last_line_count": 0, "last_activity_ts": 4980.0}),
        encoding="utf-8",
    )
    (state_dir / "notifier.pid").write_text(str(os.getpid()), encoding="utf-8")
    (ledger.parent / "notifier.log").write_text(
        "notify: 1970-01-01T01:23:15+00:00 processed 3 new ledger line(s), 3 valid\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAINSPRING_NOTIFY_ENABLED", "1")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("MAINSPRING_NOTIFY_STALE_SECONDS", "10")

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("1970-01-01T01:23:20+00:00"),
    )

    assert snapshot["notifications"]["stale_seconds"] == 10
    assert snapshot["notifications"]["status"] == "stale"
    assert snapshot["notifications"]["reason"] == "pending_lines_stale"
    assert snapshot["notifications"]["pending_lines"] == 3
    assert snapshot["notifications"]["next_step"] == "restart-notifier-daemon"


def test_build_snapshot_reports_invalid_notifier_stale_seconds_env(
    tmp_path: Path, monkeypatch
) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)
    monkeypatch.setenv("MAINSPRING_NOTIFY_ENABLED", "1")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("MAINSPRING_TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("MAINSPRING_NOTIFY_STALE_SECONDS", "soon")

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot)

    assert snapshot["notifications"]["status"] == "config_error"
    assert snapshot["notifications"]["reason"] == "invalid_stale_seconds"
    assert snapshot["notifications"]["invalid_stale_seconds"] == "soon"
    assert snapshot["notifications"]["next_step"] == "fix-notify-stale-threshold"
    assert "Notifications: config_error (invalid_stale_seconds)" in text
    assert "Notifications next: Set MAINSPRING_NOTIFY_STALE_SECONDS" in text


def test_build_snapshot_reports_unconfigured_notifier_next_step(
    tmp_path: Path, monkeypatch
) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)
    monkeypatch.setenv("MAINSPRING_NOTIFY_ENABLED", "1")
    monkeypatch.delenv("MAINSPRING_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("MAINSPRING_TELEGRAM_CHAT_ID", raising=False)

    snapshot = hud.build_snapshot(
        ledger,
        state_dir,
        now=datetime.fromisoformat("2026-04-29T05:00:00+02:00"),
    )
    text = hud.format_text(snapshot)

    assert snapshot["notifications"]["status"] == "unconfigured"
    assert snapshot["notifications"]["next_step"] == "configure-telegram"
    assert "Notifications: unconfigured (telegram token/chat id missing)" in text
    assert "Notifications next: Set MAINSPRING_TELEGRAM_BOT_TOKEN" in text


def test_cli_json_outputs_snapshot(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            "--since",
            "2026-04-29T00:00:00+02:00",
            "--json",
            "--once",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["current_wave"]["wave_id"] == "w2"
    assert payload["entry_count"] == 3


def test_cli_global_json_outputs_machine_snapshot(tmp_path: Path) -> None:
    project = tmp_path / "global-app"
    runtime = project / ".mainspring"
    ledger = runtime / "logs" / "waves.jsonl"
    state_dir = runtime / "state"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    _write_ledger(ledger)
    (state_dir / "mainspring.lock").write_text(str(os.getpid()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--global",
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            "--search-root",
            str(tmp_path),
            "--json",
            "--once",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["scope"] == "global"
    assert payload["run_count"] >= 1
    assert any(run["project"] == "global-app" for run in payload["runs"])


@pytest.mark.parametrize("rich_available", [True, False])
def test_cli_no_args_uses_live_renderer_in_tty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rich_available: bool,
) -> None:
    runtime_dir = tmp_path / ".mainspring"
    calls: list[tuple[str, tuple, dict]] = []
    availability_calls: list[bool] = []

    class TtyStdout:
        def isatty(self) -> bool:
            return True

    def rich_is_available() -> bool:
        availability_calls.append(rich_available)
        return rich_available

    monkeypatch.setattr(hud.sys, "stdout", TtyStdout())
    monkeypatch.setattr(hud, "_default_runtime_dir", lambda: runtime_dir)
    monkeypatch.delenv("MAINSPRING_STATE_DIR", raising=False)
    monkeypatch.setattr(hud, "_rich_available", rich_is_available)
    monkeypatch.setattr(
        hud,
        "rich_live_snapshot",
        lambda *args, **kwargs: calls.append(("rich", args, kwargs)),
    )
    monkeypatch.setattr(
        hud,
        "watch_snapshot",
        lambda *args, **kwargs: calls.append(("plain", args, kwargs)),
    )

    assert hud._cli_main([]) == 0
    assert availability_calls == [rich_available]
    assert len(calls) == 1
    renderer, args, kwargs = calls[0]
    assert renderer == ("rich" if rich_available else "plain")
    assert args == (runtime_dir / "logs" / "waves.jsonl", runtime_dir / "state")
    assert kwargs["global_scope"] is False
    assert kwargs["iterations"] is None


def test_cli_auto_live_promotes_plain_hud_to_rich_watch_in_tty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / ".mainspring" / "logs" / "waves.jsonl"
    state_dir = tmp_path / ".mainspring" / "state"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    _write_ledger(ledger)
    calls: dict[str, object] = {}

    class TtyStdout:
        def isatty(self) -> bool:
            return True

    def fake_rich_live_snapshot(
        ledger_path: Path,
        snapshot_state_dir: Path,
        **kwargs: object,
    ) -> None:
        calls["ledger_path"] = ledger_path
        calls["state_dir"] = snapshot_state_dir
        calls.update(kwargs)

    monkeypatch.setattr(hud.sys, "stdout", TtyStdout())
    monkeypatch.setattr(hud, "_rich_available", lambda: True)
    monkeypatch.setattr(hud, "rich_live_snapshot", fake_rich_live_snapshot)

    result = hud._cli_main(
        [
            "--global",
            "--auto-live",
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
        ]
    )

    assert result == 0
    assert calls["ledger_path"] == ledger
    assert calls["state_dir"] == state_dir
    assert calls["global_scope"] is True
    assert calls["iterations"] is None


def test_cli_auto_live_stays_one_shot_when_captured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = tmp_path / ".mainspring" / "logs" / "waves.jsonl"
    state_dir = tmp_path / ".mainspring" / "state"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    _write_ledger(ledger)

    monkeypatch.setattr(hud, "_rich_available", lambda: True)
    monkeypatch.setattr(
        hud,
        "rich_live_snapshot",
        lambda *_args, **_kwargs: pytest.fail("captured HUD must not enter Rich live"),
    )
    monkeypatch.setattr(
        hud,
        "watch_snapshot",
        lambda *_args, **_kwargs: pytest.fail("captured HUD must not enter watch"),
    )

    result = hud._cli_main(
        [
            "--global",
            "--auto-live",
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
        ]
    )

    assert result == 0
    captured = capsys.readouterr()
    assert "Mainspring" in captured.out
    assert "Runs:" in captured.out
    assert "Traceback" not in captured.err


def test_cli_width_limits_text_output(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)
    (ledger.parent / "latest.log").write_text(
        "runtime line " + ("with verbose context " * 8) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            "--width",
            "50",
            "--once",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert max(len(line) for line in result.stdout.splitlines()) <= 50


def test_cli_watch_renders_bounded_refresh_frames(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            "--watch",
            "--ansi",
            "--interval",
            "0",
            "--iterations",
            "2",
            "--width",
            "60",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.count("\033[2J\033[H") == 2
    assert result.stdout.count("Mainspring project snapshot") == 2


def test_cli_watch_defaults_to_plain_frames_when_captured(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            "--watch",
            "--interval",
            "0",
            "--iterations",
            "2",
            "--width",
            "60",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "\033[2J\033[H" not in result.stdout
    assert result.stdout.count("Mainspring project snapshot") == 2


def test_cli_watch_no_ansi_overrides_terminal_redraw(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            "--watch",
            "--no-ansi",
            "--interval",
            "0",
            "--iterations",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "\033[2J\033[H" not in result.stdout


@pytest.mark.parametrize("live_mode", ["--watch", "--rich"])
def test_cli_live_hud_exits_cleanly_on_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    live_mode: str,
) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    def interrupted_live_mode(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    if live_mode == "--rich":
        monkeypatch.setattr(hud, "rich_live_snapshot", interrupted_live_mode)
    else:
        monkeypatch.setattr(hud, "watch_snapshot", interrupted_live_mode)

    result = hud._cli_main(
        [
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            live_mode,
        ]
    )

    captured = capsys.readouterr()
    assert result == 130
    assert "Traceback" not in captured.err
    assert "KeyboardInterrupt" not in captured.err


def test_cli_no_args_stays_one_shot_when_output_is_captured(tmp_path: Path) -> None:
    ledger = tmp_path / ".mainspring" / "logs" / "waves.jsonl"
    state_dir = tmp_path / ".mainspring" / "state"
    state_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    _write_ledger(ledger)

    result = subprocess.run(
        [sys.executable, SCRIPT],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.count("Mainspring project snapshot") == 1
    assert "Folder:" in result.stdout


def test_top_level_hud_auto_live_stays_one_shot_when_output_is_captured(
    tmp_path: Path,
) -> None:
    project = tmp_path / "captured-top-level"
    project.mkdir()

    result = subprocess.run(
        [str(MAINSPRING_DIR / "mainspring.sh"), "--project", str(project), "hud"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0
    assert "Mainspring" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("width", [80, 200])
def test_cli_rich_renders_bounded_live_snapshot(tmp_path: Path, width: int) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            "--rich",
            "--interval",
            "0",
            "--iterations",
            "1",
            "--width",
            str(width),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Mainspring" in result.stdout
    assert "Mainspring HUD" not in result.stdout
    assert "Recent waves" in result.stdout
    lines = result.stdout.splitlines()
    assert max(len(line.rstrip("\n")) for line in lines) <= width
    assert len(lines) <= (24 if width == 80 else 60)


def test_cli_rich_once_renders_single_bounded_live_snapshot(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            "--rich",
            "--once",
            "--width",
            "80",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0
    assert "Mainspring" in result.stdout
    assert "Mainspring HUD" not in result.stdout
    assert "Recent waves" in result.stdout
    lines = result.stdout.splitlines()
    assert max(len(line.rstrip("\n")) for line in lines) <= 80
    assert len(lines) <= 24


def test_cli_rich_watch_renders_live_hud(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            "--rich",
            "--watch",
            "--interval",
            "0",
            "--iterations",
            "1",
            "--width",
            "120",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0
    assert "hud: --watch cannot be combined with --rich" not in result.stderr
    assert "Mainspring" in result.stdout
    assert "Mainspring HUD" not in result.stdout
    assert "Folder" in result.stdout
    assert "Started" in result.stdout
    assert "Stopped" in result.stdout


def test_mainspring_requirements_declares_runtime_dependencies() -> None:
    requirements = (MAINSPRING_DIR / "requirements.txt").read_text(encoding="utf-8")
    runtime_lines = [
        line.strip()
        for line in requirements.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert runtime_lines == [
        "rich>=13.7,<15",
        'litellm>=1.83.11,<2; python_version < "3.14"',
        'filelock>=4.2.1,<5; python_version < "3.14"',
        'aiohttp>=3.14.0; python_version < "3.14"',
        'python-dotenv>=1.2.2; python_version < "3.14"',
    ]


def test_cli_defaults_to_mainspring_runtime_on_fresh_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MAINSPRING_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("MAINSPRING_STATE_DIR", raising=False)
    assert hud._default_runtime_dir() == Path(".mainspring")
    assert hud._default_state_dir(Path(".mainspring")) == Path(".mainspring/state")


def test_cli_watch_rejects_json_output(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            "--watch",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "hud: --json cannot be combined with live HUD modes" in result.stderr


def test_cli_iterations_requires_watch(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            "--iterations",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "hud: --iterations requires --watch or --rich" in result.stderr


def test_cli_rejects_invalid_since_filter(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            "--since",
            "not-a-window",
            "--once",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "hud: --since must be a duration" in result.stderr


def test_cli_rejects_negative_since_duration(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _write_ledger(ledger)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--ledger",
            str(ledger),
            "--state-dir",
            str(state_dir),
            "--since",
            "-1h",
            "--once",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "hud: --since duration must not be negative" in result.stderr


def test_cli_rejects_missing_option_values() -> None:
    for flag in (
        "--ledger",
        "--state-dir",
        "--since",
        "--search-root",
        "--width",
        "--interval",
        "--iterations",
    ):
        result = subprocess.run(
            [sys.executable, SCRIPT, flag],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 2
        assert f"hud: {flag} requires a value" in result.stderr


def test_cli_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Mainspring HUD" in result.stdout
    assert "mainspring hud" in result.stdout
    assert "Global dashboard" in result.stdout
    assert "Project, Folder, PID, Tag" in result.stdout
    assert "Usage: hud.py" not in result.stdout
