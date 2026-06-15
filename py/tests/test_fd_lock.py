# SPDX-License-Identifier: Apache-2.0
"""Tests for the Mainspring fd-lock helper."""

from __future__ import annotations

import builtins
import fcntl
import subprocess
import sys
from pathlib import Path

import pytest

import fd_lock


HELPER = Path(__file__).resolve().parents[1] / "fd_lock.py"


# Scenario: Doctor can probe Python's stdlib fd-lock fallback without embedding
# Python in shell heredocs.
# Expected: The helper reports available fcntl support on the supported POSIX
# runtime used by Mainspring.
def test_check_command_reports_fcntl_available() -> None:
    result = subprocess.run(
        [sys.executable, str(HELPER), "check"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_check_fcntl_reports_missing_stdlib_module(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "fcntl":
            raise ImportError("missing fcntl")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert fd_lock.check_fcntl() == 2
    assert "missing fcntl" in capsys.readouterr().err


# Scenario: The shell lock fallback asks the helper to lock an existing fd.
# Expected: The helper takes and releases the lock using the same fd semantics
# as the shell runtime.
def test_lock_and_unlock_existing_fd(tmp_path: Path) -> None:
    lock_file = tmp_path / "mainspring.lock"
    with lock_file.open("w+") as handle:
        assert fd_lock.lock_fd(handle.fileno()) == 0

        with lock_file.open("w+") as competitor:
            try:
                fcntl.flock(competitor.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                blocked = True
            else:
                blocked = False
                fcntl.flock(competitor.fileno(), fcntl.LOCK_UN)

        assert blocked is True
        assert fd_lock.unlock_fd(handle.fileno()) == 0


def test_lock_and_unlock_report_missing_or_busy_fcntl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fd_lock, "_load_fcntl", lambda: None)
    assert fd_lock.lock_fd(9) == 2
    assert fd_lock.unlock_fd(9) == 2

    class BlockingFcntl:
        LOCK_EX = 1
        LOCK_NB = 2
        LOCK_UN = 4

        @staticmethod
        def flock(fd: int, flags: int) -> None:
            raise BlockingIOError()

    monkeypatch.setattr(fd_lock, "_load_fcntl", lambda: BlockingFcntl)
    assert fd_lock.lock_fd(9) == 1

    class BusyFcntl(BlockingFcntl):
        @staticmethod
        def flock(fd: int, flags: int) -> None:
            raise OSError(fd_lock.errno.EAGAIN, "busy")

    monkeypatch.setattr(fd_lock, "_load_fcntl", lambda: BusyFcntl)
    assert fd_lock.lock_fd(9) == 1


# Scenario: A broken shell invocation points at a non-open fd.
# Expected: The helper fails loud with the dependency-error status used by
# lock.sh to report lock setup problems.
def test_lock_command_rejects_invalid_fd() -> None:
    result = subprocess.run(
        [sys.executable, str(HELPER), "lock", "999999"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "could not lock fd" in result.stderr


def test_main_help_and_usage_paths(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert fd_lock.main(["--help"]) == 0
    assert "Usage: fd_lock.py" in capsys.readouterr().out

    assert fd_lock.main([]) == 2
    assert "Usage: fd_lock.py" in capsys.readouterr().out

    assert fd_lock.main(["check", "9"]) == 2
    assert "Usage: fd_lock.py" in capsys.readouterr().err

    seen: list[int] = []
    monkeypatch.setattr(fd_lock, "lock_fd", lambda fd: seen.append(fd) or 2)
    assert fd_lock.main(["lock"]) == 2
    assert seen == [9]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["lock", "bad"], "fd must be an integer"),
        (["lock", "-1"], "fd must be non-negative"),
        (["lock", "1", "2"], "too many arguments"),
        (["bogus"], "Usage: fd_lock.py"),
    ],
)
def test_main_rejects_invalid_invocations(
    args: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert fd_lock.main(args) == 2
    assert message in capsys.readouterr().err


def test_unlock_command_rejects_invalid_fd() -> None:
    result = subprocess.run(
        [sys.executable, str(HELPER), "unlock", "999999"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "could not unlock fd" in result.stderr
