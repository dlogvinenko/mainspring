# SPDX-License-Identifier: Apache-2.0
"""Repository-relative owned-TMP protocol probes; no user runtime entrypoint."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path(sys.executable).resolve()
BASH = Path("/bin/bash")
SHELL = r"""#!/bin/bash
set -eu
source "$SNAPSHOT/lib/common.sh"
source "$LOCK_SOURCE"
mainspring_python() { builtin printf '%s\n' "$PROBE_PYTHON"; }
event() {
  builtin printf '%s\n' "$1" >> "$CONTROL/$ROLE.record"
  builtin printf '%s\n' "$1" > "$CONTROL/$ROLE.events"
}
gate() { local token; IFS= read -r token < "$CONTROL/$ROLE.go"; }
inode() {
  "$PROBE_PYTHON" -B -c '
import os
s=os.fstat(9)
print(str(s.st_dev)+":"+str(s.st_ino))
'
}
# Backend selection is test configuration, not a fake native binary.
# Valid fcntl cases execute the actual published fd_lock.py helper.
if [ "$BACKEND" = fcntl ] && [[ "$MODE" != native-* ]]; then
  lock_fd9_nonblocking() {
    local runtime_python
    runtime_python="$(mainspring_python)"
    if [ ! -x "$runtime_python" ] &&
       ! command -v "$runtime_python" >/dev/null 2>&1; then
      echo "Mainspring runtime lock requires either flock or Python fcntl support." >&2
      return 2
    fi
    "$runtime_python" "$MAINSPRING_PY_DIR/fd_lock.py" lock 9
  }
  unlock_fd9() {
    local runtime_python
    runtime_python="$(mainspring_python)"
    [ -x "$runtime_python" ] || command -v "$runtime_python" >/dev/null 2>&1 || return 0
    "$runtime_python" "$MAINSPRING_PY_DIR/fd_lock.py" unlock 9 >/dev/null 2>&1 || true
  }
fi
case "$MODE" in
  stale) kill() { if [ "${1:-}" = -0 ]; then return 1; fi; builtin kill "$@"; } ;;
  missing) mainspring_python() { builtin printf '%s\n' "$CONTROL/no-python"; } ;;
  fallback-error) lock_fd9_nonblocking() { return 2; } ;;
  native-1) flock() { return 1; } ;;
  native-2) flock() { return 2; } ;;
  native-0) flock() { return 0; } ;;
