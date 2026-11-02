# SPDX-License-Identifier: Apache-2.0
"""Tests for the GitHub Actions CI workflow contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_runs_make_all_on_linux_and_macos() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "ubuntu-latest" in text
    assert "macos-latest" in text
    assert "make all" in text
    assert "shellcheck" in text
    assert "bats" in text
    assert 'python -m pip install -e ".[dev]"' in text
    for dependency in ("pytest", "ruff", "pip-audit"):
        assert dependency in pyproject


def test_ci_workflow_is_non_deploying() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "contents: read" in text
    assert "pages:" not in text
    assert "id-token:" not in text
    assert "deploy" not in text.lower()


def test_ci_workflow_uses_node24_ready_actions() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "actions/checkout@v6" in text
    assert "actions/setup-python@v6" in text
    assert "actions/checkout@v4" not in text
    assert "actions/setup-python@v5" not in text
