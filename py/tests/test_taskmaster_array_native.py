# SPDX-License-Identifier: Apache-2.0
"""Selected-task array contract and unchanged tag/default behavior."""

from __future__ import annotations

import json

import pytest

from .test_team_read_guards_native import (
    READY,
    prepare_project,
    run_helper,
    run_supervisor,
)


@pytest.mark.parametrize(
    "tasks", [{}, "", None, False, 0, {"1": {"id": 1, "status": "pending"}}, "bad"]
)
@pytest.mark.parametrize(
    "route", ["collect-parallel", "team-skip-reason", "supervisor"]
)
def test_selected_non_array_is_not_empty_work(tmp_path, tasks, route):
    prepare_project(tmp_path, json.dumps({"master": {"tasks": tasks}}))
    if route == "supervisor":
        code, reason, actions, result = run_supervisor(tmp_path)
        assert code == 2 and reason == "unset"
        assert actions == ["counts", "collect"]
        assert "No more parallel-safe Taskmaster work" not in result.stdout
    else:
        result = run_helper(tmp_path, route)
        assert result.returncode != 0 and result.stdout == ""
    assert "Selected Taskmaster tag tasks must be an array" in result.stderr


@pytest.mark.parametrize(
    "case",
    [
        "empty_array",
        "selected_release_empty",
        "env_overrides_state",
        "missing_selected_tag_default",
        "missing_tasks_default",
        "missing_file",
        "malformed_json",
        "tagged_ready_array_retained",
    ],
)
def test_existing_array_tag_and_error_controls(tmp_path, case):
    raw = json.dumps({"master": {"tasks": []}})
    state_tag = tag = None
    if case in {"selected_release_empty", "env_overrides_state"}:
        raw = json.dumps({"master": {"tasks": [READY]}, "release": {"tasks": []}})
        state_tag = "release" if case == "selected_release_empty" else "master"
        tag = "release" if case == "env_overrides_state" else None
    elif case == "missing_selected_tag_default":
        raw = json.dumps({"master": {"tasks": [READY]}})
        tag = "release"
    elif case == "missing_tasks_default":
        raw = '{"master":{}}'
    elif case == "missing_file":
        raw = None
    elif case == "malformed_json":
        raw = "{"
    elif case == "tagged_ready_array_retained":
        raw = json.dumps({"master": {"tasks": []}, "release": {"tasks": [READY]}})
        state_tag = "release"
    prepare_project(tmp_path, raw, state_tag)
    helper = run_helper(tmp_path, "collect-parallel", tag)
    code, reason, actions, result = run_supervisor(tmp_path, tag=tag)
    error = case in {"missing_file", "malformed_json"}
    ready = case == "tagged_ready_array_retained"
    assert helper.returncode != 0 if error else helper.returncode == 0
    assert code == (2 if error or ready else 0)
    assert reason == ("unset" if error or ready else "team:no_parallel_safe_work")
    assert actions == ["counts", "collect"] + ([] if error or ready else ["skip"])
    assert "dispatch" not in actions
    assert ("No more parallel-safe Taskmaster work" in result.stdout) == (
        not error and not ready
    )
    if ready:
        assert json.loads(helper.stdout)["id"] == "1"
    elif not error:
        assert helper.stdout == ""
