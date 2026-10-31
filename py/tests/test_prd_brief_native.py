# SPDX-License-Identifier: Apache-2.0
"""Synthetic explicit PRD character-budget and preserved-default controls."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from . import test_prd_brief as canonical

prd_brief = canonical.prd_brief
SCRIPT = canonical.SCRIPT


def _synthetic_long_prd(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic-brief.md"
    path.write_text(
        "**Version:** synthetic-1\n**Owner:** Synthetic Team\n"
        + "".join(
            f"## Vision {i}: " + "Synthetic context " * 24 + "\n" for i in range(40)
        )
    )
    return path


@pytest.mark.parametrize("budget", range(1, 32))
def test_positive_small_budget_is_a_real_character_limit(
    tmp_path: Path, budget: int
) -> None:
    result = prd_brief.build_brief(str(_synthetic_long_prd(tmp_path)), max_chars=budget)
    assert len(result) <= budget
    if budget >= len("\n... [truncated]"):
        assert result.endswith("\n... [truncated]")


@pytest.mark.parametrize("budget", [32, 33, 64, 200, 6000])
def test_truncated_normal_budgets_keep_the_existing_marker(
    tmp_path: Path, budget: int
) -> None:
    result = prd_brief.build_brief(str(_synthetic_long_prd(tmp_path)), max_chars=budget)
    assert len(result) <= budget
    assert result.endswith("\n... [truncated]")
    if budget >= 200:
        assert result.startswith("PRD file: ")


def test_default_budget_still_contains_useful_metadata_and_heading_context(
    tmp_path: Path,
) -> None:
    path = _synthetic_long_prd(tmp_path)
    result = prd_brief.build_brief(str(path))
    assert len(result) <= 6000
    assert result.startswith(f"PRD file: {path}\nPRD meta:\n")
    assert "**Version:** synthetic-1" in result
    assert "**Owner:** Synthetic Team" in result
    assert "Key headings:\n- Vision 0:" in result
    assert "Vision 10:" in result
    assert result.endswith("\n... [truncated]")


def test_large_budget_preserves_metadata_and_heading_selection(tmp_path: Path) -> None:
    path = _synthetic_long_prd(tmp_path)
    result = prd_brief.build_brief(str(path), max_chars=100000)
    assert "[truncated]" not in result
    assert "Vision 31:" in result
    assert "Vision 32:" not in result
    assert "**Owner:** Synthetic Team" in result


def test_exact_budget_does_not_truncate_its_complete_summary(tmp_path: Path) -> None:
    path = tmp_path / "short.md"
    path.write_text("**Status:** synthetic\n## Vision\n")
    full = prd_brief.build_brief(str(path), max_chars=100000)
    assert prd_brief.build_brief(str(path), max_chars=len(full)) == full


def test_default_cli_retains_the_same_summary_and_newline(tmp_path: Path) -> None:
    path = _synthetic_long_prd(tmp_path)
    result = subprocess.run(
        [sys.executable, SCRIPT, str(path)], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout == prd_brief.build_brief(str(path)) + "\n"


@pytest.mark.parametrize("kind", ["missing", "directory"])
def test_read_failure_is_not_success(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "absent.md" if kind == "missing" else tmp_path
    result = subprocess.run(
        [sys.executable, SCRIPT, str(path)], check=False, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr
