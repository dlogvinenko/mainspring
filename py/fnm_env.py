# SPDX-License-Identifier: Apache-2.0
"""Convert ``fnm env --json`` output into safe shell assignment lines."""

from __future__ import annotations

import json
import sys
from typing import TextIO

from cli_runtime import run_cli

ALLOWED_FNM_KEYS = (
    "FNM_COREPACK_ENABLED",
    "FNM_NODE_DIST_MIRROR",
    "FNM_VERSION_FILE_STRATEGY",
    "FNM_RESOLVE_ENGINES",
    "FNM_ARCH",
    "FNM_MULTISHELL_PATH",
    "FNM_DIR",
    "FNM_LOGLEVEL",
)


def _clean_env_value(value: object) -> str:
    return str(value).replace("\n", "").replace("\r", "")


def emit_assignments(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    try:
        payload = json.load(stdin)
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        return 1
    if not isinstance(payload, dict):
        return 1

    multishell = _clean_env_value(payload.get("FNM_MULTISHELL_PATH") or "")
    if multishell:
        print(f"MAINSPRING_FNM_BIN={multishell}/bin", file=stdout)

    for key in ALLOWED_FNM_KEYS:
        value = payload.get(key)
        if value is not None:
            print(f"{key}={_clean_env_value(value)}", file=stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print("Usage: fnm_env.py", file=sys.stderr)
        return 2
    return emit_assignments()


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
