#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Parse team backend status JSON for Mainspring.

Reads JSON from stdin and extracts a single field, replacing eight
inline ``python3 -c`` invocations in the bash monolith with one
testable CLI.

Usage:
    printf '%s' "$status_json" | python3 team_status.py --field status
    printf '%s' "$status_json" | python3 team_status.py --field phase
    printf '%s' "$status_json" | python3 team_status.py --field dead-workers
    printf '%s' "$status_json" | python3 team_status.py --field usable-check

Fields:
    status        Extract .status (empty string on error)
    phase         Extract .phase (empty string on error)
    dead-workers  Extract .workers.dead (0 on error)
    pending-lines Extract .pending_lines (0 on error)
    usable-check  Print "usable" if status=ok, total>0, dead<total; else "bad"
"""

from __future__ import annotations

from cli_runtime import run_cli

import json
import sys


def parse_field(raw: str, field: str) -> str:
    """Extract *field* from JSON string *raw*."""
    try:
        data = json.loads(raw)
    except Exception:
        if field in {"dead-workers", "pending-lines"}:
            return "0"
        if field == "usable-check":
            return "bad"
        return ""

    if field == "status":
        return str(data.get("status", "") or "")
    if field == "phase":
        return str(data.get("phase", "") or "")
    if field == "dead-workers":
        try:
            return str(int(data.get("workers", {}).get("dead", 0) or 0))
        except (TypeError, ValueError):
            return "0"
    if field == "pending-lines":
        try:
            return str(int(data.get("pending_lines", 0) or 0))
        except (TypeError, ValueError):
            return "0"
    if field == "usable-check":
        try:
            status = data.get("status")
            total = int(data.get("workers", {}).get("total", 0) or 0)
            dead = int(data.get("workers", {}).get("dead", 0) or 0)
            if status == "ok" and total > 0 and dead < total:
                return "usable"
        except (TypeError, ValueError):
            pass
        return "bad"

    print(f"Unknown field: {field}", file=sys.stderr)
    raise SystemExit(2)


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2 or args[0] != "--field":
        print(
            "Usage: team_status.py --field <status|phase|dead-workers|pending-lines|usable-check>",
            file=sys.stderr,
        )
        raise SystemExit(2)

    field = args[1]
    raw = sys.stdin.read()
    print(parse_field(raw, field))


if __name__ == "__main__":
    run_cli(main)
