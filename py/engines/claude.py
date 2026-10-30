# SPDX-License-Identifier: Apache-2.0
"""Claude Code engine adapter."""

from __future__ import annotations

import json
import re

from engines._base import EngineCommand, EngineFailure, EngineInfo, env_default

# Lines emitted by stream_json_prettify.py. Their presence means raw_tail is a
# Mainspring display file (or a raw stream-json log), not bare CLI stderr, so
# only the engine's own error evidence may drive the failure reason.
_DISPLAY_MARKER_RE = re.compile(
    r"^\[(?:review-)?(?:claude|tool)\]|^\[tool-(?:result|error)\]"
)
_DISPLAY_ERROR_RE = re.compile(r"^\[(?:review-)?claude\] error:")
_QUOTA_MARKERS = ("rate limit", "rate_limit", "quota", "usage limit")
_DETAIL_TAIL_LINES = 20


def _mentions_quota(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in _QUOTA_MARKERS)


def _parse_stream_json_line(line: str) -> dict | None:
    if not line.startswith("{"):
        return None
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) and "type" in parsed else None


def _error_evidence(line: str, event: dict | None) -> str | None:
    """Return the engine-authored error text carried by one tail line, if any."""
    if event is None:
        return line if _DISPLAY_ERROR_RE.match(line) else None
    event_type = event.get("type")
    if event_type == "result" and event.get("is_error"):
        return f"result error: {event.get('result') or event.get('subtype') or ''}"
    if event_type == "rate_limit_event":
        info = event.get("rate_limit_info")
        if isinstance(info, dict) and info.get("status") == "rejected":
            return "rate_limit_event status=rejected"
    return None


def classify_tail(exit_code: int, raw_tail: str) -> EngineFailure:
    """Classify a Claude process exit from its exit code and output tail.

    ``raw_tail`` is usually the whole prettified display file. Writer prose in
    that file may legitimately discuss quotas or rate limits, so when display or
    stream-json structure is present only ``[claude] error:`` lines, error
    ``result`` events, and rejected ``rate_limit_event`` entries count as quota
    evidence. Bare error text without that structure keeps substring matching.
    """
    if exit_code == 0 or exit_code == 141:
        return EngineFailure(False)

    lines = [line.rstrip() for line in raw_tail.splitlines() if line.strip()]
    structured = False
    evidence: list[str] = []
    display_error = False
    for line in lines:
        event = _parse_stream_json_line(line)
        if event is not None or _DISPLAY_MARKER_RE.match(line):
            structured = True
            display_error = event is None and bool(_DISPLAY_ERROR_RE.match(line))
        found = _error_evidence(line, event)
        if found:
            evidence.append(found)
        elif display_error:
            # The prettifier prefixes only the first line of a result error.
            evidence[-1] += "\n" + line

    if not structured:
        tail = raw_tail.strip()
        if _mentions_quota(tail):
            return EngineFailure(True, "engine:quota", tail)
        return EngineFailure(True, "engine:exit_nonzero", tail)

    for found in reversed(evidence):
        if _mentions_quota(found):
            return EngineFailure(True, "engine:quota", found)
    detail = evidence[-1] if evidence else "\n".join(lines[-_DETAIL_TAIL_LINES:])
    return EngineFailure(True, "engine:exit_nonzero", detail)


class ClaudeAdapter:
    """Adapter for the Claude Code CLI."""

    @property
    def info(self) -> EngineInfo:
        """Return metadata with the current operator default-model override."""
        return EngineInfo(
            name="claude",
            display_name="Claude Code",
            binary="claude",
            default_model=env_default(
                "MAINSPRING_DEFAULT_CLAUDE_MODEL",
                "opus",
            ),
            execution_status="shell-dispatch",
            quota_status="stream-json-probe",
            notes="Runtime command construction is adapter-backed; streaming stays in lib/engines.sh.",
        )

    def build_command(
        self,
        prompt: str,
        *,
        model: str = "",
        role: str = "writer",
        reasoning_effort: str = "xhigh",
    ) -> EngineCommand:
        """Build the Claude Code CLI invocation."""
        del role, reasoning_effort
        argv = [
            "claude",
            "-p",
            "--dangerously-skip-permissions",
            "--verbose",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
        ]
        if model:
            argv.extend(["--model", model])
        argv.append(prompt)
        return EngineCommand(tuple(argv), "stream-json")

    def parse_usage(self, raw_log: str) -> dict:
        """Usage parsing remains in engine_quota.py for stream-json probes."""
        del raw_log
        return {}

    def quota_snapshot(self) -> dict:
        """Quota snapshot is supplied by engine_quota.py."""
        return {}

    def detect_failure(self, exit_code: int, raw_tail: str) -> EngineFailure:
        """Classify a Claude process exit without trusting writer prose."""
        return classify_tail(exit_code, raw_tail)


ADAPTER = ClaudeAdapter()
INFO = ADAPTER.info
