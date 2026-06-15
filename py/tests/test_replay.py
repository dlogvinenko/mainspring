#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for py/replay.py — wave replay module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Allow importing from parent dir
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import replay


# ── fixtures ──────────────────────────────────────────────────────────


def _make_wave(
    *,
    wave_id: str = "w1",
    mode: str = "taskmaster",
    topology: str = "solo",
    task_id: str = "42.1",
    writer: str = "claude",
    reviewer: str = "codex",
    writer_model: str = "opus",
    reviewer_model: str = "gpt-5.5",
    duration: int = 120,
    exit_code: int = 0,
    verdict: str = "PASS",
    failure_reason: str = "",
    changed_files: list[str] | None = None,
    prompt_path: str = "",
    prompt_sha256: str = "",
    git_head: str = "",
    git_status_before: str | None = None,
    prd_path: str = "",
    chapter_delta: str | None = None,
    competitor_delta: str | None = None,
    launch_delta: str | None = None,
    product_score: int | None = None,
    replayed_from: str = "",
) -> dict:
    wave = {
        "wave_id": wave_id,
        "timestamp": "2026-04-27T10:00:00Z",
        "mode": mode,
        "topology": topology,
        "team": "",
        "task_id": task_id,
        "work_id": "",
        "selected_lane": "main",
        "engines": {"writer": writer, "reviewer": reviewer},
        "models": {
            "writer": writer_model,
            "reviewer": reviewer_model,
            "reasoning": "",
        },
        "duration_seconds": duration,
        "changed_files": changed_files or ["src/App.tsx", "tests/app.test.ts"],
        "tests": "",
        "verdict": verdict,
        "exit_code": exit_code,
        "failure_reason": failure_reason,
        "retry_count": 0,
        "blocked_reason": "",
        "next_action": "",
    }
    if prompt_path:
        wave["prompt_path"] = prompt_path
    if prompt_sha256:
        wave["prompt_sha256"] = prompt_sha256
    if git_head:
        wave["git_head"] = git_head
    if git_status_before is not None:
        wave["git_status_before"] = git_status_before
    if prd_path:
        wave["prd_path"] = prd_path
    if chapter_delta is not None:
        wave["chapter_delta"] = chapter_delta
    if competitor_delta is not None:
        wave["competitor_delta"] = competitor_delta
    if launch_delta is not None:
        wave["launch_delta"] = launch_delta
    if product_score is not None:
        wave["product_score"] = product_score
    if replayed_from:
        wave["replayed_from"] = replayed_from
    return wave


def _write_ledger(tmp_path: Path, waves: list[dict]) -> Path:
    ledger = tmp_path / "waves.jsonl"
    lines = [json.dumps(w, ensure_ascii=False) for w in waves]
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ledger


# ── read_ledger ───────────────────────────────────────────────────────


# Scenario: Ledger with 3 valid entries.
# Expected: All 3 parsed.
def test_read_ledger_happy(tmp_path: Path) -> None:
    waves = [_make_wave(wave_id=f"w{i}") for i in range(3)]
    ledger = _write_ledger(tmp_path, waves)
    result = replay.read_ledger(ledger)
    assert len(result) == 3
    assert result[0]["wave_id"] == "w0"


# Scenario: Ledger file doesn't exist.
# Expected: Empty list, no crash.
def test_read_ledger_missing(tmp_path: Path) -> None:
    assert replay.read_ledger(tmp_path / "nonexistent.jsonl") == []


