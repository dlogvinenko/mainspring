# SPDX-License-Identifier: Apache-2.0
"""Regression tests for Claude adapter failure classification.

Scenario: ``lib/wave_loop_state.sh`` passes the whole writer display file as
``--raw-tail-file``. A writer that merely talks about a product "quota" or
"rate limit" feature and then exits non-zero must not be classified as
``engine:quota``; only the engine's own error evidence may do that.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY_DIR = HERE.parent
sys.path.insert(0, str(PY_DIR))

from engines import claude

SCRIPT = str(PY_DIR / "engine_registry.py")

BENIGN_DISPLAY = """[claude] session started (claude-opus-4-7)
Implementing the per-tenant quota feature.
[tool] Bash: pytest -q tests/test_quota.py
[tool-result] 3 passed
Added rate limit middleware tests; the quota ledger now rejects overspend.

[claude] turn complete
"""

QUOTA_ERROR_DISPLAY = """[claude] session started (claude-opus-4-7)
Starting work on the login form.

[claude] error: API Error: 429 rate_limit_error: This request would exceed \
your account's rate limit
"""

REVIEWER_QUOTA_ERROR_DISPLAY = """[review-claude] session started (claude-opus-4-7)
[review-tool] Read
[review-claude] error: You have hit your usage limit. Try again later.
"""


def _stream_json_log(*events: dict) -> str:
    return "\n".join(json.dumps(event) for event in events) + "\n"


# Scenario: writer prose mentions quota and rate limits, engine exits 1.
# Expected: generic non-zero exit, not engine:quota.
def test_display_prose_mentioning_quota_is_not_quota_failure() -> None:
    failure = claude.ADAPTER.detect_failure(1, BENIGN_DISPLAY)

    assert failure.failed is True
    assert failure.reason == "engine:exit_nonzero"


# Scenario: prettified writer display ends with an engine error line.
# Expected: engine:quota, detail is the error line only.
def test_display_error_line_with_rate_limit_is_quota_failure() -> None:
    failure = claude.ADAPTER.detect_failure(1, QUOTA_ERROR_DISPLAY)

    assert failure.failed is True
    assert failure.reason == "engine:quota"
    assert failure.detail.startswith("[claude] error: API Error: 429")
    assert "Starting work on the login form." not in failure.detail


# Scenario: reviewer display reports a usage limit through its error line.
# Expected: engine:quota.
def test_reviewer_display_usage_limit_is_quota_failure() -> None:
    failure = claude.ADAPTER.detect_failure(1, REVIEWER_QUOTA_ERROR_DISPLAY)

    assert failure.failed is True
    assert failure.reason == "engine:quota"


# Scenario: raw stream-json log where the result event is an error.
# Expected: the result text drives the classification.
def test_stream_json_result_error_drives_classification() -> None:
    quota_log = _stream_json_log(
        {"type": "system", "subtype": "init", "model": "claude-opus-4-7"},
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "quota feature"}]},
        },
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "result": "rate_limit_error: too many requests",
        },
    )
    plain_log = _stream_json_log(
        {"type": "system", "subtype": "init", "model": "claude-opus-4-7"},
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "quota feature"}]},
        },
        {
            "type": "result",
            "subtype": "error_max_turns",
            "is_error": True,
            "result": "Reached max turns",
        },
    )

    assert claude.ADAPTER.detect_failure(1, quota_log).reason == "engine:quota"
    assert claude.ADAPTER.detect_failure(1, plain_log).reason == "engine:exit_nonzero"


# Scenario: stream-json rate_limit_event with a non-ok status, nonzero exit.
# Expected: engine:quota with the event status in the detail.
def test_stream_json_rate_limit_event_non_ok_status_is_quota_failure() -> None:
    log = _stream_json_log(
        {"type": "system", "subtype": "init", "model": "claude-opus-4-7"},
        {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}},
    )
    ok_log = _stream_json_log(
        {"type": "system", "subtype": "init", "model": "claude-opus-4-7"},
        {"type": "rate_limit_event", "rate_limit_info": {"status": "ok"}},
    )

    limited = claude.ADAPTER.detect_failure(1, log)
    assert limited.reason == "engine:quota"
    assert "status=rejected" in limited.detail
    assert claude.ADAPTER.detect_failure(1, ok_log).reason == "engine:exit_nonzero"


# Scenario: bare CLI stderr text without display markers (legacy callers).
# Expected: substring behaviour is preserved for compatibility.
def test_bare_error_text_keeps_legacy_quota_detection() -> None:
    quota = claude.ADAPTER.detect_failure(1, "quota exceeded")
    assert quota.reason == "engine:quota"
    assert quota.detail == "quota exceeded"

    nonzero = claude.ADAPTER.detect_failure(2, "  failed  ")
    assert nonzero.reason == "engine:exit_nonzero"
    assert nonzero.detail == "failed"


# Scenario: exit 0 and SIGPIPE exits stay successful regardless of text.
def test_zero_and_sigpipe_exits_are_not_failures() -> None:
    assert claude.ADAPTER.detect_failure(0, QUOTA_ERROR_DISPLAY).failed is False
    assert claude.ADAPTER.detect_failure(141, QUOTA_ERROR_DISPLAY).failed is False


# Scenario: the shell path used by wave_loop_state.sh with a display file.
# Expected: benign display -> engine:exit_nonzero, error display -> engine:quota.
def test_cli_raw_tail_file_path_matches_adapter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        benign = Path(tmp) / "benign.txt"
        benign.write_text(BENIGN_DISPLAY, encoding="utf-8")
        errored = Path(tmp) / "error.txt"
        errored.write_text(QUOTA_ERROR_DISPLAY, encoding="utf-8")

        results = []
        for path in (benign, errored):
            completed = subprocess.run(
                [
                    sys.executable,
                    SCRIPT,
                    "failure",
                    "--engine",
                    "claude",
                    "--exit-code",
                    "1",
                    "--raw-tail-file",
                    str(path),
                    "--format",
                    "reason",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert completed.returncode == 0, completed.stderr
            results.append(completed.stdout.strip())

    assert results == ["engine:exit_nonzero", "engine:quota"]


def test_rate_limit_warning_does_not_turn_an_unrelated_exit_into_quota() -> None:
    # The SDK permits work in allowed_warning; only rejected denotes exhaustion.
    for status in ("allowed", "allowed_warning", "unknown_future_status"):
        log = _stream_json_log(
            {"type": "rate_limit_event", "rate_limit_info": {"status": status}},
            {"type": "result", "is_error": True, "result": "Permission denied"},
        )
        failure = claude.ADAPTER.detect_failure(1, log)
        assert failure.reason == "engine:exit_nonzero", status


def test_malformed_rate_limit_metadata_cannot_crash_failure_classification() -> None:
    for info in ("rejected", ["rejected"], 42, True, None):
        log = _stream_json_log(
            {"type": "rate_limit_event", "rate_limit_info": info},
            {"type": "result", "is_error": True, "result": "Permission denied"},
        )
        failure = claude.ADAPTER.detect_failure(1, log)
        assert failure.failed is True
        assert failure.reason == "engine:exit_nonzero"


def test_multiline_engine_error_uses_actual_prettifier_continuations() -> None:
    # The real prettifier prefixes only the first line of a result error.
    raw = _stream_json_log(
        {"type": "system", "subtype": "init", "model": "test-model"},
        {
            "type": "result",
            "is_error": True,
            "result": "API Error: 429\nYour account quota is exhausted.",
        },
    )
    rendered = subprocess.run(
        [sys.executable, str(PY_DIR / "stream_json_prettify.py"), "--mode", "writer"],
        input=raw,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rendered.returncode == 0, rendered.stderr
    failure = claude.ADAPTER.detect_failure(1, rendered.stdout)
    assert failure.reason == "engine:quota"
    assert "Your account quota is exhausted." in failure.detail
