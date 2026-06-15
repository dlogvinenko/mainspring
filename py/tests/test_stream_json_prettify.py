# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for stream_json_prettify.py (P1-1).

Pytest runner is wired in P3-2; until then these tests are runnable as a
plain script:

    python3 py/tests/test_stream_json_prettify.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

# Make the parent package importable regardless of cwd.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import stream_json_prettify as sjp  # noqa: E402


def _run(events: list[dict], mode: str, display_path: str | None = None) -> str:
    """Drive the parser by feeding pre-encoded JSON lines through stdin."""
    raw = "\n".join(json.dumps(e) for e in events) + "\n"

    if display_path:
        os.environ["CLAUDE_DISPLAY_FILE"] = display_path
    else:
        os.environ.pop("CLAUDE_DISPLAY_FILE", None)

    saved_stdin = sys.stdin
    saved_stdout = sys.stdout
    try:
        sys.stdin = io.StringIO(raw)
        captured = io.StringIO()
        with redirect_stdout(captured):
            sjp.main(["--mode", mode])
        return captured.getvalue()
    finally:
        sys.stdin = saved_stdin
        sys.stdout = saved_stdout


def test_writer_happy_path() -> None:
    """Scenario: writer mode receives a session-init + text + result.
    Expected: '[claude]' prefix, model name, text body, 'turn complete'.
    """
    events = [
        {"type": "system", "subtype": "init", "model": "claude-opus-4"},
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Hello world"},
            },
        },
        {"type": "result", "is_error": False, "result": "ok"},
    ]
    out = _run(events, mode="writer")
    assert "[claude] session started (claude-opus-4)" in out
    assert "Hello world" in out
    assert "turn complete" in out
    print("✓ test_writer_happy_path")


def test_reviewer_happy_path() -> None:
    """Scenario: reviewer mode receives a session-init + text + result.
    Expected: '[review-claude]' prefix, model name, text body, 'review complete'.
    """
    events = [
        {"type": "system", "subtype": "init", "model": "claude-opus-4"},
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Reviewing..."},
            },
        },
        {"type": "result", "is_error": False, "result": "ok"},
    ]
    out = _run(events, mode="reviewer")
    assert "[review-claude] session started (claude-opus-4)" in out
    assert "Reviewing..." in out
    assert "review complete" in out
    assert "[claude]" not in out  # writer prefix must NOT appear
    print("✓ test_reviewer_happy_path")


def test_malformed_json_tolerated() -> None:
    """Scenario: a stray non-JSON line lands in the stream.
    Expected: parser skips it and continues with valid lines.
    """
    raw = (
        '{"type":"system","subtype":"init","model":"x"}\n'
        "this is not JSON at all\n"
        '{"type":"result","is_error":false}\n'
    )
    saved_stdin = sys.stdin
    saved_stdout = sys.stdout
    os.environ.pop("CLAUDE_DISPLAY_FILE", None)
    try:
        sys.stdin = io.StringIO(raw)
        captured = io.StringIO()
        with redirect_stdout(captured):
            sjp.main(["--mode", "writer"])
        out = captured.getvalue()
    finally:
        sys.stdin = saved_stdin
        sys.stdout = saved_stdout
    assert "session started" in out
    assert "turn complete" in out
    print("✓ test_malformed_json_tolerated")


def test_claude_display_file_env_honored() -> None:
    """Scenario: CLAUDE_DISPLAY_FILE env var is set.
    Expected: the same output written to stdout is also appended to the file.
    This is the core regression test for the SC2259 silent-failure bug.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        display_path = os.path.join(tmpdir, "display.log")
        events = [
            {"type": "system", "subtype": "init", "model": "claude-opus-4"},
            {"type": "result", "is_error": False, "result": "ok"},
        ]
        out = _run(events, mode="writer", display_path=display_path)
        assert "session started" in out
        assert os.path.exists(display_path), "display file must be created"
        with open(display_path, encoding="utf-8") as f:
            content = f.read()
        assert "session started" in content
        assert "turn complete" in content
        # Content must be NON-EMPTY (the SC2259 bug produced empty files).
        assert content.strip(), (
            "display file must NOT be empty (SC2259 regression check)"
        )
    print("✓ test_claude_display_file_env_honored")


def test_tool_result_string_form_tolerated() -> None:
    """Scenario: Claude serialized tool_use_result as a STRING, not a dict.
    Expected: pretty-printer surfaces first line, doesn't crash with AttributeError.
    Regression for the bug surfaced during the first claude+claude live wave.
    """
    events = [
        {
            "type": "user",
            "tool_use_result": "first line of output\nsecond line",
        },
    ]
    out = _run(events, mode="writer")
    assert "[tool-result] first line of output" in out
    print("✓ test_tool_result_string_form_tolerated")


def test_tool_result_none_tolerated() -> None:
    """Scenario: tool_use_result is None or missing.
    Expected: pretty-printer skips silently, doesn't crash.
    """
    events = [
        {"type": "user", "tool_use_result": None},
        {"type": "user"},
    ]
    out = _run(events, mode="writer")
    # Should not crash; no specific output expected for these events.
    assert "[tool-result]" not in out
    print("✓ test_tool_result_none_tolerated")


def test_error_result_surfaces_message() -> None:
    """Scenario: result event is an error.
    Expected: error line surfaces the result text.
    """
    events = [
        {"type": "system", "subtype": "init", "model": "claude-opus-4"},
        {"type": "result", "is_error": True, "result": "rate limited"},
    ]
    out = _run(events, mode="writer")
    assert "[claude] error: rate limited" in out
    print("✓ test_error_result_surfaces_message")


def test_stream_tool_use_events_are_rendered() -> None:
    events = [
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "Bash"},
            },
        },
        {"type": "stream_event", "event": {"type": "content_block_stop"}},
        {"type": "stream_event", "event": {"type": "other_event"}},
    ]

    out = _run(events, mode="writer")

    assert "[tool] Bash" in out


def test_assistant_tool_use_blocks_render_description_command_and_name() -> None:
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"description": "inspect file"},
                    },
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "make test"},
                    },
                    {"type": "tool_use", "name": "TodoWrite", "input": {}},
                ]
            },
        }
    ]

    out = _run(events, mode="reviewer")

    assert "[review-tool] Read: inspect file" in out
    assert "[review-tool] Bash: make test" in out
    assert "[review-tool] TodoWrite" in out


def test_tool_result_dict_prefers_stdout_then_stderr() -> None:
    stdout_out = _run(
        [{"type": "user", "tool_use_result": {"stdout": "first\nsecond"}}],
        mode="writer",
    )
    stderr_out = _run(
        [{"type": "user", "tool_use_result": {"stderr": "bad\nworse"}}],
        mode="writer",
    )

    assert "[tool-result] first" in stdout_out
    assert "[tool-error] bad" in stderr_out


def test_reviewer_mode_omits_verbose_tool_results() -> None:
    out = _run(
        [{"type": "user", "tool_use_result": {"stdout": "hidden"}}],
        mode="reviewer",
    )

    assert out == ""


if __name__ == "__main__":
    test_writer_happy_path()
    test_reviewer_happy_path()
    test_malformed_json_tolerated()
    test_claude_display_file_env_honored()
    test_tool_result_string_form_tolerated()
    test_tool_result_none_tolerated()
    test_error_result_surfaces_message()
    print("\nAll 7 tests passed.")
