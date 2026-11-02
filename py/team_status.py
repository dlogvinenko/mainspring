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
    total-workers Extract .workers.total (0 on error)
    pending-lines Extract .pending_lines (0 on error)
    usable-check  Print "usable" if status=ok, total>0, dead<total; else "bad"
"""

from __future__ import annotations

import json
import sys

from cli_runtime import run_cli


def _nonnegative_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        count = int(value)
    except ValueError:
        return None
    return count if count >= 0 else None


def parse_field(raw: str, field: str) -> str:
    """Extract *field* from JSON string *raw*."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError, RecursionError):
        if field in {"dead-workers", "total-workers", "pending-lines"}:
            return "0"
        if field == "usable-check":
            return "bad"
        return ""

    if not isinstance(data, dict):
        data = {}
    workers = data.get("workers")
    if not isinstance(workers, dict):
        workers = {}

    if field in {"status", "phase"}:
        value = data.get(field)
        return value if isinstance(value, str) else ""
    if field in {"dead-workers", "total-workers"}:
        count = _nonnegative_count(
            workers.get("dead" if field == "dead-workers" else "total")
        )
        return str(count if count is not None else 0)
    if field == "pending-lines":
        try:
            return str(int(data.get("pending_lines", 0) or 0))
        except (TypeError, ValueError):
            return "0"
    if field == "usable-check":
        total = _nonnegative_count(workers.get("total"))
        dead = _nonnegative_count(workers.get("dead"))
        if (
            data.get("status") == "ok"
            and total is not None
            and total > 0
            and dead is not None
            and dead < total
        ):
            return "usable"
        return "bad"

    print(f"Unknown field: {field}", file=sys.stderr)
    raise SystemExit(2)


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2 or args[0] != "--field":
        print(
            "Usage: team_status.py --field <status|phase|dead-workers|total-workers|pending-lines|usable-check>",
            file=sys.stderr,
        )
        raise SystemExit(2)

    field = args[1]
    raw = sys.stdin.read()
    print(parse_field(raw, field))


if __name__ == "__main__":
    run_cli(main)
