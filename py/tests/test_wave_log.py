# SPDX-License-Identifier: Apache-2.0
"""Tests for wave_log.py — wave ledger JSONL operations."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import wave_log


def _set_wave_env(**overrides: str) -> dict[str, str]:
    """Set a minimal set of wave env vars and return the mapping."""
    defaults = {
        "WAVE_ID": "wave-001",
        "MODE_VALUE": "taskmaster",
        "TOPOLOGY_VALUE": "solo",
        "TEAM_VALUE": "",
        "TEAM_NAME_VALUE": "",
        "TASK_ID_VALUE": "42",
        "TASK_STATUS_BEFORE_VALUE": "pending",
        "TASK_STATUS_AFTER_VALUE": "review",
        "SELECTED_LANE": "src",
        "ENGINE_VALUE": "claude",
        "REVIEWER_VALUE": "codex",
        "MODEL_VALUE": "opus",
        "REVIEW_MODEL_VALUE": "gpt-5.5",
        "REASONING_VALUE": "xhigh",
        "START_EPOCH": "1000",
        "END_EPOCH": "1060",
        "EXIT_CODE_VALUE": "0",
        "CHANGED_FILES_VALUE": "src/App.tsx\nsrc/main.tsx",
        "VERDICT_VALUE": "PASS",
        "FAILURE_REASON_VALUE": "",
        "FAILURE_REASON_CLASS_VALUE": "",
        "RETRY_COUNT_VALUE": "0",
        "BLOCKED_REASON_VALUE": "",
        "NEXT_ACTION_VALUE": "",
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        os.environ[k] = v
    return defaults


def _cleanup_env() -> None:
    for key in list(os.environ):
        if key in {
            "WAVE_ID",
            "MODE_VALUE",
            "TOPOLOGY_VALUE",
            "TEAM_VALUE",
            "TEAM_NAME_VALUE",
            "TASK_ID_VALUE",
            "TASK_STATUS_BEFORE_VALUE",
            "TASK_STATUS_AFTER_VALUE",
            "SELECTED_LANE",
            "ENGINE_VALUE",
            "REVIEWER_VALUE",
            "MODEL_VALUE",
            "REVIEW_MODEL_VALUE",
            "REASONING_VALUE",
            "START_EPOCH",
            "END_EPOCH",
            "EXIT_CODE_VALUE",
            "CHANGED_FILES_VALUE",
            "VERDICT_VALUE",
            "FAILURE_REASON_VALUE",
            "FAILURE_REASON_CLASS_VALUE",
            "FALLBACK_ENGINE_USED_VALUE",
            "PROMPT_PATH_VALUE",
            "PROMPT_SHA256_VALUE",
            "GIT_HEAD_VALUE",
            "GIT_STATUS_BEFORE_VALUE",
            "PRD_PATH_VALUE",
            "USAGE_PATH_VALUE",
            "REPLAYED_FROM_VALUE",
            "REPLAY_OVERRIDES_VALUE",
            "RETRY_COUNT_VALUE",
            "BLOCKED_REASON_VALUE",
            "NEXT_ACTION_VALUE",
        }:
            del os.environ[key]


# ── build_wave_entry ────────────────────────────────────────────────────


# Scenario: All env vars set with typical values.
# Expected: entry has correct fields, duration=60, changed_files split.
def test_build_wave_entry_happy_path() -> None:
    _set_wave_env()
    try:
        entry = wave_log.build_wave_entry()
        assert entry["wave_id"] == "wave-001"
        assert entry["wave"] == 0
        assert entry["mode"] == "taskmaster"
        assert entry["duration_s"] == 60
        assert entry["duration_seconds"] == 60
        assert entry["changed_files"] == ["src/App.tsx", "src/main.tsx"]
        assert entry["product_files_changed"] == 2
        assert entry["team_name"] == ""
        assert entry["task_status_before"] == "pending"
        assert entry["task_status_after"] == "review"
        assert entry["failure_reason_class"] == ""
        assert entry["fallback_engine_used"] is False
        assert entry["verdict"] == "PASS"
        assert entry["exit_code"] == 0
        assert entry["engine"] == "claude"
        assert entry["review_engine"] == "codex"
        assert entry["pair"] == "claude+codex"
        assert entry["model"] == "opus"
        assert entry["review_model"] == "gpt-5.5"
        assert entry["engines"]["writer"] == "claude"
        assert entry["engines"]["reviewer"] == "codex"
        assert entry["models"]["writer"] == "opus"
        assert entry["models"]["reviewer"] == "gpt-5.5"
        assert entry["retry_used"] is False
        assert "ts" in entry
        assert "timestamp" in entry
        assert entry["ts"] == entry["timestamp"]
    finally:
        _cleanup_env()


# Scenario: changed_files contains cache, ignored state, docs, and one source file.
# Expected: product_files_changed counts only the source/product path.
def test_build_wave_entry_counts_only_product_files() -> None:
    _set_wave_env(
        CHANGED_FILES_VALUE=(
            ".pytest_cache/v/cache/nodeids\n"
            ".ruff_cache/0.15.11/cache\n"
            ".taskmaster/tasks/tasks.json\n"
            ".gradle/8.10.2/fileHashes/fileHashes.bin\n"
            "build/test-results/test/TEST-Foo.xml\n"
            "dist/assets/app.js\n"
            "target/classes/App.class\n"
            "server/tracker.db-shm\n"
            "server/tracker.db-wal\n"
            "py/__pycache__/wave_log.cpython-314.pyc\n"
            "AGENTS.md\n"
            "README.md\n"
            "docs/prd.md\n"
            "py/wave_log.py"
        )
    )
    try:
        entry = wave_log.build_wave_entry()
        assert entry["product_files_changed"] == 1
        assert entry["changed_files"][-1] == "py/wave_log.py"
    finally:
        _cleanup_env()


# Scenario: Missing env vars.
# Expected: entry has empty strings / defaults, no crash.
def test_build_wave_entry_missing_env() -> None:
    _cleanup_env()
    entry = wave_log.build_wave_entry()
    assert entry["wave_id"] == ""
    assert entry["wave"] == 0
    assert entry["mode"] == ""
    assert entry["duration_s"] == 0
    assert entry["duration_seconds"] == 0
    assert entry["changed_files"] == []
    assert entry["product_files_changed"] == 0
    assert entry["exit_code"] == 0
    assert entry["team_name"] == ""
    assert entry["task_status_before"] == ""
    assert entry["task_status_after"] == ""
    assert entry["failure_reason_class"] == ""
    assert entry["pair"] == ""


# Scenario: Numeric wave id from solo loop.
# Expected: canonical wave field preserves the 1-indexed wave number.
def test_build_wave_entry_numeric_wave_alias() -> None:
    _set_wave_env(WAVE_ID="7", RETRY_COUNT_VALUE="1")
    try:
        entry = wave_log.build_wave_entry()
        assert entry["wave"] == 7
        assert entry["wave_id"] == "7"
        assert entry["retry_used"] is True
    finally:
        _cleanup_env()


# Scenario: A future fallback path can mark the ledger row explicitly.
# Expected: fallback_engine_used records the boolean truth for release evidence readers.
def test_build_wave_entry_records_fallback_engine_used() -> None:
    _set_wave_env(FALLBACK_ENGINE_USED_VALUE="true")
    try:
        entry = wave_log.build_wave_entry()
        assert entry["fallback_engine_used"] is True
    finally:
        _cleanup_env()


# Scenario: Failure reason is prefixed.
# Expected: failure_reason_class stores the canonical machine reason.
def test_build_wave_entry_derives_failure_reason_class() -> None:
    _set_wave_env(FAILURE_REASON_VALUE="review:gate_failed")
    try:
        entry = wave_log.build_wave_entry()
        assert entry["failure_reason"] == "review:gate_failed"
        assert entry["failure_reason_class"] == "review:gate_failed"
    finally:
        _cleanup_env()


# Scenario: Explicit failure class is supplied by a future caller.
# Expected: explicit class wins over derived prefix.
def test_build_wave_entry_explicit_failure_reason_class() -> None:
    _set_wave_env(
        FAILURE_REASON_VALUE="review:gate_failed",
        FAILURE_REASON_CLASS_VALUE="review:custom",
    )
    try:
        entry = wave_log.build_wave_entry()
        assert entry["failure_reason_class"] == "review:custom"
    finally:
        _cleanup_env()


# Scenario: A legacy caller provides a bare top-level failure class.
# Expected: the ledger upgrades it to the full reason when available.
def test_build_wave_entry_upgrades_legacy_bare_failure_class() -> None:
    _set_wave_env(
        FAILURE_REASON_VALUE="review:gate_failed",
        FAILURE_REASON_CLASS_VALUE="review",
    )
    try:
        entry = wave_log.build_wave_entry()
        assert entry["failure_reason_class"] == "review:gate_failed"
    finally:
        _cleanup_env()


# Scenario: An explicit class conflicts with the reason prefix.
# Expected: the ledger keeps the real prefixed reason as the canonical class.
def test_build_wave_entry_rejects_mismatched_failure_class() -> None:
    _set_wave_env(
        FAILURE_REASON_VALUE="engine:quota",
        FAILURE_REASON_CLASS_VALUE="review:custom",
    )
    try:
        entry = wave_log.build_wave_entry()
        assert entry["failure_reason_class"] == "engine:quota"
    finally:
        _cleanup_env()


# Scenario: A malformed unprefixed reason reaches the ledger writer.
# Expected: failure_reason is preserved, but no canonical class is fabricated.
def test_build_wave_entry_does_not_classify_unprefixed_failure_reason() -> None:
    _set_wave_env(FAILURE_REASON_VALUE="worker_exit_nonzero")
    try:
        entry = wave_log.build_wave_entry()
        assert entry["failure_reason"] == "worker_exit_nonzero"
        assert entry["failure_reason_class"] == ""
    finally:
        _cleanup_env()


# Scenario: Replay env vars are present.
# Expected: ledger row carries replay provenance without changing other fields.
def test_build_wave_entry_replay_metadata() -> None:
    _set_wave_env(
        REPLAYED_FROM_VALUE="original-wave",
        REPLAY_OVERRIDES_VALUE='{"overrides":{"engine":"claude → gemini"}}',
    )
    try:
        entry = wave_log.build_wave_entry()
        assert entry["wave_id"] == "wave-001"
        assert entry["replayed_from"] == "original-wave"
        assert entry["replay_overrides"]["overrides"]["engine"] == "claude → gemini"
    finally:
        _cleanup_env()


# Scenario: Prompt/worktree provenance env vars are present.
# Expected: ledger row carries replay reconstruction metadata.
def test_build_wave_entry_prompt_worktree_metadata() -> None:
    _set_wave_env(
        PROMPT_PATH_VALUE=".omx/logs/night-prompt-wave1.md",
        PROMPT_SHA256_VALUE="abc123",
        GIT_HEAD_VALUE="deadbeef",
        GIT_STATUS_BEFORE_VALUE=" M py/replay.py",
        PRD_PATH_VALUE="docs/prd.md",
    )
    try:
        entry = wave_log.build_wave_entry()
        assert entry["prompt_path"] == ".omx/logs/night-prompt-wave1.md"
        assert entry["prompt_sha256"] == "abc123"
        assert entry["git_head"] == "deadbeef"
        assert entry["git_status_before"] == " M py/replay.py"
        assert entry["prd_path"] == "docs/prd.md"
    finally:
        _cleanup_env()


# Scenario: Prompt-backed wave starts from a clean worktree.
# Expected: clean git_status_before is preserved as an explicit empty field.
def test_build_wave_entry_preserves_clean_git_status_metadata() -> None:
    _set_wave_env(
        PROMPT_PATH_VALUE=".omx/logs/night-prompt-wave1.md",
        PROMPT_SHA256_VALUE="abc123",
        GIT_HEAD_VALUE="deadbeef",
        GIT_STATUS_BEFORE_VALUE="",
    )
    try:
        entry = wave_log.build_wave_entry()
        assert "git_status_before" in entry
        assert entry["git_status_before"] == ""
    finally:
        _cleanup_env()


# Scenario: LiteLLM usage sidecar rows are present for writer and reviewer.
# Expected: ledger entry carries aggregate cost plus per-role token splits.
def test_build_wave_entry_aggregates_litellm_usage_sidecar(tmp_path: Path) -> None:
    usage_file = tmp_path / "usage.jsonl"
    usage_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "engine": "litellm",
                        "role": "writer",
                        "model": "gpt-5.5",
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 40,
                            "total_tokens": 140,
                        },
                        "cost_usd": 0.01,
                        "cost_source": "litellm.completion_cost",
                    }
                ),
                json.dumps(
                    {
                        "engine": "litellm",
                        "role": "reviewer",
                        "model": "gpt-5.5",
                        "usage": {
                            "prompt_tokens": 50,
                            "completion_tokens": 10,
                            "total_tokens": 60,
                        },
                        "cost_usd": 0.004,
                        "cost_source": "litellm.completion_cost",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _set_wave_env(USAGE_PATH_VALUE=str(usage_file))
    try:
        entry = wave_log.build_wave_entry()
    finally:
        _cleanup_env()

    assert entry["cost_usd"] == 0.014
    assert entry["total_cost_usd"] == 0.014
    assert entry["usage"]["input_tokens"] == 150
    assert entry["usage"]["output_tokens"] == 50
    assert entry["usage"]["total_tokens"] == 200
    assert entry["usage"]["writer"]["input_tokens"] == 100
    assert entry["usage"]["writer"]["output_tokens"] == 40
    assert entry["usage"]["writer"]["cost_usd"] == 0.01
    assert entry["usage"]["reviewer"]["input_tokens"] == 50
    assert entry["usage"]["reviewer"]["output_tokens"] == 10
    assert entry["usage"]["reviewer"]["cost_usd"] == 0.004
    assert entry["usage"]["cost_source"] == "litellm.completion_cost"


# Scenario: Non-integer epoch values.
# Expected: duration defaults to 0, no crash.
def test_build_wave_entry_bad_epoch() -> None:
    _set_wave_env(START_EPOCH="abc", END_EPOCH="xyz")
    try:
        entry = wave_log.build_wave_entry()
        assert entry["duration_seconds"] == 0
    finally:
        _cleanup_env()


# Scenario: The public metrics docs should describe emitted and consumed fields.
# Expected: docs/metrics.md names every current ledger field.
def test_metrics_docs_cover_wave_ledger_fields() -> None:
    _set_wave_env(
        PROMPT_PATH_VALUE=".omx/logs/night-prompt-wave1.md",
        PROMPT_SHA256_VALUE="abc123",
        GIT_HEAD_VALUE="deadbeef",
        GIT_STATUS_BEFORE_VALUE="",
        PRD_PATH_VALUE="docs/prd.md",
        REPLAYED_FROM_VALUE="source-wave",
        REPLAY_OVERRIDES_VALUE='{"reviewer":"codex"}',
    )
    try:
        entry = wave_log.build_wave_entry()
    finally:
        _cleanup_env()

    repo_root = HERE.parents[1]
    metrics_doc = repo_root / "docs" / "metrics.md"
    text = metrics_doc.read_text(encoding="utf-8")

    emitted_fields = set(entry)
    consumed_fields = {
        "chapter_delta",
        "competitor_delta",
        "launch_delta",
        "product_score",
        "product_score_delta",
        "score_delta",
        "codex_short_delta_pct",
        "claude_short_delta",
        "gemini_short_delta_pct",
        "cost_usd",
        "total_cost_usd",
        "usage",
    }
    missing = sorted(
        field for field in emitted_fields | consumed_fields if f"`{field}`" not in text
    )
    assert missing == []


# ── cmd_append ──────────────────────────────────────────────────────────


def test_cmd_append_valid_json(tmp_path: Path) -> None:
    _set_wave_env()
    try:
        import subprocess

        result = subprocess.run(
            [sys.executable, str(HERE.parent / "wave_log.py"), "append"],
            capture_output=True,
            text=True,
            env={**os.environ},
            check=False,
        )
        assert result.returncode == 0
        line = result.stdout.strip()
        entry = json.loads(line)
        assert entry["wave_id"] == "wave-001"
    finally:
        _cleanup_env()


# ── last-summary ────────────────────────────────────────────────────────


# Scenario: Empty file.
# Expected: "last-wave: none".
def test_last_summary_empty(tmp_path: Path, capsys: object) -> None:
    ledger = tmp_path / "waves.jsonl"
    ledger.write_text("")
    wave_log.cmd_last_summary(str(ledger))
    # Verify via subprocess for reliable capture
    import subprocess

    result = subprocess.run(
        [sys.executable, str(HERE.parent / "wave_log.py"), "last-summary", str(ledger)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "last-wave: none" in result.stdout


# Scenario: File does not exist.
# Expected: "last-wave: none".
def test_last_summary_missing_file(tmp_path: Path) -> None:
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "wave_log.py"),
            "last-summary",
            str(tmp_path / "nope.jsonl"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "last-wave: none" in result.stdout


# Scenario: Valid ledger with two entries.
# Expected: summary shows the second entry's data.
def test_last_summary_shows_last_entry(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    e1 = {
        "wave_id": "w1",
        "mode": "taskmaster",
        "topology": "solo",
        "verdict": "PASS",
        "duration_seconds": 30,
    }
    e2 = {
        "wave_id": "w2",
        "mode": "night",
        "topology": "team",
        "verdict": "FAIL",
        "duration_seconds": 120,
        "failure_reason": "review:bad",
    }
    ledger.write_text(json.dumps(e1) + "\n" + json.dumps(e2) + "\n")
    import subprocess

    result = subprocess.run(
        [sys.executable, str(HERE.parent / "wave_log.py"), "last-summary", str(ledger)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "id=w2" in result.stdout
    assert "mode=night" in result.stdout
    assert "failure=review:bad" in result.stdout


# ── routing-hints ───────────────────────────────────────────────────────


# Scenario: Empty ledger.
# Expected: "no wave metrics yet".
def test_routing_hints_empty(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    ledger.write_text("")
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "wave_log.py"),
            "routing-hints",
            str(ledger),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "no wave metrics yet" in result.stdout


# Scenario: 3+ recent failures.
# Expected: "stop/review recommended".
def test_routing_hints_repeated_failures(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    entries = [{"verdict": "FAIL", "exit_code": 1} for _ in range(4)]
    ledger.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "wave_log.py"),
            "routing-hints",
            str(ledger),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "stop/review recommended" in result.stdout


# Scenario: 2+ review failures.
# Expected: "retry same item in solo mode".
def test_routing_hints_review_failures(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    entries = [
        {"verdict": "PASS", "exit_code": 0, "failure_reason": ""},
        {"verdict": "FAIL", "exit_code": 0, "failure_reason": "review:missing_fields"},
        {"verdict": "FAIL", "exit_code": 0, "failure_reason": "review:invalid_json"},
    ]
    ledger.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "wave_log.py"),
            "routing-hints",
            str(ledger),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "retry same item in solo mode" in result.stdout


# Scenario: Team wave with team:no_parallel_safe_work.
# Expected: "use solo mode".
def test_routing_hints_team_no_parallel(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    entries = [
        {"verdict": "PASS", "exit_code": 0, "topology": "solo"},
        {
            "verdict": "FAIL",
            "exit_code": 0,
            "topology": "team",
            "failure_reason": "team:no_parallel_safe_work",
        },
    ]
    ledger.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "wave_log.py"),
            "routing-hints",
            str(ledger),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "use solo mode" in result.stdout


# Scenario: All waves pass.
# Expected: "no failure trend detected".
def test_routing_hints_no_failures(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    entries = [{"verdict": "PASS", "exit_code": 0} for _ in range(3)]
    ledger.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(HERE.parent / "wave_log.py"),
            "routing-hints",
            str(ledger),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "no failure trend detected" in result.stdout


# ── flock-guarded append ────────────────────────────────────────────────


# Scenario: cmd_append with --ledger writes directly to the file.
# Expected: ledger file contains a valid JSON line.
def test_cmd_append_with_ledger(tmp_path: Path) -> None:
    _set_wave_env()
    try:
        ledger = tmp_path / "waves.jsonl"
        wave_log.cmd_append(str(ledger))
        assert ledger.is_file()
        entries = wave_log.read_ledger(ledger)
        assert len(entries) == 1
        assert entries[0]["wave_id"] == "wave-001"
    finally:
        _cleanup_env()


# Scenario: cmd_append with --ledger creates lock file.
# Expected: lock file exists after append.
def test_cmd_append_creates_lock_file(tmp_path: Path) -> None:
    _set_wave_env()
    try:
        ledger = tmp_path / "waves.jsonl"
        wave_log.cmd_append(str(ledger))
        lock = tmp_path / "waves.jsonl.lock"
        assert lock.is_file()
    finally:
        _cleanup_env()


# Scenario: cmd_append without ledger path prints to stdout.
# Expected: no file created, output goes to stdout.
def test_cmd_append_stdout_fallback(capsys: object) -> None:
    _set_wave_env()
    try:
        wave_log.cmd_append(None)
        captured = capsys.readouterr()  # type: ignore[union-attr]
        entry = json.loads(captured.out.strip())
        assert entry["wave_id"] == "wave-001"
    finally:
        _cleanup_env()


# Scenario: Multiple concurrent appends to the same ledger.
# Expected: all entries survive (flock serialises writes).
def test_cmd_append_concurrent_safety(tmp_path: Path) -> None:
    import subprocess

    ledger = tmp_path / "waves.jsonl"
    procs = []
    for i in range(5):
        env = {**os.environ}
        env["WAVE_ID"] = f"concurrent-{i}"
        env["MODE_VALUE"] = "taskmaster"
        env["ENGINE_VALUE"] = "claude"
        env["REVIEWER_VALUE"] = "codex"
        env["START_EPOCH"] = "1000"
        env["END_EPOCH"] = "1060"
        env["EXIT_CODE_VALUE"] = "0"
        env["CHANGED_FILES_VALUE"] = ""
        env["VERDICT_VALUE"] = "PASS"
        p = subprocess.Popen(
            [
                sys.executable,
                str(HERE.parent / "wave_log.py"),
                "append",
                "--ledger",
                str(ledger),
            ],
            env=env,
        )
        procs.append(p)
    for p in procs:
        p.wait()
    entries = wave_log.read_ledger(ledger)
    assert len(entries) == 5
    ids = {e["wave_id"] for e in entries}
    assert ids == {f"concurrent-{i}" for i in range(5)}


# ── read_ledger ─────────────────────────────────────────────────────────


# Scenario: Mixed valid and invalid JSONL lines.
# Expected: only valid entries returned.
def test_read_ledger_skips_invalid(tmp_path: Path) -> None:
    ledger = tmp_path / "waves.jsonl"
    ledger.write_text('{"ok": true}\nnot json\n{"also": "ok"}\n')
    entries = wave_log.read_ledger(ledger)
    assert len(entries) == 2
    assert entries[0]["ok"] is True
    assert entries[1]["also"] == "ok"


# Reader shape guard: syntactically valid scalar/array values are not wave rows.
NON_OBJECT_JSON = ["[]", "[1,2]", '"text"', "0", "1.25", "true", "false", "null"]


def _run_private_reader(command: str, ledger: Path):
    import subprocess

    return subprocess.run(
        [sys.executable, str(HERE.parent / "wave_log.py"), command, str(ledger)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_read_ledger_skips_valid_non_object_rows(tmp_path: Path) -> None:
    ledger = tmp_path / "synthetic-waves.jsonl"
    ledger.write_text(
        '{"wave_id":"first"}\n{}\n'
        + "\n".join(NON_OBJECT_JSON)
        + '\nnot json\n{"wave_id":"last"}\n'
    )
    assert wave_log.read_ledger(ledger) == [
        {"wave_id": "first"},
        {},
        {"wave_id": "last"},
    ]


@pytest.mark.parametrize("bad_row", NON_OBJECT_JSON)
def test_last_summary_ignores_non_object_rows(tmp_path: Path, bad_row: str) -> None:
    ledger = tmp_path / "synthetic-waves.jsonl"
    wave = {
        "wave_id": "synthetic-last",
        "verdict": "FAIL",
        "exit_code": 1,
        "failure_reason": "review:synthetic",
    }
    ledger.write_text(json.dumps(wave) + "\n" + bad_row + "\n")
    result = _run_private_reader("last-summary", ledger)
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "id=synthetic-last" in result.stdout
    assert "verdict=FAIL" in result.stdout
    assert "failure=review:synthetic" in result.stdout


@pytest.mark.parametrize("bad_row", NON_OBJECT_JSON)
def test_routing_hints_ignores_non_object_rows_without_losing_failure_trend(
    tmp_path: Path, bad_row: str
) -> None:
    ledger = tmp_path / "synthetic-waves.jsonl"
    waves = [
        {"wave_id": f"synthetic-{index}", "verdict": "FAIL", "exit_code": 1}
        for index in range(3)
    ]
    ledger.write_text(
        "\n".join(json.dumps(row) for row in waves) + "\n" + bad_row + "\n"
    )
    result = _run_private_reader("routing-hints", ledger)
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "stop/review recommended" in result.stdout


def test_all_non_object_rows_are_no_valid_wave_entries(tmp_path: Path) -> None:
    ledger = tmp_path / "synthetic-waves.jsonl"
    ledger.write_text("\n".join(NON_OBJECT_JSON) + "\n")
    summary = _run_private_reader("last-summary", ledger)
    routing = _run_private_reader("routing-hints", ledger)
    assert summary.returncode == routing.returncode == 0
    assert "no valid ledger entries" in summary.stdout
    assert "no valid wave metrics" in routing.stdout
    assert "Traceback" not in summary.stderr + routing.stderr
