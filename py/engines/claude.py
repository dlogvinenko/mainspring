# SPDX-License-Identifier: Apache-2.0
"""Claude Code engine adapter."""

from __future__ import annotations

from engines._base import EngineCommand, EngineFailure, EngineInfo, env_default


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
        """Classify a Claude process exit."""
        if exit_code == 0 or exit_code == 141:
            return EngineFailure(False)
        lower_tail = raw_tail.lower()
        if "rate limit" in lower_tail or "quota" in lower_tail:
            return EngineFailure(True, "engine:quota", raw_tail.strip())
        return EngineFailure(True, "engine:exit_nonzero", raw_tail.strip())


ADAPTER = ClaudeAdapter()
INFO = ADAPTER.info
