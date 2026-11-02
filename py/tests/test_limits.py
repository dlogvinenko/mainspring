# SPDX-License-Identifier: Apache-2.0
"""Tests for limits.py — one-shot quota and spend view."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import limits

SCRIPT = str(HERE.parent / "limits.py")
NOW = datetime(2026, 4, 29, 20, 0, tzinfo=UTC)


def _snapshot(
    engine: str,
    *,
    available: bool = True,
    short: float | None = 75.0,
    long: float | None = 80.0,
    quota_status: str = "ok",
    quota_source: str = "fixture",
    quota_plan: str = "pro",
    short_reset: str = "2026-04-29T21:30:00Z",
    long_reset: str = "2026-05-01T20:00:00Z",
) -> dict:
    return {
        "engine": engine,
        "display_name": engine.title(),
        "binary": engine,
        "binary_path": f"/usr/bin/{engine}" if available else None,
        "available": available,
        "default_model": f"{engine}-model",
        "execution_status": "shell-dispatch",
        "quota": {
            "short": {
                "remaining_pct": short,
                "window": "5h",
                "reset": short_reset,
            },
            "long": {
                "remaining_pct": long,
                "window": "7d",
                "reset": long_reset,
            },
            "plan": quota_plan,
            "status": quota_status,
            "source": quota_source,
        },
    }


def _write_ledger(path: Path, entries: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n",
        encoding="utf-8",
    )


# Scenario: All configured engines have quota data.
# Expected: text output includes every engine, bars, and last-24h spend.
def test_limits_text_all_available(monkeypatch, tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    _write_ledger(
        ledger,
        [
            {
                "ts": "2026-04-29T19:00:00Z",
                "wave_id": "w1",
                "task_id": "42",
                "pair": "claude+codex",
                "cost_usd": 1.25,
            }
        ],
    )
    monkeypatch.setattr(limits, "load_engines", lambda: {"codex": object()})
    monkeypatch.setattr(limits, "engine_snapshot", lambda name: _snapshot(name))
    monkeypatch.setattr(limits, "readiness_errors", lambda *args, **kwargs: [])

    payload = limits.build_limits(engine_names=[], ledger_path=ledger, now=NOW)
    text = limits.format_text(payload)

    assert payload["engines"][0]["status"] == "ready"
    assert payload["engines"][0]["status_reason"]
    assert "[########--] 75.0%" in text
    assert "Run status:" in text
    assert "SPEND (last 24h, estimated)" in text
    assert "Cost: $1.25 (1/1 waves with cost truth" in text


# Scenario: One engine reports zero short-window quota.
# Expected: status is throttled and JSON remains stable.
def test_limits_json_throttled(monkeypatch, tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    _write_ledger(ledger, [])
    monkeypatch.setattr(limits, "load_engines", lambda: {"codex": object()})
    monkeypatch.setattr(limits, "readiness_errors", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        limits,
        "engine_snapshot",
        lambda name: _snapshot(name, short=0.0, quota_status="rate_limited"),
    )

    payload = limits.build_limits(engine_names=["codex"], ledger_path=ledger, now=NOW)
    rendered = json.loads(json.dumps(payload))

    assert rendered["engines"][0]["status"] == "throttled"
    assert rendered["engines"][0]["short"]["bar"] == "[----------]"
    assert rendered["spend_24h"]["wave_count"] == 0


# Scenario: A registered engine binary is missing.
# Expected: status is not-configured instead of available.
def test_limits_marks_missing_engine_not_configured(
    monkeypatch, tmp_path: Path
) -> None:
    ledger = tmp_path / "waves.jsonl"
    _write_ledger(ledger, [])
    monkeypatch.setattr(limits, "load_engines", lambda: {"gemini": object()})
    monkeypatch.setattr(limits, "readiness_errors", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        limits,
        "engine_snapshot",
        lambda name: _snapshot(name, available=False, short=None, long=None),
    )

    payload = limits.build_limits(engine_names=["gemini"], ledger_path=ledger, now=NOW)

    assert payload["engines"][0]["status"] == "not-configured"
    assert payload["engines"][0]["short"]["remaining_label"] == "unknown"


def test_limits_marks_adapter_without_quota_signal_as_adapter_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger = tmp_path / "waves.jsonl"
    _write_ledger(ledger, [])
    monkeypatch.setattr(limits, "load_engines", lambda: {"gemini": object()})
    monkeypatch.setattr(limits, "readiness_errors", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        limits,
        "engine_snapshot",
        lambda name: _snapshot(
            name,
            short=None,
            long=None,
            quota_status="unknown",
            quota_source="missing",
            quota_plan="unknown",
            short_reset="unknown",
            long_reset="unknown",
        ),
    )

    payload = limits.build_limits(engine_names=["gemini"], ledger_path=ledger, now=NOW)
    text = limits.format_text(payload)

    assert payload["engines"][0]["status"] == "adapter-only"
    assert "credentials/quota not proven" in payload["engines"][0]["status_reason"]
    assert "adapter-only" in text


def test_limits_parses_times_bars_and_reset_labels() -> None:
    future = NOW + timedelta(minutes=65)
    past = NOW - timedelta(minutes=1)

    assert limits._parse_ts("1777500000000") is not None
    assert limits._parse_ts("2026-04-29T20:00:00") == NOW
    assert limits._parse_ts("not-a-date") is None
    assert limits._bar(None) == "unknown"
    assert limits._bar(125) == "[##########]"
    assert limits._bar(-5) == "[----------]"
    assert limits._format_reset(future.isoformat(), NOW).startswith("in 1h 05m")
    assert limits._format_reset(past.isoformat(), NOW).startswith("now,")


def test_limits_text_renders_unknown_quota_cleanly(monkeypatch, tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    _write_ledger(ledger, [])
    monkeypatch.setattr(limits, "load_engines", lambda: {"gemini": object()})
    monkeypatch.setattr(limits, "readiness_errors", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        limits,
        "engine_snapshot",
        lambda name: _snapshot(name, short=None, long=None),
    )

    text = limits.format_text(
        limits.build_limits(engine_names=["gemini"], ledger_path=ledger, now=NOW)
    )

    assert "??????????" not in text
    assert "unknown unknown" not in text
    assert "gemini" in text


def test_spend_summary_filters_old_invalid_and_uncosted_entries() -> None:
    entries = [
        {"ts": "2026-04-29T19:00:00Z", "wave": 1, "cost_usd": 0.5},
        {
            "timestamp": "2026-04-29T18:00:00Z",
            "wave_id": "estimated",
            "model": "gpt-5.5",
            "usage": {"input_tokens": 1000, "output_tokens": 1000},
        },
        {"ts": "2026-04-27T19:00:00Z", "wave_id": "old", "cost_usd": 99.0},
        {"ts": "not-a-date", "wave_id": "invalid", "cost_usd": 1.0},
        {"ts": "2026-04-29T17:00:00Z", "wave_id": "uncosted"},
    ]

    summary = limits._spend_summary(entries, hours=24, now=NOW)

    assert summary["wave_count"] == 3
    assert summary["costed_wave_count"] == 2
    assert summary["uncosted_wave_count"] == 1
    assert summary["total_usd"] > 0.5
    assert [row["wave_id"] for row in summary["top_cost_waves"]]


def test_resolve_engine_names_rejects_unknown_and_dedupes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(limits, "load_engines", lambda: {"codex": object()})

    assert limits._resolve_engine_names(["codex", "codex"]) == ["codex"]
    with pytest.raises(ValueError, match="unknown engine"):
        limits._resolve_engine_names(["missing"])


# Scenario: CLI JSON mode with a real local ledger.
# Expected: JSON round-trips and contains all registered engine rows.
def test_limits_cli_json_round_trips(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    _write_ledger(
        ledger,
        [
            {
                "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "wave_id": "w-est",
                "task_id": "costed",
                "model": "gpt-5.5",
                "usage": {"input_tokens": 1000, "output_tokens": 1000},
            }
        ],
    )

    result = subprocess.run(
        [sys.executable, SCRIPT, "--ledger", str(ledger), "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    engine_names = {row["engine"] for row in payload["engines"]}
    assert {"codex", "claude", "gemini"}.issubset(engine_names)
    assert payload["spend_24h"]["costed_wave_count"] == 1


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--hours", "bad"], "--hours must be an integer"),
        (["--hours", "0"], "--hours must be positive"),
        (["--format", "yaml"], "--format must be text or json"),
        (["--missing"], "Unknown or incomplete flag: --missing"),
    ],
)
def test_parse_args_usage_errors(
    args: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        limits._parse_args(args)

    assert excinfo.value.code == 2
    assert message in capsys.readouterr().err


def test_main_reports_unknown_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(limits, "load_engines", lambda: {"codex": object()})

    exit_code = limits.main(["missing", "--ledger", str(tmp_path / "waves.jsonl")])

    assert exit_code == 2
    assert "unknown engine: missing" in capsys.readouterr().err
