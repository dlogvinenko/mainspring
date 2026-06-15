# SPDX-License-Identifier: Apache-2.0
"""Common data shapes for Mainspring engine adapters."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Protocol


@dataclass(frozen=True)
class EngineInfo:
    """Static metadata for one engine CLI."""

    name: str
    display_name: str
    binary: str
    default_model: str
    required_python_module: str = ""
    required_env_vars: tuple[str, ...] = ()
    supported_roles: tuple[str, ...] = ("writer", "reviewer")
    execution_status: str = "shell-dispatch"
    quota_status: str = "unknown"
    notes: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-safe representation."""
        data = asdict(self)
        data["required_env_vars"] = list(self.required_env_vars)
        data["supported_roles"] = list(self.supported_roles)
        return data


@dataclass(frozen=True)
class EngineCommand:
    """A concrete engine invocation plus its stream display mode."""

    argv: tuple[str, ...]
    display_mode: str

    def to_dict(self) -> dict:
        """Return a JSON-safe representation."""
        return {
            "argv": list(self.argv),
            "display_mode": self.display_mode,
        }


@dataclass(frozen=True)
class EngineFailure:
    """Classified engine exit information."""

    failed: bool
    reason: str = ""
    detail: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-safe representation."""
        return asdict(self)


def env_default(primary_name: str, default: str) -> str:
    """Read a public Mainspring env var with a default fallback."""
    primary_value = os.environ.get(primary_name)
    if primary_value:
        return primary_value

    return default


class EngineAdapter(Protocol):
    """Runtime contract every engine module must expose."""

    info: EngineInfo

    def build_command(
        self,
        prompt: str,
        *,
        model: str = "",
        role: str = "writer",
        reasoning_effort: str = "xhigh",
    ) -> EngineCommand:
        """Build the argv and display mode for one engine turn."""
        ...

    def parse_usage(self, raw_log: str) -> dict:
        """Extract usage metadata from an engine raw log."""
        ...

    def quota_snapshot(self) -> dict:
        """Return a common quota snapshot for preflight surfaces."""
        ...

    def detect_failure(self, exit_code: int, raw_tail: str) -> EngineFailure:
        """Classify an engine process result."""
        ...
