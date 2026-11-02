# SPDX-License-Identifier: Apache-2.0
"""Owned-fixture runtime fallback confinement regressions."""

from __future__ import annotations

import hashlib
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from . import test_runtime_state as canonical

EVENTS: list[dict] = []


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture(scope="session", autouse=True)
def save_events(tmp_path_factory):
    yield
    events_file = tmp_path_factory.mktemp("runtime-fallback-events") / "events.json"
    with events_file.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(EVENTS, indent=2) + "\n")


@pytest.fixture
def owned_case(request, monkeypatch: pytest.MonkeyPatch, tmp_path):
    case_id = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    owned = tmp_path / "cases-v3" / case_id
    owned.mkdir(parents=True)
    root = owned / "project" / ".mainspring" / "state"
    root.mkdir(parents=True)
    canary = owned / "unrelated.json"
    write_json(canary, {"sentinel": "unchanged-unrelated-file"})
    write_json(root / "session.json", {"pid": 771111, "session_id": "synthetic"})
    module = canonical.runtime_state
    calls = {"pid_alive": [], "runtime_pid_files": 0, "forbidden": 0, "reads": []}

    def forbidden(*args: object, **kwargs: object) -> None:
        calls["forbidden"] += 1
        raise AssertionError("process, backend or CLI operation is outside scope")

    def pid_alive(value: object) -> bool:
        calls["pid_alive"].append(value)
        return False

    def pid_files(state_dir: Path) -> list[Path]:
        assert state_dir.resolve() == root.resolve()
        calls["runtime_pid_files"] += 1
        return []

    original_read = module._read_json

    def owned_read(path: Path):
        assert path.resolve().is_relative_to(owned.resolve())
        calls["reads"].append(str(path))
        return original_read(path)

    monkeypatch.setattr(module, "_pid_alive", pid_alive)
    monkeypatch.setattr(module, "_runtime_pid_files", pid_files)
    monkeypatch.setattr(module, "_read_json", owned_read)
    monkeypatch.setattr(module.os, "kill", forbidden)
    monkeypatch.setattr(module.subprocess, "run", forbidden)
    monkeypatch.setattr(module.subprocess, "check_output", forbidden)
    monkeypatch.setattr(module, "_pid_command", forbidden)
    monkeypatch.setattr(module, "_stop_team_backend", forbidden)
    monkeypatch.setattr(module, "main", forbidden)
    return module, owned, root, canary, calls, request.node.nodeid


def setup_mode(case, field: str, style: str, *, stale: str = "dead"):
    owned, root = case[1:3]
    if style == "relative":
        label = "../neighbor"
        target = root.parent / "neighbor-state.json"
    elif style == "absolute":
        target = owned / "absolute-target-state.json"
        label = str(owned / "absolute-target")
    elif style == "contained_absolute":
        label = str(root / "team")
        target = root / "team-state.json"
    else:
        label = "team"
        target = root / "team-state.json"
    write_json(root / "skill-active-state.json", {"active": True, field: label})
    write_json(
        target,
        {
            "active": stale != "completed",
            "phase": "completed" if stale == "completed" else "owned-target-phase",
            "sentinel": "only-owned-synthetic-state",
        },
    )
    return target


def call(case, command: str, target: Path, *, state_dir: str | None = None, **kwargs):
    module, _owned, root, canary, calls, node_id = case
    tracked = [root / "skill-active-state.json", root / "session.json", target, canary]
    before = {str(p): digest(p) for p in tracked}
    stdout, stderr = io.StringIO(), io.StringIO()
    completion = "returned_none"
    code = 0
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            result = getattr(module, command)(state_dir or str(root), **kwargs)
        except SystemExit as exc:
            completion = "raised_system_exit"
            code = exc.code
        else:
            assert result is None
    after = {str(p): digest(p) for p in tracked}
    event = {
        "node_id": node_id,
        "command": command,
        "root": str(root),
        "state_dir_argument": state_dir or str(root),
        "target": str(target),
        "target_resolved": str(target.resolve()),
        "target_outside_state_root": not target.resolve().is_relative_to(
            root.resolve()
        ),
        "kwargs": kwargs,
        "completion": completion,
        "function_exit_code": code,
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
        "before_sha256": before,
        "after_sha256": after,
        "process_guard_calls": dict(calls),
    }
    EVENTS.append(event)
    assert before[str(canary)] == after[str(canary)]
    assert before[str(root / "session.json")] == after[str(root / "session.json")]
    assert calls["forbidden"] == 0
    return event


