# SPDX-License-Identifier: Apache-2.0
"""Tests for taskmaster.py — Taskmaster JSON operations."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import taskmaster

LEGACY_ENV_PREFIX = "OMX" + "_LOOP_"

SCRIPT = str(HERE.parent / "taskmaster.py")


def _write_tasks(tmp_path: Path, tasks: list[dict]) -> str:
    f = tmp_path / "tasks.json"
    f.write_text(json.dumps({"master": {"tasks": tasks}}))
    return str(f)


def _write_tagged_tasks(
    tmp_path: Path, tags: dict[str, list[dict]], current_tag: str
) -> str:
    taskmaster_dir = tmp_path / ".taskmaster"
    tasks_dir = taskmaster_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    (taskmaster_dir / "state.json").write_text(
        json.dumps({"currentTag": current_tag}), encoding="utf-8"
    )
    tasks_file = tasks_dir / "tasks.json"
    tasks_file.write_text(
        json.dumps({tag: {"tasks": tasks} for tag, tasks in tags.items()}),
        encoding="utf-8",
    )
    return str(tasks_file)


def _missing_default_tasks_file(tmp_path: Path) -> str:
    return str(tmp_path / ".taskmaster" / "tasks" / "tasks.json")


def _capture_readiness_command(command: str, tasks_file: str) -> tuple[int | None, str]:
    handlers = {
        "next": taskmaster.cmd_next,
        "status-summary": taskmaster.cmd_status_summary,
        "scope-summary": taskmaster.cmd_scope_summary,
        "fallback-next": taskmaster.cmd_fallback_next,
        "collect-parallel": taskmaster.cmd_collect_parallel,
        "team-skip-reason": taskmaster.cmd_team_skip_reason,
    }
    output = io.StringIO()
    before = Path(tasks_file).read_bytes()
    with redirect_stdout(output):
        result = handlers[command](tasks_file)
    assert Path(tasks_file).read_bytes() == before
    return result, output.getvalue()


@pytest.mark.parametrize(
    "command",
    [
        "next",
        "status-summary",
        "scope-summary",
        "fallback-next",
        "collect-parallel",
        "team-skip-reason",
    ],
)
@pytest.mark.parametrize(
    "dependencies",
    ["12", "", False, True, 0, 12, {}, {"1": "done", "2": "done"}],
)
def test_readiness_commands_reject_non_array_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    dependencies: object,
) -> None:
    monkeypatch.setenv("MAINSPRING_TASKMASTER_TAG", "master")
    monkeypatch.setenv("MAINSPRING_TEAM_EXCLUDE_PREFIXES", "")
    target = {
        "id": 20,
        "status": "in-progress",
        "title": "Dependent",
        "details": ".claude/hidden.py"
        if command == "team-skip-reason"
        else "src/dependent.py",
        "dependencies": [12],
    }
    tasks = [
        {"id": 1, "status": "done"},
        {"id": 2, "status": "done"},
        {
            "id": 12,
            "status": "pending",
            "dependencies": [],
            "details": "src/prerequisite.py",
        },
        target,
    ]
    path = _write_tasks(tmp_path, tasks)
    control = _capture_readiness_command(command, path)
    if command == "next":
        assert control == (0, "12\n")
    elif command == "collect-parallel":
        assert [json.loads(line)["id"] for line in control[1].splitlines()] == ["12"]
    elif command == "team-skip-reason":
        assert control[1].strip() == ""
    target["dependencies"] = dependencies
    _write_tasks(tmp_path, tasks)

    assert _capture_readiness_command(command, path) == control


@pytest.mark.parametrize(
    "command",
    [
        "next",
        "status-summary",
        "scope-summary",
        "fallback-next",
        "collect-parallel",
        "team-skip-reason",
    ],
)
@pytest.mark.parametrize("shape", ["missing", "null", "empty"])
def test_readiness_commands_preserve_optional_dependency_collections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    shape: str,
) -> None:
    monkeypatch.setenv("MAINSPRING_TASKMASTER_TAG", "master")
    monkeypatch.setenv("MAINSPRING_TEAM_EXCLUDE_PREFIXES", "")
    target = {
        "id": 20,
        "status": "in-progress",
        "details": ".claude/hidden.py"
        if command == "team-skip-reason"
        else "src/dependent.py",
        "dependencies": [],
    }
    tasks = [{"id": 12, "status": "pending", "details": "src/prerequisite.py"}, target]
    path = _write_tasks(tmp_path, tasks)
    control = _capture_readiness_command(command, path)
    if command == "next":
        assert control == (0, "20\n")
    if shape == "missing":
        del target["dependencies"]
    elif shape == "null":
        target["dependencies"] = None
    _write_tasks(tmp_path, tasks)

    assert _capture_readiness_command(command, path) == control


@pytest.mark.parametrize("subtask", [False, True])
@pytest.mark.parametrize("shape", ["scalar", "array", "null", "missing", "empty"])
def test_public_next_rejects_scalar_dependencies_before_prd_priority(
    tmp_path: Path,
    subtask: bool,
    shape: str,
) -> None:
    prerequisite = {
        "id": 12,
        "status": "pending",
        "title": "P2 prerequisite",
        "dependencies": [],
    }
    target = {
        "id": 20,
        "status": "pending",
        "title": "P1 dependent",
        "dependencies": [],
    }
    if shape == "scalar":
        target["dependencies"] = "12"
    elif shape == "array":
        target["dependencies"] = [12]
    elif shape == "null":
        target["dependencies"] = None
    elif shape == "missing":
        del target["dependencies"]
    if subtask:
        target["id"] = 13
        tasks = [
            {
                "id": 20,
                "status": "pending",
                "subtasks": [
                    {"id": 1, "status": "done"},
                    {"id": 2, "status": "done"},
                    prerequisite,
                    target,
                ],
            }
        ]
        expected = "20.12" if shape in {"scalar", "array"} else "20.13"
    else:
        tasks = [
            {"id": 1, "status": "done"},
            {"id": 2, "status": "done"},
            prerequisite,
            target,
        ]
        expected = "12" if shape in {"scalar", "array"} else "20"
    path = _write_tasks(tmp_path, tasks)
    active = tmp_path / "active-prd.json"
    active.write_text(json.dumps({"active_phase": "P1", "phase_order": ["P1", "P2"]}))
    runtime = tmp_path / ".mainspring"
    protected = {key: os.environ.get(key) for key in ("HOME", "home", "CODEX_HOME")}
    env = {
        **os.environ,
        "MAINSPRING_PY": sys.executable,
        "MAINSPRING_RUNTIME_PYTHON": sys.executable,
        "MAINSPRING_TASKMASTER_TAG": "master",
        "MAINSPRING_RUNTIME_DIR": str(runtime),
        "MAINSPRING_STATE_DIR": str(runtime / "state"),
    }
    before = Path(path).read_bytes()

    result = subprocess.run(
        [
            "/bin/bash",
            str(HERE.parent.parent / "mainspring.sh"),
            "--project",
            str(tmp_path),
            "next",
            path,
            "--active-prd",
            str(active),
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
    assert Path(path).read_bytes() == before
    assert {key: os.environ.get(key) for key in protected} == protected


# ── status-summary ─────────────────────────────────────────────────────


def test_status_summary_counts(tmp_path: Path) -> None:
    tasks = [
        {"id": 1, "status": "done", "subtasks": []},
        {"id": 2, "status": "pending", "dependencies": []},
        {"id": 3, "status": "in-progress", "dependencies": []},
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_status_summary(path)
    out = buf.getvalue()
    assert "done=1" in out
    assert "pending=1" in out
    assert "in-progress=1" in out


def test_status_summary_stop_blocked(tmp_path: Path) -> None:
    tasks = [
        {"id": 1, "status": "done"},
        {"id": 2, "status": "pending", "dependencies": [99]},
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_status_summary(path)
    assert "STOP_BLOCKED" in buf.getvalue()


def test_status_summary_select_implementation(tmp_path: Path) -> None:
    tasks = [{"id": 1, "status": "pending", "dependencies": []}]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_status_summary(path)
    assert "SELECT_IMPLEMENTATION" in buf.getvalue()


def test_status_summary_integrity_warning(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "status": "done",
            "subtasks": [{"id": 1, "status": "pending"}],
        },
        {"id": 2, "status": "pending", "dependencies": []},
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_status_summary(path)
    assert "REPAIR_STATUS" in buf.getvalue()


def test_status_summary_prints_unreadable_error_on_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    path.write_text("{bad json", encoding="utf-8")
    buf = io.StringIO()

    with redirect_stdout(buf):
        taskmaster.cmd_status_summary(str(path))

    assert "Taskmaster: unreadable" in buf.getvalue()


def test_status_summary_repair_status_for_unmet_subtask_deps(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "title": "Parent",
            "dependencies": [],
            "subtasks": [
                {"id": 1, "status": "pending", "dependencies": [99]},
                {"id": 2, "status": "blocked", "dependencies": []},
            ],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()

    with redirect_stdout(buf):
        taskmaster.cmd_status_summary(path)

    output = buf.getvalue()
    assert "REPAIR_STATUS #1 Parent" in output
    assert "1.1 status=pending has unmet subtask dependencies" in output


# ── scope-summary ──────────────────────────────────────────────────────


def test_scope_summary_basic(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "dependencies": [],
            "title": "Fix src/App.tsx",
            "subtasks": [],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_scope_summary(path)
    out = buf.getvalue()
    assert "scope: selected=#1" in out
    assert "src/App.tsx" in out


def test_scope_summary_excluded_prefix_warning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MAINSPRING_TEAM_EXCLUDE_PREFIXES", "plugins/example-plugin")
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "dependencies": [],
            "title": "Update plugins/example-plugin/README",
            "subtasks": [],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_scope_summary(path, plugins_ignored=True)
    assert "scope warning" in buf.getvalue()
    assert "plugins/example-plugin" in buf.getvalue()


def test_scope_summary_no_ready_top_level_item(tmp_path: Path) -> None:
    path = _write_tasks(
        tmp_path,
        [{"id": 1, "status": "blocked", "dependencies": [], "title": "Blocked"}],
    )
    buf = io.StringIO()

    with redirect_stdout(buf):
        taskmaster.cmd_scope_summary(path)

    assert buf.getvalue().strip() == "scope: no ready top-level Taskmaster item"


def test_scope_summary_missing_default_task_file_is_operator_friendly(
    tmp_path: Path,
) -> None:
    path = _missing_default_tasks_file(tmp_path)
    buf = io.StringIO()

    with redirect_stdout(buf):
        taskmaster.cmd_scope_summary(path)

    output = buf.getvalue()
    assert (
        "scope: Taskmaster backlog not found at .taskmaster/tasks/tasks.json" in output
    )
    assert "mainspring init checkout-redesign" in output
    assert "replace checkout-redesign with your feature name" in output
    assert "mainspring init <name>" not in output
    assert str(tmp_path) not in output
    assert "Errno" not in output


def test_scope_summary_selects_ready_subtask_when_parent_has_children(
    tmp_path: Path,
) -> None:
    path = _write_tasks(
        tmp_path,
        [
            {
                "id": 1,
                "status": "pending",
                "dependencies": [],
                "title": "Parent",
                "description": "Update docs/parent.md",
                "subtasks": [
                    {"id": 1, "status": "done", "description": "Done"},
                    {
                        "id": 2,
                        "status": "review",
                        "dependencies": [],
                        "description": "Review docs/child.md",
                    },
                ],
            }
        ],
    )
    buf = io.StringIO()

    with redirect_stdout(buf):
        taskmaster.cmd_scope_summary(path)

    output = buf.getvalue()
    assert "scope: selected=#1.2" in output
    assert "docs/child.md" in output


def test_taskmaster_helper_branches_cover_env_and_active_prd_shapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MAINSPRING_TEAM_EXCLUDE_PREFIXES", raising=False)
    monkeypatch.delenv(f"{LEGACY_ENV_PREFIX}TEAM_EXCLUDE_PREFIXES", raising=False)
    assert ".claude" in taskmaster._team_exclude_prefixes()

    monkeypatch.setenv(
        f"{LEGACY_ENV_PREFIX}TEAM_EXCLUDE_PREFIXES",
        "tmp/legacy, ./logs/runtime/",
    )
    prefixes = taskmaster._team_exclude_prefixes()
    assert "tmp/legacy" not in prefixes
    assert "logs/runtime" not in prefixes

    monkeypatch.setenv(
        "MAINSPRING_TEAM_EXCLUDE_PREFIXES", "tmp/public, ./logs/runtime/"
    )
    prefixes = taskmaster._team_exclude_prefixes()
    assert "tmp/public" in prefixes
    assert "logs/runtime" in prefixes

    monkeypatch.setenv("MAINSPRING_TEAM_EXCLUDE_PREFIXES", "")
    assert taskmaster._team_exclude_prefixes() == [".claude"]

    assert taskmaster._int_or_zero("bad") == 0
    assert taskmaster._title_is_vague("improve dashboard")
    assert not taskmaster._title_is_vague("fix the onboarding dashboard empty state")
    assert taskmaster._has_acceptance_criteria(
        {"details": "Acceptance criteria: state is visible."}
    )
    assert taskmaster._has_test_plan({"details": "Test plan: run pytest."})
    assert taskmaster._has_test_plan({"testStrategy": "pytest"})
    assert taskmaster._declares_oversized_effort(
        {"details": "Estimated effort: > 1 day"}
    )
    assert taskmaster._contains_manual_blocker(
        {"details": "Requires API key from ops."}
    )

    assert taskmaster._load_active_prd_state(None) == ("", [])
    assert taskmaster._load_active_prd_state(str(tmp_path / "missing.json")) == ("", [])

    invalid = tmp_path / "active-invalid.json"
    invalid.write_text("{bad json", encoding="utf-8")
    assert taskmaster._load_active_prd_state(str(invalid)) == ("", [])

    active = tmp_path / "active-prd.json"
    active.write_text(
        json.dumps(
            {
                "current_phase": "P2",
                "phases": [{"id": "P1"}, {"name": "P2"}, {"title": "P3"}, None],
            }
        ),
        encoding="utf-8",
    )
    assert taskmaster._load_active_prd_state(str(active)) == ("P2", ["P1", "P2", "P3"])


def test_phase_score_orders_current_past_future_and_unknown_phase() -> None:
    phase_order = ["P1 Plan", "P2 Build", "P3 Ship"]

    assert taskmaster._phase_score("P2 build work", "P2 Build", phase_order) == 0
    assert taskmaster._phase_score("P3 ship work", "P2 Build", phase_order) == 22
    assert taskmaster._phase_score("P1 plan work", "P2 Build", phase_order) == 10
    assert taskmaster._phase_score("P1 plan work", "Missing", phase_order) == 5
    assert taskmaster._phase_score("no phase label", "P2 Build", phase_order) == 1
    assert taskmaster._phase_score("P2 build work", "", phase_order) == 0


def test_taskmaster_subcommands_use_active_tag_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MAINSPRING_TASKMASTER_TAG", raising=False)
    monkeypatch.setenv("MAINSPRING_TEAM_EXCLUDE_PREFIXES", "plugins/example-plugin")
    path = _write_tagged_tasks(
        tmp_path,
        {
            "master": [
                {
                    "id": 1,
                    "status": "pending",
                    "dependencies": [],
                    "title": "Master backlog item",
                    "subtasks": [],
                }
            ],
            "release": [
                {
                    "id": 7,
                    "status": "pending",
                    "dependencies": [],
                    "title": "Release parent",
                    "description": "Edit docs/release.md",
                    "subtasks": [
                        {
                            "id": 1,
                            "status": "review",
                            "dependencies": [],
                            "title": "Tagged child",
                            "description": "Review docs/tagged.md",
                        }
                    ],
                },
                {
                    "id": 8,
                    "status": "pending",
                    "dependencies": [],
                    "title": "Plugin work",
                    "description": "Edit plugins/example-plugin/Panel.java",
                    "subtasks": [],
                },
                {
                    "id": 10,
                    "status": "pending",
                    "dependencies": [],
                    "title": "Rollup parent",
                    "subtasks": [
                        {"id": 1, "status": "done"},
                        {"id": 2, "status": "done"},
                    ],
                },
            ],
        },
        "release",
    )

    status = io.StringIO()
    with redirect_stdout(status):
        taskmaster.cmd_status_summary(path)
    assert "scheduler: SELECT_REVIEW #7.1 from parent #7 Release parent" in (
        status.getvalue()
    )

    metadata = io.StringIO()
    with redirect_stdout(metadata):
        taskmaster.cmd_task_metadata(path, "7.1")
    assert metadata.getvalue().splitlines() == ["Tagged child", "Review docs/tagged.md"]

    item_status = io.StringIO()
    with redirect_stdout(item_status):
        taskmaster.cmd_task_status(path, "7.1")
    assert item_status.getvalue().strip() == "review"

    work_item = io.StringIO()
    with redirect_stdout(work_item):
        taskmaster.cmd_pick_work_item(path, "7")
    assert work_item.getvalue().strip() == "7.1"

    rollup = io.StringIO()
    with redirect_stdout(rollup):
        taskmaster.cmd_parent_rollup(path, "10")
    assert rollup.getvalue().strip() == "done"

    next_item = io.StringIO()
    with redirect_stdout(next_item):
        exit_code = taskmaster.cmd_next(path)
    assert exit_code == 0
    assert next_item.getvalue().strip() == "8"

    fallback = io.StringIO()
    with redirect_stdout(fallback):
        taskmaster.cmd_fallback_next(path)
    assert fallback.getvalue().strip() == "7"

    parallel = io.StringIO()
    with redirect_stdout(parallel):
        taskmaster.cmd_collect_parallel(path, limit=6)
    assert json.loads(parallel.getvalue().splitlines()[0])["id"] == "7.1"

    skip_reason = io.StringIO()
    with redirect_stdout(skip_reason):
        taskmaster.cmd_team_skip_reason(path)
    assert skip_reason.getvalue().strip() == "routing:plugin_invisible"


def test_taskmaster_tag_env_override_wins_over_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_tagged_tasks(
        tmp_path,
        {
            "master": [
                {
                    "id": 1,
                    "status": "pending",
                    "dependencies": [],
                    "title": "State tag item",
                    "subtasks": [],
                }
            ],
            "release": [
                {
                    "id": 2,
                    "status": "pending",
                    "dependencies": [],
                    "title": "Env tag item",
                    "subtasks": [],
                }
            ],
        },
        "master",
    )
    monkeypatch.setenv("MAINSPRING_TASKMASTER_TAG", "release")

    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_status_summary(path)

    assert "scheduler: SELECT_IMPLEMENTATION #2 Env tag item" in buf.getvalue()


# ── task-metadata ──────────────────────────────────────────────────────


def test_task_metadata_found(tmp_path: Path) -> None:
    tasks = [{"id": 5, "title": "My Task", "description": "Do stuff"}]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_task_metadata(path, "5")
    lines = buf.getvalue().strip().splitlines()
    assert lines[0] == "My Task"
    assert lines[1] == "Do stuff"


def test_task_metadata_subtask(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 3,
            "title": "Parent",
            "subtasks": [{"id": 2, "title": "Child", "description": "Sub desc"}],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_task_metadata(path, "3.2")
    assert "Child" in buf.getvalue()


def test_task_metadata_not_found(tmp_path: Path) -> None:
    tasks = [{"id": 1, "title": "X"}]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_task_metadata(path, "99")
    assert buf.getvalue().strip() == ""


# ── task-status ────────────────────────────────────────────────────────


def test_task_status_found(tmp_path: Path) -> None:
    tasks = [{"id": 5, "status": "review", "subtasks": []}]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_task_status(path, "5")
    assert buf.getvalue().strip() == "review"


def test_task_status_subtask(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 3,
            "status": "pending",
            "subtasks": [{"id": 2, "status": "in-progress"}],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_task_status(path, "3.2")
    assert buf.getvalue().strip() == "in-progress"


def test_task_status_not_found(tmp_path: Path) -> None:
    tasks = [{"id": 5, "status": "review", "subtasks": []}]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_task_status(path, "9")
    assert buf.getvalue() == ""


# ── pick-work-item ─────────────────────────────────────────────────────


def test_pick_work_item_with_subtask(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "subtasks": [
                {"id": 1, "status": "done"},
                {"id": 2, "status": "pending", "dependencies": []},
            ],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_pick_work_item(path, "1")
    assert buf.getvalue().strip() == "1.2"


def test_pick_work_item_no_subs(tmp_path: Path) -> None:
    tasks = [{"id": 1, "subtasks": []}]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_pick_work_item(path, "1")
    assert buf.getvalue().strip() == "1"


def test_pick_work_item_all_done(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "subtasks": [{"id": 1, "status": "done"}],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_pick_work_item(path, "1")
    assert buf.getvalue().strip() == ""


def test_pick_work_item_for_missing_parent_prints_target_id(tmp_path: Path) -> None:
    path = _write_tasks(tmp_path, [{"id": 1, "subtasks": []}])
    buf = io.StringIO()

    with redirect_stdout(buf):
        taskmaster.cmd_pick_work_item(path, "99")

    assert buf.getvalue().strip() == "99"


# ── parent-rollup ─────────────────────────────────────────────────────


def test_parent_rollup_done(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "subtasks": [
                {"id": 1, "status": "done"},
                {"id": 2, "status": "done"},
            ],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_parent_rollup(path, "1")
    assert buf.getvalue().strip() == "done"


def test_parent_rollup_blocked(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "subtasks": [
                {"id": 1, "status": "done"},
                {"id": 2, "status": "blocked"},
            ],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_parent_rollup(path, "1")
    assert buf.getvalue().strip() == "blocked"


def test_parent_rollup_active(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "subtasks": [
                {"id": 1, "status": "done"},
                {"id": 2, "status": "pending"},
            ],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_parent_rollup(path, "1")
    assert buf.getvalue().strip() == ""


def test_parent_rollup_missing_task_prints_empty(tmp_path: Path) -> None:
    path = _write_tasks(tmp_path, [{"id": 1, "subtasks": []}])
    buf = io.StringIO()

    with redirect_stdout(buf):
        taskmaster.cmd_parent_rollup(path, "99")

    assert buf.getvalue().strip() == ""


def test_parent_rollup_no_subtasks_prints_empty(tmp_path: Path) -> None:
    path = _write_tasks(tmp_path, [{"id": 1, "subtasks": []}])
    buf = io.StringIO()

    with redirect_stdout(buf):
        taskmaster.cmd_parent_rollup(path, "1")

    assert buf.getvalue().strip() == ""


# ── next ───────────────────────────────────────────────────────────────


def test_next_skips_blocked_task(tmp_path: Path) -> None:
    tasks = [
        {"id": 1, "status": "blocked", "dependencies": [], "title": "Blocked"},
        {"id": 2, "status": "pending", "dependencies": [], "title": "Ready"},
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = taskmaster.cmd_next(path)

    assert exit_code == 0
    assert buf.getvalue().strip() == "2"


def test_next_skips_unmet_dependencies(tmp_path: Path) -> None:
    tasks = [
        {"id": 1, "status": "pending", "dependencies": [99], "title": "Blocked"},
        {"id": 2, "status": "pending", "dependencies": [], "title": "Ready"},
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = taskmaster.cmd_next(path)

    assert exit_code == 0
    assert buf.getvalue().strip() == "2"


def test_next_returns_ready_subtask(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "dependencies": [],
            "title": "Parent",
            "subtasks": [
                {"id": 1, "status": "blocked"},
                {"id": 2, "status": "pending", "dependencies": []},
            ],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = taskmaster.cmd_next(path)

    assert exit_code == 0
    assert buf.getvalue().strip() == "1.2"


def test_next_prefers_active_prd_phase(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "dependencies": [],
            "title": "P2 Later phase task",
            "subtasks": [],
        },
        {
            "id": 2,
            "status": "pending",
            "dependencies": [],
            "title": "P1 Current phase task",
            "subtasks": [],
        },
    ]
    path = _write_tasks(tmp_path, tasks)
    active_prd = tmp_path / "active-prd.json"
    active_prd.write_text(
        json.dumps({"active_phase": "P1", "phase_order": ["P1", "P2"]})
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = taskmaster.cmd_next(path, str(active_prd))

    assert exit_code == 0
    assert buf.getvalue().strip() == "2"


def test_next_cli_exits_one_when_no_ready_work(tmp_path: Path) -> None:
    path = _write_tasks(
        tmp_path,
        [{"id": 1, "status": "blocked", "dependencies": [], "title": "Blocked"}],
    )

    result = subprocess.run(
        [sys.executable, SCRIPT, "next", path],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""


def test_next_active_prd_missing_path_errors_out(tmp_path: Path) -> None:
    path = _write_tasks(
        tmp_path,
        [{"id": 1, "status": "pending", "dependencies": [], "title": "Ready"}],
    )

    result = subprocess.run(
        [sys.executable, SCRIPT, "next", path, "--active-prd"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Usage: --active-prd requires a path" in result.stderr


def test_next_skips_unready_subtask_before_ready_sibling(tmp_path: Path) -> None:
    path = _write_tasks(
        tmp_path,
        [
            {
                "id": 1,
                "status": "pending",
                "dependencies": [],
                "title": "Parent",
                "subtasks": [
                    {"id": 1, "status": "pending", "dependencies": [99]},
                    {"id": 2, "status": "pending", "dependencies": []},
                ],
            }
        ],
    )
    buf = io.StringIO()

    with redirect_stdout(buf):
        exit_code = taskmaster.cmd_next(path)

    assert exit_code == 0
    assert buf.getvalue().strip() == "1.2"


def test_next_unreadable_task_file_returns_two(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    path.write_text("{bad json", encoding="utf-8")
    buf = io.StringIO()
    err = io.StringIO()

    with redirect_stdout(buf), redirect_stderr(err):
        exit_code = taskmaster.cmd_next(str(path))

    assert exit_code == 2
    assert buf.getvalue() == ""
    assert "next: Taskmaster backlog is not valid JSON: tasks.json" in err.getvalue()
    assert str(tmp_path) not in err.getvalue()
    assert "Errno" not in err.getvalue()


def test_next_missing_default_task_file_is_operator_friendly(tmp_path: Path) -> None:
    path = _missing_default_tasks_file(tmp_path)
    buf = io.StringIO()
    err = io.StringIO()

    with redirect_stdout(buf), redirect_stderr(err):
        exit_code = taskmaster.cmd_next(path)

    assert exit_code == 2
    assert buf.getvalue() == ""
    output = err.getvalue()
    assert (
        "next: Taskmaster backlog not found at .taskmaster/tasks/tasks.json" in output
    )
    assert "mainspring init checkout-redesign" in output
    assert "replace checkout-redesign with your feature name" in output
    assert "mainspring init <name>" not in output
    assert str(tmp_path) not in output
    assert "Errno" not in output


# ── fallback-next ──────────────────────────────────────────────────────


def test_fallback_next_picks_first(tmp_path: Path) -> None:
    tasks = [
        {"id": 1, "status": "done"},
        {"id": 2, "status": "pending", "dependencies": [1]},
        {"id": 3, "status": "pending", "dependencies": [1]},
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_fallback_next(path)
    assert buf.getvalue().strip() == "2"


def test_fallback_next_empty(tmp_path: Path) -> None:
    tasks = [{"id": 1, "status": "done"}]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_fallback_next(path)
    assert buf.getvalue().strip() == ""


def test_fallback_next_skips_parent_with_no_actionable_rollup_path(
    tmp_path: Path,
) -> None:
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "dependencies": [],
            "subtasks": [{"id": 1, "status": "blocked"}],
        },
        {"id": 2, "status": "pending", "dependencies": [], "subtasks": []},
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()

    with redirect_stdout(buf):
        taskmaster.cmd_fallback_next(path)

    assert buf.getvalue().strip() == "2"


# ── collect-parallel ───────────────────────────────────────────────────


def test_collect_parallel_basic(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "dependencies": [],
            "title": "Task A",
            "description": "Fix src/main.tsx",
            "subtasks": [
                {
                    "id": 1,
                    "status": "pending",
                    "dependencies": [],
                    "title": "Sub A",
                    "description": "Edit src/main.tsx",
                }
            ],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_collect_parallel(path, limit=2)
    lines = buf.getvalue().strip().splitlines()
    assert len(lines) >= 1
    item = json.loads(lines[0])
    assert item["id"] == "1.1"


def test_collect_parallel_scope_conflict(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "dependencies": [],
            "title": "Task A",
            "description": "Fix src/main.tsx",
            "subtasks": [],
        },
        {
            "id": 2,
            "status": "pending",
            "dependencies": [],
            "title": "Task B",
            "description": "Fix src/main.tsx",
            "subtasks": [],
        },
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_collect_parallel(path, limit=4)
    lines = buf.getvalue().strip().splitlines()
    # Second task conflicts on scope, should only get 1
    assert len(lines) == 1


def test_collect_parallel_skips_team_excluded_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MAINSPRING_TEAM_EXCLUDE_PREFIXES", "plugins/example-plugin")
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "dependencies": [],
            "title": "Plugin release work",
            "description": "Edit plugins/example-plugin/Panel.java",
            "subtasks": [],
        },
        {
            "id": 2,
            "status": "pending",
            "dependencies": [],
            "title": "Docs work",
            "description": "Edit docs/guide.md",
            "subtasks": [],
        },
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_collect_parallel(path, limit=4)
    lines = buf.getvalue().strip().splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == "2"


def test_collect_parallel_skips_claude_helper_worktree_by_default(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("MAINSPRING_TEAM_EXCLUDE_PREFIXES", raising=False)
    monkeypatch.delenv(f"{LEGACY_ENV_PREFIX}TEAM_EXCLUDE_PREFIXES", raising=False)
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "dependencies": [],
            "title": "Local helper worktree",
            "description": "Edit .claude/worktrees/agent/tmp.md",
            "subtasks": [],
        },
        {
            "id": 2,
            "status": "pending",
            "dependencies": [],
            "title": "Docs work",
            "description": "Edit docs/guide.md",
            "subtasks": [],
        },
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_collect_parallel(path, limit=4)
    lines = buf.getvalue().strip().splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == "2"


def test_collect_parallel_uses_mainspring_team_exclude_prefixes(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MAINSPRING_TEAM_EXCLUDE_PREFIXES", "docs/private")
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "dependencies": [],
            "title": "Private docs",
            "description": "Edit docs/private/plan.md",
            "subtasks": [],
        },
        {
            "id": 2,
            "status": "pending",
            "dependencies": [],
            "title": "Public docs",
            "description": "Edit docs/guide.md",
            "subtasks": [],
        },
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_collect_parallel(path, limit=4)
    lines = buf.getvalue().strip().splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == "2"


def test_team_skip_reason_reports_plugin_invisible_for_ready_excluded_work(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MAINSPRING_TEAM_EXCLUDE_PREFIXES", "plugins/example-plugin")
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "dependencies": [],
            "title": "Plugin release work",
            "description": "Edit plugins/example-plugin/Panel.java",
            "subtasks": [],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_team_skip_reason(path)

    assert buf.getvalue().strip() == "routing:plugin_invisible"


def test_team_skip_reason_empty_when_parallel_safe_work_exists(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "dependencies": [],
            "title": "Docs work",
            "description": "Edit docs/guide.md",
            "subtasks": [],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        taskmaster.cmd_team_skip_reason(path)

    assert buf.getvalue().strip() == ""


def test_collect_parallel_cli_invalid_limit_falls_back_to_default(
    tmp_path: Path,
) -> None:
    path = _write_tasks(
        tmp_path,
        [
            {
                "id": task_id,
                "status": "pending",
                "dependencies": [],
                "title": f"Task {task_id}",
                "description": f"Edit docs/task-{task_id}.md",
                "subtasks": [],
            }
            for task_id in range(1, 6)
        ],
    )

    result = subprocess.run(
        [sys.executable, SCRIPT, "collect-parallel", path, "--limit", "not-int"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert len(result.stdout.strip().splitlines()) == 4


def test_collect_parallel_clamps_limit_and_uses_taskmaster_scope(
    tmp_path: Path,
) -> None:
    path = _write_tasks(
        tmp_path,
        [
            {
                "id": task_id,
                "status": "pending",
                "dependencies": [],
                "title": f"Generic task {task_id}",
                "subtasks": [],
            }
            for task_id in range(1, 9)
        ],
    )

    high = io.StringIO()
    with redirect_stdout(high):
        taskmaster.cmd_collect_parallel(path, limit=99)
    high_items = [json.loads(line) for line in high.getvalue().strip().splitlines()]
    assert len(high_items) == 6
    assert high_items[0]["scope"] == [".taskmaster/1"]

    low = io.StringIO()
    with redirect_stdout(low):
        taskmaster.cmd_collect_parallel(path, limit=0)
    assert len(low.getvalue().strip().splitlines()) == 1


def test_team_skip_reason_reports_excluded_ready_subtask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAINSPRING_TEAM_EXCLUDE_PREFIXES", "plugins/example-plugin")
    path = _write_tasks(
        tmp_path,
        [
            {
                "id": 1,
                "status": "pending",
                "dependencies": [],
                "title": "Parent",
                "subtasks": [
                    {
                        "id": 1,
                        "status": "pending",
                        "dependencies": [],
                        "description": "Edit plugins/example-plugin/Panel.java",
                    }
                ],
            }
        ],
    )
    buf = io.StringIO()

    with redirect_stdout(buf):
        taskmaster.cmd_team_skip_reason(path)

    assert buf.getvalue().strip() == "routing:plugin_invisible"


# ── scope-check ────────────────────────────────────────────────────────


def test_scope_check_flags_vague_title(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "title": "improve dashboard",
            "details": "Acceptance criteria: dashboard empty state names the next action.",
            "testStrategy": "Run npx vitest run tests/components/tabs/dashboard.test.tsx.",
            "subtasks": [],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = taskmaster.cmd_scope_check(path)

    assert exit_code == 1
    assert "vague-title" in buf.getvalue()


def test_scope_check_clean_backlog_reports_zero(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "title": "Render dashboard empty state",
            "details": (
                "Acceptance criteria: empty state shows one concrete CTA. "
                "Estimated effort: 30 min - 2 hrs."
            ),
            "testStrategy": "Run npx vitest run tests/components/tabs/dashboard.test.tsx.",
            "subtasks": [],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = taskmaster.cmd_scope_check(path)

    assert exit_code == 0
    assert "scope-check: 0 violations" in buf.getvalue()


def test_scope_check_flags_manual_blocker_before_last_phase(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "status": "blocked",
            "title": "Configure production API key",
            "details": "Acceptance criteria: API key is present. Test plan: manual verification.",
            "testStrategy": "Manual verification only.",
            "subtasks": [],
        },
        {
            "id": 2,
            "status": "pending",
            "title": "Final release checklist",
            "details": "Acceptance criteria: release notes exist.",
            "testStrategy": "Review the release notes.",
            "subtasks": [],
        },
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = taskmaster.cmd_scope_check(path)

    assert exit_code == 1
    assert "manual-blocker-phase" in buf.getvalue()


def test_scope_check_flags_missing_acceptance_and_tests(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "title": "Render dashboard empty state",
            "description": "Show a useful dashboard fallback.",
            "subtasks": [],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = taskmaster.cmd_scope_check(path)

    output = buf.getvalue()
    assert exit_code == 1
    assert "missing-acceptance" in output
    assert "missing-test-plan" in output


def test_scope_check_flags_oversized_effort(tmp_path: Path) -> None:
    tasks = [
        {
            "id": 1,
            "status": "pending",
            "title": "Render dashboard empty state",
            "details": (
                "Acceptance criteria: empty state shows one concrete CTA. "
                "Estimated effort: > half-day."
            ),
            "testStrategy": "Run npx vitest run tests/components/tabs/dashboard.test.tsx.",
            "subtasks": [],
        }
    ]
    path = _write_tasks(tmp_path, tasks)
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = taskmaster.cmd_scope_check(path)

    assert exit_code == 1
    assert "oversized-effort" in buf.getvalue()


def test_scope_check_cli_exits_nonzero_for_high_violations(tmp_path: Path) -> None:
    path = _write_tasks(
        tmp_path,
        [
            {
                "id": 1,
                "status": "pending",
                "title": "improve dashboard",
                "details": "Acceptance criteria: dashboard names the next action.",
                "testStrategy": "Run npx vitest run tests/components/tabs/dashboard.test.tsx.",
                "subtasks": [],
            }
        ],
    )

    result = subprocess.run(
        [sys.executable, SCRIPT, "scope-check", path],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "vague-title" in result.stdout


def test_scope_check_unreadable_task_file_returns_2(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    path.write_text("{bad json", encoding="utf-8")
    buf = io.StringIO()

    with redirect_stdout(buf):
        exit_code = taskmaster.cmd_scope_check(str(path))

    assert exit_code == 2
    assert (
        "scope-check: Taskmaster backlog is not valid JSON: tasks.json"
        in buf.getvalue()
    )
    assert str(tmp_path) not in buf.getvalue()
    assert "Errno" not in buf.getvalue()


def test_scope_check_missing_default_task_file_is_operator_friendly(
    tmp_path: Path,
) -> None:
    path = _missing_default_tasks_file(tmp_path)
    buf = io.StringIO()

    with redirect_stdout(buf):
        exit_code = taskmaster.cmd_scope_check(path)

    assert exit_code == 2
    output = buf.getvalue()
    assert (
        "scope-check: Taskmaster backlog not found at .taskmaster/tasks/tasks.json"
        in output
    )
    assert "mainspring init checkout-redesign" in output
    assert "replace checkout-redesign with your feature name" in output
    assert "mainspring init <name>" not in output
    assert str(tmp_path) not in output
    assert "Errno" not in output


# ── CLI error handling ─────────────────────────────────────────────────


def test_cli_no_args() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "task-status" in result.stderr
    assert "team-skip-reason" in result.stderr
    assert "scope-check" in result.stderr


def test_cli_unknown_subcommand() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "bogus"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


@pytest.mark.parametrize(
    ("args", "usage"),
    [
        (["status-summary"], "Usage: taskmaster.py status-summary"),
        (["scope-summary"], "Usage: taskmaster.py scope-summary"),
        (["task-metadata"], "Usage: taskmaster.py task-metadata"),
        (["task-status"], "Usage: taskmaster.py task-status"),
        (["pick-work-item"], "Usage: taskmaster.py pick-work-item"),
        (["parent-rollup"], "Usage: taskmaster.py parent-rollup"),
        (["next"], "Usage: mainspring next"),
        (["fallback-next"], "Usage: taskmaster.py fallback-next"),
        (["collect-parallel"], "Usage: taskmaster.py collect-parallel"),
        (["team-skip-reason"], "Usage: taskmaster.py team-skip-reason"),
        (["scope-check"], "Usage: mainspring scope-check"),
    ],
)
def test_cli_subcommands_require_expected_arguments(
    args: list[str], usage: str
) -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert usage in result.stderr


@pytest.mark.parametrize(
    ("args", "usage"),
    [
        (["next", "--help"], "Usage: mainspring next"),
        (["scope-check", "--help"], "Usage: mainspring scope-check"),
    ],
)
def test_cli_help_for_nested_commands(args: list[str], usage: str) -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert usage in result.stdout
