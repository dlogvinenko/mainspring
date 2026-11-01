# SPDX-License-Identifier: Apache-2.0
"""Tests for golden-run regression fixture checks."""

from __future__ import annotations

from pathlib import Path

import golden_run
import pytest
import replay

ROOT_DIR = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = ROOT_DIR / "tests" / "golden-runs"


# Scenario: Repo golden-run fixtures are checked by the normal pytest suite.
# Expected: Every fixture renders exactly to its committed expected.txt.
def test_all_golden_run_fixtures_match_expected() -> None:
    scenarios = golden_run.scenario_dirs(GOLDEN_ROOT)
    assert scenarios, "expected at least one golden-run scenario"
    diffs = [golden_run.check_scenario(scenario) for scenario in scenarios]
    assert [diff for diff in diffs if diff] == []


# Scenario: Render the Mainspring PRD-to-PR golden fixture.
# Expected: Output shows all waves and the replay acceptance evidence.
def test_render_prd_to_pr_fixture() -> None:
    output = golden_run.render_scenario(GOLDEN_ROOT / "mainspring-prd-to-pr")
    assert "Golden run: mainspring-prd-to-pr" in output
    assert "Waves: 3" in output
    assert "golden-003-replay-evidence PASS" in output
    assert "replayed_from=golden-002-slice-impl determinism=PASS" in output
    assert "Replay acceptance:" in output


# Scenario: The committed replay source row carries deterministic prompt material.
# Expected: Replay dry-run validation passes without launching a model provider.
def test_prd_to_pr_fixture_prompt_backed_replay_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(ROOT_DIR)
    ledger = GOLDEN_ROOT / "mainspring-prd-to-pr" / golden_run.LEDGER_NAME

    status = replay.main(
        [
            "run",
            "golden-002-slice-impl",
            str(ledger),
            "--dry-run",
            "--save-as",
            "golden-002-replay-smoke",
        ]
    )

    output = capsys.readouterr().out
    assert status == 0
    assert "MAINSPRING_REPLAY_PROMPT_FILE=" in output
    assert "MAINSPRING_WAVE_ID_OVERRIDE=golden-002-replay-smoke" in output
    assert "Real-run validation: OK" in output


# Scenario: Expected output drifts from rendered output.
# Expected: The checker returns a unified diff for CI failure diagnostics.
def test_check_scenario_reports_unified_diff(tmp_path: Path) -> None:
    scenario = tmp_path / "fixture"
    scenario.mkdir()
    (scenario / golden_run.LEDGER_NAME).write_text(
        '{"wave_id":"w1","verdict":"PASS","engines":{"writer":"claude","reviewer":"codex"}}\n',
        encoding="utf-8",
    )
    (scenario / golden_run.EXPECTED_NAME).write_text("wrong\n", encoding="utf-8")

    diff = golden_run.check_scenario(scenario)
    assert "---" in diff
    assert "+++" in diff
    assert "-wrong" in diff
    assert "+Golden run: fixture" in diff


def test_render_reports_missing_original_and_review_determinism(tmp_path: Path) -> None:
    scenario = tmp_path / "fixture"
    scenario.mkdir()
    (scenario / golden_run.LEDGER_NAME).write_text(
        (
            '{"wave_id":"w1","verdict":"PASS","engines":{"writer":"claude","reviewer":"codex"},"product_score":"10"}\n'
            '{"wave_id":"w2","verdict":"PASS","replayed_from":"missing","engines":{"writer":"claude","reviewer":"codex"}}\n'
            '{"wave_id":"w3","verdict":"FAIL","replayed_from":"w1","engines":{"writer":"claude","reviewer":"codex"},"failure_reason":"review:gate_failed","next_action":"repair"}'
        )
        + "\n",
        encoding="utf-8",
    )

    output = golden_run.render_scenario(scenario)

    assert "replayed_from=missing determinism=MISSING_ORIGINAL" in output
    assert "replayed_from=w1 determinism=REVIEW" in output
    assert "failure=review:gate_failed" in output
    assert "next_action=repair" in output


def test_scenario_dirs_missing_root_returns_empty(tmp_path: Path) -> None:
    assert golden_run.scenario_dirs(tmp_path / "missing") == []


# Scenario: CLI check-all is run on the repo fixtures.
# Expected: It exits zero and prints one OK line per scenario.
def test_cli_check_all(capsys: pytest.CaptureFixture[str]) -> None:
    status = golden_run.main(["check-all", str(GOLDEN_ROOT)])
    out = capsys.readouterr().out
    assert status == 0
    assert "golden-run OK:" in out
    assert "mainspring-prd-to-pr" in out


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["render"],
        ["check"],
        ["check-all"],
        ["unknown"],
    ],
)
def test_cli_usage_and_error_paths(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    if argv == ["check-all"]:
        argv = ["check-all", str(tmp_path / "empty")]

    status = golden_run.main(argv)

    assert status in {1, 2}
    assert capsys.readouterr().err


def test_cli_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert golden_run.main(["--help"]) == 0
    assert "golden_run.py render" in capsys.readouterr().err


def test_cli_render_and_check_single_scenario(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scenario = tmp_path / "fixture"
    scenario.mkdir()
    (scenario / golden_run.LEDGER_NAME).write_text(
        '{"wave_id":"w1","verdict":"PASS","engines":{"writer":"claude","reviewer":"codex"}}\n',
        encoding="utf-8",
    )
    expected = golden_run.render_scenario(scenario)
    (scenario / golden_run.EXPECTED_NAME).write_text(expected, encoding="utf-8")

    assert golden_run.main(["render", str(scenario)]) == 0
    assert "Golden run: fixture" in capsys.readouterr().out

    assert golden_run.main(["check", str(scenario)]) == 0
    assert "golden-run OK:" in capsys.readouterr().out
