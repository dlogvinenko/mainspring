# SPDX-License-Identifier: Apache-2.0
"""Signal shutdown regression for the solo wave loop.

Drives the real ``mainspring.sh`` with stub ``codex``, ``claude`` and ``task-master``
binaries (no model or network calls). The stub reviewer blocks, the test sends
SIGTERM or SIGINT to the Mainspring process only, and then checks that the run
stops with the conventional signal exit code, starts no further wave, keeps the
runtime lock until it exits, and leaves no engine process behind.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAINSPRING_SH = REPO_ROOT / "mainspring.sh"

pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("git") is None,
    reason="signal shutdown regression needs POSIX signals, bash and git",
)

STUB_CODEX = """#!/bin/bash
# Stub engine: records each turn; the reviewer blocks until it is signalled.
prompt="${@: -1}"
if [ "${FAKE_ENGINE:-codex}" = claude ]; then
  echo '{"type":"system","subtype":"init","model":"stub-model"}'
fi
if printf '%s' "$prompt" | grep -q 'You are the review gate'; then
  echo reviewer >> "$FAKE_CTRL/calls.log"
  echo "$$" > "$FAKE_CTRL/reviewer.pid"
  if [ "${FAKE_IGNORE_TERM:-0}" = 1 ]; then
    trap '' TERM
    sleep 60 &
    echo "$!" > "$FAKE_CTRL/engine-child.pid"
    wait
  else
    exec sleep 60
  fi
fi
echo writer >> "$FAKE_CTRL/calls.log"
mkdir -p src
[ -f src/feature.py ] || echo 'VALUE = 42' > src/feature.py
if [ "${FAKE_ENGINE:-codex}" = claude ]; then
  echo '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"Implemented src/feature.py"}}}'
  echo '{"type":"result","is_error":false}'
else
  echo "Implemented src/feature.py"
fi
"""

STUB_TASK_MASTER = """
import json
import sys

PATH = ".taskmaster/tasks/tasks.json"
data = json.load(open(PATH, encoding="utf-8"))
tasks = data["master"]["tasks"]
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
opts = dict(
    arg[2:].split("=", 1) for arg in sys.argv[2:] if arg.startswith("--") and "=" in arg
)
if cmd == "next":
    ready = [t for t in tasks if t["status"] in ("pending", "in-progress")]
    if ready:
        print(f"Next Task: #{ready[0]['id']} - {ready[0]['title']}")
    else:
        print("No eligible tasks found!")
elif cmd == "show":
    for task in tasks:
        if str(task["id"]) == sys.argv[2]:
            print(f"Task {task['id']}: {task['title']} status={task['status']}")
elif cmd == "set-status":
    for task in tasks:
        if str(task["id"]) == opts["id"]:
            task["status"] = opts["status"]
    json.dump(data, open(PATH, "w", encoding="utf-8"), indent=1)
