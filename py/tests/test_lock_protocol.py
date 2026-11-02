# SPDX-License-Identifier: Apache-2.0
"""Owned-TMP lock protocol regressions; never inspect or operate a user runtime."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

from . import lock_protocol_support as probe

ROOT = Path(__file__).resolve().parents[2]
BEFORE = ROOT / "tests/fixtures/lock_before_guard.sh"


@pytest.fixture(scope="module")
def backend():
    value = os.environ.get("MAINSPRING_LOCK_TEST_BACKEND", "fcntl")
    print(
        "LOCK_BACKEND_EVIDENCE "
        + json.dumps(probe.backend_identity(value), sort_keys=True)
    )
    return value


@pytest.fixture(scope="module")
def lifecycle(tmp_path_factory, backend):
    folder = tmp_path_factory.mktemp("protocol-lifecycle")
    return {row["name"]: row for row in probe.controls(ROOT, folder, backend)}


def test_backend_identity_requires_real_requested_binary(backend):
    info = probe.backend_identity(backend)
    assert info["native_is_stub"] is False
    if backend == "native":
        assert Path(info["native_path"]).is_file()
        assert "flock" in info["native_version"].lower()
    else:
        assert info["proof"] == "Actual Python fd_lock.py/fcntl; no native branch claim"


def test_preopened_contender_uses_the_same_guard_after_release(tmp_path, backend):
    result = probe.race(ROOT, tmp_path, backend)
    assert result["both_acquire_returned_success_before_either_release"] is False
    assert result["alive_at_observation"] == {"B": True, "C": False}
    assert [actor["returncode"] for actor in result["actors"]] == [0, 0, 1]


@pytest.mark.parametrize(
    "name",
    [
        "normal",
        "fallback-error",
        "missing",
        "native-1",
        "native-2",
        "native-0",
        "busy",
        "legacy-live-pid",
        "foreign-pid-release",
        "stale-pid",
        "reacquire",
    ],
)
def test_prior_eleven_lifecycle_controls(name, lifecycle):
    row = lifecycle[name]
    if name in {"normal", "native-0"}:
        assert row["acquired"] is True and row["actor"]["returncode"] == 0
        assert row["pid_path_after_release_exists"] is False
    elif name in {"fallback-error", "missing", "native-1", "native-2"}:
        assert row["acquired"] is False and row["actor"]["returncode"] == 1
        expected = "already running" if name == "native-1" else "could not acquire"
        assert expected in row["actor"]["stderr"]
    elif name == "busy":
        assert row["acquired_a"] is True
        assert [actor["returncode"] for actor in row["actors"]] == [1, 0]
        assert row["metadata_after_release"] is None
    elif name == "legacy-live-pid":
        assert row["acquired_a"] is False and row["actors"][0]["returncode"] == 1
        assert row["metadata_after_release"].strip() == str(os.getpid())
    elif name == "foreign-pid-release":
        assert row["acquired_a"] is True and row["actors"][0]["returncode"] == 0
        assert row["metadata_after_release"].strip() == str(os.getpid())
    elif name == "stale-pid":
        assert row["acquired_a"] is True and row["metadata_after_release"] is None
    else:
        assert row["acquired_a"] is True
        assert [actor["returncode"] for actor in row["actors"]] == [0, 0]
        assert row["metadata_after_release"] is None
    if name.startswith("native-"):
        assert (
            row["native_backend_is_stub"] is True
        )  # Status mapping only, never native proof.


@pytest.mark.parametrize(
    "case,markers,expected_code",
    [
        ("ordinary", ["AFTER_RELEASE_MARKER", "ORDINARY_EXIT_MARKER"], 0),
        ("trap_release", ["AFTER_TRAP_RELEASE_MARKER"], 0),
        ("busy", ["BUSY_EXIT_MARKER"], 0),
        ("live_refusal", ["REFUSAL_EXIT_MARKER"], 0),
        ("helper_error", ["ERROR_EXIT_MARKER"], 1),
        ("foreign_release", ["FOREIGN_AFTER_RELEASE_MARKER", "FOREIGN_EXIT_MARKER"], 0),
    ],
)
def test_stderr_survives_release_and_exit_paths(
    tmp_path, backend, case, markers, expected_code
):
    result = probe.stderr_case(ROOT, tmp_path, backend, case)
    assert result["exit_code"] == expected_code, result
    assert all(marker in result["stderr"] for marker in markers), result
    assert "UNEXPECTED_ACQUIRE" not in result["stdout"]


def test_guard_inode_persists_and_release_really_closes_the_owned_lock(
    tmp_path, backend
):
    result = probe.stderr_case(ROOT, tmp_path, backend, "guard_cycle")
    assert result["exit_code"] == 0, result
    assert all(
        marker in result["stdout"]
        for marker in (
            "GUARD_INODE_STABLE",
            "CHILD_REACQUIRED_WHILE_PARENT_ALIVE",
            "OWN_PID_REMOVED",
        )
    )


@pytest.mark.parametrize("failed_read", [1, 2, 0])
def test_guard_metadata_read_error_cannot_claim_stable_inode(
    tmp_path, backend, monkeypatch, failed_read
):
    injected = """guard_identity() {
  local reads=0
  [ ! -f "$STATE/oracle-reads" ] || reads=$(cat "$STATE/oracle-reads")
  reads=$((reads + 1))
  printf '%s\\n' "$reads" > "$STATE/oracle-reads"
  if [ "$reads" -eq FAILED_READ ] || [ FAILED_READ -eq 0 ]; then
    printf '%s\\n' SYNTHETIC_METADATA_READ_FAILED >&2
    return 73
  fi
""".replace("FAILED_READ", str(failed_read))
    assert probe.STDERR_SHELL.count("guard_identity() {\n") == 1
    monkeypatch.setattr(
        probe,
        "STDERR_SHELL",
        probe.STDERR_SHELL.replace("guard_identity() {\n", injected),
    )
    result = probe.stderr_case(ROOT, tmp_path, backend, "guard_cycle")
    assert result["exit_code"] == 73, result
    assert "GUARD_INODE_STABLE" not in result["stdout"]
    assert "SYNTHETIC_METADATA_READ_FAILED" in result["stderr"]


def test_frozen_old_protocol_retains_the_original_red_oracle(tmp_path, backend):
    assert (
        hashlib.sha256(BEFORE.read_bytes()).hexdigest()
        == "1d3cd87aca36c2fef7c82f7339683b65c756b511f4d821e161994e83093c05f7"
    )
    result = probe.race(
        ROOT, tmp_path, backend, sources={role: BEFORE for role in ("A", "B", "C")}
    )
    assert result["both_acquire_returned_success_before_either_release"] is True
    assert result["alive_at_observation"] == {"B": True, "C": True}


def test_mixed_old_waiter_and_new_launcher_is_explicitly_unsupported(tmp_path, backend):
    result = probe.race(ROOT, tmp_path, backend, sources={"A": BEFORE, "B": BEFORE})
    assert result["both_acquire_returned_success_before_either_release"] is True
    assert result["alive_at_observation"] == {"B": True, "C": True}


def test_old_stderr_red_oracle_is_not_mislabelled_as_a_new_guard_regression(
    tmp_path, backend
):
    result = probe.stderr_case(ROOT, tmp_path, backend, "ordinary", source=BEFORE)
    assert result["exit_code"] == 0 and "ORDINARY_FINISHED" in result["stdout"]
    assert "AFTER_RELEASE_MARKER" not in result["stderr"]
    assert "ORDINARY_EXIT_MARKER" not in result["stderr"]


def guard_snapshot(path):
    info = path.stat()
    return info.st_dev, info.st_ino, path.read_bytes()


@pytest.mark.parametrize("consumer", ["self_heal", "team_restart"])
def test_pid_only_shell_consumers_preserve_guard(tmp_path, consumer):
    state = tmp_path / "state"
    state.mkdir()
    pid = state / "mainspring.lock"
    guard = state / "mainspring.lock.guard"
    pid.write_text("424242\n")
    guard.write_bytes(b"owned synthetic persistent guard\n")
    before = guard_snapshot(guard)
    forbidden = tmp_path / "forbidden-process-call"
    script = r"""
set -eu
source "$1/lib/status.sh"
source "$1/lib/team.sh"
LOCK_FILE="$2/mainspring.lock"
SELF_HEAL=true
team_state_root() { printf '%s\n' "$SYNTHETIC_STATE"; }
command() {
  if [ "${1:-}" = -v ] && [ "${2:-}" = omx ]; then return 1; fi
  builtin command "$@"
}
kill() {
  if [ "${1:-}" = -0 ]; then return 1; fi
  printf '%s\n' forbidden > "$FORBIDDEN_CALL"; return 97
}
ps() { printf '%s\n' forbidden > "$FORBIDDEN_CALL"; return 97; }
omx() { printf '%s\n' forbidden > "$FORBIDDEN_CALL"; return 97; }
cleanup_team_artifacts() { printf '%s\n' forbidden > "$FORBIDDEN_CALL"; return 97; }
if [ "$3" = self_heal ]; then self_heal_runtime_state; else restart_active_teams; fi
"""
    result = subprocess.run(
        [
            "/bin/bash",
            "--noprofile",
            "--norc",
            "-c",
            script,
            "owned-consumer",
            str(ROOT),
            str(state),
            consumer,
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env={
            "PATH": "/usr/bin:/bin",
            "SYNTHETIC_STATE": str(state),
            "FORBIDDEN_CALL": str(forbidden),
        },
    )
    assert result.returncode == 0, result.stderr
    assert not pid.exists() and not forbidden.exists()
    assert guard_snapshot(guard) == before


def test_pid_only_python_repair_preserves_guard_without_process_calls(
    tmp_path, monkeypatch
):
    monkeypatch.syspath_prepend(str(ROOT / "py"))
    spec = importlib.util.spec_from_file_location(
        "owned_lock_consumer_runtime", ROOT / "py/runtime_state.py"
    )
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("process/backend call forbidden in owned repair fixture")

    monkeypatch.setattr(runtime, "_pid_alive", lambda _pid: False)
    monkeypatch.setattr(runtime.os, "kill", forbidden)
    monkeypatch.setattr(runtime.subprocess, "run", forbidden)
    monkeypatch.setattr(runtime.subprocess, "check_output", forbidden)
    state = tmp_path / "state"
    state.mkdir()
    pid = state / "mainspring.lock"
    guard = state / "mainspring.lock.guard"
    pid.write_text("424242\n")
    guard.write_bytes(b"owned synthetic persistent guard\n")
    before = guard_snapshot(guard)
    (state / "skill-active-state.json").write_text(
        json.dumps({"active": False, "skill": "owned-test"})
    )
    (state / "owned-test-state.json").write_text(json.dumps({"active": False}))
    runtime.cmd_repair(str(state), force=True)
    assert not pid.exists()
    assert guard_snapshot(guard) == before