# Scenario: Ledger with invalid JSON lines mixed in.
# Expected: Invalid lines silently skipped, valid lines parsed.
def test_read_ledger_invalid_lines(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    ledger.write_text(
        '{"wave_id": "w1"}\nthis is not json\n{"wave_id": "w2"}\n\n',
        encoding="utf-8",
    )
    result = replay.read_ledger(ledger)
    assert len(result) == 2


# ── resolve_wave ──────────────────────────────────────────────────────


# Scenario: Resolve by wave_id string.
# Expected: Matching entry returned.
def test_resolve_wave_by_id() -> None:
    waves = [_make_wave(wave_id="abc"), _make_wave(wave_id="def")]
    assert replay.resolve_wave(waves, "def")["wave_id"] == "def"


# Scenario: Resolve a canonical schema row by its wave number.
# Expected: Rows that have wave but no wave_id are still replay-addressable.
def test_resolve_wave_by_canonical_wave_number() -> None:
    waves = [{"wave": 46, "verdict": "PASS"}, {"wave": 47, "verdict": "PASS"}]
    assert replay.resolve_wave(waves, "47")["wave"] == 47


# Scenario: Resolve by index #0.
# Expected: First entry returned.
def test_resolve_wave_by_index() -> None:
    waves = [_make_wave(wave_id="first"), _make_wave(wave_id="second")]
    assert replay.resolve_wave(waves, "#0")["wave_id"] == "first"


# Scenario: Resolve by negative index #-1.
# Expected: Last entry returned.
def test_resolve_wave_last_index() -> None:
    waves = [_make_wave(wave_id="first"), _make_wave(wave_id="second")]
    assert replay.resolve_wave(waves, "#-1")["wave_id"] == "second"


# Scenario: Resolve with "last" alias.
# Expected: Last entry returned.
def test_resolve_wave_last_alias() -> None:
    waves = [_make_wave(wave_id="a"), _make_wave(wave_id="b")]
    assert replay.resolve_wave(waves, "last")["wave_id"] == "b"


# Scenario: Resolve with nonexistent wave_id.
# Expected: None returned.
def test_resolve_wave_not_found() -> None:
    waves = [_make_wave(wave_id="a")]
    assert replay.resolve_wave(waves, "zzz") is None


# Scenario: Resolve with out-of-range index.
# Expected: None returned.
def test_resolve_wave_index_out_of_range() -> None:
    waves = [_make_wave(wave_id="a")]
    assert replay.resolve_wave(waves, "#99") is None


# ── metadata extraction ───────────────────────────────────────────────


# Scenario: Extract engine/reviewer/model from a standard wave entry.
# Expected: All fields extracted correctly.
def test_engine_extraction() -> None:
    wave = _make_wave(writer="claude", reviewer="codex")
    assert replay.get_engine(wave) == "claude"
    assert replay.get_reviewer(wave) == "codex"
    assert replay.get_pair(wave) == "claude+codex"


# Scenario: Extract from legacy format (flat fields, no nested engines).
# Expected: Falls back to flat fields.
def test_engine_extraction_legacy() -> None:
    wave = {"engine": "claude", "review_engine": "codex", "model": "opus"}
    assert replay.get_engine(wave) == "claude"
    assert replay.get_reviewer(wave) == "codex"
    assert replay.get_model(wave) == "opus"


# Scenario: Check success detection for PASS and FAIL waves.
# Expected: PASS+exit0 = True; FAIL or exit!=0 = False.
def test_is_success() -> None:
    assert replay.is_success(_make_wave(verdict="PASS", exit_code=0)) is True
    assert replay.is_success(_make_wave(verdict="PASS", exit_code="0")) is True
    assert replay.is_success(_make_wave(verdict="FAIL", exit_code=0)) is False
    assert replay.is_success(_make_wave(verdict="PASS", exit_code=1)) is False
    assert replay.is_success(_make_wave(verdict="PASS", exit_code="oops")) is False


# ── overrides ─────────────────────────────────────────────────────────


# Scenario: Apply engine override to a wave.
# Expected: Only the writer engine changes.
def test_apply_overrides_engine() -> None:
    original = _make_wave(writer="claude", reviewer="codex")
    overrides = replay.ReplayOverrides(engine="gemini")
    result = replay.apply_overrides(original, overrides)
    assert result["engines"]["writer"] == "gemini"
    assert result["engines"]["reviewer"] == "codex"
    # Original unchanged (deep copy)
    assert original["engines"]["writer"] == "claude"


# Scenario: Apply reviewer override.
# Expected: Only the reviewer engine changes.
def test_apply_overrides_reviewer() -> None:
    original = _make_wave(writer="claude", reviewer="codex")
    overrides = replay.ReplayOverrides(reviewer="claude")
    result = replay.apply_overrides(original, overrides)
    assert result["engines"]["reviewer"] == "claude"
    assert result["engines"]["writer"] == "claude"


# Scenario: Apply model overrides.
# Expected: Both writer and reviewer models changed.
def test_apply_overrides_models() -> None:
    original = _make_wave(writer_model="opus", reviewer_model="gpt-5.5")
    overrides = replay.ReplayOverrides(model="sonnet", review_model="gpt-4o")
    result = replay.apply_overrides(original, overrides)
    assert result["models"]["writer"] == "sonnet"
    assert result["models"]["reviewer"] == "gpt-4o"


# Scenario: No overrides applied.
# Expected: Deep copy of original, identical content.
def test_apply_overrides_none() -> None:
    original = _make_wave()
    result = replay.apply_overrides(original, replay.ReplayOverrides())
    assert result == original
    assert result is not original


# ── format_wave_detail ────────────────────────────────────────────────


# Scenario: Format a passing wave.
# Expected: All key fields present in output.
def test_format_wave_detail() -> None:
    wave = _make_wave(wave_id="test-wave", verdict="PASS")
    output = replay.format_wave_detail(wave)
    assert "test-wave" in output
    assert "PASS" in output
    assert "claude+codex" in output
    assert "opus" in output
    assert "src/App.tsx" in output


# Scenario: Format a failed wave with failure reason.
# Expected: Failure reason line present.
def test_format_wave_detail_failure() -> None:
    wave = _make_wave(verdict="FAIL", failure_reason="review:gate_failed")
    output = replay.format_wave_detail(wave)
    assert "review:gate_failed" in output


# Scenario: Format a replay-scored wave.
# Expected: Chapter and product-score acceptance fields are prominent.
def test_format_wave_detail_replay_acceptance_fields() -> None:
    wave = _make_wave(
        chapter_delta="+12",
        competitor_delta="+8",
        launch_delta="+6",
        product_score=812,
    )
    output = replay.format_wave_detail(wave)
    assert "Chapter delta:" in output
    assert "+12" in output
    assert "Competitor delta:" in output
    assert "Launch delta:" in output
    assert "Product score:" in output
    assert "812" in output


# Scenario: Format a canonical JSONL schema row without legacy aliases.
# Expected: replay show still displays useful identity/timing/success details.
def test_format_wave_detail_canonical_schema_aliases() -> None:
    wave = {
        "wave": 7,
        "ts": "2026-04-30T08:41:49Z",
        "mode": "night",
        "topology": "solo",
        "pair": "codex+codex",
        "model": "auto",
        "review_model": "auto",
        "duration_s": 12,
        "exit_code": "0",
        "verdict": "PASS",
    }

    output = replay.format_wave_detail(wave)

    assert "Wave ID:        7" in output
    assert "Timestamp:      2026-04-30T08:41:49Z" in output
    assert "Pair:           codex+codex" in output
    assert "Duration:       12s" in output
    assert "Exit code:      0" in output
    assert "Success:        True" in output


# Scenario: Format a prompt-backed wave.
# Expected: replay show identifies it as deterministic replay material.
def test_format_wave_detail_shows_prompt_snapshot_replayability() -> None:
    wave = _make_wave(prompt_path=".omx/logs/taskmaster-prompt-wave1.md")

    output = replay.format_wave_detail(wave)

    assert "Replayability:  deterministic prompt snapshot" in output


# Scenario: Format a historical row with a recorded Taskmaster target.
# Expected: replay show calls out live-reconstruction-only status and anchor.
def test_format_wave_detail_shows_live_reconstruction_replayability() -> None:
    wave = _make_wave(task_id="42.3")

    output = replay.format_wave_detail(wave)

    assert "Replayability:  live reconstruction only" in output
    assert "Taskmaster work item #42.3" in output


# Scenario: Format a historical row without prompt snapshot or live anchor.
# Expected: replay show makes the unreplayable state explicit.
def test_format_wave_detail_shows_unreplayable_without_anchor() -> None:
    wave = _make_wave(mode="taskmaster", task_id="", prd_path="")

    output = replay.format_wave_detail(wave)

    assert (
        "Replayability:  not replayable (missing prompt snapshot and live anchor)"
        in output
    )


# ── diff_waves ────────────────────────────────────────────────────────


# Scenario: Diff two identical waves.
# Expected: No drift markers (≠).
def test_diff_identical() -> None:
    a = _make_wave(wave_id="a")
    b = _make_wave(wave_id="a")
    output = replay.diff_waves(a, b)
    # wave_id is the same, so no ≠ on that line
    # All fields match
    assert "Verdict drift" not in output


# Scenario: Diff a PASS wave and a FAIL wave with different pair.
# Expected: Verdict drift detected, pair difference shown.
def test_diff_verdict_drift() -> None:
    a = _make_wave(wave_id="a", verdict="PASS", writer="claude", reviewer="codex")
    b = _make_wave(wave_id="b", verdict="FAIL", writer="gemini", reviewer="claude")
    output = replay.diff_waves(a, b)
    assert "Verdict drift detected" in output
    assert "PASS" in output
    assert "FAIL" in output
    assert "claude+codex" in output
    assert "gemini+claude" in output


# Scenario: Diff waves with different changed files.
# Expected: File comparison section shows only-in-A and only-in-B.
def test_diff_changed_files() -> None:
    a = _make_wave(wave_id="a", changed_files=["src/a.ts", "shared/x.ts"])
    b = _make_wave(wave_id="b", changed_files=["src/b.ts", "shared/x.ts"])
    output = replay.diff_waves(a, b)
    assert "Only in a" in output
    assert "Only in b" in output
    assert "Common:" in output


# Scenario: Diff a replayed PASS wave with identical acceptance metrics.
# Expected: Diff surfaces the replay determinism proof directly.
def test_diff_replay_determinism_acceptance_pass() -> None:
    original = _make_wave(
        wave_id="original",
        verdict="PASS",
        chapter_delta="+12",
        competitor_delta="+7",
        launch_delta="+5",
        product_score=840,
    )
    replayed = _make_wave(
        wave_id="replay-1",
        verdict="PASS",
        replayed_from="original",
        chapter_delta="+12",
        competitor_delta="+7",
        launch_delta="+5",
        product_score=840,
    )

    output = replay.diff_waves(original, replayed)

    assert "Replay acceptance:" in output
    assert "Chapter delta parity: PASS (+12 vs +12)" in output
    assert "Product score parity: PASS (840 vs 840)" in output
    assert "Verdict drift: none (PASS)" in output
    assert "Success drift: none (PASS exit 0)" in output
    assert "Exit-code drift: none (0)" in output
    assert "Determinism proof: PASS" in output


# Scenario: Replay rows have matching PASS text but different exit-code truth.
# Expected: Acceptance proof fails closed instead of reporting determinism PASS.
def test_diff_replay_exit_code_truth_blocks_false_determinism_pass() -> None:
    original = _make_wave(
        wave_id="original",
        verdict="PASS",
        exit_code="1",
        chapter_delta="+12",
        product_score=840,
    )
    replayed = _make_wave(
        wave_id="replay-1",
        verdict="PASS",
        exit_code="0",
        replayed_from="original",
        chapter_delta="+12",
        product_score=840,
    )

    output = replay.diff_waves(original, replayed)

    assert "Verdict drift: none (PASS)" in output
    assert "Success drift: detected (FAIL exit 1 -> PASS exit 0)" in output
    assert "Exit-code drift: detected (1 -> 0)" in output
    assert "Determinism proof: REVIEW" in output


# Scenario: Replay rows both fail but with different exit codes.
# Expected: Determinism proof still requires exact exit-code parity.
def test_diff_replay_exit_code_drift_blocks_failed_determinism_pass() -> None:
    original = _make_wave(
        wave_id="original",
        verdict="FAIL",
        exit_code="1",
        chapter_delta="+0",
    )
    replayed = _make_wave(
        wave_id="replay-1",
        verdict="FAIL",
        exit_code="2",
        replayed_from="original",
        chapter_delta="+0",
    )

    output = replay.diff_waves(original, replayed)

    assert "Verdict drift: none (FAIL)" in output
    assert "Success drift: none (FAIL exit 1)" in output
    assert "Exit-code drift: detected (1 -> 2)" in output
    assert "Determinism proof: REVIEW" in output


# Scenario: Replaying with a different reviewer changes the verdict and deltas.
# Expected: Diff makes reviewer drift and acceptance mismatch obvious.
def test_diff_replay_reviewer_drift_acceptance_review() -> None:
    original = _make_wave(
        wave_id="original",
        verdict="PASS",
        reviewer="codex",
        chapter_delta="+12",
        product_score=840,
    )
    replayed = _make_wave(
        wave_id="replay-claude",
        verdict="FAIL",
        reviewer="claude",
        replayed_from="original",
        chapter_delta="+0",
        product_score=0,
    )

    output = replay.diff_waves(original, replayed)

    assert "Replay acceptance:" in output
    assert "Chapter delta parity: MISMATCH (+12 vs +0)" in output
    assert "Product score parity: MISMATCH (840 vs 0)" in output
    assert "Verdict drift: detected (PASS -> FAIL)" in output
    assert "Success drift: detected (PASS exit 0 -> FAIL exit 0)" in output
    assert "Exit-code drift: none (0)" in output
    assert "Reviewer changed: codex -> claude" in output
    assert "Determinism proof: REVIEW" in output


# ── build_replay_command ──────────────────────────────────────────────


# Scenario: Build command from a standard wave with no overrides.
# Expected: Mode, topology, pair, models, --once all present.
def test_build_command_basic() -> None:
    wave = _make_wave(
        mode="taskmaster",
        topology="solo",
        writer="claude",
        reviewer="codex",
        writer_model="opus",
        reviewer_model="gpt-5.5",
    )
    cmd = replay.build_replay_command(wave)
    assert cmd[0] == "./mainspring.sh"
    assert cmd[1] == "taskmaster"
    assert "--topology" in cmd
    assert "solo" in cmd
    assert "--pair" in cmd
    assert "claude+codex" in cmd
    assert "--model" in cmd
    assert "opus" in cmd
    assert "--review-model" in cmd
    assert "gpt-5.5" in cmd
    assert "--once" in cmd


# Scenario: Build command with engine override.
# Expected: Override engine appears in pair.
def test_build_command_with_overrides() -> None:
    wave = _make_wave(writer="claude", reviewer="codex")
    overrides = replay.ReplayOverrides(engine="gemini", reviewer="claude")
    cmd = replay.build_replay_command(wave, overrides)
    pair_idx = cmd.index("--pair") + 1
    assert cmd[pair_idx] == "gemini+claude"


# Scenario: Build command with default models.
# Expected: No --model or --review-model flags emitted.
def test_build_command_default_models() -> None:
    wave = _make_wave(writer_model="default", reviewer_model="default")
    cmd = replay.build_replay_command(wave)
    assert "--model" not in cmd
    assert "--review-model" not in cmd


# Scenario: Build command from a prompt-backed replay snapshot.
# Expected: The command uses night mode and carries the recorded PRD path.
def test_build_command_prompt_snapshot_uses_night_mode() -> None:
    wave = _make_wave(
        mode="taskmaster",
        topology="team",
        prompt_path=".omx/logs/taskmaster-prompt-wave1.md",
        prd_path="docs/prd.md",
    )
    cmd = replay.build_replay_command(wave)
    assert cmd[1] == "night"
    assert "--prd" in cmd
    assert "docs/prd.md" in cmd
    assert cmd[cmd.index("--topology") + 1] == "solo"


# Scenario: A legacy row uses explicit live reconstruction.
# Expected: Replay is forced through one solo wave instead of team fanout.
def test_build_command_live_reconstruction_forces_solo() -> None:
    wave = _make_wave(mode="taskmaster", topology="team", task_id="42.3")
    cmd = replay.build_replay_command(
        wave,
        replay.ReplayOverrides(allow_live_reconstruction=True),
    )
    assert cmd[1] == "taskmaster"
    assert cmd[cmd.index("--topology") + 1] == "solo"


# ── format_replay_command ─────────────────────────────────────────────


# Scenario: Format command with special characters.
# Expected: Tokens with + are quoted.
def test_format_command_quoting() -> None:
    cmd = ["mainspring.sh", "night", "--pair", "claude+codex", "--once"]
    formatted = replay.format_replay_command(cmd)
    assert "'claude+codex'" in formatted


# Scenario: Format command with shell metacharacters and quotes.
# Expected: Preview remains safe to copy into a POSIX shell.
def test_format_command_quotes_shell_metacharacters() -> None:
    cmd = [
        "mainspring.sh",
        "night",
        "--model",
        "weird;model",
        "--review-model",
        "owner's model",
    ]

    formatted = replay.format_replay_command(cmd)

    assert "'weird;model'" in formatted
    assert "'owner'\"'\"'s model'" in formatted


# Scenario: Format replay environment overrides.
# Expected: Only explicit replay env vars are shown, sorted by key.
def test_format_environment_overrides() -> None:
    output = replay.format_environment_overrides({"B": "2", "A": "1"})
    assert output.splitlines() == ["A=1", "B=2"]


# Scenario: Format a passing validation preview.
# Expected: Operator sees that a real replay run would be allowed.
def test_format_validation_preview_ok() -> None:
    assert replay.format_validation_preview([]) == "Real-run validation: OK"


# Scenario: Format a failing validation preview.
# Expected: Operator sees each blocking validation reason.
def test_format_validation_preview_errors() -> None:
    output = replay.format_validation_preview(["missing prompt", "git drift"])
    assert "would fail" in output
    assert "missing prompt" in output
    assert "git drift" in output


# ── build_replay_metadata ────────────────────────────────────────────


# Scenario: Build metadata with no overrides.
# Expected: Original fields recorded, overrides empty.
def test_replay_metadata_no_overrides() -> None:
    wave = _make_wave(wave_id="w1", verdict="PASS")
    meta = replay.build_replay_metadata(wave)
    assert meta["original_wave_id"] == "w1"
    assert meta["original_verdict"] == "PASS"
    assert meta["overrides"] == {}


# Scenario: Build metadata with engine + reviewer overrides.
# Expected: Override changes recorded with arrow notation.
def test_replay_metadata_with_overrides() -> None:
    wave = _make_wave(writer="claude", reviewer="codex")
    overrides = replay.ReplayOverrides(engine="gemini", save_as="replay-1")
    meta = replay.build_replay_metadata(wave, overrides)
    assert "engine" in meta["overrides"]
    assert "claude → gemini" in meta["overrides"]["engine"]
    assert meta["replay_wave_id"] == "replay-1"


# Scenario: Prompt-backed replay metadata builds deterministic env overrides.
# Expected: Save-as provenance and prompt replay controls are present.
def test_build_replay_environment_overrides_prompt_snapshot() -> None:
    wave = _make_wave(
        wave_id="w1",
        task_id="42.3",
        prompt_path=".omx/logs/taskmaster-prompt-wave1.md",
    )
    overrides = replay.ReplayOverrides(save_as="replay-1")
    env = replay.build_replay_environment_overrides(wave, overrides)
    assert env["MAINSPRING_WAVE_ID_OVERRIDE"] == "replay-1"
    assert env["MAINSPRING_REPLAYED_FROM"] == "w1"
    assert (
        env["MAINSPRING_REPLAY_PROMPT_FILE"] == ".omx/logs/taskmaster-prompt-wave1.md"
    )
    assert env["MAINSPRING_REPLAY_TARGET_ID"] == "42.3"
    metadata = json.loads(env["MAINSPRING_REPLAY_OVERRIDES"])
    assert metadata["original_wave_id"] == "w1"
    assert metadata["replay_wave_id"] == "replay-1"


# Scenario: Prompt-backed replay runs without an explicit save-as id.
# Expected: Ledger provenance still records that the new row is a replay.
def test_build_replay_environment_overrides_tags_provenance_without_save_as() -> None:
    wave = _make_wave(
        wave_id="w1",
        task_id="42.3",
        prompt_path=".omx/logs/taskmaster-prompt-wave1.md",
    )

    env = replay.build_replay_environment_overrides(wave, replay.ReplayOverrides())

    assert "MAINSPRING_WAVE_ID_OVERRIDE" not in env
    assert env["MAINSPRING_REPLAYED_FROM"] == "w1"
    metadata = json.loads(env["MAINSPRING_REPLAY_OVERRIDES"])
    assert metadata["original_wave_id"] == "w1"
    assert metadata["overrides"] == {}


# Scenario: A legacy Taskmaster replay explicitly opts into live reconstruction.
# Expected: Environment anchors the rerun to the recorded work item.
def test_build_replay_environment_overrides_live_reconstruction_targets_work_item() -> (
    None
):
    wave = _make_wave(wave_id="legacy", task_id="42.3")

    env = replay.build_replay_environment_overrides(
        wave,
        replay.ReplayOverrides(allow_live_reconstruction=True),
    )

    assert env["MAINSPRING_REPLAY_LIVE_RECONSTRUCTION"] == "1"
    assert env["MAINSPRING_REPLAY_TARGET_ID"] == "42.3"
    assert env["MAINSPRING_REPLAY_ORIGINAL_MODE"] == "taskmaster"
    assert "MAINSPRING_REPLAY_PROMPT_FILE" not in env


# Scenario: Prompt snapshot hash matches the recorded ledger hash.
# Expected: Replay validation passes.
def test_validate_replay_inputs_accepts_matching_prompt_hash(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("original prompt\n", encoding="utf-8")
    wave = _make_wave(
        prompt_path=str(prompt),
        prompt_sha256=replay.file_sha256(prompt),
    )
    assert replay.validate_replay_inputs(wave, replay.ReplayOverrides(), tmp_path) == []


# Scenario: Prompt snapshot content drifted after the wave was recorded.
# Expected: Replay validation fails closed with a hash mismatch.
def test_validate_replay_inputs_rejects_prompt_hash_mismatch(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("changed prompt\n", encoding="utf-8")
    wave = _make_wave(prompt_path=str(prompt), prompt_sha256="0" * 64)
    errors = replay.validate_replay_inputs(wave, replay.ReplayOverrides(), tmp_path)
    assert any("sha256 mismatch" in error for error in errors)


# Scenario: A historical row lacks a prompt snapshot.
# Expected: Real replay fails closed unless live reconstruction is explicit.
def test_validate_replay_inputs_rejects_missing_prompt_snapshot() -> None:
    wave = _make_wave()
    errors = replay.validate_replay_inputs(wave, replay.ReplayOverrides())
    assert any("prompt snapshot is required" in error for error in errors)
    allowed = replay.ReplayOverrides(allow_live_reconstruction=True)
    assert replay.validate_replay_inputs(wave, allowed) == []


# Scenario: A historical row has no prompt snapshot and no stable live anchor.
# Expected: Even explicit live reconstruction fails closed.
def test_validate_replay_inputs_rejects_live_reconstruction_without_anchor() -> None:
    wave = _make_wave(mode="taskmaster", task_id="")
    errors = replay.validate_replay_inputs(
        wave,
        replay.ReplayOverrides(allow_live_reconstruction=True),
    )
    assert any("task_id/work_id or prd_path anchor" in error for error in errors)


# Scenario: Recorded git head differs from the current worktree.
# Expected: Replay validation fails unless drift is explicitly allowed.
def test_validate_replay_inputs_rejects_git_head_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(replay, "current_git_head", lambda root=None: "current")
    wave = _make_wave(git_head="recorded")
    errors = replay.validate_replay_inputs(wave, replay.ReplayOverrides())
    assert any("git head drift" in error for error in errors)
    allowed = replay.ReplayOverrides(
        allow_worktree_drift=True,
        allow_live_reconstruction=True,
    )
    assert replay.validate_replay_inputs(wave, allowed) == []


# Scenario: Recorded dirty status differs from the current worktree.
# Expected: Replay validation fails unless drift is explicitly allowed.
def test_validate_replay_inputs_rejects_git_status_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("original prompt\n", encoding="utf-8")
    monkeypatch.setattr(replay, "current_git_status", lambda root=None: " M other.py")
    wave = _make_wave(
        prompt_path=str(prompt),
        prompt_sha256=replay.file_sha256(prompt),
        git_status_before=" M py/replay.py",
    )

    errors = replay.validate_replay_inputs(wave, replay.ReplayOverrides(), tmp_path)

    assert any("git status drift" in error for error in errors)
    allowed = replay.ReplayOverrides(allow_worktree_drift=True)
    assert replay.validate_replay_inputs(wave, allowed, tmp_path) == []


# Scenario: A prompt-backed wave recorded a clean pre-wave worktree.
# Expected: Current dirty state is still treated as replay drift.
def test_validate_replay_inputs_rejects_clean_to_dirty_status_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("original prompt\n", encoding="utf-8")
    monkeypatch.setattr(
        replay,
        "current_git_status",
        lambda root=None: " M py/replay.py",
    )
    wave = _make_wave(
        prompt_path=str(prompt),
        prompt_sha256=replay.file_sha256(prompt),
        git_status_before="",
    )

    errors = replay.validate_replay_inputs(wave, replay.ReplayOverrides(), tmp_path)

    assert any("recorded clean, current 1 changed path" in error for error in errors)


# ── _parse_overrides ─────────────────────────────────────────────────


# Scenario: Parse a full set of override flags.
# Expected: All fields populated correctly.
def test_parse_overrides_full() -> None:
    args = [
        "--engine",
        "gemini",
        "--reviewer",
        "claude",
        "--model",
        "pro",
        "--review-model",
        "opus",
        "--save-as",
        "r1",
        "--dry-run",
        "--allow-worktree-drift",
        "--allow-live-reconstruction",
    ]
    o = replay._parse_overrides(args)
    assert o.engine == "gemini"
    assert o.reviewer == "claude"
    assert o.model == "pro"
    assert o.review_model == "opus"
    assert o.save_as == "r1"
    assert o.dry_run is True
    assert o.allow_worktree_drift is True
    assert o.allow_live_reconstruction is True


# Scenario: Parse empty args.
# Expected: All defaults (None/False/empty).
def test_parse_overrides_empty() -> None:
    o = replay._parse_overrides([])
    assert o.engine is None
    assert o.reviewer is None
    assert o.dry_run is False


# Scenario: Unknown replay flags are supplied.
# Expected: Parsing fails before building an ambiguous downstream command.
def test_parse_overrides_rejects_unknown_flag() -> None:
    with pytest.raises(
        replay.ReplayArgumentError,
        match="unknown replay override flag: --prd",
    ):
        replay._parse_overrides(["--prd", "docs/prd.md"])


# Scenario: A valued replay flag is provided without a value.
# Expected: Parsing fails before forwarding a malformed command to Mainspring.
@pytest.mark.parametrize(
    "flag",
    ["--engine", "--reviewer", "--model", "--review-model", "--save-as"],
)
def test_parse_overrides_rejects_missing_values(flag: str) -> None:
    with pytest.raises(replay.ReplayArgumentError, match=f"{flag} requires a value"):
        replay._parse_overrides([flag])


# Scenario: A valued replay flag is followed by another flag.
# Expected: The second flag is not silently treated as the missing value.
def test_parse_overrides_rejects_next_flag_as_value() -> None:
    with pytest.raises(replay.ReplayArgumentError, match="--engine requires a value"):
        replay._parse_overrides(["--engine", "--dry-run"])


# ── validate_replay_overrides ────────────────────────────────────────


# Scenario: Replay save-as id is unsafe or ambiguous.
# Expected: Validation rejects it before command construction or execution.
@pytest.mark.parametrize(
    ("save_as", "message"),
    [
        ("", "non-empty"),
        (" replay-1", "leading or trailing whitespace"),
        ("replay-1 ", "leading or trailing whitespace"),
        ("last", "reference alias"),
        ("#0", "reference alias"),
    ],
)
def test_validate_replay_overrides_rejects_unsafe_save_as(
    save_as: str,
    message: str,
) -> None:
    wave = _make_wave(wave_id="original")

    errors = replay.validate_replay_overrides(
        wave,
        replay.ReplayOverrides(save_as=save_as),
        [wave],
    )

    assert any(message in error for error in errors)


# Scenario: Replay save-as id duplicates any existing ledger row.
# Expected: Validation rejects it so replay provenance stays unique.
def test_validate_replay_overrides_rejects_duplicate_save_as() -> None:
    original = _make_wave(wave_id="original")
    existing_replay = _make_wave(wave_id="replay-1")

    errors = replay.validate_replay_overrides(
        original,
        replay.ReplayOverrides(save_as="replay-1"),
        [original, existing_replay],
    )

    assert errors == ["--save-as wave id already exists in ledger: replay-1"]


# Scenario: Replay save-as id is unique and reference-safe.
# Expected: Validation accepts it.
def test_validate_replay_overrides_accepts_unique_save_as() -> None:
    original = _make_wave(wave_id="original")
    existing = _make_wave(wave_id="other")

    assert (
        replay.validate_replay_overrides(
            original,
            replay.ReplayOverrides(save_as="replay-1"),
            [original, existing],
        )
        == []
    )


# ── CLI integration ───────────────────────────────────────────────────


# Scenario: No args -> usage message on stderr, exit 2.
def test_cli_no_args(capsys: pytest.CaptureFixture[str]) -> None:
    assert replay.main([]) == 2
    captured = capsys.readouterr()
    assert "Usage:" in captured.err
    assert captured.out == ""


# Scenario: --help -> usage message on stdout, exit 0.
def test_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert replay.main(["--help"]) == 0
    captured = capsys.readouterr()
    assert "Usage:" in captured.out
    assert "Examples:" in captured.out
    assert "mainspring replay show last .mainspring/logs/waves.jsonl" in captured.out
    assert (
        'mainspring replay diff "#-2" last .mainspring/logs/waves.jsonl' in captured.out
    )
    assert (
        "mainspring replay run last .mainspring/logs/waves.jsonl --dry-run --save-as replay-smoke"
        in captured.out
    )
    assert captured.err == ""


# Scenario: Unknown subcommand → error, exit 2.
def test_cli_unknown_subcmd() -> None:
    assert replay.main(["foobar"]) == 2


# Scenario: show with valid wave from ledger.
# Expected: exit 0, output contains wave details.
def test_cli_show(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = _write_ledger(tmp_path, [_make_wave(wave_id="test1")])
    rc = replay.main(["show", "test1", str(ledger)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "test1" in out
    assert "claude+codex" in out


# Scenario: show with nonexistent wave.
# Expected: exit 1.
def test_cli_show_not_found(tmp_path: Path) -> None:
    ledger = _write_ledger(tmp_path, [_make_wave(wave_id="a")])
    assert replay.main(["show", "zzz", str(ledger)]) == 1


# Scenario: show with missing ledger file.
# Expected: exit 1.
def test_cli_show_missing_ledger(tmp_path: Path) -> None:
    assert replay.main(["show", "w1", str(tmp_path / "nope.jsonl")]) == 1


# Scenario: diff two waves.
# Expected: exit 0, output contains comparison.
def test_cli_diff(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    waves = [
        _make_wave(wave_id="a", verdict="PASS"),
        _make_wave(wave_id="b", verdict="FAIL"),
    ]
    ledger = _write_ledger(tmp_path, waves)
    rc = replay.main(["diff", "a", "b", str(ledger)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Verdict drift" in out


# Scenario: build command for a wave.
# Expected: exit 0, output contains replay command.
def test_cli_build(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = _write_ledger(tmp_path, [_make_wave(wave_id="w1")])
    rc = replay.main(["build", "w1", str(ledger)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Replay command" in out
    assert "mainspring.sh" in out
    assert "Real-run validation: would fail" in out
    assert "prompt snapshot is required" in out


# Scenario: build command with overrides.
# Expected: exit 0, overrides reflected in metadata.
def test_cli_build_with_overrides(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = _write_ledger(tmp_path, [_make_wave(wave_id="w1")])
    rc = replay.main(
        ["build", "w1", str(ledger), "--engine", "gemini", "--reviewer", "claude"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "gemini" in out


# Scenario: build gets a malformed valued override flag.
# Expected: CLI fails fast with a usage-style exit code.
def test_cli_build_rejects_missing_override_value(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = _write_ledger(tmp_path, [_make_wave(wave_id="w1")])

    rc = replay.main(["build", "w1", str(ledger), "--engine"])

    assert rc == 2
    assert "--engine requires a value" in capsys.readouterr().err


# Scenario: build gets an unknown override flag.
# Expected: CLI fails fast instead of forwarding it to Mainspring.
def test_cli_build_rejects_unknown_override_flag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = _write_ledger(tmp_path, [_make_wave(wave_id="w1")])

    rc = replay.main(["build", "w1", str(ledger), "--bogus"])

    assert rc == 2
    assert "unknown replay override flag: --bogus" in capsys.readouterr().err


# Scenario: build gets a duplicate save-as id.
# Expected: CLI fails fast before printing a misleading replay command.
def test_cli_build_rejects_duplicate_save_as(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = _write_ledger(
        tmp_path,
        [_make_wave(wave_id="w1"), _make_wave(wave_id="replay-1")],
    )

    rc = replay.main(["build", "w1", str(ledger), "--save-as", "replay-1"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "wave id already exists" in captured.err
    assert "Replay command" not in captured.out


# Scenario: run with --dry-run.
# Expected: exit 0, prints command without executing.
def test_cli_run_dry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = _write_ledger(tmp_path, [_make_wave(wave_id="w1")])
    rc = replay.main(["run", "w1", str(ledger), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Dry run" in out
    assert "mainspring.sh" in out
    assert "Original wave summary" in out
    assert "Real-run validation: would fail" in out
    assert "prompt snapshot is required" in out


# Scenario: run with --dry-run and overrides.
# Expected: exit 0, overrides visible in output.
def test_cli_run_dry_with_overrides(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = _write_ledger(tmp_path, [_make_wave(wave_id="w1")])
    rc = replay.main(
        [
            "run",
            "w1",
            str(ledger),
            "--dry-run",
            "--reviewer",
            "gemini",
            "--save-as",
            "replay-1",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "gemini" in out
    assert "replay-1" in out


# Scenario: run gets a malformed valued override flag.
# Expected: CLI fails fast before validation or subprocess execution.
def test_cli_run_rejects_missing_override_value(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = _write_ledger(tmp_path, [_make_wave(wave_id="w1")])

    rc = replay.main(["run", "w1", str(ledger), "--review-model"])

    assert rc == 2
    assert "--review-model requires a value" in capsys.readouterr().err


# Scenario: run gets an unknown override flag.
# Expected: CLI fails before validation or subprocess execution.
def test_cli_run_rejects_unknown_override_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = _write_ledger(tmp_path, [_make_wave(wave_id="w1")])

    def fake_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(replay.subprocess, "run", fake_run)
    rc = replay.main(["run", "w1", str(ledger), "--bogus"])

    assert rc == 2
    assert "unknown replay override flag: --bogus" in capsys.readouterr().err


# Scenario: run gets a save-as id that resolves like a special wave reference.
# Expected: CLI rejects it before validation or subprocess execution.
def test_cli_run_rejects_special_ref_save_as(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = _write_ledger(tmp_path, [_make_wave(wave_id="w1")])

    def fake_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(replay.subprocess, "run", fake_run)
    rc = replay.main(["run", "w1", str(ledger), "--save-as", "last"])

    assert rc == 2
    assert "reference alias" in capsys.readouterr().err


# Scenario: Dry-run for a prompt-backed row with matching prompt hash.
# Expected: Operator sees that a real replay run would be allowed.
def test_cli_run_dry_reports_validation_ok(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("replay prompt\n", encoding="utf-8")
    ledger = _write_ledger(
        tmp_path,
        [
            _make_wave(
                wave_id="w1",
                prompt_path=str(prompt),
                prompt_sha256=replay.file_sha256(prompt),
            )
        ],
    )

    rc = replay.main(["run", "w1", str(ledger), "--dry-run"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Real-run validation: OK" in out


# Scenario: Real replay of a historical row without prompt snapshot.
# Expected: CLI fails before executing a non-deterministic command.
def test_cli_run_rejects_missing_prompt_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = _write_ledger(tmp_path, [_make_wave(wave_id="legacy")])

    def fake_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(replay.subprocess, "run", fake_run)
    rc = replay.main(["run", "legacy", str(ledger)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "prompt snapshot is required" in err


# Scenario: Real replay of a legacy row explicitly allows live reconstruction.
# Expected: CLI executes one solo run anchored to the recorded work item.
def test_cli_run_allow_live_reconstruction_targets_recorded_work_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _write_ledger(tmp_path, [_make_wave(wave_id="legacy", task_id="42.3")])
    captured: dict[str, object] = {}

    def fake_run(
        cmd: list[str],
        check: bool = False,
        env: dict[str, str] | None = None,
    ) -> object:
        captured["cmd"] = cmd
        captured["env"] = env
        return _ReplayRunResult(0)

    monkeypatch.setattr(replay.subprocess, "run", fake_run)

    rc = replay.main(["run", "legacy", str(ledger), "--allow-live-reconstruction"])

    assert rc == 0
    assert captured["cmd"][captured["cmd"].index("--topology") + 1] == "solo"
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["MAINSPRING_REPLAY_LIVE_RECONSTRUCTION"] == "1"
    assert env["MAINSPRING_REPLAY_TARGET_ID"] == "42.3"
    assert env["MAINSPRING_REPLAYED_FROM"] == "legacy"


class _ReplayRunResult:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_cmd_run_saves_as_new_wave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("replay prompt\n", encoding="utf-8")
    ledger = _write_ledger(
        tmp_path,
        [
            _make_wave(
                wave_id="w1",
                prompt_path=str(prompt),
                prompt_sha256=replay.file_sha256(prompt),
            )
        ],
    )

    captured: dict[str, object] = {}

    def fake_run(
        cmd: list[str],
        check: bool = False,
        env: dict[str, str] | None = None,
    ) -> object:
        captured["cmd"] = cmd
        captured["env"] = env
        return _ReplayRunResult(0)

    monkeypatch.setattr(replay.subprocess, "run", fake_run)

    rc = replay.main(
        ["run", "w1", str(ledger), "--save-as", "replay-1", "--engine", "gemini"]
    )

    assert rc == 0
    assert "--pair" in captured["cmd"]
    assert "gemini+codex" in captured["cmd"]
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["MAINSPRING_WAVE_ID_OVERRIDE"] == "replay-1"
    assert env["MAINSPRING_REPLAYED_FROM"] == "w1"
    replay_overrides = json.loads(env["MAINSPRING_REPLAY_OVERRIDES"])
    assert replay_overrides["replay_wave_id"] == "replay-1"
    assert replay_overrides["overrides"]["engine"] == "claude → gemini"


# Scenario: Resolve wave using #-1 (last) in CLI show.
# Expected: Shows the last wave.
def test_cli_show_last_index(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    waves = [_make_wave(wave_id="first"), _make_wave(wave_id="last-one")]
    ledger = _write_ledger(tmp_path, waves)
    rc = replay.main(["show", "#-1", str(ledger)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "last-one" in out


# ── end-to-end determinism fixture ───────────────────────────────────


# Scenario: Build command for same wave twice.
# Expected: Identical commands produced (deterministic reconstruction).
def test_deterministic_reconstruction() -> None:
    wave = _make_wave(
        wave_id="det-1",
        mode="night",
        topology="solo",
        writer="claude",
        reviewer="codex",
        writer_model="opus",
        reviewer_model="gpt-5.5",
    )
    cmd1 = replay.build_replay_command(wave)
    cmd2 = replay.build_replay_command(wave)
    assert cmd1 == cmd2


# Scenario: Build command, then apply overrides, rebuild.
# Expected: Override changes are reflected; original unchanged.
def test_override_does_not_mutate_original() -> None:
    wave = _make_wave(writer="claude", reviewer="codex")
    overrides = replay.ReplayOverrides(engine="gemini")
    cmd_overridden = replay.build_replay_command(wave, overrides)
    cmd_original = replay.build_replay_command(wave)
    # Original still says claude+codex
    pair_idx = cmd_original.index("--pair") + 1
    assert cmd_original[pair_idx] == "claude+codex"
    # Overridden says gemini+codex
    pair_idx2 = cmd_overridden.index("--pair") + 1
    assert cmd_overridden[pair_idx2] == "gemini+codex"
