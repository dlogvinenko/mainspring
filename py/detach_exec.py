#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Detach the current process session and exec the requested command."""

from __future__ import annotations

from cli_runtime import run_cli

import os
import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Usage: detach_exec.py <command> [args...]", file=sys.stderr)
        return 2
    os.setsid()
    try:
        os.execvp(args[0], args)
    except OSError as exc:
        print(f"detach_exec.py: could not exec {args[0]}: {exc}", file=sys.stderr)
        return 127
    return 0


if __name__ == "__main__":
    run_cli(main)
