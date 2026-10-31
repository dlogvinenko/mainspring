#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""PRD brief generator for Mainspring.

Reads a PRD markdown file, extracts metadata and key headings, and prints
a compact summary suitable for context injection into engine prompts.

Usage:
    python3 prd_brief.py <prd-path>
"""

from __future__ import annotations

from cli_runtime import run_cli

import re
import sys
from pathlib import Path

IMPORTANT_KEYWORDS = (
    "Vision",
    "Product Principles",
    "Web Product",
    "User Experience",
    "Developer Experience",
    "Telegram",
    "Discord",
    "Cross-Surface Sync",
    "Trading Intelligence",
    "Portfolio",
    "Alerts",
    "Market Intelligence",
    "Capital and Risk",
    "Monetization",
    "Technical Stack",
    "Quality Bar",
    "Release Gates",
    "Roadmap",
    "Launch Operations",
    "Tactical Queue",
)


def build_brief(prd_path: str, max_chars: int = 6000) -> str:
    """Build a compact PRD summary from *prd_path*."""
    path = Path(prd_path)
    text = path.read_text(errors="ignore")
    lines = text.splitlines()

    meta: list[str] = []
    for prefix in ("**Version:**", "**Last updated:**", "**Owner:**", "**Status:**"):
        for line in lines[:80]:
            if line.strip().startswith(prefix):
                meta.append(line.strip())
                break

    headings: list[str] = []
    for line in lines:
        if re.match(r"^#{1,3}\s+", line):
            h = re.sub(r"^#{1,3}\s+", "", line).strip()
            if h and h not in headings:
                headings.append(h)
        elif re.match(r"^\d+(\.\d+)?\.\s+", line):
            h = re.sub(r"^\d+(\.\d+)?\.\s+", "", line).strip()
            if h and h not in headings:
                headings.append(h)

    important: list[str] = []
    for heading in headings:
        if any(kw.lower() in heading.lower() for kw in IMPORTANT_KEYWORDS):
            important.append(heading)

    if not important:
        important = headings[:24]
    important = important[:32]

    summary_parts: list[str] = []
    summary_parts.append(f"PRD file: {path}")
    if meta:
        summary_parts.append("PRD meta:")
        summary_parts.extend(f"- {line}" for line in meta)
    summary_parts.append("Key headings:")
    summary_parts.extend(f"- {heading}" for heading in important)

    summary = "\n".join(summary_parts)
    if len(summary) > max_chars:
        if 0 <= max_chars < 32:
            summary = "\n... [truncated]"[:max_chars]
        else:
            summary = summary[: max_chars - 32].rstrip() + "\n... [truncated]"
    return summary


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: prd_brief.py <prd-path>", file=sys.stderr)
        raise SystemExit(2)
    print(build_brief(args[0]))


if __name__ == "__main__":
    run_cli(main)
