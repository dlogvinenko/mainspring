# SPDX-License-Identifier: Apache-2.0
"""Synthetic lifetime controls for the stream display writer."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from . import test_stream_json_prettify as canonical

PY_DIR = Path(__file__).resolve().parents[1]
TEXT = "owned synthetic text\n"
LINE = (
    json.dumps(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": TEXT},
            },
        }
    )
    + "\n"
)


@pytest.fixture
def module():
    return canonical.sjp


class TrackedStream(io.StringIO):
    def __init__(self, name, events, failure=None):
        super().__init__()
        self.name = name
        self.events = events
        self.failure = failure
        self.close_count = 0
        self.saved = ""

    def write(self, text):
        self.events.append((self.name, "write", text))
        if self.failure == "write":
            raise OSError("synthetic write interruption")
        return super().write(text)

    def flush(self):
        self.events.append((self.name, "flush"))
        if self.failure == "flush":
            raise OSError("synthetic flush interruption")
        return super().flush()

    def close(self):
        self.close_count += 1
        self.events.append((self.name, "close"))
        self.saved = self.getvalue()
        super().close()


def input_lines(interrupt):
    yield LINE
    if interrupt:
        raise KeyboardInterrupt


@pytest.mark.parametrize("mode", ["writer", "reviewer"])
@pytest.mark.parametrize(
    "failure",
    [None, "input", "stdout_write", "stdout_flush", "display_write", "display_flush"],
)
def test_owned_display_closes_on_each_exit(module, monkeypatch, mode, failure):
    events = []
    stdout_failure = failure.removeprefix("stdout_") if failure else None
    display_failure = failure.removeprefix("display_") if failure else None
    stdout = TrackedStream("stdout", events, stdout_failure)
    display = TrackedStream("display", events, display_failure)

    def open_display(path, mode, encoding):
        events.append(("open", path, mode, encoding))
        return display

    monkeypatch.setenv("CLAUDE_DISPLAY_FILE", "synthetic-display")
    monkeypatch.setattr(module, "open", open_display, raising=False)
    monkeypatch.setattr(sys, "stdin", input_lines(failure == "input"))
    monkeypatch.setattr(sys, "stdout", stdout)
    if failure:
        expected = KeyboardInterrupt if failure == "input" else OSError
        with pytest.raises(expected):
            module.main(["--mode", mode])
    else:
        assert module.main(["--mode", mode]) == 0
        assert stdout.getvalue() == display.saved == TEXT
        assert events == [
            ("open", "synthetic-display", "a", "utf-8"),
            ("stdout", "write", TEXT),
            ("stdout", "flush"),
            ("display", "write", TEXT),
            ("display", "flush"),
            ("display", "close"),
        ]
    assert display.close_count == 1
    assert display.closed
    assert stdout.close_count == 0
    assert not stdout.closed


@pytest.mark.parametrize("mode", ["writer", "reviewer"])
@pytest.mark.parametrize("failure", [None, "input", "write", "flush"])
def test_borrowed_stdout_never_closed(module, monkeypatch, mode, failure):
    stdout = TrackedStream("stdout", [], failure)
    monkeypatch.delenv("CLAUDE_DISPLAY_FILE", raising=False)
    monkeypatch.setattr(sys, "stdin", input_lines(failure == "input"))
    monkeypatch.setattr(sys, "stdout", stdout)
    if failure:
        expected = KeyboardInterrupt if failure == "input" else OSError
        with pytest.raises(expected):
            module.main(["--mode", mode])
    else:
        assert module.main(["--mode", mode]) == 0
        assert stdout.getvalue() == TEXT
    assert stdout.close_count == 0
    assert not stdout.closed


def cli(mode, display, raw):
    env = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"}
    env["CLAUDE_DISPLAY_FILE"] = str(display)
    return subprocess.run(
        [sys.executable, "-B", str(PY_DIR / "stream_json_prettify.py"), "--mode", mode],
        input=raw,
        capture_output=True,
        env=env,
        check=False,
        timeout=10,
    )


@pytest.mark.parametrize("mode", ["writer", "reviewer"])
def test_actual_cli_exact_parity_and_append(tmp_path, mode):
    display = tmp_path / "display.log"
    display.write_bytes(b"prior synthetic output\n")
    raw = (
        LINE
        + json.dumps({"type": "user", "tool_use_result": "synthetic preview"})
        + "\n"
        + json.dumps({"type": "result", "is_error": False})
        + "\n"
    ).encode()
    expected = TEXT
    if mode == "writer":
        expected += "[tool-result] synthetic preview\n\n[claude] turn complete\n"
    else:
        expected += "\n[review-claude] review complete\n"
    result = cli(mode, display, raw)
    assert result.returncode == 0
    assert result.stderr == b""
    assert result.stdout == expected.encode()
    assert display.read_bytes() == b"prior synthetic output\n" + result.stdout


@pytest.mark.parametrize("mode", ["writer", "reviewer"])
def test_empty_input_eagerly_creates_display(tmp_path, mode):
    display = tmp_path / "empty.log"
    result = cli(mode, display, b"")
    assert result.returncode == 0
    assert result.stdout == result.stderr == b""
    assert display.read_bytes() == b""


def test_invalid_mode_does_not_create_display(tmp_path):
    display = tmp_path / "absent.log"
    result = cli("invalid-synthetic-mode", display, LINE.encode())
    assert result.returncode == 2
    assert result.stdout == b""
    assert not display.exists()


def test_empty_input_still_reports_display_open_error(tmp_path):
    result = cli("writer", tmp_path, b"")
    assert result.returncode != 0
    assert result.stdout == b""


def test_keyboard_interrupt_exit_130_also_closes_owned_display(module, monkeypatch):
    display = TrackedStream("display", [])
    stdout = TrackedStream("stdout", [])
    monkeypatch.setenv("CLAUDE_DISPLAY_FILE", "synthetic-display")
    monkeypatch.setattr(module, "open", lambda *args, **kwargs: display, raising=False)
    monkeypatch.setattr(sys, "stdin", input_lines(True))
    monkeypatch.setattr(sys, "stdout", stdout)
    with pytest.raises(SystemExit) as exc:
        module.run_cli(lambda: module.main(["--mode", "writer"]))
    assert exc.value.code == 130
    assert display.close_count == 1
    assert stdout.close_count == 0
