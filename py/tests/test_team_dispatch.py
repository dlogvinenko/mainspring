# SPDX-License-Identifier: Apache-2.0
"""Tests for team_dispatch.py — team task dispatch, counts, nudge, requeue."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import team_dispatch

SCRIPT = str(HERE.parent / "team_dispatch.py")
RUNTIME_ENV_KEYS = (
    "MAINSPRING_RUNTIME_DIR",
    "MAINSPRING_STATE_DIR",
)


@pytest.fixture(autouse=True)
def isolate_runtime_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in RUNTIME_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


def _make_completed(
    returncode: int = 0, stdout: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


def _list_tasks_response(tasks: list[dict]) -> str:
    return json.dumps({"data": {"tasks": tasks}})


@contextmanager
def _cwd(path: Path):
    original = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def _dispatch_ledger(team_name: str) -> Path:
    return Path(".mainspring") / "state" / "team" / team_name / "dispatch-ledger.json"


# ── dispatch ───────────────────────────────────────────────────────────


def test_dispatch_no_items(capsys: object) -> None:
    """Empty JSONL → prints no items, exits 0."""
    team_dispatch.cmd_dispatch("test-team", 2, "")
    # Should not raise


def test_dispatch_invalid_jsonl(capsys: object) -> None:
    """Invalid JSON lines are skipped."""
    team_dispatch.cmd_dispatch("test-team", 2, "not json\n")
    # Should not raise


@patch("team_dispatch.subprocess.run")
def test_dispatch_creates_tasks(mock_run: MagicMock, tmp_path: Path) -> None:
    """Valid items create tasks and send messages."""
    items = [
        {
            "id": "1",
            "title": "Fix bug",
            "description": "Fix the thing",
            "scope": ["src/"],
        },
    ]
    items_jsonl = json.dumps(items[0])

    # First call: list-tasks (no existing)
    # Second call: create-task
    # Third call: send-message
    mock_run.side_effect = [
        _make_completed(0, _list_tasks_response([])),
        _make_completed(0, json.dumps({"data": {"task": {"id": "task-99"}}})),
        _make_completed(0, ""),
    ]

    with _cwd(tmp_path):
        team_dispatch.cmd_dispatch("test-team", 2, items_jsonl)
        ledger = json.loads(_dispatch_ledger("test-team").read_text())

    assert mock_run.call_count == 3
    # Verify create-task was called
    create_call = mock_run.call_args_list[1]
    create_args = create_call[0][0]
    assert "create-task" in create_args
    create_payload = json.loads(create_args[create_args.index("--input") + 1])
    description = create_payload["description"]
    assert "read project guidance files" in description
    assert "AGENTS.md / CLAUDE.md when present" in description
    stale_claude_only_guidance = "read CLAUDE.md and .taskmaster " + "docs first"
    assert stale_claude_only_guidance not in description
    assert ledger["1"]["status"] == "pending"
    assert ledger["1"]["team_task_id"] == "task-99"
    assert ledger["1"]["owner"] == "worker-1"


def test_dispatch_ledger_path_uses_mainspring_runtime_when_no_env(
    tmp_path: Path,
) -> None:
    with _cwd(tmp_path):
        Path(".omx").mkdir()
        assert team_dispatch._dispatch_ledger_path("demo") == (
            Path(".mainspring") / "state" / "team" / "demo" / "dispatch-ledger.json"
        )


def test_runtime_paths_prefer_explicit_state_and_runtime_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    state = tmp_path / "state"
    monkeypatch.setenv("MAINSPRING_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("MAINSPRING_STATE_DIR", str(state))

    assert team_dispatch._runtime_dir() == runtime
    assert team_dispatch._runtime_state_dir() == state
    assert team_dispatch._dispatch_ledger_path("demo") == (
        state / "team" / "demo" / "dispatch-ledger.json"
    )


@pytest.mark.parametrize("team_name", ["../outside", "a/b", "", ".", ".."])
def test_dispatch_ledger_rejects_unsafe_team_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    team_name: str,
) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("MAINSPRING_STATE_DIR", str(state))

    with pytest.raises(ValueError, match="unsafe team name"):
        team_dispatch._dispatch_ledger_path(team_name)

    assert not (tmp_path / "outside").exists()


def test_dispatch_ledger_invalid_json_returns_empty(tmp_path: Path) -> None:
    with _cwd(tmp_path):
        ledger_path = _dispatch_ledger("demo")
        ledger_path.parent.mkdir(parents=True)
        ledger_path.write_text("{bad json", encoding="utf-8")

        assert team_dispatch._read_dispatch_ledger("demo") == {}


def test_taskmaster_subject_parsing_and_duplicate_statuses() -> None:
    assert team_dispatch._taskmaster_id_from_subject("Task Master 7 - Work") == "7"
    assert team_dispatch._taskmaster_id_from_subject("Task Master 7.2 Work") == "7.2"
    assert team_dispatch._taskmaster_id_from_subject("Not Task Master") == ""
    assert team_dispatch._taskmaster_id_from_subject("Task Master ") == ""
    assert team_dispatch._duplicate_status_blocks_dispatch("dispatched") is True
    assert team_dispatch._duplicate_status_blocks_dispatch("open") is False


@patch("team_dispatch.subprocess.run")
def test_dispatch_skips_duplicates(mock_run: MagicMock) -> None:
    """Existing active task with same subject is skipped."""
    existing = [{"subject": "Task Master 1 - Fix bug", "status": "pending"}]
    items_jsonl = json.dumps({"id": "1", "title": "Fix bug"})

    mock_run.side_effect = [
        _make_completed(0, _list_tasks_response(existing)),
    ]

    team_dispatch.cmd_dispatch("test-team", 2, items_jsonl)
    # Only list-tasks called, no create-task
    assert mock_run.call_count == 1


@patch("team_dispatch.subprocess.run")
def test_dispatch_skips_completed_task_from_dispatch_ledger(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    """Previously completed Taskmaster id is not redispatched automatically."""
    items_jsonl = json.dumps({"id": "1", "title": "Fix bug"})
    ledger_path = tmp_path / _dispatch_ledger("test-team")
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(
        json.dumps(
            {
                "1": {
                    "status": "completed",
                    "subject": "Task Master 1 - Fix bug",
                    "team_task_id": "team-task-1",
                    "owner": "worker-1",
                    "ts": "2026-04-29T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    mock_run.return_value = _make_completed(0, _list_tasks_response([]))

    with _cwd(tmp_path):
        team_dispatch.cmd_dispatch("test-team", 2, items_jsonl)

    assert mock_run.call_count == 1


@patch("team_dispatch.subprocess.run")
def test_dispatch_refreshes_ledger_from_active_team_tasks(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    """Active OMX tasks refresh the ledger before duplicate checks."""
    active = [
        {
            "id": "team-task-7",
            "subject": "Task Master 7 - Existing work",
            "status": "in_progress",
            "owner": "worker-2",
        }
    ]
    items_jsonl = json.dumps({"id": "7", "title": "Existing work"})
    mock_run.return_value = _make_completed(0, _list_tasks_response(active))

    with _cwd(tmp_path):
        team_dispatch.cmd_dispatch("test-team", 2, items_jsonl)
        ledger = json.loads(_dispatch_ledger("test-team").read_text())

    assert mock_run.call_count == 1
    assert ledger["7"]["status"] == "in_progress"
    assert ledger["7"]["team_task_id"] == "team-task-7"


@patch("team_dispatch.subprocess.run")
def test_dispatch_retry_task_overrides_ledger_duplicate(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    """--retry-task allows an explicit redispatch of a recorded id."""
    items_jsonl = json.dumps({"id": "1", "title": "Fix bug"})
    ledger_path = tmp_path / _dispatch_ledger("test-team")
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(
        json.dumps(
            {
                "1": {
                    "status": "failed",
                    "subject": "Task Master 1 - Fix bug",
                    "team_task_id": "team-task-1",
                    "owner": "worker-1",
                    "ts": "2026-04-29T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    mock_run.side_effect = [
        _make_completed(0, _list_tasks_response([])),
        _make_completed(0, json.dumps({"data": {"task": {"id": "task-99"}}})),
        _make_completed(0, ""),
    ]

    with _cwd(tmp_path):
        team_dispatch.cmd_dispatch(
            "test-team", 2, items_jsonl, retry_ids=frozenset({"1"})
        )
        ledger = json.loads(_dispatch_ledger("test-team").read_text())

    assert mock_run.call_count == 3
    assert ledger["1"]["status"] == "pending"
    assert ledger["1"]["team_task_id"] == "task-99"


@patch("team_dispatch.subprocess.run")
def test_dispatch_send_fallback(mock_run: MagicMock, tmp_path: Path) -> None:
    """When send-message fails, falls back to write-worker-inbox."""
    items_jsonl = json.dumps({"id": "2", "title": "Add feat"})

    mock_run.side_effect = [
        _make_completed(0, _list_tasks_response([])),  # list-tasks
        _make_completed(
            0, json.dumps({"data": {"task": {"id": "t-1"}}})
        ),  # create-task
        _make_completed(1, "send failed"),  # send-message fails
        _make_completed(0, ""),  # write-worker-inbox succeeds
    ]

    with _cwd(tmp_path):
        team_dispatch.cmd_dispatch("test-team", 1, items_jsonl)
    assert mock_run.call_count == 4


@patch("team_dispatch.subprocess.run")
def test_dispatch_exit_1_on_failures(mock_run: MagicMock, tmp_path: Path) -> None:
    """SystemExit(1) raised when create-task fails."""
    items_jsonl = json.dumps({"id": "3", "title": "Broken"})

    mock_run.side_effect = [
        _make_completed(0, _list_tasks_response([])),  # list-tasks
        _make_completed(1, "create failed"),  # create-task fails
    ]

    with _cwd(tmp_path):
        try:
            team_dispatch.cmd_dispatch("test-team", 1, items_jsonl)
            raised = False
        except SystemExit as exc:
            raised = True
            assert exc.code == 1
        ledger = json.loads(_dispatch_ledger("test-team").read_text())
    assert raised
    assert ledger["3"]["status"] == "failed"


# ── counts ─────────────────────────────────────────────────────────────


@patch("team_dispatch.subprocess.run")
def test_counts_happy_path(mock_run: MagicMock, capsys: object) -> None:
    """Prints space-separated counts for TM tasks."""
    tasks = [
        {"subject": "Task Master 1 - A", "status": "pending"},
        {"subject": "Task Master 2 - B", "status": "in_progress"},
        {"subject": "Task Master 3 - C", "status": "completed"},
        {"subject": "Task Master 4 - D", "status": "completed"},
        {"subject": "Non-TM task", "status": "pending"},
    ]
    mock_run.return_value = _make_completed(0, _list_tasks_response(tasks))

    team_dispatch.cmd_counts("test-team")
    import contextlib
    import io

    buf = io.StringIO()
    mock_run.return_value = _make_completed(0, _list_tasks_response(tasks))
    with contextlib.redirect_stdout(buf):
        team_dispatch.cmd_counts("test-team")
    assert buf.getvalue().strip() == "1 1 2 0"


@patch("team_dispatch.subprocess.run")
def test_counts_api_failure(mock_run: MagicMock) -> None:
    """Exit 1 when list-tasks fails."""
    mock_run.return_value = _make_completed(1, "error")
    try:
        team_dispatch.cmd_counts("test-team")
        raised = False
    except SystemExit as exc:
        raised = True
        assert exc.code == 1
    assert raised


@patch("team_dispatch.subprocess.run")
def test_counts_invalid_json(mock_run: MagicMock) -> None:
    """Exit 1 when list-tasks returns invalid JSON."""
    mock_run.return_value = _make_completed(0, "not json")
    try:
        team_dispatch.cmd_counts("test-team")
        raised = False
    except SystemExit as exc:
        raised = True
        assert exc.code == 1
    assert raised


# ── nudge ──────────────────────────────────────────────────────────────


@patch("team_dispatch.subprocess.run")
def test_nudge_api_failure(mock_run: MagicMock) -> None:
    """Nudge silently exits when list-tasks fails."""
    mock_run.return_value = _make_completed(1, "")
    team_dispatch.cmd_nudge("test-team")
    # Should not raise


@patch("team_dispatch.subprocess.run")
def test_nudge_no_pending_tasks(mock_run: MagicMock) -> None:
    """No nudges sent when no pending TM tasks."""
    tasks = [
        {"subject": "Task Master 1 - A", "status": "in_progress", "owner": "worker-1"}
    ]
    mock_run.return_value = _make_completed(0, _list_tasks_response(tasks))
    team_dispatch.cmd_nudge("test-team")
    assert mock_run.call_count == 1  # Only list-tasks


@patch("team_dispatch.subprocess.run")
def test_nudge_sends_reminder(mock_run: MagicMock, tmp_path: Path) -> None:
    """Pending task older than min_age gets a nudge message."""
    tasks = [
        {
            "subject": "Task Master 5 - Old task",
            "status": "pending",
            "owner": "worker-1",
            "id": "t-5",
            "created_at": "2020-01-01T00:00:00Z",
        }
    ]
    mock_run.side_effect = [
        _make_completed(0, _list_tasks_response(tasks)),  # list-tasks
        _make_completed(0, ""),  # send-message
    ]

    team_dispatch.cmd_nudge("test-team", min_age_seconds=1)
    assert mock_run.call_count == 2
    send_call = mock_run.call_args_list[1]
    assert "send-message" in send_call[0][0]


@patch("team_dispatch.subprocess.run")
def test_nudge_skips_recent_pending_busy_and_active_workers(
    mock_run: MagicMock,
    tmp_path: Path,
) -> None:
    worker_state = (
        tmp_path / ".mainspring/state/team/test-team/workers/worker-active/status.json"
    )
    worker_state.parent.mkdir(parents=True)
    worker_state.write_text(json.dumps({"state": "working"}), encoding="utf-8")
    tasks = [
        {
            "subject": "Task Master 1 - Recent",
            "status": "pending",
            "owner": "worker-recent",
            "created_at": "2999-01-01T00:00:00Z",
        },
        {
            "subject": "Task Master 2 - Active worker",
            "status": "pending",
            "owner": "worker-active",
            "created_at": "2020-01-01T00:00:00Z",
        },
        {
            "subject": "Task Master 3 - Busy worker",
            "status": "pending",
            "owner": "worker-busy",
            "created_at": "2020-01-01T00:00:00Z",
        },
        {
            "subject": "Task Master 4 - Existing work",
            "status": "in_progress",
            "owner": "worker-busy",
        },
    ]
    mock_run.return_value = _make_completed(0, _list_tasks_response(tasks))

    with _cwd(tmp_path):
        team_dispatch.cmd_nudge("test-team", min_age_seconds=15)

    assert mock_run.call_count == 1


# ── requeue ────────────────────────────────────────────────────────────


@patch("team_dispatch.subprocess.run")
def test_requeue_api_failure(mock_run: MagicMock) -> None:
    """Requeue silently exits when list-tasks fails."""
    mock_run.return_value = _make_completed(1, "")
    team_dispatch.cmd_requeue("test-team")


@patch("team_dispatch.subprocess.run")
def test_requeue_dead_heartbeat(mock_run: MagicMock, tmp_path: Path) -> None:
    """Task with dead heartbeat gets requeued."""
    tasks = [
        {
            "subject": "Task Master 6 - Stuck",
            "status": "in_progress",
            "owner": "worker-1",
            "id": "t-6",
            "claim": {"token": "tok-1", "owner": "worker-1"},
        }
    ]

    # Create heartbeat file with alive=False
    state_dir = (
        tmp_path
        / ".mainspring"
        / "state"
        / "team"
        / "test-team"
        / "workers"
        / "worker-1"
    )
    state_dir.mkdir(parents=True)
    (state_dir / "heartbeat.json").write_text(json.dumps({"alive": False}))
    (state_dir / "status.json").write_text(json.dumps({"state": "idle"}))

    import os

    orig_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        mock_run.side_effect = [
            _make_completed(0, _list_tasks_response(tasks)),  # list-tasks
            _make_completed(0, ""),  # release-task-claim
        ]
        team_dispatch.cmd_requeue("test-team", stale_minutes=1)
        assert mock_run.call_count == 2
        release_call = mock_run.call_args_list[1]
        assert "release-task-claim" in release_call[0][0]
    finally:
        os.chdir(orig_cwd)


@patch("team_dispatch.subprocess.run")
def test_requeue_not_stale(mock_run: MagicMock) -> None:
    """In-progress task without stale signals is not requeued."""
    tasks = [
        {
            "subject": "Task Master 7 - Active",
            "status": "in_progress",
            "owner": "worker-1",
            "id": "t-7",
            "claim": {"token": "tok-2", "owner": "worker-1"},
        }
    ]
    mock_run.return_value = _make_completed(0, _list_tasks_response(tasks))
    team_dispatch.cmd_requeue("test-team")
    # Only list-tasks called, no release
    assert mock_run.call_count == 1


@patch("team_dispatch.subprocess.run")
def test_requeue_expired_idle_and_stale_heartbeat(
    mock_run: MagicMock,
    tmp_path: Path,
) -> None:
    tasks = [
        {
            "subject": "Task Master 8 - Expired",
            "status": "in_progress",
            "owner": "worker-1",
            "id": "t-8",
            "claim": {
                "token": "tok-8",
                "owner": "worker-1",
                "leased_until": "2020-01-01T00:00:00Z",
            },
        }
    ]
    state_dir = tmp_path / ".mainspring/state/team/test-team/workers/worker-1"
    state_dir.mkdir(parents=True)
    (state_dir / "status.json").write_text(
        json.dumps({"state": "idle", "updated_at": "2020-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    (state_dir / "heartbeat.json").write_text(
        json.dumps({"alive": True, "last_turn_at": "2020-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    mock_run.side_effect = [
        _make_completed(0, _list_tasks_response(tasks)),
        _make_completed(0, ""),
    ]

    with _cwd(tmp_path):
        team_dispatch.cmd_requeue("test-team", stale_minutes=1)

    assert mock_run.call_count == 2
    assert "release-task-claim" in mock_run.call_args_list[1][0][0]


# ── close-bootstrap ───────────────────────────────────────────────────


@patch("team_dispatch.subprocess.run")
def test_close_bootstrap_closes_pending_non_taskmaster_task(
    mock_run: MagicMock,
) -> None:
    """Pending bootstrap task is claimed and transitioned to completed."""
    tasks = [
        {
            "id": "bootstrap-1",
            "subject": "Bootstrap only for the coordinator",
            "status": "pending",
        },
        {
            "id": "tm-1",
            "subject": "Task Master 1 - Real work",
            "status": "pending",
        },
    ]
    mock_run.side_effect = [
        _make_completed(0, _list_tasks_response(tasks)),
        _make_completed(0, json.dumps({"data": {"claim": {"token": "claim-1"}}})),
        _make_completed(0, "{}"),
    ]

    closed = team_dispatch.cmd_close_bootstrap("test-team")

    assert closed == 1
    assert mock_run.call_count == 3
    claim_payload = json.loads(mock_run.call_args_list[1][0][0][5])
    transition_payload = json.loads(mock_run.call_args_list[2][0][0][5])
    assert claim_payload["task_id"] == "bootstrap-1"
    assert transition_payload["task_id"] == "bootstrap-1"
    assert transition_payload["from"] == "in_progress"
    assert transition_payload["to"] == "completed"
    assert transition_payload["claim_token"] == "claim-1"


@patch("team_dispatch.subprocess.run")
def test_close_bootstrap_uses_existing_claim_for_in_progress_task(
    mock_run: MagicMock,
) -> None:
    """In-progress bootstrap tasks with a token do not need a new claim."""
    tasks = [
        {
            "id": "bootstrap-2",
            "subject": "Bootstrap only for the coordinator",
            "status": "in_progress",
            "claim": {"token": "existing-token"},
        }
    ]
    mock_run.side_effect = [
        _make_completed(0, _list_tasks_response(tasks)),
        _make_completed(0, "{}"),
    ]

    closed = team_dispatch.cmd_close_bootstrap("test-team")

    assert closed == 1
    assert mock_run.call_count == 2
    transition_payload = json.loads(mock_run.call_args_list[1][0][0][5])
    assert transition_payload["from"] == "in_progress"
    assert transition_payload["claim_token"] == "existing-token"


@patch("team_dispatch.subprocess.run")
def test_close_bootstrap_ignores_taskmaster_and_completed_tasks(
    mock_run: MagicMock,
) -> None:
    """Only active non-Task-Master bootstrap tasks are closed."""
    tasks = [
        {
            "id": "tm-1",
            "subject": "Task Master 1 - Real work",
            "status": "pending",
        },
        {
            "id": "bootstrap-done",
            "subject": "Bootstrap only for the coordinator",
            "status": "completed",
        },
    ]
    mock_run.return_value = _make_completed(0, _list_tasks_response(tasks))

    closed = team_dispatch.cmd_close_bootstrap("test-team")

    assert closed == 0
    assert mock_run.call_count == 1


@patch("team_dispatch.subprocess.run")
def test_close_bootstrap_skips_invalid_claim_response(
    mock_run: MagicMock,
) -> None:
    tasks = [{"id": "bootstrap-3", "subject": "Bootstrap", "status": "pending"}]
    mock_run.side_effect = [
        _make_completed(0, _list_tasks_response(tasks)),
        _make_completed(0, "not-json"),
    ]

    assert team_dispatch.cmd_close_bootstrap("test-team") == 0
    assert mock_run.call_count == 2


@patch("team_dispatch.subprocess.run")
def test_close_bootstrap_skips_in_progress_without_token(
    mock_run: MagicMock,
) -> None:
    tasks = [{"id": "bootstrap-4", "subject": "Bootstrap", "status": "in_progress"}]
    mock_run.return_value = _make_completed(0, _list_tasks_response(tasks))

    assert team_dispatch.cmd_close_bootstrap("test-team") == 0
    assert mock_run.call_count == 1


# ── CLI entry ──────────────────────────────────────────────────────────


def test_cli_no_args() -> None:
    """No subcommand → exit 2."""
    result = subprocess.run(
        [sys.executable, SCRIPT],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_cli_unknown_subcommand() -> None:
    """Unknown subcommand → exit 2."""
    result = subprocess.run(
        [sys.executable, SCRIPT, "bogus"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_cli_dispatch_missing_args() -> None:
    """dispatch without enough args → exit 2."""
    result = subprocess.run(
        [sys.executable, SCRIPT, "dispatch", "team"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_cli_dispatch_parses_retry_task_flags() -> None:
    """dispatch forwards repeated --retry-task ids to cmd_dispatch."""
    with patch("team_dispatch.cmd_dispatch") as mock_dispatch:
        team_dispatch.main(
            [
                "dispatch",
                "test-team",
                "2",
                "{}",
                "--retry-task",
                "1",
                "--retry-task",
                "2",
            ]
        )

    mock_dispatch.assert_called_once_with("test-team", 2, "{}", frozenset({"1", "2"}))


def test_cli_dispatch_invalid_team_size_defaults_to_one() -> None:
    with patch("team_dispatch.cmd_dispatch") as mock_dispatch:
        team_dispatch.main(["dispatch", "test-team", "bad", "{}"])

    mock_dispatch.assert_called_once_with("test-team", 1, "{}", frozenset())


def test_cli_dispatch_rejects_unknown_retry_arg() -> None:
    """dispatch rejects unknown trailing args instead of ignoring them."""
    try:
        team_dispatch.main(["dispatch", "test-team", "2", "{}", "--bogus"])
        raised = False
    except SystemExit as exc:
        raised = True
        assert exc.code == 2
    assert raised


def test_cli_counts_missing_args() -> None:
    """counts without team_name → exit 2."""
    result = subprocess.run(
        [sys.executable, SCRIPT, "counts"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_cli_nudge_missing_args() -> None:
    """nudge without team_name → exit 2."""
    result = subprocess.run(
        [sys.executable, SCRIPT, "nudge"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_cli_requeue_missing_args() -> None:
    """requeue without team_name → exit 2."""
    result = subprocess.run(
        [sys.executable, SCRIPT, "requeue"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
