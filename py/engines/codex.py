# SPDX-License-Identifier: Apache-2.0
"""Codex engine adapter."""

from __future__ import annotations

from engines._base import EngineCommand, EngineFailure, EngineInfo, env_default


class CodexAdapter:
    """Adapter for the Codex CLI."""

    @property
    def info(self) -> EngineInfo:
        """Return metadata with the current operator default-model override."""
        return EngineInfo(
            name="codex",
            display_name="Codex",
            binary="codex",
            default_model=env_default(
                "MAINSPRING_DEFAULT_CODEX_MODEL",
                "gpt-5.5",
            ),
            execution_status="shell-dispatch",
            quota_status="codex-session-jsonl",
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
        """Build the Codex CLI invocation."""
        del role
        argv = [
            "codex",
            "exec",
            "--ignore-user-config",
            "--yolo",
            "-c",
            "features.codex_hooks=false",
            "-c",
            f'model_reasoning_effort="{reasoning_effort}"',
        ]
        if model and model != "auto":
            argv.extend(["-m", model])
        argv.append(prompt)
        return EngineCommand(tuple(argv), "plain")

    def parse_usage(self, raw_log: str) -> dict:
        """Usage parsing remains in engine_quota.py for the legacy session feed."""
        del raw_log
        return {}

    def quota_snapshot(self) -> dict:
        """Quota snapshot is supplied by engine_quota.py."""
        return {}

    def detect_failure(self, exit_code: int, raw_tail: str) -> EngineFailure:
        """Classify a Codex process exit."""
        if exit_code == 0 or exit_code == 141:
            return EngineFailure(False)
        lower_tail = raw_tail.lower()
        if "rate limit" in lower_tail or "quota" in lower_tail:
            return EngineFailure(True, "engine:quota", raw_tail.strip())
        return EngineFailure(True, "engine:exit_nonzero", raw_tail.strip())


ADAPTER = CodexAdapter()
INFO = ADAPTER.info
