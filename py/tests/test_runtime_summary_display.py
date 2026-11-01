# SPDX-License-Identifier: Apache-2.0
"""Owned synthetic runtime-summary display paths; no process or repair calls."""

from __future__ import annotations

import hashlib
import io
import json
import os
import signal
import socket
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from . import test_runtime_state as canonical

EVENTS: list[dict] = []


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture(scope="session", autouse=True)
def save_display_events(tmp_path_factory):
    yield
    path = tmp_path_factory.mktemp("runtime-display-events") / "events.json"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(EVENTS, ensure_ascii=True, indent=2) + "\n")


@pytest.fixture
def owned_display(request, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    owned = tmp_path / "owned"
    root = owned / "project" / "state"
    root.mkdir(parents=True)
    (root / "team").mkdir()
    (owned / "proj").mkdir()
    (owned / "elsewhere").mkdir()
    canary = owned / "unrelated.json"
    write_json(canary, {"sentinel": "unchanged-owned-file"})
    write_json(
        root / "session.json",
        {"session_id": "synthetic", "pid": 771111, "cwd": "synthetic"},
    )
    module = canonical.runtime_state
    calls = {"pid_alive": 0, "pid_files": 0, "forbidden": 0, "reads": []}

    def forbidden(*_args, **_kwargs):
        calls["forbidden"] += 1
        raise AssertionError("process, network, signal, repair or CLI call forbidden")

    def pid_alive(_value):
        calls["pid_alive"] += 1
        return False

    def pid_files(path):
        assert path.resolve() == root.resolve()
        calls["pid_files"] += 1
        return []

    original_read = module._read_json

    def owned_read(path):
        assert path.resolve().is_relative_to(owned.resolve())
        calls["reads"].append(str(path))
        return original_read(path)

    monkeypatch.setattr(module, "_pid_alive", pid_alive)
    monkeypatch.setattr(module, "_runtime_pid_files", pid_files)
    monkeypatch.setattr(module, "_read_json", owned_read)
    for name in (
        "_pid_command",
        "_stop_team_backend",
        "main",
        "cmd_repair",
        "cmd_stop_processes",
        "cmd_cleanup_stale",
    ):
        monkeypatch.setattr(module, name, forbidden, raising=False)
    for name in ("run", "Popen", "check_output", "call"):
        monkeypatch.setattr(module.subprocess, name, forbidden)
    for name in ("kill", "killpg", "system"):
        monkeypatch.setattr(module.os, name, forbidden)
    for name in ("signal", "raise_signal", "setitimer", "pthread_kill"):
        if hasattr(signal, name):
            monkeypatch.setattr(signal, name, forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    return module, owned, root, canary, calls, request.node.nodeid


@pytest.mark.parametrize(
    "selector", ["skill", "initialized_mode", "explicit_absolute", "explicit_relative"]
)
@pytest.mark.parametrize("mode", ["active", "completed", "missing"])
@pytest.mark.parametrize(
    "relation", ["prefix_sibling", "ancestor", "equal_root", "unrelated"]
)
@pytest.mark.parametrize("argument", ["absolute", "relative"])
def test_summary_display_preserves_valid_selection_and_warnings(
    owned_display,
    monkeypatch: pytest.MonkeyPatch,
    selector: str,
    mode: str,
    relation: str,
    argument: str,
):
    module, owned, root, _canary, calls, node_id = owned_display
    cwd = {
        "prefix_sibling": owned / "proj",
        "ancestor": owned,
        "equal_root": root,
        "unrelated": owned / "elsewhere",
    }[relation]
    monkeypatch.chdir(cwd)
    root_argument = root if argument == "absolute" else Path(os.path.relpath(root, cwd))
    target = root / "display-state.json"
    skill = {"active": True, "phase": "running"}
    if selector in {"skill", "initialized_mode"}:
        skill[selector] = "display"
        selected = root_argument / "display-state.json"
    else:
        skill["skill"] = "display"
        skill["initialized_state_path"] = (
            str(target) if selector == "explicit_absolute" else "display-state.json"
        )
        selected = (
            target
            if selector == "explicit_absolute" or relation == "equal_root"
            else root_argument / "display-state.json"
        )
    write_json(root / "skill-active-state.json", skill)
    if mode != "missing":
        write_json(
            target,
            {
                "active": mode == "active",
                "current_phase": "working" if mode == "active" else "completed",
                "sentinel": "only-owned-mode",
            },
        )
    before = {str(p): digest(p) for p in owned.rglob("*.json")}
    output = io.StringIO()
    caught = None
    try:
        with redirect_stdout(output):
            module.cmd_runtime_summary(str(root_argument))
    except Exception as error:
        caught = type(error).__name__
        raise
    finally:
        after = {str(p): digest(p) for p in owned.rglob("*.json")}
        EVENTS.append(
            {
                "node": node_id,
                "selector": selector,
                "mode": mode,
                "cwd_relation": relation,
                "argument": argument,
                "selected_lexical_path": str(selected),
                "exception_type": caught,
                "stdout": output.getvalue(),
                "calls": calls,
                "before_sha256": before,
                "after_sha256": after,
                "fixture_files_unchanged": before == after,
            }
        )
        assert before == after
        assert calls["forbidden"] == 0
    if selected.is_absolute():
        expected = {
            "ancestor": "project/state/display-state.json",
            "equal_root": "display-state.json",
            "prefix_sibling": str(target),
            "unrelated": str(target),
        }[relation]
    else:
        expected = str(selected)
    text = output.getvalue()
    assert f"mode-state: path={expected}" in text
    assert str(selected) in calls["reads"]
    assert Path(selected).resolve() == target.resolve()
    assert calls["pid_alive"] == calls["pid_files"] == 1
    if mode == "missing":
        assert f"mode-state: path={expected} missing/unreadable\n" in text
        assert text.endswith("warnings: none\n")
    elif mode == "completed":
        assert text.endswith(
            "warnings:\n  - stale skill-active state: active=true while mode state is completed/inactive\n"
        )
    else:
        assert text.endswith(
            "warnings:\n  - stale active mode state: active=true but session pid is not alive and no team state exists\n"
        )
