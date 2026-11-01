# SPDX-License-Identifier: Apache-2.0
"""Tests for metrics.py — Mainspring JSONL metrics reader."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import metrics


def _make_entry(
    *,
    wave_id: str = "w1",
    task_id: str = "42",
    writer: str = "claude",
    reviewer: str = "codex",
    verdict: str = "PASS",
    exit_code: int = 0,
    duration: int = 60,
    ts: str | None = None,
    failure_reason: str = "",
    failure_reason_class: str = "",
    chapter_delta: str | None = None,
    topology: str = "solo",
    changed_files: list[str] | None = None,
    cost_usd: float | None = None,
    models: dict[str, str] | None = None,
) -> dict:
    if ts is None:
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    entry: dict = {
        "timestamp": ts,
        "wave_id": wave_id,
        "task_id": task_id,
        "topology": topology,
        "engines": {"writer": writer, "reviewer": reviewer},
        "verdict": verdict,
        "exit_code": exit_code,
        "duration_seconds": duration,
        "changed_files": changed_files or [],
        "failure_reason": failure_reason,
        "failure_reason_class": failure_reason_class,
    }
    if models is not None:
        entry["models"] = models
    if chapter_delta is not None:
        entry["chapter_delta"] = chapter_delta
    if cost_usd is not None:
        entry["cost_usd"] = cost_usd
    return entry


def _write_ledger(path: Path, entries: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


def test_metrics_ignore_non_object_json_rows(tmp_path: Path) -> None:
    entries = [
        _make_entry(wave_id="valid-pass"),
        _make_entry(wave_id="valid-fail", writer="ollama", verdict="FAIL", exit_code=1),
    ]
    ledger = tmp_path / "synthetic.jsonl"
    ledger.write_text(
        "\n".join(
            [
                json.dumps(entries[0]),
                "null",
                "[]",
                '[{"verdict": "PASS"}]',
                "42",
                "true",
                '"non-wave text"',
                "malformed JSON",
                json.dumps(entries[1]),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert metrics.read_ledger(ledger) == entries
    for extra in ([], ["--routing"]):
        result = subprocess.run(
            [
                sys.executable,
                str(HERE.parent / "metrics.py"),
                str(ledger),
                "--format",
                "json",
                *extra,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        if extra:
            assert payload["pass_rate_by_pair"]["claude+codex"]["pass"] == 1
            assert payload["pass_rate_by_pair"]["ollama+codex"]["pass"] == 0
        else:
            assert payload["total_waves"] == 2
            assert payload["success_rate"] == 50.0


def test_metrics_missing_exit_code_does_not_count_as_success(tmp_path: Path) -> None:
    partial = _make_entry(wave_id="missing-exit")
    del partial["exit_code"]
    entries = [_make_entry(wave_id="observed-success"), partial]
    summary = metrics.compute_metrics(entries)
    routing = metrics.compute_routing_metrics(entries)

    assert summary["total_waves"] == 2
    assert summary["success_rate"] == 50.0
    assert summary["pass_rate_per_pair"]["claude+codex"] == 50.0
    assert routing["pass_rate_by_pair"]["claude+codex"]["pass"] == 1
    assert routing["pass_rate_by_topology"]["solo"]["pass_rate"] == 50.0

    ledger = tmp_path / "synthetic-partial.jsonl"
    _write_ledger(ledger, entries)
    for extra in ([], ["--routing"]):
        result = subprocess.run(
            [
                sys.executable,
                str(HERE.parent / "metrics.py"),
                str(ledger),
                "--format",
                "json",
                *extra,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        if extra:
            assert payload["pass_rate_by_pair"]["claude+codex"]["pass_rate"] == 50.0
        else:
            assert payload["success_rate"] == 50.0


@pytest.mark.parametrize(
    ("exit_status", "successful"),
    [
        (0, True),
        (1, False),
        (-1, False),
        (False, False),
        (True, False),
        (None, False),
        ("0", False),
        ("1", False),
        (0.0, False),
        (-0.0, False),
        (1.0, False),
        (-1.0, False),
        (0.5, False),
    ],
)
def test_metrics_success_requires_integer_exit_status(
    exit_status: object, successful: bool
) -> None:
    typed = _make_entry(wave_id="typed-status")
    typed["exit_code"] = exit_status
    entries = [_make_entry(wave_id="known-success"), typed]
    expected_passes = 2 if successful else 1
    expected_rate = 100.0 if successful else 50.0

    summary = metrics.compute_metrics(entries)
    routing = metrics.compute_routing_metrics(entries)

    assert summary["total_waves"] == 2
    assert summary["success_rate"] == expected_rate
    assert summary["pass_rate_per_pair"]["claude+codex"] == expected_rate
    assert routing["pass_rate_by_pair"]["claude+codex"]["total"] == 2
    assert routing["pass_rate_by_pair"]["claude+codex"]["pass"] == expected_passes
    assert routing["pass_rate_by_topology"]["solo"]["pass_rate"] == expected_rate


def test_metrics_time_filter_skips_unzoned_row_timestamps(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    zoned = _make_entry(wave_id="utc-z", ts=now.isoformat().replace("+00:00", "Z"))
    offset = _make_entry(
        wave_id="explicit-offset",
        ts=now.astimezone(timezone(timedelta(hours=2))).isoformat(),
        verdict="FAIL",
        exit_code=1,
        duration=120,
    )
    entries = [
        zoned,
        _make_entry(wave_id="naive", ts=now.replace(tzinfo=None).isoformat()),
        _make_entry(wave_id="date-only", ts=now.date().isoformat()),
        _make_entry(wave_id="invalid", ts="not-a-date"),
        offset,
    ]

    assert metrics.filter_entries(entries, days=7) == [zoned, offset]
    assert metrics.filter_entries(entries, since=now.date().isoformat()) == [
        zoned,
        offset,
    ]
    assert metrics.filter_entries(entries) == entries

    ledger = tmp_path / "synthetic-timezones.jsonl"
    _write_ledger(ledger, entries)
    for extra in ([], ["--routing"]):
        result = subprocess.run(
            [
                sys.executable,
                str(HERE.parent / "metrics.py"),
                str(ledger),
                "--format",
                "json",
                *extra,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        if extra:
            assert payload["pass_rate_by_pair"]["claude+codex"]["total"] == 2
            assert payload["mean_duration_by_task_class"]["unknown"] == 90.0
        else:
            assert payload["total_waves"] == 2
            assert payload["mean_duration_s"] == 90.0


# ── compute_metrics ────────────────────────────────────────────────────


# Scenario: Empty entries.
# Expected: all zeros.
def test_compute_metrics_empty() -> None:
    m = metrics.compute_metrics([])
    assert m["total_waves"] == 0
    assert m["success_rate"] == 0.0
    assert m["mean_duration_s"] == 0.0
    assert m["top_stuck_tasks"] == []
    assert m["pass_rate_per_pair"] == {}


# Scenario: All passing waves.
# Expected: 100% success rate.
def test_compute_metrics_all_pass() -> None:
    entries = [_make_entry(wave_id=f"w{i}") for i in range(5)]
    m = metrics.compute_metrics(entries)
    assert m["total_waves"] == 5
    assert m["success_rate"] == 100.0
    assert m["mean_duration_s"] == 60.0
    assert m["pass_rate_per_pair"]["claude+codex"] == 100.0


# Scenario: Ledger rows use PRD canonical fields instead of legacy aliases.
# Expected: Metrics still compute pair, timestamp, duration, and model truth.
def test_canonical_ledger_fields() -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    entries = [
        {
            "ts": now,
            "wave_id": "canonical",
            "task_id": "42",
            "topology": "solo",
            "engine": "codex",
            "review_engine": "claude",
            "pair": "codex+claude",
            "model": "gpt-5.5",
            "review_model": "opus",
            "verdict": "PASS",
            "exit_code": 0,
            "duration_s": 42,
            "changed_files": ["py/notify_telegram.py"],
            "chapter_delta": "+2",
            "cost_usd": 1.0,
        }
    ]

    filtered = metrics.filter_entries(entries, days=1, pair="codex+claude")
    summary = metrics.compute_metrics(filtered)
    routing = metrics.compute_routing_metrics(filtered)

    assert len(filtered) == 1
    assert summary["mean_duration_s"] == 42.0
    assert summary["pass_rate_per_pair"] == {"codex+claude": 100.0}
    assert summary["top_expensive_waves"][0]["duration_s"] == 42.0
    assert routing["chapter_delta_per_dollar_14d"]["codex+claude"]["models"] == [
        "gpt-5.5",
        "opus",
    ]


# Scenario: Mixed pass/fail waves.
# Expected: correct success rate.
def test_compute_metrics_mixed() -> None:
    entries = [
        _make_entry(wave_id="w1", verdict="PASS"),
        _make_entry(wave_id="w2", verdict="FAIL"),
        _make_entry(wave_id="w3", verdict="PASS"),
        _make_entry(wave_id="w4", verdict="FAIL", exit_code=1),
    ]
    m = metrics.compute_metrics(entries)
    assert m["total_waves"] == 4
    assert m["success_rate"] == 50.0


# Scenario: Top stuck tasks — 3+ consecutive fails on same task.
# Expected: task appears in stuck list.
def test_compute_metrics_stuck_tasks() -> None:
    entries = [
        _make_entry(wave_id="w1", task_id="99", verdict="FAIL"),
        _make_entry(wave_id="w2", task_id="99", verdict="FAIL"),
        _make_entry(wave_id="w3", task_id="99", verdict="FAIL"),
        _make_entry(wave_id="w4", task_id="99", verdict="FAIL"),
        _make_entry(wave_id="w5", task_id="10", verdict="PASS"),
    ]
    m = metrics.compute_metrics(entries)
    assert len(m["top_stuck_tasks"]) == 1
    assert m["top_stuck_tasks"][0]["task_id"] == "99"
    assert m["top_stuck_tasks"][0]["consecutive_fails"] >= 3


# Scenario: Chapter delta per pair.
# Expected: mean is computed correctly.
def test_compute_metrics_chapter_delta() -> None:
    entries = [
        _make_entry(wave_id="w1", chapter_delta="+40"),
        _make_entry(wave_id="w2", chapter_delta="+20"),
        _make_entry(
            wave_id="w3", chapter_delta="-10", writer="codex", reviewer="codex"
        ),
    ]
    m = metrics.compute_metrics(entries)
    assert m["chapter_delta_per_pair"]["claude+codex"] == 30.0
    assert m["chapter_delta_per_pair"]["codex+codex"] == -10.0


# Scenario: Top expensive waves sorted by duration.
# Expected: longest duration first.
def test_compute_metrics_expensive_waves() -> None:
    entries = [
        _make_entry(wave_id="fast", duration=10),
        _make_entry(wave_id="slow", duration=600),
        _make_entry(wave_id="mid", duration=120),
    ]
    m = metrics.compute_metrics(entries)
    assert m["top_expensive_waves"][0]["wave_id"] == "slow"
    assert m["top_expensive_waves"][1]["wave_id"] == "mid"
    assert m["top_expensive_waves"][2]["wave_id"] == "fast"


# Scenario: Pass rate per pair with multiple pairs.
# Expected: each pair gets its own rate.
def test_compute_metrics_pass_rate_per_pair() -> None:
    entries = [
        _make_entry(wave_id="w1", writer="claude", reviewer="codex", verdict="PASS"),
        _make_entry(wave_id="w2", writer="claude", reviewer="codex", verdict="FAIL"),
        _make_entry(wave_id="w3", writer="codex", reviewer="codex", verdict="PASS"),
    ]
    m = metrics.compute_metrics(entries)
    assert m["pass_rate_per_pair"]["claude+codex"] == 50.0
    assert m["pass_rate_per_pair"]["codex+codex"] == 100.0


# ── filter_entries ─────────────────────────────────────────────────────


# Scenario: Filter by days.
# Expected: only recent entries returned.
def test_filter_by_days() -> None:
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    new_ts = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    entries = [
        _make_entry(wave_id="old", ts=old_ts),
        _make_entry(wave_id="new", ts=new_ts),
    ]
    filtered = metrics.filter_entries(entries, days=7)
    assert len(filtered) == 1
    assert filtered[0]["wave_id"] == "new"


# Scenario: Filter by pair.
# Expected: only matching pair returned.
def test_filter_by_pair() -> None:
    entries = [
        _make_entry(wave_id="w1", writer="claude", reviewer="codex"),
        _make_entry(wave_id="w2", writer="codex", reviewer="codex"),
    ]
    filtered = metrics.filter_entries(entries, pair="codex+codex")
    assert len(filtered) == 1
    assert filtered[0]["wave_id"] == "w2"


def test_filter_helpers_accept_invalid_timestamps_and_fallback_shapes() -> None:
    entries = [
        _make_entry(wave_id="missing-ts", ts=""),
        _make_entry(wave_id="bad-ts", ts="not-a-date"),
        _make_entry(wave_id="good", ts="2026-05-04T10:00:00Z"),
    ]

    assert metrics._parse_timestamp({"timestamp": ""}) is None
    assert metrics._parse_timestamp({"timestamp": "not-a-date"}) is None
    assert metrics._duration_s({"duration_seconds": "bad"}) == 0.0
    assert metrics._wave_cost_usd({"usage": {"total_cost_usd": "0.25"}}) == 0.25
    assert (
        metrics._wave_cost_usd({"cost_usd": "-1", "usage": {"cost_usd": "bad"}}) is None
    )
    assert metrics._entry_models({"model": "gpt", "review_model": " opus "}) == [
        "gpt",
        "opus",
    ]
    assert metrics._task_class({"selected_lane": "maintenance"}) == "maintenance"
    assert metrics._task_class({"changed_files": ["db/migrations/001.sql"]}) == (
        "migration"
    )
    assert metrics._task_class({"changed_files": ["scripts/release.sh"]}) == "src"

    assert metrics.filter_entries(entries, since="not-a-date") == entries
    filtered = metrics.filter_entries(entries, since="2026-05-04")
    assert [entry["wave_id"] for entry in filtered] == ["good"]


# ── format_text ────────────────────────────────────────────────────────


# Scenario: Format text output.
# Expected: contains key headings.
def test_format_text() -> None:
    m = metrics.compute_metrics([_make_entry()])
    text = metrics.format_text(m)
    assert "Total waves:" in text
    assert "Success rate:" in text
    assert "Mean duration:" in text
    assert "Pass rate per pair:" in text


def test_format_text_includes_optional_sections() -> None:
    entries = [
        _make_entry(wave_id="fail-1", task_id="7", verdict="FAIL", duration=10),
        _make_entry(wave_id="fail-2", task_id="7", verdict="FAIL", duration=20),
        _make_entry(
            wave_id="fail-3",
            task_id="7",
            verdict="FAIL",
            duration=30,
            chapter_delta="-2",
        ),
        _make_entry(wave_id="pass", task_id="", duration=120, chapter_delta="+8"),
    ]

    text = metrics.format_text(metrics.compute_metrics(entries))

    assert "Top stuck tasks" in text
    assert "task 7: 3 consecutive fails" in text
    assert "Mean chapter delta per pair:" in text
    assert "claude+codex: +3.0" in text
    assert "Top 10 most expensive waves:" in text
    assert "pass task=none pair=claude+codex 120.0s verdict=PASS" in text


# ── routing metrics ────────────────────────────────────────────────────


def test_compute_routing_metrics() -> None:
    entries = [
        _make_entry(
            wave_id="w1",
            writer="claude",
            reviewer="codex",
            topology="solo",
            duration=60,
            changed_files=["docs/prd.md"],
            chapter_delta="+10",
            cost_usd=2.0,
            models={"writer": "opus", "reviewer": "gpt-5.5"},
        ),
        _make_entry(
            wave_id="w2",
            writer="claude",
            reviewer="codex",
            topology="solo",
            verdict="FAIL",
            duration=120,
            changed_files=["src/App.tsx"],
            failure_reason="review:gate_failed",
        ),
        _make_entry(
            wave_id="w3",
            writer="codex",
            reviewer="codex",
            topology="team",
            verdict="FAIL",
            duration=30,
            changed_files=["tests/foo.test.ts"],
            failure_reason_class="review:gate_failed",
        ),
    ]

    routing = metrics.compute_routing_metrics(entries)

    assert routing["pass_rate_by_pair"]["claude+codex"]["pass_rate"] == 50.0
    assert routing["pass_rate_by_topology"]["solo"]["pass_rate"] == 50.0
    assert routing["pass_rate_by_topology"]["team"]["pass_rate"] == 0.0
    assert routing["mean_duration_by_task_class"]["docs"] == 60.0
    assert routing["mean_duration_by_task_class"]["src"] == 120.0
    assert routing["mean_duration_by_task_class"]["tests"] == 30.0
    assert (
        routing["repeat_failure_clusters"][0]["failure_reason_class"]
        == "review:gate_failed"
    )
    assert routing["repeat_failure_clusters"][0]["count"] == 2
    assert (
        routing["cost_per_chapter_delta_per_pair"]["claude+codex"][
            "cost_per_chapter_delta"
        ]
        == 0.2
    )
    assert (
        routing["chapter_delta_per_dollar_14d"]["claude+codex"][
            "chapter_delta_per_dollar"
        ]
        == 5.0
    )
    assert not routing["chapter_delta_per_dollar_14d"]["claude+codex"][
        "auto_disable_eligible"
    ]


def test_routing_metrics_upgrade_legacy_bare_failure_class() -> None:
    entries = [
        _make_entry(
            wave_id="legacy",
            verdict="FAIL",
            failure_reason="review:gate_failed",
            failure_reason_class="review",
        ),
        _make_entry(
            wave_id="current",
            verdict="FAIL",
            failure_reason_class="review:gate_failed",
        ),
    ]

    routing = metrics.compute_routing_metrics(entries)

    assert (
        routing["repeat_failure_clusters"][0]["failure_reason_class"]
        == "review:gate_failed"
    )
    assert routing["repeat_failure_clusters"][0]["count"] == 2


def test_auto_disable_recommends_cheap_pair_below_median() -> None:
    entries = [
        _make_entry(
            wave_id="premium",
            writer="claude",
            reviewer="codex",
            chapter_delta="+100",
            cost_usd=10.0,
            models={"writer": "opus", "reviewer": "gpt-5.5"},
        ),
        _make_entry(
            wave_id="cheap-good",
            writer="codex",
            reviewer="codex",
            chapter_delta="+90",
            cost_usd=10.0,
            models={"writer": "gpt-5.3-codex-spark", "reviewer": "gpt-5.4-mini"},
        ),
        _make_entry(
            wave_id="cheap-bad",
            writer="claude-haiku",
            reviewer="claude-haiku",
            chapter_delta="+10",
            cost_usd=10.0,
            models={"writer": "haiku", "reviewer": "haiku"},
        ),
    ]

    routing = metrics.compute_routing_metrics(entries)

    assert routing["auto_disable"]["median_chapter_delta_per_dollar"] == 9.0
    assert routing["auto_disable"]["threshold_chapter_delta_per_dollar"] == 6.3
    assert routing["auto_disable"]["pairs"] == [
        {
            "pair": "claude-haiku+claude-haiku",
            "chapter_delta_per_dollar": 1.0,
            "median_chapter_delta_per_dollar": 9.0,
            "threshold_chapter_delta_per_dollar": 6.3,
            "waves": 1,
            "cost_usd": 10.0,
            "positive_chapter_delta": 10.0,
            "reason": "chapter_delta_per_dollar_14d_more_than_30pct_below_median",
        }
    ]


def test_auto_disable_boundary_exactly_30_percent_below_is_kept() -> None:
    value_metrics = {
        "cheap-good": {
            "cost_usd": 1.0,
            "chapter_delta_per_dollar": 10.0,
            "auto_disable_eligible": True,
            "waves": 1,
            "positive_chapter_delta": 10.0,
        },
        "cheap-boundary": {
            "cost_usd": 1.0,
            "chapter_delta_per_dollar": 7.0,
            "auto_disable_eligible": True,
            "waves": 1,
            "positive_chapter_delta": 7.0,
        },
        "cheap-high": {
            "cost_usd": 1.0,
            "chapter_delta_per_dollar": 13.0,
            "auto_disable_eligible": True,
            "waves": 1,
            "positive_chapter_delta": 13.0,
        },
    }

    recommendation = metrics.compute_auto_disable_recommendation(value_metrics)

    assert recommendation["median_chapter_delta_per_dollar"] == 10.0
    assert recommendation["pairs"] == []


def test_update_disabled_pairs_state_preserves_reactivation(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "disabled-pairs.json").write_text(
        json.dumps(
            {
                "disabled_pairs": ["claude-haiku+claude-haiku"],
                "manual_reactivated_pairs": ["claude-haiku+claude-haiku"],
            }
        ),
        encoding="utf-8",
    )
    value_metrics = {
        "claude-haiku+claude-haiku": {
            "cost_usd": 10.0,
            "positive_chapter_delta": 1.0,
            "chapter_delta_per_dollar": 0.1,
            "auto_disable_eligible": True,
            "waves": 1,
            "models": ["haiku"],
        }
    }
    recommendation = metrics.compute_auto_disable_recommendation(value_metrics)

    state = metrics.update_disabled_pairs_state(
        state_dir, value_metrics, recommendation
    )

    assert state["disabled_pairs"] == []
    assert state["pairs"]["claude-haiku+claude-haiku"]["status"] == "manual_reactivated"


def test_disabled_pair_state_accepts_legacy_shapes_and_manual_disabled(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "disabled-pairs.json"
    state_file.write_text(
        json.dumps(
            {
                "pairs": {
                    "cheap-old+cheap-old": {"status": "auto_disabled"},
                    "manual+manual": {"status": "manual_disabled"},
                    "reactivated+reactivated": {"status": "manual_reactivated"},
                }
            }
        ),
        encoding="utf-8",
    )

    assert metrics.load_disabled_pairs(state_file) == ["cheap-old+cheap-old"]

    value_metrics = {
        "cheap-new+cheap-new": {
            "cost_usd": 2.0,
            "positive_chapter_delta": 0.1,
            "chapter_delta_per_dollar": 0.05,
            "auto_disable_eligible": True,
            "waves": 2,
            "models": ["mini"],
        }
    }
    recommendation = {
        "pairs": [
            {
                "pair": "cheap-new+cheap-new",
                "reason": "below_median",
            }
        ],
        "median_chapter_delta_per_dollar": 1.0,
        "threshold_chapter_delta_per_dollar": 0.7,
    }

    state = metrics.update_disabled_pairs_state(
        state_file,
        value_metrics,
        recommendation,
        now=datetime(2026, 5, 4, tzinfo=timezone.utc),
    )

    assert state["disabled_pairs"] == [
        "cheap-new+cheap-new",
        "cheap-old+cheap-old",
        "manual+manual",
    ]
    assert state["pairs"]["manual+manual"]["status"] == "manual_disabled"
    assert state["pairs"]["manual+manual"]["reason"] == "manual_disabled"
    assert state["pairs"]["reactivated+reactivated"]["status"] == "manual_reactivated"
    assert state["pairs"]["cheap-old+cheap-old"]["reason"] == (
        "previously_auto_disabled_until_manual_reactivation"
    )


def test_load_disabled_pairs_handles_list_and_corrupt_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_file = state_dir / "disabled-pairs.json"
    state_file.write_text(json.dumps(["codex+codex", "", "codex+codex"]))
    assert metrics.load_disabled_pairs(state_dir) == ["codex+codex"]

    state_file.write_text("{bad json", encoding="utf-8")
    assert metrics.read_disabled_pairs_state(state_dir) == {}
    assert metrics.load_disabled_pairs(state_dir) == []


def test_cli_update_disabled_pairs_writes_state(tmp_path: Path) -> None:
    ledger = tmp_path / "logs" / "waves.jsonl"
    ledger.parent.mkdir()
    state_dir = tmp_path / "state"
    _write_ledger(
        ledger,
        [
            _make_entry(
                wave_id="good",
                writer="codex",
                reviewer="codex",
                chapter_delta="+100",
                cost_usd=10.0,
                models={
                    "writer": "gpt-5.3-codex-spark",
                    "reviewer": "gpt-5.3-codex-spark",
                },
            ),
            _make_entry(
                wave_id="bad",
                writer="claude-haiku",
                reviewer="claude-haiku",
                chapter_delta="+1",
                cost_usd=10.0,
                models={"writer": "haiku", "reviewer": "haiku"},
            ),
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "metrics.py"),
            str(ledger),
            "--routing",
            "--days",
            "30",
            "--update-disabled-pairs",
            "--state-dir",
            str(state_dir),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    state = json.loads((state_dir / "disabled-pairs.json").read_text())
    assert state["disabled_pairs"] == ["claude-haiku+claude-haiku"]
    listed = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "metrics.py"),
            "disabled-pairs",
            str(state_dir),
        ],
        capture_output=True,
        text=True,
    )
    assert listed.stdout.strip() == "claude-haiku+claude-haiku"


def test_format_routing_text() -> None:
    routing = metrics.compute_routing_metrics(
        [_make_entry(changed_files=["docs/a.md"], chapter_delta="+5", cost_usd=1.0)]
    )
    text = metrics.format_routing_text(routing)
    assert "Routing metrics" in text
    assert "Pass rate by pair:" in text
    assert "Pass rate by topology:" in text
    assert "Mean duration by task class:" in text
    assert "Cost per chapter delta by pair:" in text


def test_format_routing_text_empty_is_actionable() -> None:
    text = metrics.format_routing_text(metrics.compute_routing_metrics([]))

    assert "No routing data in the selected window." in text
    assert "Run Mainspring first" in text
    assert "Pass rate by pair:" not in text


def test_format_routing_text_includes_failures_value_and_candidates() -> None:
    routing = metrics.compute_routing_metrics(
        [
            _make_entry(
                wave_id="good",
                writer="codex-mini",
                reviewer="codex-mini",
                chapter_delta="+100",
                cost_usd=10.0,
                models={"writer": "mini", "reviewer": "mini"},
            ),
            _make_entry(
                wave_id="bad-value",
                writer="haiku",
                reviewer="haiku",
                chapter_delta="+1",
                cost_usd=10.0,
                models={"writer": "haiku", "reviewer": "haiku"},
            ),
            _make_entry(
                wave_id="fail-1",
                verdict="FAIL",
                failure_reason_class="engine:quota",
                task_id="17",
            ),
            _make_entry(
                wave_id="fail-2",
                verdict="FAIL",
                failure_reason_class="engine:quota",
                task_id="18",
            ),
        ]
    )

    text = metrics.format_routing_text(routing)

    assert "Repeat failure clusters:" in text
    assert "engine:quota: 2 waves tasks=17,18" in text
    assert "Chapter delta per dollar (14d):" in text
    assert "Auto-disabled pair candidates:" in text
    assert "haiku+haiku" in text


# ── CLI ────────────────────────────────────────────────────────────────


# Scenario: CLI with --format json.
# Expected: valid JSON output.
def test_cli_json_output(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    _write_ledger(ledger, [_make_entry()])
    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "metrics.py"),
            str(ledger),
            "--format",
            "json",
            "--days",
            "30",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["total_waves"] == 1


def test_cli_routing_json_output(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    _write_ledger(ledger, [_make_entry(topology="team")])
    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "metrics.py"),
            str(ledger),
            "--routing",
            "--format",
            "json",
            "--days",
            "30",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["pass_rate_by_topology"]["team"]["pass_rate"] == 100.0


def test_cli_routing_defaults_to_fourteen_day_window(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    now = datetime.now(timezone.utc)
    _write_ledger(
        ledger,
        [
            _make_entry(
                wave_id="old",
                topology="solo",
                ts=(now - timedelta(days=15)).isoformat().replace("+00:00", "Z"),
            ),
            _make_entry(
                wave_id="recent",
                topology="team",
                ts=(now - timedelta(days=13)).isoformat().replace("+00:00", "Z"),
            ),
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "metrics.py"),
            str(ledger),
            "--routing",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["pass_rate_by_topology"] == {
        "team": {"total": 1, "pass": 1, "pass_rate": 100.0}
    }


# Scenario: CLI with no args.
# Expected: exits 2.
def test_cli_no_args() -> None:
    result = subprocess.run(
        [sys.executable, str(HERE.parent / "metrics.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


# Scenario: CLI with empty ledger.
# Expected: zero metrics, no crash.
def test_cli_empty_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    ledger.write_text("")
    result = subprocess.run(
        [sys.executable, str(HERE.parent / "metrics.py"), str(ledger), "--days", "7"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Total waves:    0" in result.stdout
    assert "No wave data in the selected window." in result.stdout
    assert "none yet" in result.stdout


def test_cli_disabled_pairs_requires_state_path() -> None:
    result = subprocess.run(
        [sys.executable, str(HERE.parent / "metrics.py"), "disabled-pairs"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Usage: metrics.py disabled-pairs" in result.stderr


def test_cli_rejects_unknown_flag(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    ledger.write_text("", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(HERE.parent / "metrics.py"), str(ledger), "--unknown"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Unknown flag: --unknown" in result.stderr


def test_cli_routing_update_uses_default_state_dir(tmp_path: Path) -> None:
    ledger = tmp_path / "logs" / "waves.jsonl"
    ledger.parent.mkdir()
    _write_ledger(
        ledger,
        [
            _make_entry(
                writer="codex-mini",
                reviewer="codex-mini",
                chapter_delta="+100",
                cost_usd=10.0,
                models={"writer": "mini", "reviewer": "mini"},
            ),
            _make_entry(
                writer="haiku",
                reviewer="haiku",
                chapter_delta="+1",
                cost_usd=10.0,
                models={"writer": "haiku", "reviewer": "haiku"},
            ),
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "metrics.py"),
            str(ledger),
            "--routing",
            "--update-disabled-pairs",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert (tmp_path / "state" / "disabled-pairs.json").is_file()