esac
eval "$(
  declare -f lock_fd9_nonblocking |
    sed '1s/lock_fd9_nonblocking/real_lock_fd9_nonblocking/'
)"
lock_fd9_nonblocking() {
  event "opened:$(inode)"
  if [ "$ROLE" = B ] && [ "$MODE" = race ]; then gate; fi
  local status=0
  real_lock_fd9_nonblocking || status=$?
  event "lock-status:$status:$(inode)"
  return "$status"
}
printf() {
  if [ "$MODE" = race ] && [ "$ROLE" != A ] &&
     [ "${1:-}" = '%s\n' ] && [ "${2:-}" = "$$" ]; then
    event "prewrite:$(inode)"
    gate
  fi
  builtin printf "$@"
}
event "started:$$"
acquire_lock
event "acquired:$$:$(inode)"
gate
release_lock
event released
"""


class Actor:
    def __init__(self, probe: Probe, role: str, mode: str) -> None:
        self.probe = probe
        self.role = role
        self.pending: list[str] = []
        self.record: list[str] = []
        self.buffer = b""
        for suffix in ("events", "go"):
            path = probe.control / f"{role}.{suffix}"
            os.mkfifo(path)
        self.event_fd = os.open(
            probe.control / f"{role}.events", os.O_RDWR | os.O_NONBLOCK
        )
        self.go_fd = os.open(probe.control / f"{role}.go", os.O_RDWR | os.O_NONBLOCK)
        env = {
            "PATH": probe.path,
            "PYTHONNOUSERSITE": "1",
            "BACKEND": probe.backend,
            "LOCK_SOURCE": str(probe.sources.get(role, probe.source)),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PROBE_PYTHON": str(PYTHON),
            "SNAPSHOT": str(probe.snapshot),
            "CONTROL": str(probe.control),
            "LOCK_FILE": str(probe.lock_file),
            "MAINSPRING_PY_DIR": str(probe.snapshot / "py"),
            "ROLE": role,
            "MODE": mode,
        }
        self.process = subprocess.Popen(
            [str(BASH), str(probe.script)],
            cwd=probe.control,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        probe.actors.append(self)

    def read_events(self) -> None:
        while True:
            try:
                chunk = os.read(self.event_fd, 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            self.buffer += chunk
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            text = line.decode()
            self.pending.append(text)
            self.record.append(text)

    def wait(self, prefix: str) -> str | None:
        deadline = time.monotonic() + 10
        with selectors.DefaultSelector() as selector:
            selector.register(self.event_fd, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                self.read_events()
                for i, item in enumerate(self.pending):
                    if item == prefix or item.startswith(prefix + ":"):
                        return self.pending.pop(i)
                if self.process.poll() is not None:
                    self.read_events()
                    for i, item in enumerate(self.pending):
                        if item == prefix or item.startswith(prefix + ":"):
                            return self.pending.pop(i)
                    return None
                selector.select(min(0.1, deadline - time.monotonic()))
        raise AssertionError(f"actor {self.role} missing {prefix}: {self.record}")

    def go(self) -> None:
        os.write(self.go_fd, b"continue\n")

    def finish(self) -> dict:
        stdout, stderr = self.process.communicate(timeout=10)
        self.read_events()
        return {
            "role": self.role,
            "pid": self.process.pid,
            "returncode": self.process.returncode,
            "events": self.record,
            "stdout": stdout.decode(),
            "stderr": stderr.decode(),
        }


class Probe:
    def __init__(
        self,
        snapshot: Path,
        name: str,
        parent: Path,
        backend: str,
        source: Path | None = None,
        sources: dict | None = None,
    ) -> None:
        self.snapshot = snapshot.resolve()
        self.backend = backend
        info = backend_identity(backend)
        self.path = info["path"]
        self.source = source or self.snapshot / "lib/lock.sh"
        self.sources = sources or {}
        self.control = Path(tempfile.mkdtemp(prefix=name + "-", dir=parent))
        self.script = self.control / "actor.sh"
        self.script.write_text(SHELL)
        self.lock_file = self.control / "synthetic.lock"
        self.actors: list[Actor] = []

    def close(self) -> None:
        for actor in self.actors:
            if actor.process.poll() is None:
                actor.process.terminate()
            actor.process.communicate(timeout=10)
            os.close(actor.event_fd)
            os.close(actor.go_fd)


def race(snapshot: Path, parent: Path, backend: str, sources=None) -> dict:
    probe = Probe(snapshot, "race", parent, backend, sources=sources)
    try:
        a = Actor(probe, "A", "normal")
        acquired_a = a.wait("acquired")
        assert acquired_a
        sequence = ["A " + acquired_a]
        initial_inode = probe.lock_file.stat().st_ino
        b = Actor(probe, "B", "race")
        opened_b = b.wait("opened")
        assert opened_b
        sequence.append("B " + opened_b)
        a.go()
        assert a.wait("released")
        sequence.append("A released")
        a_result = a.finish()
        after_a = probe.lock_file.exists()
        b.go()
        prewrite_b = b.wait("prewrite")
        assert prewrite_b
        sequence.append("B " + prewrite_b)
        c = Actor(probe, "C", "race")
        c_prewrite = c.wait("prewrite")
        if c_prewrite:
            sequence.append("C " + c_prewrite)
            # Both successful kernel locks and both PID reads occurred before
            # either advisory PID write. Only now permit those writes.
            b.go()
            c.go()
            acquired_b = b.wait("acquired")
            acquired_c = c.wait("acquired")
        else:
            sequence.append("C exited without prewrite")
            b.go()
            acquired_b = b.wait("acquired")
            acquired_c = None
        overlap = bool(acquired_b and acquired_c)
        sequence.extend(["B " + str(acquired_b), "C " + str(acquired_c)])
        alive_at_observation = {
            "B": b.process.poll() is None,
            "C": c.process.poll() is None,
        }
        current_inode = probe.lock_file.stat().st_ino
        metadata = probe.lock_file.read_text()
        b.go()
        if acquired_c:
            c.go()
        b_result = b.finish()
        c_result = c.finish()
        return {
            "name": "preopened-inode-release-race",
            "controller_sequence": sequence,
            "control": str(probe.control),
            "pid_path_initial_inode": initial_inode,
            "pid_path_after_a_exists": after_a,
            "pid_path_current_inode": current_inode,
            "both_acquire_returned_success_before_either_release": overlap,
            "alive_at_observation": alive_at_observation,
            "pid_metadata_at_observation": metadata,
            "actors": [a_result, b_result, c_result],
        }
    finally:
        probe.close()


def controls(snapshot: Path, parent: Path, backend: str) -> list[dict]:
    results = []
    for mode in (
        "normal",
        "fallback-error",
        "missing",
        "native-1",
        "native-2",
        "native-0",
    ):
        probe = Probe(snapshot, mode, parent, "fcntl" if mode == "missing" else backend)
        try:
            actor = Actor(probe, "A", mode)
            acquired = actor.wait("acquired")
            metadata = probe.lock_file.read_text() if probe.lock_file.exists() else None
            if acquired:
                actor.go()
                assert actor.wait("released")
            result = actor.finish()
            results.append(
                {
                    "name": mode,
                    "acquired": bool(acquired),
                    "metadata_after_acquire": metadata,
                    "pid_path_after_release_exists": probe.lock_file.exists(),
                    "actor": result,
                    "native_backend_is_stub": mode.startswith("native-"),
                }
            )
        finally:
            probe.close()

    for name in (
        "busy",
        "legacy-live-pid",
        "foreign-pid-release",
        "stale-pid",
        "reacquire",
    ):
        probe = Probe(snapshot, name, parent, backend)
        try:
            if name == "legacy-live-pid":
                probe.lock_file.write_text(str(os.getpid()) + "\n")
            elif name == "stale-pid":
                # This case tests advisory stale-PID handling, not PID reuse.
                # The actor's MODE=stale stubs only its synthetic liveness check.
                probe.lock_file.write_text("424242\n")
            a = Actor(probe, "A", "stale" if name == "stale-pid" else "normal")
            acquired_a = a.wait("acquired")
            actors = []
            if name == "busy":
                b = Actor(probe, "B", "normal")
                assert b.wait("acquired") is None
                actors.append(b.finish())
            if name == "foreign-pid-release":
                probe.lock_file.write_text(str(os.getpid()) + "\n")
            if acquired_a:
                a.go()
                assert a.wait("released")
            actors.append(a.finish())
            after_release = (
                probe.lock_file.read_text() if probe.lock_file.exists() else None
            )
            if name == "reacquire":
                b = Actor(probe, "B", "normal")
                assert b.wait("acquired")
                b.go()
                assert b.wait("released")
                actors.append(b.finish())
            results.append(
                {
                    "name": name,
                    "acquired_a": bool(acquired_a),
                    "metadata_after_release": after_release,
                    "expected_foreign_pid": os.getpid()
                    if "pid" in name and name != "stale-pid"
                    else None,
                    "actors": actors,
                }
            )
        finally:
            probe.close()
    return results


def backend_identity(backend: str) -> dict:
    """Require a genuine native executable when the Linux job requests it."""
    if backend not in {"fcntl", "native"}:
        raise AssertionError("unknown test backend")
    info = {
        "backend": backend,
        "python": str(PYTHON),
        "platform": sys.platform,
        "path": "/usr/bin:/bin",
        "native_is_stub": False,
    }
    if backend == "native":
        import shutil

        binary = shutil.which("flock")
        if binary is None:
            raise AssertionError(
                "native flock required; absence is a failure, not a skip"
            )
        binary = Path(binary).resolve()
        with binary.open("rb") as stream:
            magic = stream.read(4)
        if sys.platform == "linux" and magic != b"\x7fELF":
            raise AssertionError(
                "Linux native flock must be an actual executable, not a script stub"
            )
        result = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        if "flock" not in result.stdout.lower():
            raise AssertionError("native flock version identity missing")
        info.update(
            native_path=str(binary),
            native_version=result.stdout.strip(),
            path=str(binary.parent) + ":/usr/bin:/bin",
        )
    else:
        import fcntl

        info["python_fcntl_module"] = fcntl.__name__

        info["proof"] = "Actual Python fd_lock.py/fcntl; no native branch claim"
    return info


STDERR_SHELL = r"""#!/bin/bash
set -u
MODE="$1"; VARIANT="$2"; STATE="$3"; HELPERS="$4"
LOCK_FILE="$STATE/runtime.lock"
MAINSPRING_PY_DIR="$HELPERS"
mainspring_python() { printf '%s\n' "$NATIVE_PYTHON"; }
source "$VARIANT"
guard_identity() {
  "$NATIVE_PYTHON" -B -c '
import os,sys
s=os.stat(sys.argv[1])
print(str(s.st_dev)+":"+str(s.st_ino))
' "$LOCK_FILE.guard"
}
if [ "$BACKEND" = fcntl ]; then
  lock_fd9_nonblocking() { "$NATIVE_PYTHON" "$HELPERS/fd_lock.py" lock 9; }
  unlock_fd9() {
    "$NATIVE_PYTHON" "$HELPERS/fd_lock.py" unlock 9 >/dev/null 2>&1 || true
  }
