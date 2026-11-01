#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate a Method-shaped PRD.

The validator is intentionally small and dependency-free. It checks the
contract used by ``mainspring validate-prd``:

- all canonical Method sections are present
- no ``{{placeholder}}`` text remains
- the verified truth snapshot table has non-empty Source cells
- every ADR has the required decision-record fields
- the backlog includes an explicit Won't lane

Usage:
    mainspring validate-prd <prd-path> [--format text|json]
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from cli_runtime import run_cli

SECTION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Mission", ("Mission",)),
    ("Durability principles", ("Durability principles",)),
    ("Current truth snapshot", ("Current truth snapshot (verified)",)),
    ("Naming and brand boundary", ("Naming and brand boundary",)),
    ("Target architecture", ("Target architecture",)),
    ("Phase map", ("Phase map",)),
    ("Architecture decisions", ("Architecture decisions (ADRs)",)),
    ("Operational doctrine", ("Operational doctrine",)),
    ("Health rituals", ("Health rituals",)),
    ("Disaster recovery", ("Disaster recovery",)),
    ("Versioning and migration", ("Versioning and migration",)),
    (
        "Definition of Done / release checklist",
        ("Definition of Done (release checklist)", "v1.0 GitHub release checklist"),
    ),
    ("Explicit non-goals", ("Explicit non-goals",)),
    ("Backlog", ("Backlog (Must / Should / Could / Won't)",)),
    (
        "Appendix A",
        (
            "Appendix A — Source-of-knowledge recipes",
            "Appendix A - Source-of-knowledge recipes",
        ),
    ),
    (
        "Appendix B",
        ("Appendix B — Verification commands", "Appendix B - Verification commands"),
    ),
    (
        "Acknowledgments / lineage",
        ("Acknowledgments / Lineage", "Appendix C — Competitor landscape"),
    ),
)

ADR_FIELDS: tuple[str, ...] = (
    "Context",
    "Options considered",
    "Decision",
    "Rationale",
    "Consequences",
    "Reversal cost",
)

TOP_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
ADR_HEADING_RE = re.compile(r"^###\s+(ADR-\d+:.+?)\s*$", re.MULTILINE)
ADR_FIELD_RE = re.compile(
    r"^\*\*(" + "|".join(re.escape(field) for field in ADR_FIELDS) + r"):\*\*",
    re.MULTILINE,
)
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    line: int | None = None


def _normalize_heading(value: str) -> str:
    normalized = value.lower()
    normalized = normalized.replace("’", "'").replace("`", "")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _heading_matches(title: str, aliases: tuple[str, ...]) -> bool:
    normalized = _normalize_heading(title)
    for alias in aliases:
        normalized_alias = _normalize_heading(alias)
        if normalized == normalized_alias or normalized.startswith(
            f"{normalized_alias} "
        ):
            return True
    return False


def _without_fenced_code(text: str) -> str:
    """Hide fenced examples while preserving offsets and line endings."""
    result: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if fence is None:
            opening = FENCE_RE.match(content)
            if not opening or (
                opening.group(1).startswith("`") and "`" in opening.group(2)
            ):
                result.append(line)
                continue
            fence = opening.group(1)
        elif re.fullmatch(
            r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*",
            content,
        ):
            fence = None
        result.append("".join(char if char in "\r\n" else " " for char in line))
    return "".join(result)


def _top_headings(text: str) -> list[tuple[str, int, int, int]]:
    headings: list[tuple[str, int, int, int]] = []
    for match in TOP_HEADING_RE.finditer(_without_fenced_code(text)):
        title = match.group(1).strip()
        line = text.count("\n", 0, match.start()) + 1
        headings.append((title, match.start(), match.end(), line))
    return headings


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _section_text(text: str, aliases: tuple[str, ...]) -> str:
    headings = _top_headings(text)
    for index, (title, _start, end, _line) in enumerate(headings):
        if _heading_matches(title, aliases):
            next_start = (
                headings[index + 1][1] if index + 1 < len(headings) else len(text)
            )
            return text[end:next_start]
    return ""


def _validate_sections(text: str) -> list[ValidationIssue]:
    headings = [title for title, *_ in _top_headings(text)]
    issues: list[ValidationIssue] = []
    for label, aliases in SECTION_GROUPS:
        if not any(_heading_matches(heading, aliases) for heading in headings):
            issues.append(
                ValidationIssue(
                    code="section:missing",
                    message=f"Missing canonical PRD section: {label}",
                )
            )
    return issues