@pytest.mark.parametrize("field", ["skill", "initialized_mode"])
@pytest.mark.parametrize("style", ["relative", "absolute"])
def test_regression_summary_must_not_read_fallback_outside(owned_case, field, style):
    target = setup_mode(owned_case, field, style)
    event = call(owned_case, "cmd_runtime_summary", target)
    assert "owned-target-phase" not in event["stdout"]
    assert "outside runtime state dir" in event["stdout"]
    assert target.resolve() not in {
        Path(path).resolve() for path in owned_case[4]["reads"]
    }


@pytest.mark.parametrize("field", ["skill", "initialized_mode"])
@pytest.mark.parametrize("style", ["relative", "absolute"])
@pytest.mark.parametrize("stale", ["dead", "completed"])
def test_regression_force_must_not_write_fallback_outside(
    owned_case, field, style, stale
):
    target = setup_mode(owned_case, field, style, stale=stale)
    event = call(owned_case, "cmd_repair", target, force=True)
    assert event["before_sha256"][str(target)] == event["after_sha256"][str(target)]
    assert event["function_exit_code"] == 2
    assert "outside runtime state dir" in event["stdout"]
    assert target.resolve() not in {
        Path(path).resolve() for path in owned_case[4]["reads"]
    }


@pytest.mark.parametrize("field", ["skill", "initialized_mode"])
def test_control_valid_fallback_name_repairs_owned_child(owned_case, field):
    target = setup_mode(owned_case, field, "valid")
    event = call(owned_case, "cmd_repair", target, force=True)
    assert event["function_exit_code"] == 0
    assert event["before_sha256"][str(target)] != event["after_sha256"][str(target)]
    assert json.loads(target.read_text())["current_phase"] == "completed"


@pytest.mark.parametrize("absolute", [False, True])
def test_control_explicit_contained_path_wins_over_fallback(owned_case, absolute):
    root = owned_case[2]
    outside = setup_mode(owned_case, "skill", "relative")
    contained = root / "explicit-mode.json"
    write_json(contained, {"active": True, "phase": "owned-contained"})
    skill_path = root / "skill-active-state.json"
    skill = json.loads(skill_path.read_text())
    skill["initialized_state_path"] = str(contained) if absolute else contained.name
    write_json(skill_path, skill)
    outside_before = digest(outside)
    event = call(owned_case, "cmd_repair", contained, force=True)
    assert event["function_exit_code"] == 0
    assert digest(outside) == outside_before
    assert json.loads(contained.read_text())["current_phase"] == "completed"


@pytest.mark.parametrize("style", ["relative", "absolute"])
@pytest.mark.parametrize("command", ["cmd_runtime_summary", "cmd_repair"])
def test_control_explicit_outside_path_is_refused(owned_case, style, command):
    root, calls = owned_case[2], owned_case[4]
    target = setup_mode(owned_case, "skill", style)
    skill_path = root / "skill-active-state.json"
    skill = json.loads(skill_path.read_text())
    skill["initialized_state_path"] = (
        "../neighbor-state.json" if style == "relative" else str(target)
    )
    write_json(skill_path, skill)
    kwargs = {"force": True} if command == "cmd_repair" else {}
    event = call(owned_case, command, target, **kwargs)
    assert "outside runtime state dir" in event["stdout"]
    assert event["before_sha256"] == event["after_sha256"]
    assert target.resolve() not in {Path(path).resolve() for path in calls["reads"]}
    assert event["function_exit_code"] == (2 if command == "cmd_repair" else 0)


