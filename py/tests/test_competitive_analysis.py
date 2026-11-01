# SPDX-License-Identifier: Apache-2.0
"""Tests for the public competitive-analysis document."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "competitive-analysis.md"
PRD = REPO_ROOT / "docs" / "prd.md"


def _doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_competitive_analysis_has_required_market_sections() -> None:
    text = _doc_text()
    assert "**Snapshot date:** 2026-06-14" in text

    for heading in (
        "# Mainspring Competitive Positioning",
        "## Executive Summary",
        "## Market Map",
        "## Fresh Landscape",
        "## 1000-Point Release Readiness Method",
        "## Mainspring v1 Score",
        "## Fit Matrix",
        "## Public Claims Mainspring Can Make",
        "## Claims To Avoid",
        "## Search And Discovery Plan",
        "## Next Public Evidence",
        "## Bottom Line",
    ):
        assert heading in text


def test_competitive_analysis_scores_sum_to_1000() -> None:
    text = _doc_text()
    scoring = text.split("## 1000-Point Release Readiness Method", 1)[1].split(
        "## Mainspring v1 Score", 1
    )[0]
    points = []
    for line in scoring.splitlines():
        match = re.match(r"\| [^|]+ \| (\d+) \|", line)
        if match:
            points.append(int(match.group(1)))

    assert points
    assert sum(points) == 1000
    assert "| **Total** | **1000** |" in scoring


def test_competitive_analysis_names_core_competitors_and_release_score() -> None:
    text = _doc_text()
    for name in (
        "OpenCode",
        "OpenHands",
        "Cline",
        "Goose",
        "Aider",
        "Continue",
        "Claude Task Master",
        "OpenAI Symphony",
        "Roo Code",
        "SWE-agent",
        "Claude Squad",
        "Agent Orchestrator",
        "GitHub Copilot cloud agent",
        "Agent HQ",
        "Devin",
        "Claude Code Agent Teams",
    ):
        assert name in text

    assert "| **Total** | **900 / 1000** |" in text
    assert "Public source release is live on a clean `main`" in text
    assert "Mainspring source release | 705" not in text


def test_competitive_analysis_uses_official_source_links() -> None:
    text = _doc_text()
    for link in (
        "https://opencode.ai/",
        "https://github.com/anomalyco/opencode",
        "https://docs.openhands.dev/sdk",
        "https://docs.cline.bot/cline-overview",
        "https://goose-docs.ai/",
        "https://aider.chat/docs/",
        "https://docs.continue.dev/",
        "https://tryhamster.com/product/taskmaster",
        "https://openai.com/index/open-source-codex-orchestration-symphony/",
        "https://github.com/AgentWrapper/agent-orchestrator",
        "https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent",
        "https://docs.github.com/copilot/concepts/agents/about-third-party-agents",
        "https://github.com/features/copilot/agents",
        "https://devin.ai/",
        "https://code.claude.com/docs/en/agent-teams",
    ):
        assert link in text


def test_competitive_analysis_omits_volatile_star_counts() -> None:
    text = _doc_text()

    assert (
        "| Tool | Official surface | Main positioning | How Mainspring differs |"
        in text
    )
    assert "Stars" not in text
    assert "Star counts" not in text
    assert "metadata collected with `gh repo view`" not in text
    assert "Experimental, disabled-by-default coordination" in text


def test_competitive_analysis_locks_seo_positioning_language() -> None:
    text = _doc_text()

    assert (
        "Product Requirements Document (PRD)-first AI coding agent orchestration"
        in text
    )
    for phrase in (
        "AI coding agent orchestration",
        "autonomous coding workflow",
        "production-grade software delivery",
        "local open-source operator tool",
        "production-grade work",
    ):
        assert phrase in text

    assert "source-available" not in text
    assert "serious work" not in text
    assert "harness/runbook" not in text
    assert "post-" + "v1" not in text
    assert "source-release " + "blockers" not in text
    assert "public-source " + "blocker" not in text
    assert "public-visibility " + "blockers" not in text
    assert "External growth " + "proof" not in text
    assert "next " + "proof" not in text
    assert "proof-" + "ledger" not in text
    assert "proof " + "ledger" not in text
    assert "proof " + "layer" not in text
    assert "Public repository + signed `v1.0.0` tag + GitHub Release" not in text
    assert "| P0 | Add GitHub topics:" not in text
    assert "| P0 | Keep GitHub topics aligned:" in text
    assert "source-only benchmark tooling" in text
    assert "JSONL evidence ledger and replay" in text
    assert "outside a hosted control plane" in text
    assert "Hosted docs are live" in text
    assert "Signed tag and GitHub Release remain the publication steps" in text


def test_prd_points_to_refreshed_competitive_analysis() -> None:
    prd = PRD.read_text(encoding="utf-8")
    assert "Competitor landscape / competitive positioning (June 2026 refresh)" in prd
    assert "[`docs/competitive-analysis.md`](competitive-analysis.md)" in prd
    assert "**Snapshot date:** 2026-06-14" in prd
    assert "_Last edited: 2026-10-30." in prd
    assert "release-" + "status box" not in prd
    assert "no unsupported release-management CLI commands" in prd
    assert "publication-only helper commands" not in prd
    assert "maintainer-only helper commands" not in prd
    assert "Mainspring's v1 source release readiness at 900/1000" in prd
    assert "GitHub credential that has `workflow` scope" in prd
    assert "public visibility " + "blocker" not in prd
    assert "tag/release/Pages/Homebrew" not in prd
    assert "GitHub metadata was collected" not in prd
