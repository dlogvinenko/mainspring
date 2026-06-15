# SPDX-License-Identifier: Apache-2.0
"""Tests for notify_telegram.py — Telegram notification daemon."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import notify_telegram  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_entry(
    verdict: str = "PASS",
    exit_code: object = 0,
    task_id: str = "42",
    failure_reason: str = "",
    chapter_delta: str | None = None,
    next_action: str = "",
    duration_seconds: int = 60,
    writer: str = "claude",
    reviewer: str = "codex",
    **extra: object,
) -> dict:
    entry: dict = {
        "timestamp": "2026-04-26T12:00:00Z",
        "wave_id": "wave-001",
        "mode": "taskmaster",
        "topology": "solo",
        "task_id": task_id,
        "engines": {"writer": writer, "reviewer": reviewer},
        "verdict": verdict,
        "exit_code": exit_code,
        "failure_reason": failure_reason,
        "duration_seconds": duration_seconds,
        "next_action": next_action,
    }
    if chapter_delta is not None:
        entry["chapter_delta"] = chapter_delta
    entry.update(extra)
    return entry


def _write_ledger(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e, ensure_ascii=False) for e in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Event detection tests ────────────────────────────────────────────────


class TestDetectWaveFailed:
    # Scenario: Wave with FAIL verdict.
    # Expected: Returns failure message with task and reason.
    def test_fail_verdict(self) -> None:
        entry = _make_entry(verdict="FAIL", failure_reason="review:invalid_json")
        msg = notify_telegram.detect_wave_failed(entry)
        assert msg is not None
        assert "Wave failed" in msg
        assert "42" in msg
        assert "review:invalid_json" in msg

    # Scenario: Wave failure carries project and Taskmaster tag context.
    # Expected: The Telegram payload identifies which parallel project spoke.
    def test_fail_verdict_includes_project_and_tag_context(self) -> None:
        entry = _make_entry(
            verdict="FAIL",
            failure_reason="scope:violation",
            project_name="client-app",
            project_root="/work/client-app",
            taskmaster_tag="release",
        )

        msg = notify_telegram.detect_wave_failed(entry)

        assert msg is not None
        assert "Project: client-app" in msg
        assert "Folder: /work/client-app" in msg
        assert "Tag: release" in msg
        assert "Task: 42" in msg
        assert "Pair: claude+codex" in msg
        assert "Result: FAIL" in msg
        assert "Duration: 60s" in msg

    # Scenario: Wave with non-zero exit code but PASS verdict.
    # Expected: Still detects failure because exit_code != 0.
    def test_nonzero_exit_code(self) -> None:
        entry = _make_entry(verdict="PASS", exit_code=1)
        msg = notify_telegram.detect_wave_failed(entry)
        assert msg is not None
        assert "Wave failed" in msg

    # Scenario: Legacy JSONL stores a successful exit code as the string "0".
    # Expected: It does not create a false failure notification.
    def test_string_zero_exit_code_does_not_fail(self) -> None:
        entry = _make_entry(verdict="PASS", exit_code="0")
        msg = notify_telegram.detect_wave_failed(entry)
        assert msg is None

    # Scenario: Legacy JSONL stores a nonzero exit code as a string.
    # Expected: It still fails loud.
    def test_string_nonzero_exit_code_fails(self) -> None:
        entry = _make_entry(verdict="PASS", exit_code="1")
        msg = notify_telegram.detect_wave_failed(entry)
        assert msg is not None
        assert "Wave failed" in msg

    # Scenario: Wave with PASS and exit_code 0.
    # Expected: No failure detected.
    def test_pass_no_failure(self) -> None:
        entry = _make_entry(verdict="PASS", exit_code=0)
        msg = notify_telegram.detect_wave_failed(entry)
        assert msg is None

    # Scenario: Wave with ERROR verdict.
    # Expected: Detected as failure.
    def test_error_verdict(self) -> None:
        entry = _make_entry(verdict="ERROR")
        msg = notify_telegram.detect_wave_failed(entry)
        assert msg is not None

    # Scenario: Failed wave carries reviewer score/delta context.
    # Expected: Alert copy includes the context instead of only a raw reason.
    def test_failure_context_fields(self) -> None:
        entry = _make_entry(
            verdict="FAIL",
            failure_reason="review:reviewer_unreachable",
            chapter_delta="+0",
            competitor_delta="+0",
            launch_delta="+0",
            product_score=0,
        )

        msg = notify_telegram.detect_wave_failed(entry)

        assert msg is not None
        assert "Reason: review:reviewer_unreachable" in msg
        assert "Chapter delta: +0" in msg
        assert "Competitor delta: +0" in msg
        assert "Launch delta: +0" in msg
        assert "Product score: 0" in msg
        assert "Next: Restore the reviewer engine" in msg

    # Scenario: Failed row uses the PRD's canonical JSONL fields only.
    # Expected: Alert still includes pair, failure class, and duration truth.
    def test_canonical_ledger_failure_fields(self) -> None:
        entry = {
            "ts": "2026-04-29T10:00:00Z",
            "wave_id": "w-canonical",
            "mode": "taskmaster",
            "task_id": "99",
            "engine": "codex",
            "review_engine": "claude",
            "pair": "codex+claude",
            "verdict": "FAIL",
            "exit_code": 0,
            "failure_reason_class": "review:reviewer_unreachable",
            "duration_s": 42,
            "next_action": "Restore reviewer engine, then rerun the review gate.",
        }

        msg = notify_telegram.detect_wave_failed(entry)

        assert msg is not None
        assert "Pair: codex+claude" in msg
        assert "Result: FAIL" in msg
        assert "Reason: review:reviewer_unreachable" in msg
        assert "Next: Restore reviewer engine, then rerun the review gate." in msg
        assert "Duration: 42s" in msg


class TestDetectLoopStopped:
    # Scenario: Scheduler writes a terminal STOP row.
    # Expected: Telegram payload explains that the loop stopped and why.
    def test_stop_verdict(self) -> None:
        entry = _make_entry(
            verdict="STOP",
            failure_reason="routing:idle_threshold",
            task_id="7",
            next_action="Loop stopped after 2 consecutive idle waves.",
            duration_seconds=0,
            project_name="client-app",
            project_root="/work/client-app",
            taskmaster_tag="release",
        )

        msg = notify_telegram.detect_loop_stopped(entry)

        assert msg is not None
        assert "Mainspring stopped" in msg
        assert "Project: client-app" in msg
        assert "Folder: /work/client-app" in msg
        assert "Tag: release" in msg
        assert "Task: 7" in msg
        assert "Pair: claude+codex" in msg
        assert "Result: STOP" in msg
        assert "Reason: routing:idle_threshold" in msg
        assert "Loop stopped after 2 consecutive idle waves" in msg
        assert "Duration: 0s" in msg

    # Scenario: Ordinary idle rows are non-terminal.
    # Expected: They do not create stop notifications on their own.
    def test_idle_verdict_is_not_stop(self) -> None:
        entry = _make_entry(verdict="IDLE", failure_reason="engine:no_file_changes")

        assert notify_telegram.detect_loop_stopped(entry) is None


class TestDetectRetryLoop:
    # Scenario: 3 consecutive failures on the same task.
    # Expected: Returns retry loop warning.
    def test_three_consecutive_fails(self) -> None:
        entries = [
            _make_entry(verdict="FAIL", task_id="7"),
            _make_entry(verdict="FAIL", task_id="7"),
            _make_entry(verdict="FAIL", task_id="7"),
        ]
        msg = notify_telegram.detect_retry_loop(entries)
        assert msg is not None
        assert "Mainspring is stuck" in msg
        assert "7" in msg
        assert "Next: stop the loop" in msg

    # Scenario: Project context is available for a retry loop.
    # Expected: The alert includes concrete local open/stop commands.
    def test_retry_loop_includes_operator_commands(self) -> None:
        entries = [
            _make_entry(verdict="FAIL", task_id="7"),
            _make_entry(verdict="FAIL", task_id="7"),
            _make_entry(verdict="FAIL", task_id="7"),
        ]
        msg = notify_telegram.detect_retry_loop(
            entries,
            context={"project_name": "demo", "project_root": "/tmp/demo app"},
        )

        assert msg is not None
        assert "Open: cd '/tmp/demo app' && mainspring hud --local" in msg
        assert "Stop: cd '/tmp/demo app' && mainspring stop --force" in msg
        assert "Folder: /tmp/demo app" in msg
        assert "Pair: claude+codex" in msg
        assert "Result: RETRY_LOOP" in msg
        assert "Duration: 60s" in msg

    # Scenario: 3 consecutive failures are reviewer transport outages.
    # Expected: Recovery guidance says to restore the reviewer, not block the task.
    def test_reviewer_unreachable_retry_loop(self) -> None:
        entries = [
            _make_entry(
                verdict="FAIL",
                task_id="7",
                failure_reason="review:reviewer_unreachable",
            ),
            _make_entry(
                verdict="FAIL",
                task_id="7",
                failure_reason="review:reviewer_unreachable",
            ),
            _make_entry(
                verdict="FAIL",
                task_id="7",
                failure_reason="review:reviewer_unreachable",
            ),
        ]

        msg = notify_telegram.detect_retry_loop(entries)

        assert msg is not None
        assert "Reviewer outage loop" in msg
        assert "Restore the reviewer engine" in msg
        assert "Pair: claude+codex" in msg
        assert "Result: RETRY_LOOP" in msg
        assert "Reason: review:reviewer_unreachable" in msg
        assert "Duration: 60s" in msg
        assert "do not mark the task blocked" in msg
        assert "switching pair" not in msg

    # Scenario: Canonical ledger rows store the reason under failure_reason_class.
    # Expected: Reviewer-outage loop detection still uses the specific guidance.
    def test_reviewer_unreachable_retry_loop_canonical_reason(self) -> None:
        entries = [
            _make_entry(
                verdict="FAIL",
                task_id="7",
                failure_reason_class="review:reviewer_unreachable",
            ),
            _make_entry(
                verdict="FAIL",
                task_id="7",
                failure_reason_class="review:reviewer_unreachable",
            ),
            _make_entry(
                verdict="FAIL",
                task_id="7",
                failure_reason_class="review:reviewer_unreachable",
            ),
        ]

        msg = notify_telegram.detect_retry_loop(entries)

        assert msg is not None
        assert "Reviewer outage loop" in msg
        assert "Restore the reviewer engine" in msg

    # Scenario: 3 failures but different tasks.
    # Expected: No retry loop.
    def test_different_tasks(self) -> None:
        entries = [
            _make_entry(verdict="FAIL", task_id="1"),
            _make_entry(verdict="FAIL", task_id="2"),
            _make_entry(verdict="FAIL", task_id="3"),
        ]
        msg = notify_telegram.detect_retry_loop(entries)
        assert msg is None

    # Scenario: Only 2 entries (below threshold).
    # Expected: No retry loop.
    def test_below_threshold(self) -> None:
        entries = [
            _make_entry(verdict="FAIL", task_id="7"),
            _make_entry(verdict="FAIL", task_id="7"),
        ]
        msg = notify_telegram.detect_retry_loop(entries)
        assert msg is None

    # Scenario: Legacy JSONL stores successful exit codes as strings.
    # Expected: The notifier does not report a false retry loop.
    def test_string_zero_exit_codes_do_not_create_retry_loop(self) -> None:
        entries = [
            _make_entry(verdict="PASS", task_id="7", exit_code="0"),
            _make_entry(verdict="PASS", task_id="7", exit_code="0"),
            _make_entry(verdict="PASS", task_id="7", exit_code="0"),
        ]
        msg = notify_telegram.detect_retry_loop(entries)
        assert msg is None

    # Scenario: 3 entries, same task, but last one passes.
    # Expected: No retry loop.
    def test_last_passes(self) -> None:
        entries = [
            _make_entry(verdict="FAIL", task_id="7"),
            _make_entry(verdict="FAIL", task_id="7"),
            _make_entry(verdict="PASS", task_id="7"),
        ]
        msg = notify_telegram.detect_retry_loop(entries)
        assert msg is None

    # Scenario: Empty task_id in entries.
    # Expected: No retry loop (can't track without task_id).
    def test_empty_task_id(self) -> None:
        entries = [
            _make_entry(verdict="FAIL", task_id=""),
            _make_entry(verdict="FAIL", task_id=""),
            _make_entry(verdict="FAIL", task_id=""),
        ]
        msg = notify_telegram.detect_retry_loop(entries)
        assert msg is None


class TestDetectQuotaWarn:
    # Scenario: Codex usage at 95%.
    # Expected: Returns quota warning.
    def test_codex_high(self) -> None:
        entry = _make_entry(codex_short_delta_pct=95)
        msg = notify_telegram.detect_quota_warn(entry)
        assert msg is not None
        assert "codex" in msg
        assert "95" in msg

    # Scenario: Usage at 50%.
    # Expected: No warning.
    def test_below_threshold(self) -> None:
        entry = _make_entry(codex_short_delta_pct=50)
        msg = notify_telegram.detect_quota_warn(entry)
        assert msg is None

    # Scenario: No quota fields present.
    # Expected: No warning.
    def test_no_fields(self) -> None:
        entry = _make_entry()
        msg = notify_telegram.detect_quota_warn(entry)
        assert msg is None


class TestDetectMilestone:
    # Scenario: chapter_delta = +60.
    # Expected: Returns milestone message.
    def test_high_chapter_delta(self) -> None:
        entry = _make_entry(chapter_delta="+60")
        msg = notify_telegram.detect_milestone(entry)
        assert msg is not None
        assert "Milestone" in msg

    # Scenario: chapter_delta = +20 (below threshold).
    # Expected: No milestone.
    def test_low_chapter_delta(self) -> None:
        entry = _make_entry(chapter_delta="+20")
        msg = notify_telegram.detect_milestone(entry)
        assert msg is None

    # Scenario: Task marked done.
    # Expected: Returns task completion message.
    def test_task_done(self) -> None:
        entry = _make_entry(verdict="PASS", next_action="Mark task done and pick next")
        msg = notify_telegram.detect_milestone(entry)
        assert msg is not None
        assert "Task completed" in msg

    # Scenario: Canonical wave ledger records the post-review Taskmaster status.
    # Expected: Completion notification is based on explicit status truth.
    def test_task_done_from_status_after(self) -> None:
        entry = _make_entry(
            verdict="PASS",
            next_action="Continue with next Taskmaster-ready item.",
            task_status_after="done",
        )
        msg = notify_telegram.detect_milestone(entry)
        assert msg is not None
        assert "Task completed" in msg

    # Scenario: A corrupt/legacy row says PASS but carries a nonzero exit code.
    # Expected: Completion milestones fail closed just like failure alerts/digests.
    def test_task_done_requires_clean_pass(self) -> None:
        entry = _make_entry(
            verdict="PASS",
            exit_code="1",
            next_action="Continue with next Taskmaster-ready item.",
            task_status_after="done",
        )
        msg = notify_telegram.detect_milestone(entry)
        assert msg is None

    # Scenario: Reviewer/advisory guidance explicitly says not to mark done.
    # Expected: The legacy next_action fallback does not create a false milestone.
    def test_negated_done_guidance_is_not_completion(self) -> None:
        entry = _make_entry(
            verdict="PASS",
            next_action=(
                "Do not mark task done; keep work item in review until a "
                "code-mode wave ships product changes."
            ),
        )
        msg = notify_telegram.detect_milestone(entry)
        assert msg is None

    # Scenario: Explicit Taskmaster status says the item remained in review.
    # Expected: Status truth wins over any loose next_action wording.
    def test_non_done_status_after_blocks_legacy_completion_text(self) -> None:
        entry = _make_entry(
            verdict="PASS",
            next_action="Mark task done and pick next",
            task_status_after="review",
        )
        msg = notify_telegram.detect_milestone(entry)
        assert msg is None

    # Scenario: PASS but no "done" in next_action.
    # Expected: No milestone.
    def test_pass_no_done(self) -> None:
        entry = _make_entry(verdict="PASS", next_action="Continue to next wave")
        msg = notify_telegram.detect_milestone(entry)
        assert msg is None


class TestBuildDailyDigest:
    # Scenario: Usage has tokens and a known model price.
    # Expected: Cost is estimated from the model price table.
    def test_estimates_cost_from_known_model_tokens(self) -> None:
        entry = _make_entry(
            models={"writer": "gpt-5.5"},
            usage={
                "input_tokens": 1_000_000,
                "cached_input_tokens": 100_000,
                "output_tokens": 100_000,
            },
        )

        cost = notify_telegram.extract_wave_cost(entry)

        assert cost is not None
        assert cost[1] == "estimated"
        assert cost[0] == 7.55

    # Scenario: Usage has per-role token counts with known writer and reviewer models.
    # Expected: Cost is estimated for both roles and summed.
    def test_estimates_cost_from_per_role_usage(self) -> None:
        entry = _make_entry(
            models={"writer": "opus", "reviewer": "gpt-5.4-mini"},
            usage={
                "writer": {"input_tokens": 100_000, "output_tokens": 10_000},
                "reviewer": {"input_tokens": 200_000, "output_tokens": 20_000},
            },
        )

        cost = notify_telegram.extract_wave_cost(entry)

        assert cost is not None
        assert cost[1] == "estimated"
        assert round(cost[0], 2) == 0.99

    # Scenario: Role usage is paired with legacy top-level model fields.
    # Expected: Cost uses each role's model truth, not the writer model for both.
    def test_estimates_cost_from_legacy_role_model_fields(self) -> None:
        entry = _make_entry(
            writer_model="gpt-5.4-mini",
            review_model="sonnet",
            usage={
                "writer": {"input_tokens": 100_000, "output_tokens": 10_000},
                "reviewer": {"input_tokens": 200_000, "output_tokens": 20_000},
            },
        )

        cost = notify_telegram.extract_wave_cost(entry)

        assert cost is not None
        assert cost[1] == "estimated"
        assert round(cost[0], 2) == 1.02

    # Scenario: Per-role usage has no reviewer model, but a root writer model exists.
    # Expected: No cost is estimated because the reviewer price would be a guess.
    def test_per_role_usage_needs_each_role_model(self) -> None:
        entry = _make_entry(
            model="gpt-5.5",
            usage={
                "writer": {"input_tokens": 100_000, "output_tokens": 10_000},
                "reviewer": {"input_tokens": 200_000, "output_tokens": 20_000},
            },
        )

        assert notify_telegram.extract_wave_cost(entry) is None

    # Scenario: Usage has tokens but no known model price.
    # Expected: No cost is reported rather than fabricating spend.
    def test_unknown_model_cost_is_not_estimated(self) -> None:
        entry = _make_entry(
            models={"writer": "gpt-unknown"},
            usage={"input_tokens": 100_000, "output_tokens": 10_000},
        )

        assert notify_telegram.extract_wave_cost(entry) is None

    # Scenario: Usage is split by writer/reviewer role.
    # Expected: Token digest totals both roles without double-counting cached tokens.
    def test_extract_token_count_from_per_role_usage(self) -> None:
        entry = _make_entry(
            usage={
                "writer": {"input_tokens": 100_000, "output_tokens": 10_000},
                "reviewer": {"input_tokens": 200_000, "output_tokens": 20_000},
            },
        )

        assert notify_telegram.extract_token_count(entry) == 330_000
        assert notify_telegram.extract_role_token_counts(entry) == {
            "writer": 110_000,
            "reviewer": 220_000,
        }

    # Scenario: Mix of pass and fail entries from today.
    # Expected: Digest with correct counts and pass rate.
    def test_basic_digest(self) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entries = [
            _make_entry(verdict="PASS", duration_seconds=100, task_id="1"),
            _make_entry(verdict="PASS", duration_seconds=200, task_id="2"),
            _make_entry(verdict="FAIL", duration_seconds=50, task_id="3"),
        ]
        for e in entries:
            e["timestamp"] = now_iso

        msg = notify_telegram.build_daily_digest(entries, days=1)
        assert msg is not None
        assert "Daily Digest" in msg
        assert "Waves: 3" in msg
        assert "2 pass" in msg
        assert "1 fail" in msg
        assert "Quota: Waiting for quota data" in msg
        assert "Disabled pairs: Waiting for state data" in msg
        assert "Cost: Waiting for usage data" in msg

    # Scenario: Digest receives rows that use canonical PRD schema fields.
    # Expected: The row is included and pair/duration/cost truth is preserved.
    def test_canonical_ledger_digest_fields(self) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entries = [
            {
                "ts": now_iso,
                "wave_id": "w-canonical",
                "mode": "taskmaster",
                "engine": "codex",
                "review_engine": "claude",
                "pair": "codex+claude",
                "task_id": "42",
                "verdict": "PASS",
                "exit_code": 0,
                "duration_s": 30,
                "chapter_delta": "+5",
                "cost_usd": 0.5,
                "usage": {"total_tokens": 100},
            }
        ]

        msg = notify_telegram.build_daily_digest(entries, days=1)

        assert msg is not None
        assert "Waves: 1" in msg
        assert "Mean duration: 30s" in msg
        assert "w-canonical task=42 codex+claude $0.50" in msg
        assert "codex+claude: 100" in msg

    # Scenario: A canonical row has PASS text but a nonzero exit code.
    # Expected: Digest failure math follows the same fail-closed truth as alerts.
    def test_digest_counts_nonzero_exit_as_failure(self) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entries = [
            _make_entry(verdict="PASS", exit_code="0", task_id="clean"),
            _make_entry(verdict="PASS", exit_code="1", task_id="failed-exit"),
            _make_entry(verdict="STOP", exit_code=0, task_id="scheduler-stop"),
        ]
        for entry in entries:
            entry["timestamp"] = now_iso

        msg = notify_telegram.build_daily_digest(entries, days=1)

        assert msg is not None
        assert "Waves: 3 (1 pass, 1 fail, 1 other)" in msg
        assert "Pass rate: 33%" in msg

    # Scenario: Repeated nonzero-exit rows have legacy PASS verdicts.
    # Expected: Stuck-task detection still flags the failing task.
    def test_digest_stuck_tasks_use_exit_code_failure_truth(self) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entries = [
            _make_entry(verdict="PASS", exit_code="1", task_id="stuck-exit"),
            _make_entry(verdict="PASS", exit_code="1", task_id="stuck-exit"),
            _make_entry(verdict="PASS", exit_code="1", task_id="stuck-exit"),
        ]
        for entry in entries:
            entry["timestamp"] = now_iso

        msg = notify_telegram.build_daily_digest(entries, days=1)

        assert msg is not None
        assert "Waves: 3 (0 pass, 3 fail)" in msg
        assert "Stuck tasks:" in msg
        assert "stuck-exit" in msg

    # Scenario: Recent entries include real cost and token usage.
    # Expected: Digest reports spend, top-cost waves, token totals, and unit costs.
    def test_cost_and_token_digest(self) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entries = [
            _make_entry(
                wave_id="w1",
                task_id="1",
                chapter_delta="+20",
                cost_usd=1.25,
                product_score_delta="+5",
                usage={"total_tokens": 1200},
            ),
            _make_entry(
                wave_id="w2",
                task_id="2",
                chapter_delta="+5",
                total_cost_usd=0.75,
                usage={"input_tokens": 300, "output_tokens": 200},
            ),
        ]
        for e in entries:
            e["timestamp"] = now_iso

        msg = notify_telegram.build_daily_digest(entries, days=1)

        assert msg is not None
        assert "Cost: $2.00 (2/2 waves with cost truth)" in msg
        assert "Cost / chapter delta: $0.08/pt" in msg
        assert "Cost / score delta: $0.40/pt" in msg
        assert "Top cost waves:" in msg
        assert "w1 task=1 claude+codex $1.25" in msg
        assert "Tokens by pair:" in msg
        assert "claude+codex: 1700" in msg

    # Scenario: Digest has canonical product_score rows but no explicit score_delta.
    # Expected: Cost per score movement is inferred and clearly labeled.
    def test_cost_digest_uses_product_score_movement_when_delta_absent(self) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entries = [
            _make_entry(wave_id="w-low", cost_usd=1.0, product_score=700),
            _make_entry(wave_id="w-high", cost_usd=1.0, product_score=740),
        ]
        for entry in entries:
            entry["timestamp"] = now_iso

        msg = notify_telegram.build_daily_digest(entries, days=1)

        assert msg is not None
        assert "Cost / score delta: $0.05/pt (from product_score movement)" in msg
        assert "Cost / score delta: Waiting for score-delta data" not in msg

    # Scenario: Some rows have product movement but no cost truth.
    # Expected: Unit economics use only costed wave deltas.
    def test_cost_digest_unit_costs_ignore_uncosted_delta_rows(self) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entries = [
            _make_entry(
                wave_id="w-cost-1",
                chapter_delta="+10",
                cost_usd=1.0,
                product_score=700,
            ),
            _make_entry(
                wave_id="w-free",
                chapter_delta="+90",
                product_score=790,
            ),
            _make_entry(
                wave_id="w-cost-2",
                chapter_delta="+10",
                cost_usd=1.0,
                product_score=800,
            ),
        ]
        for entry in entries:
            entry["timestamp"] = now_iso

        msg = notify_telegram.build_daily_digest(entries, days=1)

        assert msg is not None
        assert "Cost: $2.00 (2/3 waves with cost truth)" in msg
        assert "Cost / chapter delta: $0.10/pt" in msg
        assert "Cost / score delta: $0.20/pt (from product_score movement)" in msg
        assert "Uncosted chapter delta: +90 (excluded from unit costs)" in msg
        assert "Uncosted score delta: +90 (excluded from unit costs)" in msg
        assert "$0.02/pt" not in msg

    # Scenario: Positive chapter movement exists only on rows with no cost truth.
    # Expected: Digest refuses to report a cost-per-delta line.
    def test_cost_digest_waits_for_costed_chapter_delta(self) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entries = [
            _make_entry(wave_id="w-cost", chapter_delta="+0", cost_usd=1.0),
            _make_entry(wave_id="w-free", chapter_delta="+50"),
        ]
        for entry in entries:
            entry["timestamp"] = now_iso

        msg = notify_telegram.build_daily_digest(entries, days=1)

        assert msg is not None
        assert "Cost / chapter delta: Waiting for costed positive chapter_delta" in msg

    # Scenario: Recent entries include token usage but no explicit cost field.
    # Expected: Digest reports transparent estimated cost instead of waiting.
    def test_estimated_cost_digest(self) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entries = [
            _make_entry(
                wave_id="w-est",
                task_id="9",
                chapter_delta="+10",
                models={"writer": "gpt-5.5"},
                usage={"input_tokens": 1_000_000, "output_tokens": 100_000},
            )
        ]
        entries[0]["timestamp"] = now_iso

        msg = notify_telegram.build_daily_digest(entries, days=1)

        assert msg is not None
        assert "Cost: $8.00 (1/1 waves with cost truth)" in msg
        assert "Estimated cost waves: 1" in msg
        assert "w-est task=9 claude+codex $8.00 estimated" in msg

    # Scenario: Recent entries include writer/reviewer role-specific token usage.
    # Expected: Digest keeps the pair total and exposes the per-role split.
    def test_role_token_digest(self) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entries = [
            _make_entry(
                usage={
                    "writer": {"input_tokens": 100_000, "output_tokens": 10_000},
                    "reviewer": {"input_tokens": 200_000, "output_tokens": 20_000},
                },
            )
        ]
        entries[0]["timestamp"] = now_iso

        msg = notify_telegram.build_daily_digest(entries, days=1)

        assert msg is not None
        assert "Tokens by pair:" in msg
        assert "claude+codex: 330000" in msg
        assert "Role tokens by pair:" in msg
        assert "claude+codex: writer=110000, reviewer=220000" in msg

    # Scenario: Recent entries include quota fields and disabled pair state.
    # Expected: Digest reports the current quota snapshot and disabled pair list.
    def test_quota_and_disabled_pairs_digest(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "disabled-pairs.json").write_text(
            json.dumps(
                {
                    "codex+haiku": {"reason": "low chapter_delta_per_dollar"},
                    "gemini+claude": {"reason": "manual disable"},
                    "updated_at": now_iso,
                }
            ),
            encoding="utf-8",
        )
        entries = [
            _make_entry(
                codex_short_delta_pct=91,
                quota={"claude": {"short_remaining_pct": 42.5}},
            )
        ]
        entries[0]["timestamp"] = now_iso

        msg = notify_telegram.build_daily_digest(entries, days=1, state_dir=state_dir)

        assert msg is not None
        assert "Quota: codex 91% short used, claude 57.5% short used" in msg
        assert "Disabled pairs: codex+haiku, gemini+claude" in msg

    # Scenario: Metrics state has active/reactivated pair details but no disabled pairs.
    # Expected: Digest reports no disabled pairs instead of metadata keys.
    def test_metrics_state_without_disabled_pairs_digest(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "disabled-pairs.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "updated_at": now_iso,
                    "window_days": 14,
                    "threshold_ratio": 0.7,
                    "disabled_pairs": [],
                    "manual_reactivated_pairs": ["claude-haiku+claude-haiku"],
                    "median_chapter_delta_per_dollar_14d": 10.0,
                    "threshold_chapter_delta_per_dollar_14d": 7.0,
                    "pairs": {
                        "claude-haiku+claude-haiku": {"status": "manual_reactivated"},
                        "claude+codex": {"status": "active"},
                    },
                }
            ),
            encoding="utf-8",
        )
        entry = _make_entry()
        entry["timestamp"] = now_iso

        msg = notify_telegram.build_daily_digest([entry], days=1, state_dir=state_dir)

        assert msg is not None
        assert "Disabled pairs: none" in msg
        assert "manual_reactivated_pairs" not in msg
        assert "Disabled pairs: pairs" not in msg
        assert "threshold" not in msg

    # Scenario: Metrics state omits the top-level disabled list but has pair statuses.
    # Expected: Digest falls back to disabled statuses in pair details only.
    def test_metrics_pair_detail_disabled_status_digest(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "disabled-pairs.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "updated_at": now_iso,
                    "pairs": {
                        "codex+spark": {"status": "auto_disabled"},
                        "claude+haiku": {"status": "manual_disabled"},
                        "claude+codex": {"status": "active"},
                    },
                }
            ),
            encoding="utf-8",
        )
        entry = _make_entry()
        entry["timestamp"] = now_iso

        msg = notify_telegram.build_daily_digest([entry], days=1, state_dir=state_dir)

        assert msg is not None
        assert "Disabled pairs: claude+haiku, codex+spark" in msg
        assert "claude+codex" not in msg

    # Scenario: Entries older than 1 day.
    # Expected: Returns None (no recent entries).
    def test_old_entries(self) -> None:
        entries = [_make_entry()]
        entries[0]["timestamp"] = "2020-01-01T00:00:00Z"
        msg = notify_telegram.build_daily_digest(entries, days=1)
        assert msg is None

    # Scenario: Calendar-mode digest includes only the target day.
    # Expected: Today's entry is excluded when reporting yesterday.
    def test_calendar_mode_is_yesterday(self) -> None:
        from datetime import datetime, timezone

        now = datetime(2026, 4, 30, 9, 0, tzinfo=timezone.utc)
        entries = [
            _make_entry(
                verdict="PASS",
                task_id="today",
                wave_id="w1",
                cost_usd=1.0,
            ),
            _make_entry(
                verdict="PASS",
                task_id="yesterday",
                wave_id="w2",
                cost_usd=1.0,
            ),
        ]
        entries[0]["timestamp"] = "2026-04-30T08:59:00Z"
        entries[1]["timestamp"] = "2026-04-29T23:59:00Z"

        msg = notify_telegram.build_daily_digest(
            entries,
            days=1,
            mode="calendar",
            now=now,
        )

        assert msg is not None
        assert "Daily Digest (2026-04-29)" in msg
        assert "Waves: 1" in msg
        assert "w2" in msg
        assert "w1" not in msg

    # Scenario: P-Comp-5 daily digest acceptance path at the 09:00 local run.
    # Expected: Digest reports the previous local calendar day with cost truth,
    # top cost waves, tokens by pair, and explicit uncosted movement.
    def test_comp5_daily_cost_digest_acceptance(self) -> None:
        from datetime import datetime, timedelta, timezone

        local_tz = timezone(timedelta(hours=2))
        now = datetime(2026, 4, 30, 9, 0, tzinfo=local_tz)
        entries = [
            _make_entry(
                wave_id="w-ledger",
                task_id="costed-ledger",
                chapter_delta="+20",
                product_score_delta="+5",
                cost_usd=3.0,
                usage={"total_tokens": 5_000},
            ),
            _make_entry(
                wave_id="w-estimated",
                task_id="costed-estimated",
                chapter_delta="+10",
                product_score_delta="+10",
                models={"writer": "gpt-5.5"},
                usage={"input_tokens": 1_000_000, "output_tokens": 100_000},
            ),
            _make_entry(
                wave_id="w-uncosted",
                task_id="uncosted-movement",
                chapter_delta="+40",
                product_score_delta="+10",
            ),
            _make_entry(
                wave_id="w-today",
                task_id="today-excluded",
                chapter_delta="+999",
                product_score_delta="+999",
                cost_usd=99.0,
            ),
        ]
        # UTC 2026-04-28T23:30 is already 2026-04-29 locally (+02:00), so it
        # must be included in the prior local-day digest.
        entries[0]["timestamp"] = "2026-04-28T23:30:00Z"
        entries[1]["timestamp"] = "2026-04-29T10:00:00+02:00"
        entries[2]["timestamp"] = "2026-04-29T23:30:00+02:00"
        entries[3]["timestamp"] = "2026-04-30T00:01:00+02:00"

        msg = notify_telegram.build_daily_digest(
            entries,
            days=1,
            mode="calendar",
            now=now,
        )

        assert msg is not None
        assert "Daily Digest (2026-04-29)" in msg
        assert "Waves: 3" in msg
        assert "Cost: $11.00 (2/3 waves with cost truth)" in msg
        assert "Estimated cost waves: 1" in msg
        assert "Cost / chapter delta: $0.37/pt" in msg
        assert "Cost / score delta: $0.73/pt" in msg
        assert "Uncosted chapter delta: +40 (excluded from unit costs)" in msg
        assert "Uncosted score delta: +10 (excluded from unit costs)" in msg
        assert "Top cost waves:" in msg
        assert "w-estimated task=costed-estimated claude+codex $8.00 estimated" in msg
        assert "w-ledger task=costed-ledger claude+codex $3.00" in msg
        assert "Tokens by pair:" in msg
        assert "claude+codex: 1105000" in msg
        assert "w-today" not in msg
        assert "+999" not in msg

    # Scenario: Empty entries list.
    # Expected: Returns None.
    def test_empty(self) -> None:
        msg = notify_telegram.build_daily_digest([], days=1)
        assert msg is None

    # Scenario: Stuck tasks (3+ fails on same task).
    # Expected: Digest includes stuck task list.
    def test_stuck_tasks(self) -> None:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entries = [
            _make_entry(verdict="FAIL", task_id="stuck-1"),
            _make_entry(verdict="FAIL", task_id="stuck-1"),
            _make_entry(verdict="FAIL", task_id="stuck-1"),
            _make_entry(verdict="FAIL", task_id="stuck-2"),
            _make_entry(verdict="FAIL", task_id="stuck-2"),
            _make_entry(verdict="FAIL", task_id="stuck-2"),
            _make_entry(verdict="FAIL", task_id="stuck-3"),
            _make_entry(verdict="FAIL", task_id="stuck-3"),
            _make_entry(verdict="FAIL", task_id="stuck-3"),
            _make_entry(verdict="FAIL", task_id="stuck-4"),
            _make_entry(verdict="FAIL", task_id="stuck-4"),
            _make_entry(verdict="FAIL", task_id="stuck-4"),
            _make_entry(verdict="PASS", task_id="ok-1"),
        ]
        for e in entries:
            e["timestamp"] = now_iso

        msg = notify_telegram.build_daily_digest(entries, days=1)
        assert msg is not None
        assert "Stuck tasks:" in msg
        assert "stuck-1" in msg
        assert "stuck-2" in msg
        assert "stuck-3" in msg
        assert "stuck-4" not in msg


# ── NotifyState tests ────────────────────────────────────────────────────


class TestNotifyState:
    # Scenario: Fresh state file.
    # Expected: All defaults are zero/empty.
    def test_fresh_state(self, tmp_path: Path) -> None:
        state = notify_telegram.NotifyState(tmp_path / "state.json")
        assert state.last_line_count == 0
        assert state.last_activity_ts == 0.0
        assert state.last_digest_date == ""

    # Scenario: Save and reload state.
    # Expected: State persists across instances.
    def test_save_and_reload(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        state = notify_telegram.NotifyState(state_path)
        state.last_line_count = 42
        state.last_activity_ts = 1000.0
        state.record_sent("wave_failed", now=5000.0)
        state.save()

        state2 = notify_telegram.NotifyState(state_path)
        assert state2.last_line_count == 42
        assert state2.last_activity_ts == 1000.0
        assert state2.is_rate_limited("wave_failed", now=5100.0)

    # Scenario: State save completes the atomic replace.
    # Expected: Parent directory is fsynced so the new directory entry is durable.
    def test_save_fsyncs_parent_directory_after_replace(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        state = notify_telegram.NotifyState(state_path)
        state.last_line_count = 42

        with patch("notify_telegram._fsync_directory") as fsync_directory:
            state.save()

        fsync_directory.assert_called_once_with(tmp_path)

    # Scenario: A Telegram delivery attempt fails before a message is sent.
    # Expected: The event class is attempt-limited without claiming delivery.
    def test_attempt_limited_without_sent_truth(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        state = notify_telegram.NotifyState(state_path)
        state.record_attempt("wave_failed", now=5000.0)
        state.save()

        state2 = notify_telegram.NotifyState(state_path)

        assert state2.is_rate_limited("wave_failed", now=5100.0) is False
        assert state2.is_attempt_limited("wave_failed", now=5100.0) is True
        assert state2.is_attempt_limited("wave_failed", now=5400.0) is False

    # Scenario: Atomic replacement fails after writing the temporary state file.
    # Expected: Existing state remains readable and no temp file is left behind.
    def test_save_replace_failure_keeps_existing_state(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        original = notify_telegram.NotifyState(state_path)
        original.last_line_count = 7
        original.save()

        updated = notify_telegram.NotifyState(state_path)
        updated.last_line_count = 9

        with patch("notify_telegram.os.replace", side_effect=OSError("replace failed")):
            try:
                updated.save()
            except OSError:
                pass
            else:  # pragma: no cover - defensive assertion around the patch contract
                raise AssertionError("expected os.replace failure")

        reloaded = notify_telegram.NotifyState(state_path)
        assert reloaded.last_line_count == 7
        assert list(tmp_path.glob(".state.json.*.tmp")) == []

    # Scenario: Rate limit window not expired.
    # Expected: is_rate_limited returns True.
    def test_rate_limited(self, tmp_path: Path) -> None:
        state = notify_telegram.NotifyState(tmp_path / "state.json")
        state.record_sent("wave_failed", now=1000.0)
        assert state.is_rate_limited("wave_failed", now=1200.0) is True

    # Scenario: Rate limit window expired.
    # Expected: is_rate_limited returns False.
    def test_rate_limit_expired(self, tmp_path: Path) -> None:
        state = notify_telegram.NotifyState(tmp_path / "state.json")
        state.record_sent("wave_failed", now=1000.0)
        assert state.is_rate_limited("wave_failed", now=1400.0) is False

    # Scenario: Different event classes tracked independently.
    # Expected: Rate limit for one class doesn't affect another.
    def test_independent_classes(self, tmp_path: Path) -> None:
        state = notify_telegram.NotifyState(tmp_path / "state.json")
        state.record_sent("wave_failed", now=1000.0)
        assert state.is_rate_limited("wave_failed", now=1100.0) is True
        assert state.is_rate_limited("milestone", now=1100.0) is False

    # Scenario: Corrupted state file.
    # Expected: Loads empty state without crashing.
    def test_corrupted_file(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        state_path.write_text("{invalid json", encoding="utf-8")
        state = notify_telegram.NotifyState(state_path)
        assert state.last_line_count == 0

    # Scenario: State file is valid JSON but not an object.
    # Expected: Loads empty state instead of crashing on dict-only operations.
    def test_non_object_state_file_is_treated_as_empty(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        state_path.write_text('["not", "a", "mapping"]', encoding="utf-8")
        state = notify_telegram.NotifyState(state_path)

        assert state.last_line_count == 0
        assert state.last_activity_ts == 0.0
        assert state.last_digest_date == ""

        state.record_sent("wave_failed", now=1000.0)
        state.last_line_count = 1
        state.save()

        reloaded = notify_telegram.NotifyState(state_path)
        assert reloaded.last_line_count == 1
        assert reloaded.is_rate_limited("wave_failed", now=1100.0) is True

    # Scenario: Rate-limit state has malformed last_sent data from corruption
    # or a partial manual edit.
    # Expected: Notification processing treats it as unsent instead of crashing.
    def test_corrupted_last_sent_state_does_not_crash(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        state_path.write_text(
            json.dumps({"last_sent": {"wave_failed": "not-a-timestamp"}}),
            encoding="utf-8",
        )
        state = notify_telegram.NotifyState(state_path)

        assert state.is_rate_limited("wave_failed", now=1000.0) is False

        with patch("notify_telegram.send_message", return_value={"ok": True}):
            sent = notify_telegram.process_new_entries(
                [_make_entry(verdict="FAIL")],
                [_make_entry(verdict="FAIL")],
                state,
                now=1000.0,
            )

        assert sent == ["wave_failed"]
        assert state.is_rate_limited("wave_failed", now=1100.0) is True

    # Scenario: The last_sent root is not a mapping.
    # Expected: record_sent repairs the shape before writing the event timestamp.
    def test_non_mapping_last_sent_state_is_repaired(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        state_path.write_text(
            json.dumps({"last_sent": "corrupt"}),
            encoding="utf-8",
        )
        state = notify_telegram.NotifyState(state_path)

        assert state.is_rate_limited("wave_failed", now=1000.0) is False
        state.record_sent("wave_failed", now=1000.0)
        state.save()

        reloaded = notify_telegram.NotifyState(state_path)
        assert reloaded.is_rate_limited("wave_failed", now=1100.0) is True

    # Scenario: The last_attempt root is corrupt.
    # Expected: record_attempt repairs it before throttling future attempts.
    def test_non_mapping_last_attempt_state_is_repaired(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        state_path.write_text(
            json.dumps({"last_attempt": "corrupt"}),
            encoding="utf-8",
        )
        state = notify_telegram.NotifyState(state_path)

        assert state.is_attempt_limited("wave_failed", now=1000.0) is False
        state.record_attempt("wave_failed", now=1000.0)
        state.save()

        reloaded = notify_telegram.NotifyState(state_path)
        assert reloaded.is_attempt_limited("wave_failed", now=1100.0) is True


# ── send_message tests ───────────────────────────────────────────────────


class TestSendMessage:
    # Scenario: No bot token set.
    # Expected: Returns None without sending.
    def test_no_token(self) -> None:
        for key in (
            "MAINSPRING_TELEGRAM_BOT_TOKEN",
            "MAINSPRING_TELEGRAM_CHAT_ID",
        ):
            os.environ.pop(key, None)
        result = notify_telegram.send_message("test")
        assert result is None

    # Scenario: Successful send with explicit token/chat_id.
    # Expected: Returns response dict.
    def test_success(self) -> None:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"ok": true, "result": {}}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "notify_telegram.urllib.request.urlopen", return_value=mock_response
        ):
            result = notify_telegram.send_message(
                "hello", bot_token="tok123", chat_id="456"
            )
        assert result is not None
        assert result["ok"] is True

    # Scenario: Network error during send.
    # Expected: Returns None, doesn't raise.
    def test_network_error(self) -> None:
        import urllib.error

        with patch(
            "notify_telegram.urllib.request.urlopen",
            side_effect=urllib.error.URLError("timeout"),
        ):
            result = notify_telegram.send_message(
                "hello", bot_token="tok", chat_id="123"
            )
        assert result is None

    # Scenario: Telegram API returns ok: false.
    # Expected: Returns None and logs an error.
    def test_error_response(self, capsys) -> None:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"ok": false, "description": "bad token"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "notify_telegram.urllib.request.urlopen", return_value=mock_response
        ):
            result = notify_telegram.send_message(
                "hello", bot_token="tok", chat_id="123"
            )

        assert result is None
        assert "Telegram API error" in capsys.readouterr().err

    # Scenario: Telegram returns a JSON object without ok=true.
    # Expected: Treat it as failed delivery so rate-limit state cannot record
    # a false successful send.
    def test_missing_ok_true_response_is_not_delivered(self, capsys) -> None:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"result": {}}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "notify_telegram.urllib.request.urlopen", return_value=mock_response
        ):
            result = notify_telegram.send_message(
                "hello", bot_token="tok", chat_id="123"
            )

        assert result is None
        assert "missing ok=true" in capsys.readouterr().err


# ── process_new_entries tests ────────────────────────────────────────────


class TestProcessNewEntries:
    # Scenario: One failed wave, no rate limit.
    # Expected: wave_failed notification sent.
    def test_wave_failed_sent(self, tmp_path: Path) -> None:
        state = notify_telegram.NotifyState(tmp_path / "state.json")
        entries = [_make_entry(verdict="FAIL", failure_reason="engine:crash")]
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        os.environ["MAINSPRING_TELEGRAM_BOT_TOKEN"] = "test-tok"
        os.environ["MAINSPRING_TELEGRAM_CHAT_ID"] = "12345"
        try:
            with patch(
                "notify_telegram.urllib.request.urlopen", return_value=mock_resp
            ):
                sent = notify_telegram.process_new_entries(
                    entries, entries, state, now=1000.0
                )
            assert "wave_failed" in sent
        finally:
            os.environ.pop("MAINSPRING_TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("MAINSPRING_TELEGRAM_CHAT_ID", None)

    # Scenario: Reviewer is unreachable and the wave has review-score context.
    # Expected: The delivered Telegram payload includes the failure reason and deltas.
    def test_reviewer_unreachable_payload_includes_score_context(
        self, tmp_path: Path
    ) -> None:
        state = notify_telegram.NotifyState(tmp_path / "state.json")
        entries = [
            _make_entry(
                verdict="FAIL",
                failure_reason="review:reviewer_unreachable",
                chapter_delta="+0",
                competitor_delta="+0",
                launch_delta="+0",
                product_score=0,
            )
        ]

        with patch("notify_telegram.send_message", return_value={"ok": True}) as send:
            sent = notify_telegram.process_new_entries(
                entries, entries, state, now=1000.0
            )

        assert sent == ["wave_failed"]
        payload = send.call_args.args[0]
        assert "Wave failed" in payload
        assert "Reason: review:reviewer_unreachable" in payload
        assert "Chapter delta: +0" in payload
        assert "Competitor delta: +0" in payload
        assert "Launch delta: +0" in payload
        assert "Product score: 0" in payload

    # Scenario: Same event class within rate limit.
    # Expected: Second notification is suppressed.
    def test_rate_limited(self, tmp_path: Path) -> None:
        state = notify_telegram.NotifyState(tmp_path / "state.json")
        state.record_sent("wave_failed", now=900.0)

        entries = [_make_entry(verdict="FAIL")]
        os.environ["MAINSPRING_TELEGRAM_BOT_TOKEN"] = "test-tok"
        os.environ["MAINSPRING_TELEGRAM_CHAT_ID"] = "12345"
        try:
            sent = notify_telegram.process_new_entries(
                entries, entries, state, now=1000.0
            )
            assert "wave_failed" not in sent  # rate limited (1000-900=100 < 300)
        finally:
            os.environ.pop("MAINSPRING_TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("MAINSPRING_TELEGRAM_CHAT_ID", None)

    # Scenario: Passing wave, no special events.
    # Expected: Nothing sent.
    def test_pass_no_events(self, tmp_path: Path) -> None:
        state = notify_telegram.NotifyState(tmp_path / "state.json")
        entries = [_make_entry(verdict="PASS")]
        sent = notify_telegram.process_new_entries(entries, entries, state, now=1000.0)
        assert sent == []

    # Scenario: Scheduler stop row arrives.
    # Expected: loop_stopped notification is sent separately from failures.
    def test_loop_stopped_sent(self, tmp_path: Path) -> None:
        state = notify_telegram.NotifyState(tmp_path / "state.json")
        entries = [
            _make_entry(
                verdict="STOP",
                failure_reason="routing:idle_threshold",
                next_action="Loop stopped after 2 consecutive idle waves.",
            )
        ]

        with patch("notify_telegram.send_message", return_value={"ok": True}) as send:
            sent = notify_telegram.process_new_entries(
                entries,
                entries,
                state,
                now=1000.0,
            )

        assert sent == ["loop_stopped"]
        payload = send.call_args.args[0]
        assert "Mainspring stopped" in payload
        assert "routing:idle_threshold" in payload
        assert "Loop stopped after 2 consecutive idle waves" in payload

    # Scenario: A failure is inside the rate-limit window.
    # Expected: Caller can log the suppressed event class without sending.
    def test_status_log_records_rate_limited_event(self, tmp_path: Path) -> None:
        state = notify_telegram.NotifyState(tmp_path / "state.json")
        state.record_sent("wave_failed", now=950.0)
        entries = [_make_entry(verdict="FAIL")]
        statuses: list[tuple[str, str]] = []

        sent = notify_telegram.process_new_entries(
            entries, entries, state, now=1000.0, status_log=statuses
        )

        assert sent == []
        assert statuses == [("wave_failed", "rate_limited")]

    # Scenario: 50 failures for the same task arrive in one ledger batch.
    # Expected: The stronger retry_loop alert sends once and ordinary
    # wave_failed noise is suppressed for that batch.
    def test_fifty_failures_do_not_flood_wave_failed(self, tmp_path: Path) -> None:
        state = notify_telegram.NotifyState(tmp_path / "state.json")
        entries = [
            _make_entry(verdict="FAIL", task_id="7", wave_id=f"w-{i}")
            for i in range(50)
        ]
        statuses: list[tuple[str, str]] = []

        with patch("notify_telegram.send_message", return_value={"ok": True}) as send:
            sent = notify_telegram.process_new_entries(
                entries, entries, state, now=1000.0, status_log=statuses
            )

        retry_loop_statuses = [
            status for event, status in statuses if event == "retry_loop"
        ]
        wave_failed_statuses = [
            status for event, status in statuses if event == "wave_failed"
        ]
        assert sent == ["retry_loop"]
        assert retry_loop_statuses == ["sent"]
        assert wave_failed_statuses == []
        assert send.call_count == 1
        assert "Mainspring is stuck" in send.call_args.args[0]

    # Scenario: Telegram delivery is failing while many failures arrive at once.
    # Expected: The daemon makes one send attempt, then suppresses duplicates
    # without recording the message as delivered.
    def test_failed_send_attempts_do_not_flood_wave_failed(
        self, tmp_path: Path
    ) -> None:
        state = notify_telegram.NotifyState(tmp_path / "state.json")
        entries = [
            _make_entry(verdict="FAIL", task_id="7", wave_id=f"w-{i}")
            for i in range(50)
        ]
        statuses: list[tuple[str, str]] = []

        with patch("notify_telegram.send_message", return_value=None) as send:
            sent = notify_telegram.process_new_entries(
                entries, entries, state, now=1000.0, status_log=statuses
            )

        assert sent == []
        retry_loop_statuses = [
            status for event, status in statuses if event == "retry_loop"
        ]
        wave_failed_statuses = [
            status for event, status in statuses if event == "wave_failed"
        ]
        assert send.call_count == 1
        assert retry_loop_statuses == ["failed"]
        assert wave_failed_statuses == []
        assert state.is_rate_limited("wave_failed", now=1100.0) is False
        assert state.is_attempt_limited("wave_failed", now=1100.0) is False
        assert state.is_attempt_limited("retry_loop", now=1100.0) is True

    # Scenario: Many repeated suppressed statuses appear in one batch.
    # Expected: Status formatting compresses the repeated event names.
    def test_format_statuses_counts_repeated_events(self) -> None:
        statuses = [("wave_failed", "rate_limited")] * 49
        statuses.append(("retry_loop", "rate_limited"))

        formatted = notify_telegram._format_statuses(statuses, "rate_limited")

        assert formatted == "retry_loop,wave_failedx49"


# ── CLI tests ────────────────────────────────────────────────────────────


class TestCli:
    # Scenario: Top-level --help.
    # Expected: Exits cleanly and prints usage without treating --help as a subcommand.
    def test_top_level_help(self, capsys) -> None:
        notify_telegram.main(["--help"])

        captured = capsys.readouterr()
        assert "Usage: notify_telegram.py" in captured.out
        assert captured.err == ""

    # Scenario: No arguments.
    # Expected: Exits with code 2.
    def test_no_args(self) -> None:
        import pytest

        with pytest.raises(SystemExit, match="2"):
            notify_telegram.main([])

    # Scenario: Unknown subcommand.
    # Expected: Exits with code 2.
    def test_unknown_subcmd(self) -> None:
        import pytest

        with pytest.raises(SystemExit, match="2"):
            notify_telegram.main(["bogus"])

    # Scenario: send with no message.
    # Expected: Exits with code 2.
    def test_send_no_message(self) -> None:
        import pytest

        with pytest.raises(SystemExit, match="2"):
            notify_telegram.main(["send"])

    # Scenario: send --help.
    # Expected: Prints usage and does not make a Telegram API call.
    def test_send_help_does_not_send(self, capsys) -> None:
        with patch("notify_telegram.send_message") as send_mock:
            notify_telegram.main(["send", "--help"])

        send_mock.assert_not_called()
        captured = capsys.readouterr()
        assert "Usage: notify_telegram.py send" in captured.out
        assert captured.err == ""

    # Scenario: send receives an unsupported parse mode.
    # Expected: Exits before making a Telegram API call.
    def test_send_bad_parse_mode_exits(self, capsys) -> None:
        import pytest

        with patch("notify_telegram.send_message") as send_mock:
            with pytest.raises(SystemExit, match="2"):
                notify_telegram.main(["send", "hello", "--parse-mode", "ansi"])

        send_mock.assert_not_called()
        captured = capsys.readouterr()
        assert "--parse-mode must be html or markdown" in captured.err

    # Scenario: send receives --parse-mode without a value.
    # Expected: Exits closed with a specific parser error.
    def test_send_missing_parse_mode_value_exits(self, capsys) -> None:
        import pytest

        with patch("notify_telegram.send_message") as send_mock:
            with pytest.raises(SystemExit, match="2"):
                notify_telegram.main(["send", "hello", "--parse-mode"])

        send_mock.assert_not_called()
        captured = capsys.readouterr()
        assert "--parse-mode requires a value" in captured.err

    # Scenario: send receives an unknown trailing flag.
    # Expected: Exits closed instead of silently sending the message.
    def test_send_unknown_flag_exits(self, capsys) -> None:
        import pytest

        with patch("notify_telegram.send_message") as send_mock:
            with pytest.raises(SystemExit, match="2"):
                notify_telegram.main(["send", "hello", "--markdown"])

        send_mock.assert_not_called()
        captured = capsys.readouterr()
        assert "unknown send flag: --markdown" in captured.err

    # Scenario: send receives a valid parse mode.
    # Expected: Sends the message with the requested parse mode.
    def test_send_accepts_valid_parse_mode(self, capsys) -> None:
        with patch("notify_telegram.send_message", return_value={"ok": True}) as send:
            notify_telegram.main(["send", "hello", "--parse-mode", "markdown"])

        send.assert_called_once_with("hello", parse_mode="markdown")
        captured = capsys.readouterr()
        assert "message sent" in captured.err

    # Scenario: watch with no ledger path.
    # Expected: Exits with code 2.
    def test_watch_no_path(self) -> None:
        import pytest

        with pytest.raises(SystemExit, match="2"):
            notify_telegram.main(["watch"])

    # Scenario: watch --help.
    # Expected: Prints usage and does not start the watcher.
    def test_watch_help_does_not_start_daemon(self, capsys) -> None:
        with patch("notify_telegram.watch_loop") as watch_loop:
            notify_telegram.main(["watch", "--help"])

        watch_loop.assert_not_called()
        captured = capsys.readouterr()
        assert "Usage: notify_telegram.py watch" in captured.out
        assert captured.err == ""

    # Scenario: watch receives a flag where the ledger path belongs.
    # Expected: Exits closed instead of treating the flag as a ledger path.
    def test_watch_flag_without_path_exits(self, capsys) -> None:
        import pytest

        with patch("notify_telegram.watch_loop") as watch_loop:
            with pytest.raises(SystemExit, match="2"):
                notify_telegram.main(["watch", "--poll"])

        watch_loop.assert_not_called()
        captured = capsys.readouterr()
        assert "watch requires a ledger path before flags" in captured.err

    # Scenario: watch receives --state-dir without a value.
    # Expected: Exits closed instead of starting a daemon with the default state dir.
    def test_watch_missing_state_dir_value_exits(self, tmp_path: Path, capsys) -> None:
        import pytest

        ledger = tmp_path / "logs" / "waves.jsonl"
        with patch("notify_telegram.watch_loop") as watch_loop:
            with pytest.raises(SystemExit, match="2"):
                notify_telegram.main(["watch", str(ledger), "--state-dir"])

        watch_loop.assert_not_called()
        captured = capsys.readouterr()
        assert "--state-dir requires a value" in captured.err

    # Scenario: watch receives an unknown trailing flag.
    # Expected: Exits closed instead of silently ignoring a bad daemon invocation.
    def test_watch_unknown_flag_exits(self, tmp_path: Path, capsys) -> None:
        import pytest

        ledger = tmp_path / "logs" / "waves.jsonl"
        with patch("notify_telegram.watch_loop") as watch_loop:
            with pytest.raises(SystemExit, match="2"):
                notify_telegram.main(["watch", str(ledger), "--poll"])

        watch_loop.assert_not_called()
        captured = capsys.readouterr()
        assert "unknown watch flag: --poll" in captured.err

    # Scenario: watch receives a valid explicit state directory.
    # Expected: Starts the watcher with that exact notify-state path.
    def test_watch_accepts_state_dir(self, tmp_path: Path, capsys) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state_dir = tmp_path / "state"

        with patch("notify_telegram.watch_loop") as watch_loop:
            notify_telegram.main(["watch", str(ledger), "--state-dir", str(state_dir)])

        watch_loop.assert_called_once()
        called_ledger, called_state = watch_loop.call_args.args[:2]
        assert called_ledger == ledger
        assert called_state.path == state_dir / "notify-state.json"
        captured = capsys.readouterr()
        assert f"state dir {state_dir}" in captured.err

    # Scenario: watch is interrupted by the operator.
    # Expected: Persists state and exits with the conventional SIGINT status.
    def test_watch_keyboard_interrupt_exits_130(self, tmp_path: Path, capsys) -> None:
        import pytest

        ledger = tmp_path / "logs" / "waves.jsonl"
        state_dir = tmp_path / "state"

        with patch("notify_telegram.watch_loop", side_effect=KeyboardInterrupt):
            with pytest.raises(SystemExit) as exc_info:
                notify_telegram.main(
                    ["watch", str(ledger), "--state-dir", str(state_dir)]
                )

        captured = capsys.readouterr()
        assert exc_info.value.code == 130
        assert "notify: stopped" in captured.err
        assert (state_dir / "notify-state.json").is_file()

    # Scenario: health with no ledger path.
    # Expected: Exits with code 2.
    def test_health_no_path(self) -> None:
        import pytest

        with pytest.raises(SystemExit, match="2"):
            notify_telegram.main(["health"])

    # Scenario: health --help.
    # Expected: Prints usage and does not run a health probe against a fake ledger.
    def test_health_help_does_not_probe_fake_ledger(self, capsys) -> None:
        notify_telegram.main(["health", "--help"])

        captured = capsys.readouterr()
        assert "Usage: notify_telegram.py health" in captured.out
        assert "health status=" not in captured.out
        assert captured.err == ""

    # Scenario: health receives a flag where the ledger path belongs.
    # Expected: Exits closed instead of using the flag as a path.
    def test_health_flag_without_path_exits(self, capsys) -> None:
        import pytest

        with pytest.raises(SystemExit, match="2"):
            notify_telegram.main(["health", "--format", "json"])

        captured = capsys.readouterr()
        assert "health requires a ledger path before flags" in captured.err

    # Scenario: health receives a non-integer stale threshold.
    # Expected: Exits closed instead of silently using the default threshold.
    def test_health_bad_stale_seconds_exits(self, tmp_path: Path, capsys) -> None:
        import pytest

        ledger = tmp_path / "logs" / "waves.jsonl"
        _write_ledger(ledger, [])

        with pytest.raises(SystemExit, match="2"):
            notify_telegram.main(["health", str(ledger), "--stale-seconds", "soon"])

        captured = capsys.readouterr()
        assert "--stale-seconds must be an integer" in captured.err

    # Scenario: health receives a negative stale threshold.
    # Expected: Exits closed so a bad supervisor env var cannot force restarts.
    def test_health_negative_stale_seconds_exits(self, tmp_path: Path, capsys) -> None:
        import pytest

        ledger = tmp_path / "logs" / "waves.jsonl"
        _write_ledger(ledger, [])

        with pytest.raises(SystemExit, match="2"):
            notify_telegram.main(["health", str(ledger), "--stale-seconds", "-1"])

        captured = capsys.readouterr()
        assert "--stale-seconds must not be negative" in captured.err

    # Scenario: health receives an unsupported output format.
    # Expected: Exits closed so operator scripts notice the bad invocation.
    def test_health_bad_format_exits(self, tmp_path: Path, capsys) -> None:
        import pytest

        ledger = tmp_path / "logs" / "waves.jsonl"
        _write_ledger(ledger, [])

        with pytest.raises(SystemExit, match="2"):
            notify_telegram.main(["health", str(ledger), "--format", "yaml"])

        captured = capsys.readouterr()
        assert "--format must be text or json" in captured.err

    # Scenario: health receives an unknown flag.
    # Expected: Exits closed instead of ignoring a typo in the safety probe.
    def test_health_unknown_flag_exits(self, tmp_path: Path, capsys) -> None:
        import pytest

        ledger = tmp_path / "logs" / "waves.jsonl"
        _write_ledger(ledger, [])

        with pytest.raises(SystemExit, match="2"):
            notify_telegram.main(["health", str(ledger), "--stale-second", "1"])

        captured = capsys.readouterr()
        assert "unknown health flag: --stale-second" in captured.err

    # Scenario: health receives a flag that requires a value.
    # Expected: Exits closed with a specific parser error.
    def test_health_missing_flag_value_exits(self, tmp_path: Path, capsys) -> None:
        import pytest

        ledger = tmp_path / "logs" / "waves.jsonl"
        _write_ledger(ledger, [])

        for flag in (
            "--state-dir",
            "--log-file",
            "--pid-file",
            "--stale-seconds",
            "--format",
        ):
            with pytest.raises(SystemExit, match="2"):
                notify_telegram.main(["health", str(ledger), flag])

            captured = capsys.readouterr()
            assert f"{flag} requires a value" in captured.err

    # Scenario: test --help.
    # Expected: Prints usage and does not send a Telegram test notification.
    def test_test_help_does_not_send(self, capsys) -> None:
        with patch("notify_telegram.send_message") as send_mock:
            notify_telegram.main(["test", "--help"])

        send_mock.assert_not_called()
        captured = capsys.readouterr()
        assert "Usage: notify_telegram.py test" in captured.out
        assert captured.err == ""

    # Scenario: test receives an unexpected flag.
    # Expected: Exits before attempting a Telegram API call.
    def test_test_unknown_flag_exits(self, capsys) -> None:
        import pytest

        with patch("notify_telegram.send_message") as send_mock:
            with pytest.raises(SystemExit, match="2"):
                notify_telegram.main(["test", "--json"])

        send_mock.assert_not_called()
        captured = capsys.readouterr()
        assert "unknown test flag: --json" in captured.err


# ── Watch loop integration test ──────────────────────────────────────────


class TestWatchLoop:
    # Scenario: Watch loop processes new entries and stops after max_iterations.
    # Expected: State reflects processed entries.
    def test_watch_processes_entries(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state_path = tmp_path / "state" / "notify-state.json"
        state = notify_telegram.NotifyState(state_path)

        # Write one entry before starting
        _write_ledger(ledger, [_make_entry(verdict="PASS")])

        # Run one iteration of watch
        notify_telegram.watch_loop(ledger, state, poll_interval=0.01, max_iterations=1)

        assert state.last_line_count == 1

    # Scenario: Watch loop sees a new ledger line with no send-worthy event.
    # Expected: notifier.log still gets an activity line.
    def test_watch_logs_processed_lines(self, tmp_path: Path, capsys) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state_path = tmp_path / "state" / "notify-state.json"
        state = notify_telegram.NotifyState(state_path)
        _write_ledger(ledger, [_make_entry(verdict="PASS")])

        notify_telegram.watch_loop(ledger, state, poll_interval=0.01, max_iterations=1)

        captured = capsys.readouterr()
        assert "processed 1 new ledger line(s), 1 valid" in captured.err
        assert "sent=none" in captured.err
        assert "suppressed=none" in captured.err

    # Scenario: Watch loop sees the explicit scheduler STOP row emitted after
    # the idle threshold.
    # Expected: It sends a loop_stopped Telegram alert and logs the event class.
    def test_watch_idle_threshold_stop_sends_loop_stopped(
        self, tmp_path: Path, capsys
    ) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state_path = tmp_path / "state" / "notify-state.json"
        state = notify_telegram.NotifyState(state_path)
        _write_ledger(
            ledger,
            [
                _make_entry(
                    verdict="STOP",
                    failure_reason="routing:idle_threshold",
                    next_action="Loop stopped after 2 consecutive idle waves.",
                )
            ],
        )

        with (
            patch("notify_telegram.time.time", return_value=1000.0),
            patch("notify_telegram.send_message", return_value={"ok": True}) as send,
        ):
            notify_telegram.watch_loop(
                ledger,
                state,
                poll_interval=0.01,
                max_iterations=1,
            )

        captured = capsys.readouterr()
        payload = send.call_args.args[0]
        assert "Mainspring stopped" in payload
        assert "routing:idle_threshold" in payload
        assert "sent=loop_stopped" in captured.err
        assert "suppressed=none" in captured.err

    # Scenario: 50 failed waves arrive before the watcher wakes up.
    # Expected: It sends one wave_failed alert, compresses the 49 suppressed
    # duplicates into one operator log line, and records progress through the
    # whole batch.
    def test_watch_fifty_failures_do_not_flood_wave_failed(
        self, tmp_path: Path, capsys
    ) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state_path = tmp_path / "state" / "notify-state.json"
        state = notify_telegram.NotifyState(state_path)
        _write_ledger(
            ledger,
            [
                _make_entry(
                    verdict="FAIL",
                    task_id=f"task-{index}",
                    wave_id=f"failure-{index}",
                )
                for index in range(50)
            ],
        )

        with (
            patch("notify_telegram.time.time", return_value=1000.0),
            patch("notify_telegram.send_message", return_value={"ok": True}) as send,
        ):
            notify_telegram.watch_loop(
                ledger,
                state,
                poll_interval=0.01,
                max_iterations=1,
            )

        captured = capsys.readouterr()

        assert send.call_count == 1
        assert state.last_line_count == 50
        assert "processed 50 new ledger line(s), 50 valid" in captured.err
        assert "sent=wave_failed" in captured.err
        assert "suppressed=wave_failedx49" in captured.err
        assert "failed=none" in captured.err

    # Scenario: A project-specific watcher sees a failed Taskmaster wave.
    # Expected: The notification derives project name from the ledger root and
    # active tag from .taskmaster/state.json.
    def test_watch_failure_includes_project_and_taskmaster_tag(
        self, tmp_path: Path
    ) -> None:
        project = tmp_path / "client-app"
        ledger = project / ".mainspring" / "logs" / "waves.jsonl"
        state_path = project / ".mainspring" / "state" / "notify-state.json"
        taskmaster_state = project / ".taskmaster" / "state.json"
        taskmaster_state.parent.mkdir(parents=True)
        taskmaster_state.write_text('{"currentTag":"release"}', encoding="utf-8")
        state = notify_telegram.NotifyState(state_path)
        _write_ledger(
            ledger,
            [
                _make_entry(
                    verdict="FAIL",
                    task_id="4",
                    failure_reason="scope:violation",
                    writer="codex",
                    reviewer="codex",
                )
            ],
        )

        with (
            patch("notify_telegram.time.time", return_value=1000.0),
            patch("notify_telegram.send_message", return_value={"ok": True}) as send,
        ):
            notify_telegram.watch_loop(
                ledger,
                state,
                poll_interval=0.01,
                max_iterations=1,
            )

        payload = send.call_args.args[0]
        assert "Project: client-app" in payload
        assert f"Folder: {project}" in payload
        assert "Tag: release" in payload
        assert "Task: 4" in payload
        assert "Pair: codex+codex" in payload
        assert "Result: FAIL" in payload

    # Scenario: Three reviewer-unreachable rows arrive through the watched ledger.
    # Expected: The watcher sends exactly one retry_loop notification with
    # reviewer-restoration guidance and suppresses ordinary wave_failed noise.
    def test_watch_reviewer_outage_loop_emits_one_retry_loop(
        self, tmp_path: Path, capsys
    ) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state_path = tmp_path / "state" / "notify-state.json"
        state = notify_telegram.NotifyState(state_path)
        _write_ledger(
            ledger,
            [
                _make_entry(
                    verdict="FAIL",
                    task_id="review-gate-7",
                    wave_id=f"review-outage-{index}",
                    failure_reason="review:reviewer_unreachable",
                )
                for index in range(3)
            ],
        )

        with (
            patch("notify_telegram.time.time", return_value=1000.0),
            patch("notify_telegram.send_message", return_value={"ok": True}) as send,
        ):
            notify_telegram.watch_loop(
                ledger,
                state,
                poll_interval=0.01,
                max_iterations=1,
            )

        payloads = [call.args[0] for call in send.call_args_list]
        retry_loop_payloads = [
            payload for payload in payloads if "Reviewer outage loop" in payload
        ]
        captured = capsys.readouterr()

        assert len(retry_loop_payloads) == 1
        assert "Restore the reviewer engine" in retry_loop_payloads[0]
        assert "Pair: claude+codex" in retry_loop_payloads[0]
        assert "Result: RETRY_LOOP" in retry_loop_payloads[0]
        assert "Duration: 60s" in retry_loop_payloads[0]
        assert "do not mark the task blocked" in retry_loop_payloads[0]
        assert len(payloads) == 1
        assert state.last_line_count == 3
        assert "sent=retry_loop" in captured.err
        assert "suppressed=none" in captured.err

    # Scenario: Telegram sending is down while a watched failure batch arrives.
    # Expected: The watcher attempts the strongest event class once and persists
    # attempt throttling without claiming successful delivery.
    def test_watch_failed_sends_log_and_persist_attempt_throttle(
        self, tmp_path: Path, capsys
    ) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state_path = tmp_path / "state" / "notify-state.json"
        state = notify_telegram.NotifyState(state_path)
        _write_ledger(
            ledger,
            [
                _make_entry(verdict="FAIL", task_id="7", wave_id=f"outage-{index}")
                for index in range(3)
            ],
        )

        with (
            patch("notify_telegram.time.time", return_value=1000.0),
            patch("notify_telegram.send_message", return_value=None) as send,
        ):
            notify_telegram.watch_loop(
                ledger,
                state,
                poll_interval=0.01,
                max_iterations=1,
            )

        captured = capsys.readouterr()
        reloaded = notify_telegram.NotifyState(state_path)

        assert send.call_count == 1
        assert "failed=retry_loop" in captured.err
        assert "suppressed=none" in captured.err
        assert reloaded.is_rate_limited("wave_failed", now=1100.0) is False
        assert reloaded.is_attempt_limited("wave_failed", now=1100.0) is False
        assert reloaded.is_attempt_limited("retry_loop", now=1100.0) is True

    # Scenario: Telegram sending is still down after the watcher restarts and
    # the same event classes reappear inside the attempt-rate window.
    # Expected: Persisted last_attempt state suppresses new network attempts
    # without recording false delivery truth.
    def test_failed_send_attempt_throttle_survives_state_reload(
        self, tmp_path: Path
    ) -> None:
        state_path = tmp_path / "state" / "notify-state.json"
        state = notify_telegram.NotifyState(state_path)
        entries = [
            _make_entry(verdict="FAIL", task_id="7", wave_id=f"outage-{index}")
            for index in range(3)
        ]

        with (
            patch("notify_telegram.time.time", return_value=1000.0),
            patch("notify_telegram.send_message", return_value=None) as send,
        ):
            statuses: list[tuple[str, str]] = []
            notify_telegram.process_new_entries(
                entries, entries, state, now=1000.0, status_log=statuses
            )
            state.save()

        reloaded = notify_telegram.NotifyState(state_path)
        with patch("notify_telegram.send_message", return_value=None) as send_again:
            statuses_again: list[tuple[str, str]] = []
            sent = notify_telegram.process_new_entries(
                entries, entries, reloaded, now=1100.0, status_log=statuses_again
            )

        assert send.call_count == 1
        send_again.assert_not_called()
        assert sent == []
        assert ("retry_loop", "rate_limited") in statuses_again
        assert ("wave_failed", "rate_limited") not in statuses_again
        assert reloaded.is_rate_limited("wave_failed", now=1100.0) is False

    # Scenario: Ledger grows with malformed JSON while the daemon is watching.
    # Expected: The watcher records activity so health does not mistake bad rows
    # for a stuck daemon.
    def test_watch_growth_with_invalid_json_updates_last_activity_ts(
        self, tmp_path: Path
    ) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state_path = tmp_path / "state" / "notify-state.json"
        state = notify_telegram.NotifyState(state_path)
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        state.last_line_count = 1
        state.last_activity_ts = 100.0
        state.save()
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write("not-json\n")

        with patch("notify_telegram.time.time", return_value=200.0):
            notify_telegram.watch_loop(
                ledger,
                state,
                poll_interval=0.01,
                max_iterations=1,
            )

        assert state.last_line_count == 2
        assert state.last_activity_ts == 200.0

    # Scenario: Team is stale with no new lines for >30m.
    # Expected: team_stuck notification is attempted.
    def test_watch_stuck_wave_emits_team_stuck(self, tmp_path: Path, capsys) -> None:
        from datetime import datetime, timezone

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                fixed = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
                return fixed.astimezone(tz) if tz else fixed

        ledger = tmp_path / "logs" / "waves.jsonl"
        state_path = tmp_path / "state" / "notify-state.json"
        state = notify_telegram.NotifyState(state_path)
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        state.last_line_count = 1
        state.last_activity_ts = 100.0
        state.save()

        with (
            patch("notify_telegram.time.time", return_value=2000.0),
            patch("notify_telegram.send_message", return_value={"ok": True}) as send,
            patch("notify_telegram.datetime", FixedDateTime),
        ):
            notify_telegram.watch_loop(
                ledger,
                state,
                poll_interval=0.01,
                max_iterations=1,
            )

        captured = capsys.readouterr()
        payload = send.call_args.args[0]
        assert "Task: 42" in payload
        assert "Pair: claude+codex" in payload
        assert "Result: STUCK" in payload
        assert "Reason: no_new_wave_32m" in payload
        assert "Duration: 60s" in payload
        assert "team_stuck notification sent" in captured.err

    # Scenario: Watch loop detects new entries added between iterations.
    # Expected: Processes only the new entries.
    def test_watch_incremental(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state_path = tmp_path / "state" / "notify-state.json"
        state = notify_telegram.NotifyState(state_path)
        state.last_line_count = 0
        state.save()

        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        notify_telegram.watch_loop(ledger, state, poll_interval=0.01, max_iterations=1)
        assert state.last_line_count == 1

        # Append another entry
        with open(ledger, "a") as f:
            f.write(json.dumps(_make_entry(verdict="PASS", task_id="99")) + "\n")

        notify_telegram.watch_loop(ledger, state, poll_interval=0.01, max_iterations=1)
        assert state.last_line_count == 2

    # Scenario: Ledger is truncated below the persisted line count.
    # Expected: Watcher treats this as a reset and processes current lines.
    def test_watch_recovers_from_truncated_ledger(self, tmp_path: Path, capsys) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state_path = tmp_path / "state" / "notify-state.json"
        state = notify_telegram.NotifyState(state_path)
        state.last_line_count = 5
        _write_ledger(ledger, [_make_entry(verdict="PASS")])

        notify_telegram.watch_loop(ledger, state, poll_interval=0.01, max_iterations=1)

        captured = capsys.readouterr()
        assert "ledger line count reset from 5 to 1" in captured.err
        assert state.last_line_count == 1

    # Scenario: Watcher starts before any ledger processing.
    # Expected: It persists state immediately so health checks have a startup heartbeat.
    def test_watch_persists_startup_heartbeat(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state_path = tmp_path / "state" / "notify-state.json"
        state = notify_telegram.NotifyState(state_path)
        _write_ledger(ledger, [])

        notify_telegram.watch_loop(ledger, state, poll_interval=0.01, max_iterations=0)

        assert state_path.is_file()


# ── Watch health tests ───────────────────────────────────────────────────


class TestWatchHealth:
    # Scenario: State is caught up with the ledger.
    # Expected: Health is healthy with zero pending lines.
    def test_caught_up_is_healthy(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        state.last_line_count = 1
        state.last_activity_ts = 1000.0

        health = notify_telegram.check_watch_health(ledger, state, now=5000.0)

        assert health["status"] == "healthy"
        assert health["next_step"] == "none"
        assert health["pending_lines"] == 0

    # Scenario: notify-state.json has malformed numeric fields from corruption
    # or a partial manual edit.
    # Expected: Health does not crash; it coerces to safe defaults so the
    # wrapper/HUD can report a stale watcher when ledger lines are pending.
    def test_corrupt_numeric_state_is_restartable_stale(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state_path = tmp_path / "state" / "notify-state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {
                    "last_line_count": "not-a-count",
                    "last_activity_ts": "not-a-timestamp",
                }
            ),
            encoding="utf-8",
        )
        os.utime(state_path, (1000.0, 1000.0))
        state = notify_telegram.NotifyState(state_path)
        _write_ledger(ledger, [_make_entry(verdict="PASS")])

        health = notify_telegram.check_watch_health(
            ledger, state, now=5000.0, stale_seconds=3600
        )

        assert health["status"] == "stale"
        assert health["reason"] == "pending_without_activity_stale"
        assert health["next_step"] == "restart-notifier-daemon"
        assert health["last_line_count"] == 0
        assert health["last_activity_ts"] == 0.0
        assert health["pending_lines"] == 1

    # Scenario: notify-state.json is valid JSON but not a mapping.
    # Expected: Health coerces it to empty state and reports restartable staleness.
    def test_non_object_state_file_is_restartable_stale(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state_path = tmp_path / "state" / "notify-state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text('"corrupt-root"', encoding="utf-8")
        os.utime(state_path, (1000.0, 1000.0))
        state = notify_telegram.NotifyState(state_path)
        _write_ledger(ledger, [_make_entry(verdict="PASS")])

        health = notify_telegram.check_watch_health(
            ledger, state, now=5000.0, stale_seconds=3600
        )

        assert health["status"] == "stale"
        assert health["reason"] == "pending_without_activity_stale"
        assert health["last_line_count"] == 0
        assert health["pending_lines"] == 1

    # Scenario: State/log are caught up but the requested pid file is missing.
    # Expected: Health is stale so direct probes catch a dead daemon before new waves.
    def test_pid_file_missing_is_stale(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        pid_path = tmp_path / "state" / "notifier.pid"
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        state.last_line_count = 1
        state.last_activity_ts = 1000.0

        health = notify_telegram.check_watch_health(
            ledger, state, now=5000.0, pid_path=pid_path
        )

        assert health["status"] == "stale"
        assert health["reason"] == "daemon_pid_missing"
        assert health["next_step"] == "restart-notifier-daemon"
        assert health["pid_exists"] is False
        assert health["daemon_pid"] is None

    # Scenario: State/log are caught up but the pid file points at no process.
    # Expected: Health is stale with a process-specific reason.
    def test_dead_pid_file_is_stale(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        pid_path = tmp_path / "state" / "notifier.pid"
        pid_path.parent.mkdir(parents=True)
        pid_path.write_text("999999999", encoding="utf-8")
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        state.last_line_count = 1
        state.last_activity_ts = 1000.0

        health = notify_telegram.check_watch_health(
            ledger, state, now=5000.0, pid_path=pid_path
        )

        assert health["status"] == "stale"
        assert health["reason"] == "daemon_pid_not_running"
        assert health["daemon_pid"] == 999999999
        assert health["daemon_pid_running"] is False

    # Scenario: State/log are caught up and pid file points at the test process.
    # Expected: Health remains healthy and reports process truth.
    def test_running_pid_file_keeps_health_healthy(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        pid_path = tmp_path / "state" / "notifier.pid"
        pid_path.parent.mkdir(parents=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        state.last_line_count = 1
        state.last_activity_ts = 1000.0

        health = notify_telegram.check_watch_health(
            ledger, state, now=5000.0, pid_path=pid_path
        )

        assert health["status"] == "healthy"
        assert health["reason"] == "caught_up"
        assert health["daemon_pid"] == os.getpid()
        assert health["daemon_pid_running"] is True

    # Scenario: State is caught up and notifier.log has recent processed proof.
    # Expected: Health stays healthy and reports the processed-log timestamp.
    def test_recent_processed_log_keeps_caught_up_healthy(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        log_path = tmp_path / "logs" / "notifier.log"
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        log_path.write_text(
            "notify: 1970-01-01T01:21:40Z processed 1 new ledger line(s), 1 valid\n",
            encoding="utf-8",
        )
        os.utime(ledger, (4900.0, 4900.0))
        state.last_line_count = 1
        state.last_activity_ts = 4900.0

        health = notify_telegram.check_watch_health(
            ledger, state, now=5000.0, stale_seconds=3600, log_path=log_path
        )

        assert health["status"] == "healthy"
        assert health["reason"] == "caught_up"
        assert health["last_processed_log_ts"] == 4900.0
        assert health["seconds_since_log_activity"] == 100.0

    # Scenario: State is caught up but the operator-visible notifier log is old
    # while the ledger file has newer wave activity.
    # Expected: Health goes stale so the wrapper/HUD do not trust silent state.
    def test_old_processed_log_with_newer_ledger_is_stale(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        log_path = tmp_path / "logs" / "notifier.log"
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        log_path.write_text(
            "notify: 1970-01-01T00:16:40Z processed 1 new ledger line(s), 1 valid\n",
            encoding="utf-8",
        )
        os.utime(ledger, (5000.0, 5000.0))
        state.last_line_count = 1
        state.last_activity_ts = 5000.0

        health = notify_telegram.check_watch_health(
            ledger, state, now=5000.0, stale_seconds=3600, log_path=log_path
        )

        assert health["status"] == "stale"
        assert health["reason"] == "notifier_log_stale"
        assert health["last_processed_log_ts"] == 1000.0
        assert health["seconds_since_log_activity"] == 4000.0

    # Scenario: State is caught up but notifier.log has not produced its first
    # processed activity line yet.
    # Expected: Health reports startup/warmup instead of forcing a restart loop.
    def test_missing_processed_log_activity_is_warming_up(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        log_path = tmp_path / "logs" / "notifier.log"
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        log_path.write_text("notify: watching waves.jsonl\n", encoding="utf-8")
        state.last_line_count = 1
        state.last_activity_ts = 1000.0

        health = notify_telegram.check_watch_health(
            ledger, state, now=1100.0, log_path=log_path
        )

        assert health["status"] == "starting"
        assert health["reason"] == "notifier_log_warming_up"
        assert health["next_step"] == "wait-for-heartbeat"

    # Scenario: State is caught up but notifier.log has no processed activity
    # line past the stale threshold.
    # Expected: Health is stale because the warmup grace has expired.
    def test_missing_processed_log_activity_ages_to_stale(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        log_path = tmp_path / "logs" / "notifier.log"
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        log_path.write_text("notify: watching waves.jsonl\n", encoding="utf-8")
        state.last_line_count = 1
        state.last_activity_ts = 1000.0

        health = notify_telegram.check_watch_health(
            ledger, state, now=5000.0, stale_seconds=3600, log_path=log_path
        )

        assert health["status"] == "stale"
        assert health["reason"] == "notifier_log_no_processed_activity"

    # Scenario: State is caught up but notifier.log has not been created yet.
    # Expected: Health uses the same warmup grace as a log with no processed line.
    def test_missing_log_file_is_warming_up(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        log_path = tmp_path / "logs" / "notifier.log"
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        state.last_line_count = 1
        state.last_activity_ts = 1000.0

        health = notify_telegram.check_watch_health(
            ledger, state, now=1100.0, log_path=log_path
        )

        assert health["status"] == "starting"
        assert health["reason"] == "notifier_log_warming_up"

    # Scenario: State is caught up but notifier.log is still missing after the
    # stale threshold.
    # Expected: Health is stale so the next wave boundary can restart it.
    def test_missing_log_file_ages_to_stale(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        log_path = tmp_path / "logs" / "notifier.log"
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        state.last_line_count = 1
        state.last_activity_ts = 1000.0

        health = notify_telegram.check_watch_health(
            ledger, state, now=5000.0, stale_seconds=3600, log_path=log_path
        )

        assert health["status"] == "stale"
        assert health["reason"] == "notifier_log_missing"

    # Scenario: Ledger has new lines and no prior activity timestamp yet.
    # Expected: Health reports starting, avoiding immediate restart loops.
    def test_pending_without_activity_is_starting(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])

        health = notify_telegram.check_watch_health(ledger, state, now=5000.0)

        assert health["status"] == "starting"
        assert health["reason"] == "pending_without_activity"

    # Scenario: Ledger has pending lines, no activity, and old watcher state.
    # Expected: Health becomes stale instead of staying "starting" forever.
    def test_pending_without_activity_with_old_state_is_stale(
        self, tmp_path: Path
    ) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        state.last_line_count = 0
        state.save()
        os.utime(state.path, (1000.0, 1000.0))

        health = notify_telegram.check_watch_health(
            ledger, state, now=5000.0, stale_seconds=3600
        )

        assert health["status"] == "stale"
        assert health["reason"] == "pending_without_activity_stale"
        assert health["pending_lines"] == 1
        assert health["seconds_since_state_write"] == 4000.0

    # Scenario: Ledger has pending lines and no persisted heartbeat file.
    # Expected: Health falls back to ledger age and becomes stale after the threshold.
    def test_pending_without_activity_without_state_file_uses_ledger_age(
        self, tmp_path: Path
    ) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        os.utime(ledger, (1000.0, 1000.0))

        health = notify_telegram.check_watch_health(
            ledger, state, now=5000.0, stale_seconds=3600
        )

        assert health["status"] == "stale"
        assert health["reason"] == "pending_without_activity_stale"
        assert health["pending_lines"] == 1
        assert health["seconds_since_state_write"] is None
        assert health["seconds_since_ledger_write"] == 4000.0

    # Scenario: Ledger has pending lines and the watcher has been inactive too long.
    # Expected: Health is stale so the shell wrapper can restart it.
    def test_pending_lines_with_old_activity_is_stale(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(
            ledger,
            [
                _make_entry(verdict="PASS", wave_id="w1"),
                _make_entry(verdict="PASS", wave_id="w2"),
            ],
        )
        state.last_line_count = 1
        state.last_activity_ts = 1000.0

        health = notify_telegram.check_watch_health(
            ledger, state, now=5000.0, stale_seconds=3600
        )

        assert health["status"] == "stale"
        assert health["reason"] == "pending_lines_stale"
        assert health["pending_lines"] == 1

    # Scenario: Ledger line count is lower than persisted state after rotation/truncate.
    # Expected: Health is stale and reports line-count reset.
    def test_line_count_reset_is_stale(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"
        state = notify_telegram.NotifyState(tmp_path / "state" / "notify-state.json")
        _write_ledger(ledger, [_make_entry(verdict="PASS")])
        state.last_line_count = 3
        state.last_activity_ts = 1000.0

        health = notify_telegram.check_watch_health(ledger, state, now=1100.0)

        assert health["status"] == "stale"
        assert health["reason"] == "ledger_line_count_reset"
        assert health["next_step"] == "review-ledger-rotation"

    # Scenario: CLI health sees stale state.
    # Expected: Exits with code 2 and prints JSON health.
    def test_health_cli_stale_json(self, tmp_path: Path, capsys) -> None:
        import pytest

        ledger = tmp_path / "logs" / "waves.jsonl"
        state_dir = tmp_path / "state"
        state = notify_telegram.NotifyState(state_dir / "notify-state.json")
        _write_ledger(
            ledger,
            [
                _make_entry(verdict="PASS", wave_id="w1"),
                _make_entry(verdict="PASS", wave_id="w2"),
            ],
        )
        state.last_line_count = 1
        state.last_activity_ts = 1.0
        state.save()

        with pytest.raises(SystemExit, match="2"):
            notify_telegram.main(
                [
                    "health",
                    str(ledger),
                    "--state-dir",
                    str(state_dir),
                    "--stale-seconds",
                    "1",
                    "--format",
                    "json",
                ]
            )

        captured = capsys.readouterr()
        assert '"status": "stale"' in captured.out
        assert '"next_step": "restart-notifier-daemon"' in captured.out

    # Scenario: CLI health text output sees stale state.
    # Expected: It includes the recovery action without requiring JSON parsing.
    def test_health_cli_text_includes_next_step(self, tmp_path: Path, capsys) -> None:
        import pytest

        ledger = tmp_path / "logs" / "waves.jsonl"
        state_dir = tmp_path / "state"
        state = notify_telegram.NotifyState(state_dir / "notify-state.json")
        _write_ledger(
            ledger,
            [
                _make_entry(verdict="PASS", wave_id="w1"),
                _make_entry(verdict="PASS", wave_id="w2"),
            ],
        )
        state.last_line_count = 1
        state.last_activity_ts = 1.0
        state.save()

        with pytest.raises(SystemExit, match="2"):
            notify_telegram.main(
                [
                    "health",
                    str(ledger),
                    "--state-dir",
                    str(state_dir),
                    "--stale-seconds",
                    "1",
                ]
            )

        captured = capsys.readouterr()
        assert "status=stale" in captured.out
        assert "next_step=restart-notifier-daemon" in captured.out

    # Scenario: Static health statuses that are owned by HUD still use the
    # canonical recovery vocabulary from notify_telegram.py.
    # Expected: Operators get specific setup actions, not just status labels.
    def test_static_status_guidance(self) -> None:
        disabled = notify_telegram.health_next_step(
            "disabled",
            "MAINSPRING_NOTIFY_ENABLED not set",
        )
        unconfigured = notify_telegram.health_next_step(
            "unconfigured",
            "telegram token/chat id missing",
        )

        assert disabled["next_step"] == "enable-notifications"
        assert "MAINSPRING_NOTIFY_ENABLED=1" in disabled["next_step_message"]
        assert unconfigured["next_step"] == "configure-telegram"
        assert "mainspring notify-test" in unconfigured["next_step_message"]
        stale = notify_telegram.health_next_step("stale", "daemon_pid_missing")
        assert stale["next_step"] == "restart-notifier-daemon"
        assert "mainspring notify-restart" in stale["next_step_message"]
        assert "MAINSPRING_NOTIFY_ENABLED=1" in stale["next_step_message"]
        assert "next enabled wave" not in stale["next_step_message"]

    # Scenario: Operator health is requested while Telegram monitoring is off.
    # Expected: It reports disabled status with setup guidance, not stale daemon noise.
    def test_operator_health_reports_disabled(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"

        with patch.dict(os.environ, {}, clear=True):
            health = notify_telegram.operator_health(
                ledger,
                state_dir=tmp_path / "state",
                log_path=tmp_path / "logs" / "notifier.log",
                pid_path=tmp_path / "state" / "notifier.pid",
            )

        assert health["status"] == "disabled"
        assert health["enabled"] is False
        assert health["configured"] is False
        assert health["next_step"] == "enable-notifications"

    # Scenario: Operator health is enabled but credentials are absent.
    # Expected: It reports configuration guidance before inspecting daemon state.
    def test_operator_health_reports_unconfigured(self, tmp_path: Path) -> None:
        ledger = tmp_path / "logs" / "waves.jsonl"

        with patch.dict(os.environ, {"MAINSPRING_NOTIFY_ENABLED": "1"}, clear=True):
            health = notify_telegram.operator_health(
                ledger,
                state_dir=tmp_path / "state",
                log_path=tmp_path / "logs" / "notifier.log",
                pid_path=tmp_path / "state" / "notifier.pid",
            )

        assert health["status"] == "unconfigured"
        assert health["enabled"] is True
        assert health["configured"] is False
        assert health["next_step"] == "configure-telegram"

    # Scenario: Top-level operator-health CLI is enabled without Telegram credentials.
    # Expected: It exits 1 and prints unconfigured recovery guidance.
    def test_operator_health_cli_unconfigured_exits_1(
        self, tmp_path: Path, capsys
    ) -> None:
        import pytest

        ledger = tmp_path / "logs" / "waves.jsonl"

        with patch.dict(os.environ, {"MAINSPRING_NOTIFY_ENABLED": "1"}, clear=True):
            with pytest.raises(SystemExit, match="1"):
                notify_telegram.main(
                    [
                        "operator-health",
                        str(ledger),
                        "--state-dir",
                        str(tmp_path / "state"),
                    ]
                )

        captured = capsys.readouterr()
        assert "status=unconfigured" in captured.out
        assert "next_step=configure-telegram" in captured.out
        assert "mainspring notify-test" in captured.out

    # Scenario: Top-level operator-health CLI sees stale enabled daemon state.
    # Expected: It exits 2 and emits JSON with the recovery next step.
    def test_operator_health_cli_stale_json(self, tmp_path: Path, capsys) -> None:
        import pytest

        ledger = tmp_path / "logs" / "waves.jsonl"
        state_dir = tmp_path / "state"
        state = notify_telegram.NotifyState(state_dir / "notify-state.json")
        _write_ledger(
            ledger,
            [
                _make_entry(verdict="PASS", wave_id="w1"),
                _make_entry(verdict="PASS", wave_id="w2"),
            ],
        )
        state.last_line_count = 1
        state.last_activity_ts = 1.0
        state.save()

        with patch.dict(
            os.environ,
            {
                "MAINSPRING_NOTIFY_ENABLED": "1",
                "MAINSPRING_TELEGRAM_BOT_TOKEN": "token",
                "MAINSPRING_TELEGRAM_CHAT_ID": "123",
            },
            clear=True,
        ):
            with pytest.raises(SystemExit, match="2"):
                notify_telegram.main(
                    [
                        "operator-health",
                        str(ledger),
                        "--state-dir",
                        str(state_dir),
                        "--stale-seconds",
                        "1",
                        "--format",
                        "json",
                    ]
                )

        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["status"] == "stale"
        assert payload["next_step"] == "restart-notifier-daemon"
        assert payload["enabled"] is True
        assert payload["configured"] is True
