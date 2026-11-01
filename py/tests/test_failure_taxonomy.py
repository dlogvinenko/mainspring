# SPDX-License-Identifier: Apache-2.0
"""Tests for failure_taxonomy.py — failure reason classification."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import failure_taxonomy


# ── extract_prefix ─────────────────────────────────────────────────────


# Scenario: Valid prefixed reason.
# Expected: returns the prefix.
def test_extract_prefix_routing() -> None:
    assert failure_taxonomy.extract_prefix("routing:no_actionable_task") == "routing"


def test_extract_prefix_engine() -> None:
    assert failure_taxonomy.extract_prefix("engine:exit_nonzero") == "engine"


def test_ci_failure_reasons_are_known_engine_reasons() -> None:
    assert failure_taxonomy.is_known_reason("engine:test_fail") is True
    assert failure_taxonomy.is_known_reason("engine:lint_fail") is True
    assert failure_taxonomy.is_known_reason("engine:typecheck_fail") is True
    assert failure_taxonomy.is_known_reason("engine:quota") is True
    assert failure_taxonomy.is_known_reason("engine:dependency_missing") is True


def test_replay_routing_failures_are_known_reasons() -> None:
    assert failure_taxonomy.is_known_reason("routing:missing_replay_prompt") is True
    assert failure_taxonomy.is_known_reason("routing:missing_replay_target") is True
    assert failure_taxonomy.is_known_reason("routing:replay_target_unavailable") is True


def test_extract_prefix_review() -> None:
    assert failure_taxonomy.extract_prefix("review:gate_failed") == "review"


def test_reviewer_unreachable_is_known_review_reason() -> None:
    assert failure_taxonomy.is_known_reason("review:reviewer_unreachable") is True


def test_extract_prefix_scope() -> None:
    assert failure_taxonomy.extract_prefix("scope:violation") == "scope"


def test_extract_prefix_team() -> None:
    assert failure_taxonomy.extract_prefix("team:run_failed") == "team"


# Scenario: Unprefixed reason.
# Expected: returns None.
def test_extract_prefix_no_prefix() -> None:
    assert failure_taxonomy.extract_prefix("some_random_reason") is None


# Scenario: Empty string.
# Expected: returns None.
def test_extract_prefix_empty() -> None:
    assert failure_taxonomy.extract_prefix("") is None


# Scenario: Unknown prefix class.
# Expected: returns None.
def test_extract_prefix_unknown_class() -> None:
    assert failure_taxonomy.extract_prefix("network:timeout") is None


# ── is_valid_prefix ────────────────────────────────────────────────────


# Scenario: Known prefixed reasons.
# Expected: all return True.
def test_is_valid_prefix_known() -> None:
    for reason in failure_taxonomy.ALL_KNOWN_REASONS:
        assert failure_taxonomy.is_valid_prefix(reason), f"Expected valid: {reason}"


# Scenario: Unknown but correctly prefixed.
# Expected: still returns True (forward compat).
def test_is_valid_prefix_unknown_leaf() -> None:
    assert failure_taxonomy.is_valid_prefix("engine:new_future_error") is True


# Scenario: No prefix.
# Expected: returns False.
def test_is_valid_prefix_unprefixed() -> None:
    assert failure_taxonomy.is_valid_prefix("worker_exit_nonzero") is False


# ── is_known_reason ────────────────────────────────────────────────────


# Scenario: All canonical reasons.
# Expected: all return True.
def test_is_known_reason_all_canonical() -> None:
    for reason in failure_taxonomy.ALL_KNOWN_REASONS:
        assert failure_taxonomy.is_known_reason(reason), f"Expected known: {reason}"


# Scenario: Valid prefix but unknown leaf.
# Expected: returns False.
def test_is_known_reason_unknown_leaf() -> None:
    assert failure_taxonomy.is_known_reason("engine:new_future_error") is False


# ── normalise_failure_reason_class ─────────────────────────────────────


# Scenario: New ledger rows provide only failure_reason.
# Expected: failure_reason_class is the same prefixed machine reason.
def test_normalise_failure_reason_class_from_reason() -> None:
    assert (
        failure_taxonomy.normalise_failure_reason_class("review:gate_failed")
        == "review:gate_failed"
    )


# Scenario: Legacy caller provides a bare class and a full reason.
# Expected: bare class is upgraded to the full prefixed reason.
def test_normalise_failure_reason_class_upgrades_legacy_bare_class() -> None:
    assert (
        failure_taxonomy.normalise_failure_reason_class(
            "review:gate_failed",
            "review",
        )
        == "review:gate_failed"
    )


# Scenario: Future caller provides an explicit prefixed class.
# Expected: explicit prefixed class is preserved.
def test_normalise_failure_reason_class_preserves_explicit_prefixed_class() -> None:
    assert (
        failure_taxonomy.normalise_failure_reason_class(
            "review:gate_failed",
            "review:custom",
        )
        == "review:custom"
    )


# Scenario: Explicit class conflicts with the failure reason prefix.
# Expected: the actual failure reason wins so the row is not misclassified.
def test_normalise_failure_reason_class_rejects_mismatched_explicit_class() -> None:
    assert (
        failure_taxonomy.normalise_failure_reason_class(
            "engine:quota",
            "review:custom",
        )
        == "engine:quota"
    )


# Scenario: Unprefixed reason reaches the taxonomy helper.
# Expected: no canonical class is fabricated.
def test_normalise_failure_reason_class_rejects_unprefixed_reason() -> None:
    assert failure_taxonomy.normalise_failure_reason_class("worker_exit_nonzero") == ""


# ── routing_failure_action ─────────────────────────────────────────────


# Scenario: Team mode cannot see a nested repo but solo can.
# Expected: the scheduler falls back to solo instead of blocking Taskmaster.
def test_routing_failure_action_plugin_invisible_uses_solo_fallback() -> None:
    assert (
        failure_taxonomy.routing_failure_action("routing:plugin_invisible")
        == "solo_fallback"
    )


# Scenario: A task-scoped routing failure cannot be recovered by changing topology.
# Expected: Taskmaster is blocked with the same machine-readable reason.
def test_routing_failure_action_scope_blocked_blocks_taskmaster() -> None:
    assert (
        failure_taxonomy.routing_failure_action("routing:scope_blocked")
        == "block_taskmaster"
    )


# Scenario: Team topology simply has no independent work to fan out.
# Expected: no Taskmaster item is blocked.
def test_routing_failure_action_ignores_nonrouting_failure() -> None:
    assert failure_taxonomy.routing_failure_action("team:no_parallel_safe_work") == ""


# Scenario: The backlog has no actionable item.
# Expected: the scheduler stops without inventing a task block.
def test_routing_failure_action_no_actionable_task_stops_without_block() -> None:
    assert (
        failure_taxonomy.routing_failure_action("routing:no_actionable_task")
        == "stop_no_task"
    )


def test_routing_failure_action_unknown_routing_defaults_to_fail_no_task() -> None:
    assert (
        failure_taxonomy.routing_failure_action("routing:future_failure")
        == "fail_no_task"
    )


def test_normalise_failure_reason_class_preserves_legacy_explicit_class_only() -> None:
    assert failure_taxonomy.normalise_failure_reason_class("", "engine") == "engine"
    assert failure_taxonomy.normalise_failure_reason_class("", "unknown") == ""


# ── Taxonomy coverage ──────────────────────────────────────────────────


# Scenario: Every prefix class has at least one entry.
# Expected: no empty sets.
def test_all_prefix_classes_populated() -> None:
    assert len(failure_taxonomy.ROUTING_REASONS) > 0
    assert len(failure_taxonomy.ENGINE_REASONS) > 0
    assert len(failure_taxonomy.REVIEW_REASONS) > 0
    assert len(failure_taxonomy.SCOPE_REASONS) > 0
    assert len(failure_taxonomy.TEAM_REASONS) > 0


# Scenario: All reasons use their declared prefix.
# Expected: routing:* reasons start with "routing:", etc.
def test_prefix_consistency() -> None:
    for reason in failure_taxonomy.ROUTING_REASONS:
        assert reason.startswith("routing:"), reason
    for reason in failure_taxonomy.ENGINE_REASONS:
        assert reason.startswith("engine:"), reason
    for reason in failure_taxonomy.REVIEW_REASONS:
        assert reason.startswith("review:"), reason
    for reason in failure_taxonomy.SCOPE_REASONS:
        assert reason.startswith("scope:"), reason
    for reason in failure_taxonomy.TEAM_REASONS:
        assert reason.startswith("team:"), reason


# ── CLI ────────────────────────────────────────────────────────────────


# Scenario: `list` subcommand.
# Expected: prints all known reasons sorted.
def test_cli_list() -> None:
    result = subprocess.run(
        [sys.executable, str(HERE.parent / "failure_taxonomy.py"), "list"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == len(failure_taxonomy.ALL_KNOWN_REASONS)
    assert lines == sorted(lines)


# Scenario: `validate` with valid known reason.
# Expected: exit 0.
def test_cli_validate_known() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "failure_taxonomy.py"),
            "validate",
            "routing:no_actionable_task",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


# Scenario: `validate` with valid prefix but unknown leaf.
# Expected: exit 0 with warning on stderr.
def test_cli_validate_unknown_leaf() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "failure_taxonomy.py"),
            "validate",
            "engine:brand_new_error",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "warning" in result.stderr.lower()


# Scenario: `validate` with unprefixed reason.
# Expected: exit 1.
def test_cli_validate_invalid() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "failure_taxonomy.py"),
            "validate",
            "worker_exit_nonzero",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "no recognized prefix" in result.stderr


# Scenario: `validate` with empty string.
# Expected: exit 0 (no failure is valid).
def test_cli_validate_empty() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "failure_taxonomy.py"),
            "validate",
            "",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


# Scenario: `prefix` subcommand.
# Expected: prints the prefix class.
def test_cli_prefix() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "failure_taxonomy.py"),
            "prefix",
            "review:gate_failed",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "review"


# Scenario: `normalize` subcommand.
# Expected: prints the canonical ledger class.
def test_cli_normalize() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "failure_taxonomy.py"),
            "normalize",
            "review:gate_failed",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "review:gate_failed"


# Scenario: `action` subcommand.
# Expected: prints the routing scheduler policy for the failure.
def test_cli_action() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "failure_taxonomy.py"),
            "action",
            "routing:plugin_invisible",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "solo_fallback"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "Usage: failure_taxonomy.py"),
        (["validate"], "Usage: failure_taxonomy.py validate"),
        (["prefix"], "Usage: failure_taxonomy.py prefix"),
        (["normalize"], "Usage: failure_taxonomy.py normalize"),
        (["action"], "Usage: failure_taxonomy.py action"),
        (["bogus"], "Unknown command: bogus"),
    ],
)
def test_cli_usage_errors(args: list[str], message: str) -> None:
    result = subprocess.run(
        [sys.executable, str(HERE.parent / "failure_taxonomy.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert message in result.stderr
