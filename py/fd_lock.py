#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""File-descriptor lock helper for the Mainspring shell runtime."""

from __future__ import annotations

import errno
import sys
from typing import Sequence

from cli_runtime import run_cli

BUSY_ERRNOS = {errno.EACCES, errno.EAGAIN}
USAGE = "Usage: fd_lock.py check|lock|unlock [fd]"


def _load_fcntl():
    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - fcntl is present on CI POSIX.
        print(f"Mainspring fd locks require Python fcntl: {exc}", file=sys.stderr)
        return None
    return fcntl


def check_fcntl() -> int:
    """Return 0 when Python can provide stdlib fcntl locks."""
    return 0 if _load_fcntl() is not None else 2


def lock_fd(fd: int) -> int:
    """Acquire a nonblocking exclusive flock on an already-open file descriptor."""
    fcntl = _load_fcntl()
    if fcntl is None:
        return 2
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 1
    except OSError as exc:
        if exc.errno in BUSY_ERRNOS:
            return 1
        print(f"Mainspring could not lock fd {fd}: {exc}", file=sys.stderr)
        return 2
    return 0


def unlock_fd(fd: int) -> int:
    """Release a flock on an already-open file descriptor."""
    fcntl = _load_fcntl()
    if fcntl is None:
        return 2
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError as exc:
        print(f"Mainspring could not unlock fd {fd}: {exc}", file=sys.stderr)
        return 2
    return 0


def _parse_fd(args: Sequence[str]) -> int:
    if not args:
        return 9
    if len(args) > 1:
        raise ValueError("too many arguments")
    try:
        fd = int(args[0])
    except ValueError as exc:
        raise ValueError("fd must be an integer") from exc
    if fd < 0:
        raise ValueError("fd must be non-negative")
    return fd


def main(argv: Sequence[str] | None = None) -> int:
    """Run the fd-lock helper CLI."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(USAGE)
        return 0 if args and args[0] in {"-h", "--help"} else 2

    command = args[0]
    if command == "check":
        if len(args) != 1:
            print(USAGE, file=sys.stderr)
            return 2
        return check_fcntl()

    if command not in {"lock", "unlock"}:
        print(USAGE, file=sys.stderr)
        return 2

    try:
        fd = _parse_fd(args[1:])
    except ValueError as exc:
        print(f"{USAGE}\nfd_lock.py: {exc}", file=sys.stderr)
        return 2

    if command == "lock":
        return lock_fd(fd)
    return unlock_fd(fd)


if __name__ == "__main__":
    run_cli(main)