"""

TASKS = {
    "master": {
        "tasks": [
            {
                "id": 1,
                "title": "Add feature value",
                "description": "Implement src/feature.py",
                "status": "pending",
                "dependencies": [],
                "subtasks": [],
            }
        ]
    }
}


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    state = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return bool(state) and not state.startswith("Z")


def _wait_for(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _make_project(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    project = tmp_path / "project"
    ctrl = tmp_path / "ctrl"
    bin_dir = tmp_path / "bin"
    for path in (project / ".taskmaster" / "tasks", ctrl, bin_dir):
        path.mkdir(parents=True)
    (project / ".taskmaster" / "tasks" / "tasks.json").write_text(
        json.dumps(TASKS), encoding="utf-8"
    )
    (project / "README.md").write_text("fixture\n", encoding="utf-8")
    git_identity = [
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "user.name=fixture",
    ]
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(
        ["git", *git_identity, "commit", "-qm", "fixture"], cwd=project, check=True
    )

    _write_executable(bin_dir / "codex", STUB_CODEX)
    _write_executable(bin_dir / "claude", STUB_CODEX)
    _write_executable(
        bin_dir / "task-master", f"#!{sys.executable}\n{STUB_TASK_MASTER}"
    )

    env = {k: v for k, v in os.environ.items() if not k.startswith("MAINSPRING_")}
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_CTRL": str(ctrl),
            "MAINSPRING_PY": sys.executable,
            "MAINSPRING_PATH_PREFIX": str(bin_dir),
            "MAINSPRING_NOTIFY_ENABLED": "0",
        }
    )
    return project, ctrl, env


@pytest.mark.parametrize(
    "signum", [signal.SIGTERM, signal.SIGINT], ids=["sigterm", "sigint"]
)
@pytest.mark.parametrize(
    "ignore_term", [False, True], ids=["cooperative", "ignores-term"]
)
@pytest.mark.parametrize("engine", ["codex", "claude"])
def test_signal_during_review_stops_loop_and_holds_lock_until_exit(
    tmp_path: Path, signum: signal.Signals, ignore_term: bool, engine: str
) -> None:
    project, ctrl, env = _make_project(tmp_path)
    env["FAKE_IGNORE_TERM"] = str(int(ignore_term))
    env["FAKE_ENGINE"] = engine
    lock_file = project / ".mainspring" / "state" / "mainspring.lock"
    reviewer_pid_file = ctrl / "reviewer.pid"
    output = (tmp_path / "run.out").open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            str(MAINSPRING_SH),
            "--project",
            str(project),
            "taskmaster",
            "--pair",
            f"{engine}+{engine}",
        ],
        cwd=project,
        env=env,
        stdout=output,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    reviewer_pid = 0
    try:
        assert _wait_for(
            lambda: reviewer_pid_file.is_file() or proc.poll() is not None, 60
        ), "reviewer turn never started"
        assert reviewer_pid_file.is_file(), (tmp_path / "run.out").read_text()
        reviewer_pid = int(reviewer_pid_file.read_text(encoding="utf-8").strip())
        if ignore_term:
            assert _wait_for((ctrl / "engine-child.pid").is_file, 5), (
                "TERM-resistant engine subprocess never started"
            )
        assert lock_file.read_text(encoding="utf-8").strip() == str(proc.pid)

        proc.send_signal(signum)
        lock_gone_at = None
        engine_unlocked = False
        deadline = time.monotonic() + 15
        while proc.poll() is None and time.monotonic() < deadline:
            if not lock_file.exists():
                if lock_gone_at is None:
                    lock_gone_at = time.monotonic()
                engine_unlocked = engine_unlocked or _pid_alive(reviewer_pid)
                child_file = ctrl / "engine-child.pid"
                if child_file.exists():
                    engine_unlocked = engine_unlocked or _pid_alive(
                        int(child_file.read_text().strip())
                    )
            time.sleep(0.05)
        exited_at = time.monotonic()
        still_running = proc.poll() is None
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        output.close()

    calls = (ctrl / "calls.log").read_text(encoding="utf-8").split()
    engine_survived = _wait_for(lambda: not _pid_alive(reviewer_pid), 3) is False
    if engine_survived:
        os.kill(reviewer_pid, signal.SIGKILL)
    child_pid_file = ctrl / "engine-child.pid"
    child_survived = False
    if child_pid_file.exists():
        child_pid = int(child_pid_file.read_text().strip())
        child_survived = not _wait_for(lambda: not _pid_alive(child_pid), 3)
        if child_survived:
            os.kill(child_pid, signal.SIGKILL)

    problems = []
    if still_running:
        problems.append("Mainspring kept running 15s after the signal")
    elif proc.returncode != 128 + signum:
        problems.append(f"exit code {proc.returncode}, expected {128 + signum}")
    if calls.count("writer") != 1:
        problems.append(f"a further wave started: {calls}")
    if engine_survived:
        problems.append("engine turn outlived the Mainspring process")
    if child_survived:
        problems.append("engine subprocess outlived the Mainspring process")
    if engine_unlocked:
        problems.append("lock was released while an engine process was still running")
    if lock_gone_at is not None and exited_at - lock_gone_at >= 2:
        problems.append(
            f"lock released {exited_at - lock_gone_at:.1f}s before the process exited"
        )
    if not still_running and lock_file.exists():
        problems.append("runtime lock was not released on exit")
    assert not problems, "; ".join(problems)


@pytest.mark.parametrize("mode", ["cooperative", "mixed"])
def test_cleanup_signals_only_owned_processes_still_observed_live(
    tmp_path: Path, mode: str
) -> None:
    import re

    match = re.search(
        r"(?ms)^cleanup_children\(\) \{\n.*?^\}",
        MAINSPRING_SH.read_text(encoding="utf-8"),
    )
    assert match is not None
    # Mock only OS command boundaries; execute the actual production cleanup.
    # In mixed mode PID 101 becomes a zombie, then appears live as a reused PID.
    # PID 103 is already a zombie before TERM and must never be signalled.
    script = r"""
set -eu
ACTIVE_CHILD_PID=101
ACTIVE_HEARTBEAT_PID=""
ps() {
  if [ "$1" = "-axo" ]; then
    printf '101 1\n102 101\n103 102\n'
    return
  fi
  wanted=""
  format="$2"
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "-p" ]; then wanted="$2"; break; fi
    shift
  done
  phase=before
  [ ! -f "$CTRL/phase" ] || phase="$(cat "$CTRL/phase")"
  count=0
  [ ! -f "$CTRL/count" ] || count="$(cat "$CTRL/count")"
  count=$((count + 1))
  printf '%s\n' "$count" > "$CTRL/count"
  if [ "$phase" = killed ]; then return 1; fi
  if [ "$MODE" = cooperative ] && [ "$phase" = term ]; then return 1; fi
  for pid in 101 102 103; do
    case ",$wanted," in
      *",$pid,"*)
        state=S
        if [ "$MODE" = mixed ]; then
          [ "$pid" != 103 ] || state=Z
          if [ "$phase" = term ] && [ "$pid" = 101 ] && [ "$count" -eq 1 ]; then
            state=Z
          fi
        fi
        if [ "$format" = "stat=" ]; then
          printf '%s\n' "$state"
        else
          printf '%s %s\n' "$pid" "$state"
        fi
        ;;
    esac
  done
}
kill() {
  printf 'SIGNAL %s\n' "$*" >> "$CTRL/events"
  if [ "$1" = "-TERM" ]; then
    printf term > "$CTRL/phase"
    printf 0 > "$CTRL/count"
  elif [ "$1" = "-KILL" ]; then
    printf killed > "$CTRL/phase"
  fi
}
sleep() { :; }
wait() { printf 'WAIT %s\n' "$*" >> "$CTRL/events"; }
reap_notify_daemon() { :; }
release_lock() { printf 'RELEASE\n' >> "$CTRL/events"; }
"""
    env = {**os.environ, "CTRL": str(tmp_path), "MODE": mode}
    result = subprocess.run(
        ["bash", "-c", script + "\n" + match.group() + "\ncleanup_children\n"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    events = (tmp_path / "events").read_text().splitlines()
    signals = [line.split()[1:] for line in events if line.startswith("SIGNAL ")]
    if mode == "cooperative":
        assert [signal[0] for signal in signals] == ["-TERM"]
    else:
        assert len(signals) == 2
        assert signals[0][0] == "-TERM"
        assert set(signals[0][1:]) == {"101", "102"}
        assert signals[1] == ["-KILL", "102"]
    assert events[-2:] == ["WAIT 101", "RELEASE"]
