# SPDX-License-Identifier: Apache-2.0
"""parse_review.py — structured review parser for Mainspring.

Parses reviewer output in two modes:
  1. JSON-strict: extracts a fenced ```json block and validates required fields.
  2. Markdown fallback: scrapes FIELD: VALUE lines (legacy v1 format).

CLI:
  python3 parse_review.py parse   <file>          → JSON dict of all fields
  python3 parse_review.py validate <file>         → exit 0 if valid, exit 1 + reasons on stderr
  python3 parse_review.py field   <file> <name>   → single field value to stdout
"""

from __future__ import annotations

from cli_runtime import run_cli

import json
import re
import sys
from pathlib import Path
from typing import Any

# The 11 fields from the PRD REQUIRED_FIELDS contract, plus 5 operational
# fields the current review gate uses for repair instructions.
REQUIRED_FIELDS: tuple[str, ...] = (
    "verdict",
    "chapters",
    "chapter_delta",
    "competitor_delta",
    "launch_delta",
    "product_score",
    "strengths",
    "gaps",
    "next_actions",
    "verification_evidence",
    "rationale",
)

OPERATIONAL_FIELDS: tuple[str, ...] = (
    "fail_reason_category",
    "files_to_touch",
    "required_changes",
    "tests_to_run",
    "pass_bar",
)

ALL_FIELDS: tuple[str, ...] = REQUIRED_FIELDS + OPERATIONAL_FIELDS
PRODUCT_SCORE_MIN = 0
PRODUCT_SCORE_MAX = 1000
DELTA_FIELDS: tuple[str, ...] = (
    "chapter_delta",
    "competitor_delta",
    "launch_delta",
)

# Map from legacy FIELD: VALUE header names to canonical snake_case keys.
_LEGACY_KEY_MAP: dict[str, str] = {
    "REVIEW_VERDICT": "verdict",
    "CHAPTERS": "chapters",
    "CHAPTER_SCORE_DELTA": "chapter_delta",
    "COMPETITOR_DELTA": "competitor_delta",
    "LAUNCH_DELTA": "launch_delta",
    "PRODUCT_SCORE": "product_score",
    "STRENGTHS": "strengths",
    "GAPS": "gaps",
    "NEXT_ACTIONS": "next_actions",
    "VERIFICATION_EVIDENCE": "verification_evidence",
    "RATIONALE": "rationale",
    "FAIL_REASON_CATEGORY": "fail_reason_category",
    "FILES_TO_TOUCH": "files_to_touch",
    "REQUIRED_CHANGES": "required_changes",
    "TESTS_TO_RUN": "tests_to_run",
    "PASS_BAR": "pass_bar",
}

# Reverse map: snake_case → LEGACY_KEY (for extract_review_field compat)
_SNAKE_TO_LEGACY: dict[str, str] = {v: k for k, v in _LEGACY_KEY_MAP.items()}

# Regex to find fenced ```json ... ``` blocks
_JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL)


def _extract_json_block(text: str) -> dict[str, Any] | None:
    """Try to extract and parse a fenced ```json block from reviewer output."""
    m = _JSON_FENCE_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _normalize_json_keys(obj: dict[str, Any]) -> dict[str, str]:
    """Normalize keys and scalar values; malformed required text stays empty."""
    result: dict[str, str] = {}
    for k, v in obj.items():
        # Accept both snake_case and LEGACY_KEY formats in JSON
        canonical = _LEGACY_KEY_MAP.get(k, k)
        if (
            canonical in ALL_FIELDS
            and canonical not in DELTA_FIELDS
            and canonical != "product_score"
            and isinstance(v, (list, dict, bool))
        ):
            v = None
        result[canonical] = str(v) if v is not None else ""
    return result