def _validate_placeholders(text: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    # Literal placeholder syntax may be referenced inside inline code when
    # documenting templates. Only unquoted placeholders count as unresolved.
    text_without_inline_code = re.sub(r"`[^`\n]*`", "", text)
    for match in re.finditer(r"\{\{[^}]*\}\}|\{\{|\}\}", text_without_inline_code):
        snippet = match.group(0)
        issues.append(
            ValidationIssue(
                code="placeholder:unresolved",
                message=f"Unresolved placeholder remains: {snippet[:40]}",
                line=_line_for_offset(text, match.start()),
            )
        )
    return issues


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _validate_truth_snapshot(text: str) -> list[ValidationIssue]:
    section = _section_text(text, ("Current truth snapshot (verified)",))
    if not section:
        return [
            ValidationIssue(
                code="truth:missing",
                message="Current truth snapshot section is missing",
            )
        ]

    lines = _without_fenced_code(section).splitlines()
    header_index = None
    source_index = None
    for index, line in enumerate(lines):
        if "|" not in line or "Source" not in line:
            continue
        cells = _split_table_row(line)
        for cell_index, cell in enumerate(cells):
            if cell.lower() == "source":
                header_index = index
                source_index = cell_index
                break
        if source_index is not None:
            break

    if header_index is None or source_index is None:
        return [
            ValidationIssue(
                code="truth:source_table_missing",
                message="Current truth snapshot must include a markdown table with a Source column",
            )
        ]

    issues: list[ValidationIssue] = []
    data_rows = 0
    for row in lines[header_index + 2 :]:
        if "|" not in row:
            if data_rows:
                break
            continue
        cells = _split_table_row(row)
        if not cells or set("".join(cells)) <= {"-", ":"}:
            continue
        data_rows += 1
        source = cells[source_index].strip() if len(cells) > source_index else ""
        if not source or source in {"-", "N/A"}:
            issues.append(
                ValidationIssue(
                    code="truth:source_missing",
                    message=f"Truth snapshot row has empty Source cell: {row.strip()}",
                )
            )

    if data_rows == 0:
        issues.append(
            ValidationIssue(
                code="truth:no_rows",
                message="Current truth snapshot Source table has no data rows",
            )
        )
    return issues


def _validate_adrs(text: str) -> list[ValidationIssue]:
    section = _section_text(text, ("Architecture decisions (ADRs)",))
    if not section:
        return [
            ValidationIssue(
                code="adr:missing",
                message="Architecture decisions section is missing",
            )
        ]

    structural_section = _without_fenced_code(section)
    matches = list(ADR_HEADING_RE.finditer(structural_section))
    if not matches:
        return [
            ValidationIssue(
                code="adr:none",
                message="Architecture decisions section must include at least one ADR heading",
            )
        ]

    issues: list[ValidationIssue] = []
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        body = section[start:end]
        labels = list(ADR_FIELD_RE.finditer(structural_section[start:end]))
        populated: set[str] = set()
        for field_index, label in enumerate(labels):
            value_end = (
                labels[field_index + 1].start()
                if field_index + 1 < len(labels)
                else len(body)
            )
            value = body[label.end() : value_end]
            if any(
                line.strip()
                and not re.fullmatch(r"(?:-{3,}|\*{3,}|_{3,})", line.strip())
                for line in value.splitlines()
            ):
                populated.add(label.group(1))
        missing = [field for field in ADR_FIELDS if field not in populated]
        if missing:
            issues.append(
                ValidationIssue(
                    code="adr:missing_fields",
                    message=f"{title} missing ADR field(s): {', '.join(missing)}",
                )
            )
    return issues


def _validate_backlog(text: str) -> list[ValidationIssue]:
    backlog = _section_text(text, ("Backlog (Must / Should / Could / Won't)",))
    if not backlog:
        return [
            ValidationIssue(
                code="backlog:missing",
                message="Backlog section is missing",
            )
        ]
    if not re.search(
        r"^###\s+Won['’]?t\b", _without_fenced_code(backlog), re.MULTILINE
    ):
        return [
            ValidationIssue(
                code="backlog:wont_missing",
                message="Backlog must include an explicit Won't lane",
            )
        ]
    return []


def validate_text(text: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues.extend(_validate_sections(text))
    issues.extend(_validate_placeholders(text))
    issues.extend(_validate_truth_snapshot(text))
    issues.extend(_validate_adrs(text))
    issues.extend(_validate_backlog(text))
    return issues


def validate_prd(path: Path) -> list[ValidationIssue]:
    if not path.exists():
        return [
            ValidationIssue(
                code="file:missing",
                message=f"PRD file not found: {path}",
            )
        ]
    return validate_text(path.read_text(errors="ignore"))


def _format_text(path: Path, issues: list[ValidationIssue]) -> str:
    if not issues:
        return f"PRD validation passed: {path}"
    lines = [f"PRD validation failed: {path}", f"{len(issues)} issue(s):"]
    for issue in issues:
        location = f":{issue.line}" if issue.line else ""
        lines.append(f"- [{issue.code}]{location} {issue.message}")
    return "\n".join(lines)


HELP_TEXT = """Usage: mainspring validate-prd <prd-path> [--format text|json]

Validate a Mainspring Method Product Requirements Document (PRD) before
decomposition or autonomous execution.

Checks:
  canonical sections, unresolved placeholders, truth-snapshot Source cells,
  ADR fields, and the explicit Won't backlog lane.

Examples:
  mainspring validate-prd docs/prd.md
  mainspring validate-prd docs/prd.md --format json
"""


def _cli_main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(HELP_TEXT, file=sys.stderr)
        return 2
    if args[0] in {"--help", "-h"}:
        print(HELP_TEXT)
        return 0

    path = Path(args[0])
    output_format = "text"
    index = 1
    while index < len(args):
        if args[index] == "--format" and index + 1 < len(args):
            output_format = args[index + 1]
            index += 2
        else:
            print(f"Unknown flag: {args[index]}", file=sys.stderr)
            return 2

    issues = validate_prd(path)
    if output_format == "json":
        print(json.dumps([asdict(issue) for issue in issues], indent=2))
    elif output_format == "text":
        print(_format_text(path, issues))
    else:
        print(f"Unknown format: {output_format}", file=sys.stderr)
        return 2
    return 1 if issues else 0


if __name__ == "__main__":
    run_cli(_cli_main)
