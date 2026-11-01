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
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

# Make the parent package importable regardless of cwd.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import stream_json_prettify as sjp


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


def _cli(events, mode, display_path):
    env = dict(os.environ)
    env["CLAUDE_DISPLAY_FILE"] = str(display_path)
    display_path.parent.mkdir(parents=True, exist_ok=True)
    raw = "".join(json.dumps(event) + "\n" for event in events).encode()
    return subprocess.run(
        [sys.executable, "-B", str(Path(sjp.__file__)), "--mode", mode],
        input=raw,
        capture_output=True,
        env=env,
        check=False,
    )


def _assert_cli_survives(bad, tmp_path):
    valid = {
        "type": "stream_event",
        "event": {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "LATER_SYNTHETIC_TEXT"},
        },
    }
    for mode in ("writer", "reviewer"):
        display = tmp_path / (mode + ".log")
        result = _cli(
            [bad, valid, {"type": "result", "is_error": False}], mode, display
        )
        assert result.returncode == 0, result.stderr.decode()
        assert b"LATER_SYNTHETIC_TEXT" in result.stdout
        assert result.stdout == display.read_bytes()


def test_top_null_does_not_abort_later_cli_text(tmp_path):
    _assert_cli_survives(None, tmp_path)


def test_top_array_does_not_abort_later_cli_text(tmp_path):
    _assert_cli_survives([], tmp_path)


def test_null_stream_event_does_not_abort_later_cli_text(tmp_path):
    _assert_cli_survives({"type": "stream_event", "event": None}, tmp_path)


def test_null_delta_does_not_abort_later_cli_text(tmp_path):
    _assert_cli_survives(
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": None},
        },
        tmp_path,
    )


def test_null_message_does_not_abort_later_cli_text(tmp_path):
    _assert_cli_survives({"type": "assistant", "message": None}, tmp_path)


def test_null_content_block_does_not_abort_later_cli_text(tmp_path):
    _assert_cli_survives(
        {"type": "assistant", "message": {"content": [None]}}, tmp_path
    )


def test_numeric_tool_stdout_does_not_abort_later_cli_text(tmp_path):
    _assert_cli_survives({"type": "user", "tool_use_result": {"stdout": 42}}, tmp_path)


def test_null_text_delta_does_not_abort_later_cli_text(tmp_path):
    _assert_cli_survives(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": None},
            },
        },
        tmp_path,
    )


def test_neighboring_non_object_and_non_text_fields_are_skipped(tmp_path):
    cases = [
        {
            "type": "stream_event",
            "event": {"type": "content_block_start", "content_block": None},
        },
        {"type": "assistant", "message": {"content": "not an array"}},
        {"type": "assistant", "message": {"content": 42}},
        {"type": "assistant", "message": {"content": [42]}},
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Read", "input": 42}]},
        },
        {"type": "user", "tool_use_result": {"stderr": 42}},
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": 42},
            },
        },
    ]
    for index, case in enumerate(cases):
        _assert_cli_survives(case, tmp_path / str(index))


def test_valid_cli_outputs_remain_exact_and_do_not_add_text_fallback(tmp_path):
    events = [
        {"type": "system", "subtype": "init", "model": "synthetic-model"},
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Visible synthetic text"},
            },
        },
        {"type": "stream_event", "event": {"type": "content_block_stop"}},
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "Bash"},
            },
        },
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "DO_NOT_ADD_FALLBACK"},
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"description": "inspect"},
                    },
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "printf synthetic"},
                    },
                    {"type": "tool_use", "name": "Task", "input": {}},
                ]
            },
        },
        {"type": "user", "tool_use_result": {"stdout": "first\nsecond"}},
        {"type": "user", "tool_use_result": {"stderr": "problem\nmore"}},
        {"type": "user", "tool_use_result": "direct\nmore"},
        {"type": "result", "is_error": False, "result": "DO_NOT_ADD_FALLBACK"},
        {"type": "result", "is_error": True, "result": "synthetic error"},
    ]
    for mode, engine, tool, complete in (
        ("writer", "claude", "tool", "turn complete"),
        ("reviewer", "review-claude", "review-tool", "review complete"),
    ):
        expected = (
            f"[{engine}] session started (synthetic-model)\nVisible synthetic text\n"
            f"\n[{tool}] Bash\n[{tool}] Read: inspect\n"
            f"[{tool}] Bash: printf synthetic\n[{tool}] Task\n"
            + (
                "[tool-result] first\n[tool-error] problem\n[tool-result] direct\n"
                if mode == "writer"
                else ""
            )
            + f"\n[{engine}] {complete}\n\n[{engine}] error: synthetic error\n"
        ).encode()
        display = tmp_path / (mode + ".log")
        result = _cli(events, mode, display)
        assert result.returncode == 0, result.stderr.decode()
        assert result.stdout == expected == display.read_bytes()
        assert b"DO_NOT_ADD_FALLBACK" not in result.stdout


def test_bad_assistant_block_does_not_hide_later_valid_tool():
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    None,
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"description": "visible tool"},
                    },
                ]
            },
        }
    ]
    for mode, label in (("writer", "tool"), ("reviewer", "review-tool")):
        assert _run(events, mode) == f"[{label}] Read: visible tool\n"


def test_bad_tool_input_keeps_supported_name():
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Read", "input": 42},
                ]
            },
        }
    ]
    for mode, label in (("writer", "tool"), ("reviewer", "review-tool")):
        assert _run(events, mode) == f"[{label}] Read\n"


def test_bad_stdout_does_not_hide_valid_stderr():
    assert (
        _run(
            [
                {
                    "type": "user",
                    "tool_use_result": {
                        "stdout": 42,
                        "stderr": "visible failure\nmore",
                    },
                }
            ],
            "writer",
        )
        == "[tool-error] visible failure\n"
    )


def test_output_io_failure_is_not_swallowed():
    def failing_out(_text):
        raise OSError("synthetic output failure")

    event = {
        "type": "stream_event",
        "event": {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "valid output"},
        },
    }
    try:
        sjp._handle_event(event, "writer", failing_out)
    except OSError as error:
        assert str(error) == "synthetic output failure"
    else:
        raise AssertionError("output I/O failure was swallowed")


def test_display_open_failure_keeps_nonzero_cli_exit(tmp_path):
    for mode in ("writer", "reviewer"):
        result = _cli([{"type": "result", "is_error": False}], mode, tmp_path)
        assert result.returncode != 0
        assert b"IsADirectoryError" in result.stderr
