# SPDX-License-Identifier: Apache-2.0
"""Tests for the BacklogSource protocol and Taskmaster adapter."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from backlog_source import BacklogSourceError, TaskmasterJsonBacklogSource  # noqa: E402


def _write_tasks(tmp_path: Path, tasks: list[dict]) -> Path:
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(
        json.dumps({"master": {"tasks": tasks}}),
        encoding="utf-8",
    )
    return tasks_file


def test_taskmaster_source_lists_ready_subtasks_with_active_prd_priority(
    tmp_path: Path,
) -> None:
    tasks_file = _write_tasks(
        tmp_path,
        [
            {
                "id": 1,
                "status": "pending",
                "dependencies": [],
                "title": "P2 later work",
                "subtasks": [],
            },
            {
                "id": 2,
                "status": "pending",
                "dependencies": [],
                "title": "P1 current phase parent",
                "subtasks": [
                    {"id": 1, "status": "blocked", "title": "Blocked child"},
                    {
                        "id": 2,
                        "status": "pending",
                        "dependencies": [],
                        "title": "Implement current slice",
                        "description": "Edit py/taskmaster.py",
                    },
                ],
            },
        ],
    )
    active_prd = tmp_path / "active-prd.json"
    active_prd.write_text(
        json.dumps({"active_phase": "P1", "phase_order": ["P1", "P2"]}),
        encoding="utf-8",
    )

    source = TaskmasterJsonBacklogSource(tasks_file)

    ready = source.list_ready_tasks(active_prd_file=active_prd, limit=1)

    assert [item.id for item in ready] == ["2.2"]
    assert ready[0].parent_id == "2"
    assert ready[0].title == "Implement current slice"


def test_taskmaster_source_skips_unmet_dependencies(tmp_path: Path) -> None:
    tasks_file = _write_tasks(
        tmp_path,
        [
            {"id": 1, "status": "pending", "dependencies": [99], "title": "Blocked"},
            {"id": 2, "status": "review", "dependencies": [], "title": "Ready"},
        ],
    )

    source = TaskmasterJsonBacklogSource(tasks_file)

    assert [item.id for item in source.list_ready_tasks()] == ["2"]


@pytest.mark.parametrize(
    "dependencies",
    ["12", "", False, True, 0, 12, {}, {"1": "done", "2": "done"}],
)
def test_taskmaster_source_rejects_non_array_task_dependencies(
    tmp_path: Path, dependencies: object
) -> None:
    tasks_file = _write_tasks(
        tmp_path,
        [
            {"id": 1, "status": "done"},
            {"id": 2, "status": "done"},
            {"id": 12, "status": "pending", "dependencies": []},
            {"id": 20, "status": "pending", "dependencies": dependencies},
        ],
    )

    assert [
        item.id for item in TaskmasterJsonBacklogSource(tasks_file).list_ready_tasks()
    ] == ["12"]


@pytest.mark.parametrize(
    "dependencies",
    ["12", "", False, True, 0, 12, {}, {"1": "done", "2": "done"}],
)
def test_taskmaster_source_rejects_non_array_subtask_dependencies(
    tmp_path: Path, dependencies: object
) -> None:
    tasks_file = _write_tasks(
        tmp_path,
        [
            {
                "id": 20,
                "status": "pending",
                "dependencies": [],
                "subtasks": [
                    {"id": 1, "status": "done"},
                    {"id": 2, "status": "done"},
                    {"id": 12, "status": "pending", "dependencies": []},
                    {"id": 13, "status": "pending", "dependencies": dependencies},
                ],
            }
        ],
    )

    assert [
        item.id for item in TaskmasterJsonBacklogSource(tasks_file).list_ready_tasks()
    ] == ["20.12"]


@pytest.mark.parametrize("subtask", [False, True])
@pytest.mark.parametrize("dependency_id", [12, "12"])
def test_taskmaster_source_dependency_arrays_still_wait_for_done(
    tmp_path: Path, subtask: bool, dependency_id: int | str
) -> None:
    prerequisite = {"id": 12, "status": "pending", "dependencies": []}
    dependent = {"id": 20, "status": "pending", "dependencies": [dependency_id]}
    if subtask:
        dependent["id"] = 13
        tasks = [{"id": 20, "status": "pending", "subtasks": [prerequisite, dependent]}]
        expected_pending = ["20.12"]
        expected_ready = ["20.13"]
    else:
        tasks = [prerequisite, dependent]
        expected_pending = ["12"]
        expected_ready = ["20"]
    tasks_file = _write_tasks(tmp_path, tasks)
    source = TaskmasterJsonBacklogSource(tasks_file)

    assert [item.id for item in source.list_ready_tasks()] == expected_pending
    prerequisite["status"] = "done"
    _write_tasks(tmp_path, tasks)
    assert [item.id for item in source.list_ready_tasks()] == expected_ready


@pytest.mark.parametrize("subtask", [False, True])
def test_taskmaster_source_missing_and_empty_dependency_arrays_stay_ready(
    tmp_path: Path, subtask: bool
) -> None:
    ready = [
        {"id": 12, "status": "pending"},
        {"id": 13, "status": "pending", "dependencies": []},
        {"id": 14, "status": "pending", "dependencies": None},
        {"id": 15, "status": "done", "dependencies": "12"},
    ]
    tasks = [{"id": 20, "status": "pending", "subtasks": ready}] if subtask else ready
    tasks_file = _write_tasks(tmp_path, tasks)
    expected = ["20.12", "20.13", "20.14"] if subtask else ["12", "13", "14"]

    assert [
        item.id for item in TaskmasterJsonBacklogSource(tasks_file).list_ready_tasks()
    ] == expected


def test_taskmaster_source_dependency_arrays_keep_exact_sibling_id_matching(
    tmp_path: Path,
) -> None:
    # Compatibility control only; no new dotted or cross-parent resolution policy.
    tasks_file = _write_tasks(
        tmp_path,
        [
            {"id": 7, "status": "done", "subtasks": [{"id": 1, "status": "done"}]},
            {
                "id": 20,
                "status": "pending",
                "subtasks": [
                    {"id": 1, "status": "done"},
                    {"id": 2, "status": "pending", "dependencies": ["7.1"]},
                    {"id": 3, "status": "pending", "dependencies": ["20.1"]},
                    {"id": 4, "status": "pending", "dependencies": [1]},
                ],
            },
        ],
    )

    assert [
        item.id for item in TaskmasterJsonBacklogSource(tasks_file).list_ready_tasks()
    ] == ["20.4"]


def test_taskmaster_source_get_details_for_subtask(tmp_path: Path) -> None:
    tasks_file = _write_tasks(
        tmp_path,
        [
            {
                "id": 4,
                "status": "pending",
                "title": "Parent",
                "subtasks": [
                    {
                        "id": 3,
                        "status": "in-progress",
                        "title": "Child",
                        "description": "Subtask details",
                    }
                ],
            }
        ],
    )

    source = TaskmasterJsonBacklogSource(tasks_file)

    item = source.get_details("4.3")

    assert item is not None
    assert item.id == "4.3"
    assert item.parent_id == "4"
    assert item.status == "in-progress"
    assert item.title == "Child"
    assert item.description == "Subtask details"


def test_taskmaster_source_marks_done_through_taskmaster_cli(tmp_path: Path) -> None:
    tasks_file = _write_tasks(tmp_path, [])
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    source = TaskmasterJsonBacklogSource(
        tasks_file,
        taskmaster_bin="task-master",
        command_runner=fake_run,
    )

    source.mark_done("7.2")

    assert calls == [["task-master", "set-status", "--id=7.2", "--status=done"]]


def test_taskmaster_source_marks_blocked_with_reason_before_status(
    tmp_path: Path,
) -> None:
    tasks_file = _write_tasks(tmp_path, [])
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    source = TaskmasterJsonBacklogSource(
        tasks_file,
        taskmaster_bin="task-master",
        command_runner=fake_run,
    )

    source.mark_blocked("7.2", "needs live API key")

    assert calls == [
        [
            "task-master",
            "update-subtask",
            "--id=7.2",
            "--prompt=Blocked by Mainspring: needs live API key",
        ],
        ["task-master", "set-status", "--id=7.2", "--status=blocked"],
    ]


def test_taskmaster_source_fails_closed_when_status_command_fails(
    tmp_path: Path,
) -> None:
    tasks_file = _write_tasks(tmp_path, [])

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "permission denied")

    source = TaskmasterJsonBacklogSource(
        tasks_file,
        taskmaster_bin="task-master",
        command_runner=fake_run,
    )

    with pytest.raises(BacklogSourceError, match="task-master set-status failed"):
        source.mark_done("7.2")