def _parse_markdown_fallback(text: str) -> dict[str, str]:
    """Parse legacy FIELD: VALUE format line by line."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        for legacy_key, canonical in _LEGACY_KEY_MAP.items():
            prefix = f"{legacy_key}:"
            if line.startswith(prefix):
                value = line[len(prefix) :].strip()
                result[canonical] = value
                break
    return result


def parse_review(file_path: str | Path) -> dict[str, Any]:
    """Parse a review file, returning a dict with canonical snake_case keys.

    Tries JSON-strict first, falls back to Markdown FIELD: VALUE parsing.
    Returns a dict with all found fields plus ``_parse_mode`` indicating
    which parser succeeded (``"json"`` or ``"markdown"``).
    """
    text = Path(file_path).read_text(encoding="utf-8", errors="replace")

    # Try JSON-strict first
    json_obj = _extract_json_block(text)
    if json_obj is not None:
        fields = _normalize_json_keys(json_obj)
        fields["_parse_mode"] = "json"
        return fields

    # Markdown fallback
    fields = _parse_markdown_fallback(text)
    fields["_parse_mode"] = "markdown"
    return fields


def validate_review(file_path: str | Path) -> list[str]:
    """Validate a review file. Returns list of error reasons (empty = valid)."""
    fields = parse_review(file_path)
    reasons: list[str] = []

    verdict = fields.get("verdict", "").strip()
    if verdict != "PASS":
        reasons.append("review verdict is not PASS")

    for field_name in ALL_FIELDS:
        value = fields.get(field_name, "").strip()
        if not value:
            # Use the specific error format from the PRD:
            # review:missing_fields:<key>
            reasons.append(
                f"missing {_SNAKE_TO_LEGACY.get(field_name, field_name.upper())}"
            )

    for field_name in DELTA_FIELDS:
        value = fields.get(field_name, "").strip()
        if value and not _is_signed_integer(value):
            legacy_name = _SNAKE_TO_LEGACY.get(field_name, field_name.upper())
            reasons.append(f"invalid_type:{legacy_name}")

    product_score = fields.get("product_score", "").strip()
    if product_score:
        try:
            parsed_product_score = int(product_score)
        except ValueError:
            reasons.append("invalid_type:PRODUCT_SCORE")
        else:
            if not PRODUCT_SCORE_MIN <= parsed_product_score <= PRODUCT_SCORE_MAX:
                reasons.append("invalid_range:PRODUCT_SCORE")

    return reasons


def _is_signed_integer(value: str) -> bool:
    return bool(re.fullmatch(r"[+-]?\d+", value))


def get_field(file_path: str | Path, field_name: str) -> str:
    """Get a single field value from a review file.

    Accepts both legacy FIELD_NAME (e.g. NEXT_ACTIONS) and
    canonical snake_case (e.g. next_actions).
    """
    fields = parse_review(file_path)
    # Normalize the requested field name
    canonical = _LEGACY_KEY_MAP.get(field_name, field_name)
    return fields.get(canonical, "")


def fields_as_shell_vars(file_path: str | Path) -> str:
    """Output fields as single-quoted KEY=VALUE assignment lines."""
    fields = parse_review(file_path)
    lines: list[str] = []
    for canonical in ALL_FIELDS:
        legacy = _SNAKE_TO_LEGACY.get(canonical, canonical.upper())
        value = fields.get(canonical, "")
        # Shell-safe: single-quote the value, escaping embedded single quotes
        safe_value = value.replace("'", "'\\''")
        lines.append(f"{legacy}='{safe_value}'")
    # Also emit parse mode
    lines.append(f"_PARSE_MODE='{fields.get('_parse_mode', 'unknown')}'")
    return "\n".join(lines)


def _cli_main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print(
            "Usage: parse_review.py <parse|validate|field|shell-vars> <file> [field_name]",
            file=sys.stderr,
        )
        return 2

    cmd = args[0]
    file_path = args[1]

    if not Path(file_path).is_file():
        print(f"File not found: {file_path}", file=sys.stderr)
        return 2

    if cmd == "parse":
        result = parse_review(file_path)
        print(json.dumps(result, indent=2))
        return 0

    elif cmd == "validate":
        reasons = validate_review(file_path)
        if reasons:
            for r in reasons:
                print(r, file=sys.stderr)
            return 1
        return 0

    elif cmd == "field":
        if len(args) < 3:
            print("Usage: parse_review.py field <file> <field_name>", file=sys.stderr)
            return 2
        value = get_field(file_path, args[2])
        if value:
            print(value)
        return 0

    elif cmd == "shell-vars":
        print(fields_as_shell_vars(file_path))
        return 0

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    run_cli(_cli_main)