fi
mkdir -p "$STATE"
case "$MODE" in
  ordinary)
    trap 'printf "%s\n" ORDINARY_EXIT_MARKER >&2' EXIT
    acquire_lock
    printf '%s\n' ORDINARY_ACQUIRED
    release_lock
    printf '%s\n' AFTER_RELEASE_MARKER >&2
    printf '%s\n' ORDINARY_FINISHED
    ;;
  trap_release)
    trap 'release_lock; printf "%s\n" AFTER_TRAP_RELEASE_MARKER >&2' EXIT
    acquire_lock
    printf '%s\n' TRAP_BODY_FINISHED
    ;;
  child_busy)
    trap 'printf "%s\n" BUSY_EXIT_MARKER >&2' EXIT
    acquire_lock
    printf '%s\n' BUSY_UNEXPECTED_ACQUIRE
    release_lock
    ;;
  busy)
    acquire_lock
    /bin/bash --noprofile --norc "$0" child_busy "$VARIANT" "$STATE" "$HELPERS"
    result=$?
    printf 'BUSY_CHILD_RC=%s\n' "$result"
    release_lock
    [ "$result" -eq 1 ]
    ;;
  child_refusal)
    trap 'printf "%s\n" REFUSAL_EXIT_MARKER >&2' EXIT
    acquire_lock
    printf '%s\n' REFUSAL_UNEXPECTED_ACQUIRE
    release_lock
    ;;
  live_refusal)
    # This is the PID of the owned fixture parent, never a user/worker process.
    printf '%s\n' "$$" > "$LOCK_FILE"
    /bin/bash --noprofile --norc "$0" child_refusal "$VARIANT" "$STATE" "$HELPERS"
    result=$?
    printf 'REFUSAL_CHILD_RC=%s\n' "$result"
    acquire_lock
    printf '%s\n' REFUSAL_PARENT_REACQUIRED
    release_lock
    [ "$result" -eq 1 ]
    ;;
  helper_error)
    trap 'printf "%s\n" ERROR_EXIT_MARKER >&2' EXIT
    exec 8>&-
    # Exercise real helper/fcntl error handling on a deliberately closed owned FD.
    lock_fd9_nonblocking() { "$NATIVE_PYTHON" "$HELPERS/fd_lock.py" lock 8; }
    acquire_lock
    printf '%s\n' ERROR_UNEXPECTED_ACQUIRE
    release_lock
    ;;
  foreign_release)
    trap 'printf "%s\n" FOREIGN_EXIT_MARKER >&2' EXIT
    acquire_lock
    printf '%s\n' fixture-foreign-advisory > "$LOCK_FILE"
    release_lock
    [ "$(cat "$LOCK_FILE")" = fixture-foreign-advisory ] || exit 7
    printf '%s\n' FOREIGN_PID_PRESERVED
    printf '%s\n' FOREIGN_AFTER_RELEASE_MARKER >&2
    ;;
  guard_child)
    acquire_lock
    printf '%s\n' GUARD_CHILD_ACQUIRED
    release_lock
    ;;
  guard_cycle)
    acquire_lock
    first=$(guard_identity) || exit $?
    release_lock
    /bin/bash --noprofile --norc "$0" guard_child "$VARIANT" "$STATE" "$HELPERS"
    result=$?
    second=$(guard_identity) || exit $?
    [ "$first" = "$second" ] && [ "$result" -eq 0 ] || exit 8
    [ ! -f "$LOCK_FILE" ] || exit 9
    printf '%s\n' GUARD_INODE_STABLE CHILD_REACQUIRED_WHILE_PARENT_ALIVE OWN_PID_REMOVED
    ;;
  *) exit 64 ;;
esac
"""


def stderr_case(
    snapshot: Path, parent: Path, backend: str, case: str, source: Path | None = None
) -> dict:
    folder = parent / case
    folder.mkdir()
    script = folder / "stderr_actor.sh"
    script.write_text(STDERR_SHELL)
    info = backend_identity(backend)
    args = [
        str(BASH),
        "--noprofile",
        "--norc",
        str(script),
        case,
        str(source or snapshot / "lib/lock.sh"),
        str(folder / "state"),
        str(snapshot / "py"),
    ]
    result = subprocess.run(
        args,
        check=False,
        cwd=folder,
        capture_output=True,
        text=True,
        timeout=8,
        env={
            "PATH": info["path"],
            "BACKEND": backend,
            "NATIVE_PYTHON": str(PYTHON),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONIOENCODING": "utf-8",
        },
    )
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


if __name__ == "__main__":
    print(
        json.dumps(
            backend_identity(os.environ.get("MAINSPRING_LOCK_TEST_BACKEND", "fcntl")),
            sort_keys=True,
        )
    )
