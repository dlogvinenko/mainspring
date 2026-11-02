# SPDX-License-Identifier: Apache-2.0
"""Pretty-print Claude --output-format stream-json events.

Reads stream-json events on stdin (one JSON line per event) and writes
human-readable progress lines to stdout. If the CLAUDE_DISPLAY_FILE env
var is set, also appends the same output to that file.

Fixes the SC2259 silent-failure bug present in the pre-P1-1 monolith.
The heredoc form `python3 - <<'PY' ... PY` overrode the piped stdin, so
when Claude was the writer the display_file ended up empty and the
review gate evaluated on `[no human-readable engine output captured]`.
Extracting the Python into this real file lets `python3 <file>` read the
script from the file while leaving stdin available for `sys.stdin`.

Modes differ only in log-line prefix:
  writer:   `[claude]` / `[tool]` / `[tool-result]` / `[tool-error]`
  reviewer: `[review-claude]` / `[review-tool]` (no tool-result detail)

Usage:
    cmd | tee raw.log | python3 stream_json_prettify.py --mode writer
    cmd | tee raw.log | python3 stream_json_prettify.py --mode reviewer

Set CLAUDE_DISPLAY_FILE inline on the python3 call rather than exporting
in a subshell (SC2031). Example:
    | CLAUDE_DISPLAY_FILE="$display_file" python3 stream_json_prettify.py --mode writer
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import ExitStack

from cli_runtime import run_cli


def _make_writer(display_fp):
    def out(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()
        if display_fp:
            display_fp.write(text)
            display_fp.flush()

    return out


def _handle_event(obj: object, mode: str, out) -> None:
    if not isinstance(obj, dict):
        return
    engine_label = "claude" if mode == "writer" else "review-claude"
    tool_label = "tool" if mode == "writer" else "review-tool"
    complete_msg = "turn complete" if mode == "writer" else "review complete"
    verbose_tool_results = mode == "writer"

    t = obj.get("type")

    if t == "system" and obj.get("subtype") == "init":
        model = obj.get("model") or "unknown"
        out(f"[{engine_label}] session started ({model})\n")
        return

    if t == "stream_event":
        event = obj.get("event", {})
        if not isinstance(event, dict):
            return
        et = event.get("type")

        if et == "content_block_delta":
            delta = event.get("delta", {})
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if isinstance(text, str):
                    out(text)
            return

        if et == "content_block_start":
            block = event.get("content_block", {})
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name", "tool")
                out(f"\n[{tool_label}] {name}\n")
            return

        if et == "content_block_stop":
            out("\n")
            return

        return

    if t == "assistant":
        msg = obj.get("message", {})
        if not isinstance(msg, dict):
            return
        content = msg.get("content", [])
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name = block.get("name", "tool")
                tool_input = block.get("input") or {}
                if not isinstance(tool_input, dict):
                    tool_input = {}
                description = tool_input.get("description")
                command = tool_input.get("command")
                if description:
                    out(f"[{tool_label}] {name}: {description}\n")
                elif command:
                    out(f"[{tool_label}] {name}: {command}\n")
                else:
                    out(f"[{tool_label}] {name}\n")
        return

    if verbose_tool_results and t == "user":
        tool_result = obj.get("tool_use_result")
        # Claude can serialize tool_use_result as either a dict or a plain string
        # (depending on tool type and version). Handle both shapes; ignore None
        # and other types defensively so the pretty-printer never crashes mid-stream.
        if isinstance(tool_result, dict):
            stdout_v = tool_result.get("stdout", "") or ""
            stderr_v = tool_result.get("stderr", "") or ""
            if not isinstance(stdout_v, str):
                stdout_v = ""
            if not isinstance(stderr_v, str):
                stderr_v = ""
            if stdout_v.strip():
                preview = stdout_v.strip().splitlines()[0]
                out(f"[tool-result] {preview}\n")
            elif stderr_v.strip():
                preview = stderr_v.strip().splitlines()[0]
                out(f"[tool-error] {preview}\n")
        elif isinstance(tool_result, str) and tool_result.strip():
            preview = tool_result.strip().splitlines()[0]
            out(f"[tool-result] {preview}\n")
        return

    if t == "result":
        if obj.get("is_error"):
            out(f"\n[{engine_label}] error: {obj.get('result', 'unknown error')}\n")
        else:
            out(f"\n[{engine_label}] {complete_msg}\n")
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pretty-print Claude stream-json events to stdout (and optionally to CLAUDE_DISPLAY_FILE)."
    )
    parser.add_argument(
        "--mode",
        choices=("writer", "reviewer"),
        required=True,
        help="Log-line prefix mode: 'writer' for run_engine path, 'reviewer' for run_reviewer path.",
    )
    args = parser.parse_args(argv)

    display_path = os.environ.get("CLAUDE_DISPLAY_FILE")
    with ExitStack() as stack:
        display_fp = (
            stack.enter_context(open(display_path, "a", encoding="utf-8"))
            if display_path
            else None
        )
        out = _make_writer(display_fp)
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (ValueError, TypeError, RecursionError):
                continue
            _handle_event(obj, args.mode, out)
    return 0


if __name__ == "__main__":
    run_cli(main)
