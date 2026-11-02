# SPDX-License-Identifier: Apache-2.0
"""Exact Taskmaster output bytes for equivalent print and range call forms."""

from __future__ import annotations

import json

import pytest

from . import test_taskmaster as canonical

taskmaster = canonical.taskmaster


@pytest.fixture(autouse=True)
def owned_case(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MAINSPRING_TASKMASTER_TAG", raising=False)
    monkeypatch.delenv("MAINSPRING_TEAM_EXCLUDE_PREFIXES", raising=False)


def _tasks(tmp_path, rows):
    path = tmp_path / ".taskmaster/tasks/tasks.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"master": {"tasks": rows}}))
    return str(path)


@pytest.mark.parametrize(
    "case,rows",
    [
        ("parent-no-children", [{"id": 7, "subtasks": []}]),
        ("parent-active", [{"id": 7, "subtasks": [{"id": 1, "status": "pending"}]}]),
        (
            "parent-other-status",
            [
                {
                    "id": 7,
                    "subtasks": [{"id": 1, "status": "unrecognized-fixture-status"}],
                }
            ],
        ),
        ("parent-missing", [{"id": 8, "subtasks": []}]),
        ("fallback-empty", []),
        ("team-no-reason", []),
    ],
)
def test_six_empty_result_sites_emit_exactly_one_newline(tmp_path, capsys, case, rows):
    path = _tasks(tmp_path, rows)
    if case.startswith("parent-"):
        taskmaster.cmd_parent_rollup(path, "7")
    elif case == "fallback-empty":
        taskmaster.cmd_fallback_next(path)
    else:
        taskmaster.cmd_team_skip_reason(path)
    captured = capsys.readouterr()
    assert captured.out.encode("utf-8") == b"\n"
    assert captured.err == ""


@pytest.mark.parametrize(
    "statuses,expected",
    [
        (["done", "deferred"], b"done\n"),
        (["blocked"], b"blocked\n"),
    ],
)
def test_normal_parent_rollup_bytes(tmp_path, capsys, statuses, expected):
    path = _tasks(
        tmp_path,
        [
            {
                "id": 7,
                "subtasks": [
                    {"id": i, "status": status} for i, status in enumerate(statuses)
                ],
            }
        ],
    )
    taskmaster.cmd_parent_rollup(path, "7")
    captured = capsys.readouterr()
    assert captured.out.encode() == expected and captured.err == ""


def test_normal_fallback_selection_bytes(tmp_path, capsys):
    path = _tasks(tmp_path, [{"id": 12, "status": "pending", "dependencies": []}])
    taskmaster.cmd_fallback_next(path)
    captured = capsys.readouterr()
    assert captured.out.encode() == b"12\n" and captured.err == ""


def test_normal_team_exclusion_bytes(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("MAINSPRING_TEAM_EXCLUDE_PREFIXES", "plugins")
    path = _tasks(
        tmp_path,
        [
            {
                "id": 7,
                "status": "pending",
                "dependencies": [],
                "description": "Update plugins/demo/file.py",
            }
        ],
    )
    taskmaster.cmd_team_skip_reason(path)
    captured = capsys.readouterr()
    assert captured.out.encode() == b"routing:plugin_invisible\n" and captured.err == ""


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", "."),
        ("one", "one"),
        ("one/two", "one/two"),
        (".taskmaster/tasks/tasks.json", ".taskmaster/tasks/tasks.json"),
        ("prefix/.taskmaster/tasks/tasks.json", ".taskmaster/tasks/tasks.json"),
        (
            "prefix/.taskmaster/tasks/tasks.json/.taskmaster/tasks/tasks.json",
            ".taskmaster/tasks/tasks.json",
        ),
        (".taskmaster/tasks/not-tasks.json", ".taskmaster/tasks/not-tasks.json"),
    ],
)
def test_short_no_match_and_first_matching_path_marker(value, expected):
    assert taskmaster._display_tasks_path(value) == expected


def test_absolute_owned_path_display(tmp_path):
    assert (
        taskmaster._display_tasks_path(str(tmp_path / "own/tasks.json"))
        == "own/tasks.json"
    )
    assert (
        taskmaster._display_tasks_path(str(tmp_path.parent / "other/file.json"))
        == "file.json"
    )


def test_existing_json_error_is_not_reclassified(tmp_path, capsys):
    path = tmp_path / "owned-malformed.json"
    path.write_text("{not-json")
    with pytest.raises(json.JSONDecodeError):
        taskmaster.cmd_parent_rollup(str(path), "7")
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
