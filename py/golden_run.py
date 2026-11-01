#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Golden-run regression verifier for recorded Mainspring wave fixtures.

The fixture format is intentionally small:

    tests/golden-runs/<scenario>/waves.jsonl
    tests/golden-runs/<scenario>/expected.txt

``check`` renders deterministic wave-by-wave output from the ledger and diffs
it against ``expected.txt``. This gives CI a stable end-to-end regression guard
without launching model CLIs or mutating Taskmaster state.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

import replay
from cli_runtime import run_cli

LEDGER_NAME = "waves.jsonl"
EXPECTED_NAME = "expected.txt"


def _value(entry: dict, key: str) -> str:
    value = entry.get(key)
    if value is None or value == "":
        return "missing"
    return str(value)


def _changed_files(entry: dict) -> list[str]:
    files = entry.get("changed_files") or []
    return [str(file) for file in files]


def _determinism_status(original: dict | None, replayed: dict) -> str:
    if original is None:
        return "MISSING_ORIGINAL"

    mismatched = [
        key
        for key, _label in replay.REPLAY_ACCEPTANCE_FIELDS
        if _value(original, key) != _value(replayed, key)
    ]
    original_verdict = str(original.get("verdict") or "unknown").upper()
    replayed_verdict = str(replayed.get("verdict") or "unknown").upper()
    if not mismatched and original_verdict == replayed_verdict:
        return "PASS"
    return "REVIEW"


def _render_wave(index: int, entry: dict, by_id: dict[str, dict]) -> list[str]:
    files = _changed_files(entry)
    wave_id = str(entry.get("wave_id") or "unknown")
    verdict = str(entry.get("verdict") or "unknown").upper()
    lines = [
        (
            f"{index}. {wave_id} {verdict} "
            f"pair={replay.get_pair(entry)} "
            f"mode={entry.get('mode', 'unknown')}/{entry.get('topology', 'unknown')} "
            f"lane={entry.get('selected_lane') or 'unknown'}"
        ),
        (
            "   score: "
            f"chapter={_value(entry, 'chapter_delta')} "
            f"competitor={_value(entry, 'competitor_delta')} "
            f"launch={_value(entry, 'launch_delta')} "
            f"product={_value(entry, 'product_score')}"
        ),
        (
            f"   task={entry.get('task_id') or 'none'} "
            f"duration={entry.get('duration_seconds', 0)}s "
            f"files={len(files)}"
        ),
    ]

    replayed_from = str(entry.get("replayed_from") or "")
    if replayed_from:
        original = by_id.get(replayed_from)
        lines.append(
            f"   replayed_from={replayed_from} "
            f"determinism={_determinism_status(original, entry)}"
        )

    failure_reason = str(entry.get("failure_reason") or "")
    if failure_reason:
        lines.append(f"   failure={failure_reason}")

    next_action = str(entry.get("next_action") or "")
    if next_action:
        lines.append(f"   next_action={next_action}")

    for file in files:
        lines.append(f"   - {file}")
    return lines


def render_scenario(scenario_dir: Path) -> str:
    """Render deterministic summary output for one golden-run scenario."""
    scenario_dir = Path(scenario_dir)
    ledger = scenario_dir / LEDGER_NAME
    entries = replay.read_ledger(ledger)
    by_id = {str(entry.get("wave_id")): entry for entry in entries}

    lines = [
        f"Golden run: {scenario_dir.name}",
        f"Waves: {len(entries)}",
        "",
    ]

    for index, entry in enumerate(entries, 1):
        lines.extend(_render_wave(index, entry, by_id))
        lines.append("")

    replay_pairs = [
        (by_id.get(str(entry.get("replayed_from") or "")), entry)
        for entry in entries
        if entry.get("replayed_from")
    ]
    if replay_pairs:
        lines.append("Replay acceptance:")
        for original, replayed in replay_pairs:
            wave_id = str(replayed.get("wave_id") or "unknown")
            original_id = str(replayed.get("replayed_from") or "unknown")
            status = _determinism_status(original, replayed)
            lines.append(f"- {wave_id} from {original_id}: {status}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def check_scenario(scenario_dir: Path) -> str:
    """Return an empty string when the rendered scenario matches expected.txt."""
    scenario_dir = Path(scenario_dir)
    expected_path = scenario_dir / EXPECTED_NAME
    actual = render_scenario(scenario_dir)
    expected = expected_path.read_text(encoding="utf-8")
    if actual == expected:
        return ""
    return "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile=str(expected_path),
            tofile=f"{scenario_dir}/{EXPECTED_NAME} (rendered)",
            lineterm="",
        )
    )


def scenario_dirs(root: Path) -> list[Path]:
    """Return all golden-run scenario directories under *root*."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / LEDGER_NAME).is_file()
    )


USAGE = """\
Usage:
  golden_run.py render <scenario-dir>
  golden_run.py check <scenario-dir>
  golden_run.py check-all <golden-runs-dir>
"""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] in {"-h", "--help"}:
        print(USAGE, file=sys.stderr)
        return 2 if not args else 0

    subcmd = args[0]
    if subcmd == "render":
        if len(args) != 2:
            print("Usage: golden_run.py render <scenario-dir>", file=sys.stderr)
            return 2
        print(render_scenario(Path(args[1])), end="")
        return 0

    if subcmd == "check":
        if len(args) != 2:
            print("Usage: golden_run.py check <scenario-dir>", file=sys.stderr)
            return 2
        diff = check_scenario(Path(args[1]))
        if diff:
            print(diff, file=sys.stderr)
            return 1
        print(f"golden-run OK: {args[1]}")
        return 0

    if subcmd == "check-all":
        if len(args) != 2:
            print("Usage: golden_run.py check-all <golden-runs-dir>", file=sys.stderr)
            return 2
        scenarios = scenario_dirs(Path(args[1]))
        if not scenarios:
            print(f"No golden-run scenarios found in {args[1]}", file=sys.stderr)
            return 1
        failed = False
        for scenario in scenarios:
            diff = check_scenario(scenario)
            if diff:
                print(diff, file=sys.stderr)
                failed = True
            else:
                print(f"golden-run OK: {scenario}")
        return 1 if failed else 0

    print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    run_cli(main)
