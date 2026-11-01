# SPDX-License-Identifier: Apache-2.0
"""Tests for prd_brief.py — PRD brief generator."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import prd_brief  # noqa: E402

SCRIPT = str(HERE.parent / "prd_brief.py")


def test_build_brief_extracts_meta(tmp_path: Path) -> None:
    prd = tmp_path / "prd.md"
    prd.write_text(
        "# My PRD\n\n**Version:** 1.0\n**Owner:** Team A\n\n## Vision\n\nBuild something.\n"
    )
    result = prd_brief.build_brief(str(prd))
    assert "PRD file:" in result
    assert "Version:** 1.0" in result
    assert "Vision" in result


def test_build_brief_extracts_headings(tmp_path: Path) -> None:
    prd = tmp_path / "prd.md"
    prd.write_text("# Top\n## Portfolio\n## Alerts\n### Market Intelligence\n")
    result = prd_brief.build_brief(str(prd))
    assert "Portfolio" in result
    assert "Alerts" in result
    assert "Market Intelligence" in result


def test_build_brief_truncates(tmp_path: Path) -> None:
    prd = tmp_path / "prd.md"
    prd.write_text("".join(f"## Heading {i}\n" for i in range(500)))
    result = prd_brief.build_brief(str(prd), max_chars=200)
    assert len(result) <= 200
    assert "[truncated]" in result


def test_build_brief_fallback_headings(tmp_path: Path) -> None:
    """When no important keywords match, fallback to first 24 headings."""
    prd = tmp_path / "prd.md"
    prd.write_text("## Unique heading alpha\n## Unique heading beta\n")
    result = prd_brief.build_brief(str(prd))
    assert "Unique heading alpha" in result


def test_cli_no_args() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2


def test_cli_valid_file(tmp_path: Path) -> None:
    prd = tmp_path / "prd.md"
    prd.write_text("# Test PRD\n## Vision\nBuild it.\n")
    result = subprocess.run(
        [sys.executable, SCRIPT, str(prd)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Vision" in result.stdout