@pytest.mark.parametrize("style", ["valid", "contained_absolute"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_control_dry_run_and_no_force_preserve_contained_behavior(
    owned_case, style, dry_run
):
    target = setup_mode(owned_case, "skill", style)
    event = call(owned_case, "cmd_repair", target, dry_run=dry_run)
    assert event["before_sha256"] == event["after_sha256"]
    assert event["function_exit_code"] == (0 if dry_run else 2)


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
def test_control_missing_mode_never_creates_target(owned_case, force, dry_run):
    root = owned_case[2]
    target = root / "absent-state.json"
    write_json(
        root / "skill-active-state.json",
        {"active": True, "initialized_mode": str(root / "absent")},
    )
    event = call(owned_case, "cmd_repair", target, force=force, dry_run=dry_run)
    assert event["function_exit_code"] == (1 if force else 0)
    assert event["before_sha256"] == event["after_sha256"]
    assert not target.exists()


@pytest.mark.parametrize("style", ["valid", "contained_absolute"])
def test_control_nonstale_state_is_not_repaired_even_with_force(owned_case, style):
    root = owned_case[2]
    target = setup_mode(owned_case, "initialized_mode", style)
    skill_path = root / "skill-active-state.json"
    skill = json.loads(skill_path.read_text())
    skill["active"] = False
    write_json(skill_path, skill)
    event = call(owned_case, "cmd_repair", target, force=True)
    assert "No stale" in event["stdout"]
    assert event["before_sha256"] == event["after_sha256"]


@pytest.mark.parametrize("command", ["cmd_runtime_summary", "cmd_repair"])
def test_relative_candidate_outside_is_not_retargeted_to_nested_collision(
    owned_case, monkeypatch: pytest.MonkeyPatch, command
):
    root = owned_case[2]
    target = setup_mode(owned_case, "skill", "relative")
    shadow = root / "neighbor-state.json"
    write_json(shadow, {"active": True, "phase": "owned-inside-shadow"})
    shadow_before = digest(shadow)
    monkeypatch.chdir(root.parent)
    kwargs = {"force": True} if command == "cmd_repair" else {}
    event = call(owned_case, command, target, state_dir="state", **kwargs)
    event["collision_shadow_sha256"] = [shadow_before, digest(shadow)]
    assert "outside runtime state dir" in event["stdout"]
    assert event["before_sha256"] == event["after_sha256"]
    assert shadow_before == digest(shadow)
    resolved_reads = {Path(path).resolve() for path in owned_case[4]["reads"]}
    assert not ({shadow.resolve(), target.resolve()} & resolved_reads)
    assert "owned-inside-shadow" not in event["stdout"]
    if command == "cmd_runtime_summary":
        assert "mode-state:" not in event["stdout"]


@pytest.mark.parametrize("command", ["cmd_runtime_summary", "cmd_repair"])
def test_relative_candidate_valid_nested_label_preserves_path_and_target(
    owned_case, monkeypatch: pytest.MonkeyPatch, command
):
    root = owned_case[2]
    target = root / "nested" / "demo-state.json"
    target.parent.mkdir()
    write_json(target, {"active": True, "phase": "owned-nested-child"})
    outside = root.parent / "nested" / "demo-state.json"
    outside.parent.mkdir()
    write_json(outside, {"active": True, "phase": "owned-cwd-collision"})
    outside_before = digest(outside)
    write_json(
        root / "skill-active-state.json",
        {"active": True, "initialized_mode": "nested/demo"},
    )
    monkeypatch.chdir(root.parent)
    kwargs = {"force": True} if command == "cmd_repair" else {}
    event = call(owned_case, command, target, state_dir="state", **kwargs)
    event["outside_cwd_collision_sha256"] = [outside_before, digest(outside)]
    assert outside_before == digest(outside)
    assert event["function_exit_code"] == 0
    if command == "cmd_repair":
        assert "mode_path=state/nested/demo-state.json" in event["stdout"]
        assert event["before_sha256"][str(target)] != event["after_sha256"][str(target)]
    else:
        assert "path=state/nested/demo-state.json" in event["stdout"]
        assert event["before_sha256"] == event["after_sha256"]


@pytest.mark.parametrize("style", ["relative", "absolute"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_outside_reference_refuses_before_read_in_dry_or_nonforce(
    owned_case, style, dry_run
):
    target = setup_mode(owned_case, "skill", style)
    event = call(owned_case, "cmd_repair", target, dry_run=dry_run)
    assert event["function_exit_code"] == 2
    assert "outside runtime state dir" in event["stdout"]
    assert target.resolve() not in {
        Path(path).resolve() for path in owned_case[4]["reads"]
    }
    assert event["before_sha256"] == event["after_sha256"]


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
def test_missing_outside_reference_refuses_before_read(owned_case, force, dry_run):
    owned, root = owned_case[1:3]
    target = owned / "absent-state.json"
    write_json(
        root / "skill-active-state.json",
        {"active": True, "initialized_mode": str(owned / "absent")},
    )
    event = call(owned_case, "cmd_repair", target, force=force, dry_run=dry_run)
    assert event["function_exit_code"] == 2
    assert "outside runtime state dir" in event["stdout"]
    assert target.resolve() not in {
        Path(path).resolve() for path in owned_case[4]["reads"]
    }
    assert event["before_sha256"] == event["after_sha256"]
    assert not target.exists()


@pytest.mark.parametrize("style", ["relative", "absolute"])
def test_nonstale_outside_reference_refuses_before_read(owned_case, style):
    root = owned_case[2]
    target = setup_mode(owned_case, "initialized_mode", style)
    skill_path = root / "skill-active-state.json"
    skill = json.loads(skill_path.read_text())
    skill["active"] = False
    write_json(skill_path, skill)
    event = call(owned_case, "cmd_repair", target, force=True)
    assert event["function_exit_code"] == 2
    assert "outside runtime state dir" in event["stdout"]
    assert target.resolve() not in {
        Path(path).resolve() for path in owned_case[4]["reads"]
    }
    assert event["before_sha256"] == event["after_sha256"]
