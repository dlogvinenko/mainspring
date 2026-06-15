# SPDX-License-Identifier: Apache-2.0
"""LiteLLM engine adapter.

This is the first P-Comp-1 bridge: a generic shell-dispatch engine that calls
LiteLLM through ``litellm_runner.py``. Provider-specific engines can either
wrap this adapter later or pass provider/model strings through ``--model`` now.
"""

from __future__ import annotations

from collections.abc import Mapping
import sys
from pathlib import Path

from engines._base import EngineCommand, EngineFailure, EngineInfo


PROVIDER_ENV_VARS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("azure/",), ("AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION")),
    (("gemini/", "gemini-", "google/"), ("GOOGLE_API_KEY",)),
    (("xai/", "grok"), ("XAI_API_KEY",)),
    (("openrouter/",), ("OPENROUTER_API_KEY",)),
    (("mistral/",), ("MISTRAL_API_KEY",)),
    (("anthropic/", "claude-"), ("ANTHROPIC_API_KEY",)),
    (("openai/", "gpt-", "o1", "o3", "o4"), ("OPENAI_API_KEY",)),
    (("ollama/", "ollama_chat/"), ()),
)
DEFAULT_LITELLM_MODEL = "gpt-5.5"


def required_env_vars_for_model(model: str) -> tuple[str, ...]:
    """Return known provider credential env vars for a LiteLLM model name."""
    model_name = (model or DEFAULT_LITELLM_MODEL).lower()
    for prefixes, env_vars in PROVIDER_ENV_VARS:
        if model_name.startswith(prefixes):
            return env_vars
    return ()


def missing_env_vars_for_model(
    model: str,
    environ: Mapping[str, str],
) -> tuple[str, ...]:
    """Return unset provider env vars for a known LiteLLM model prefix."""
    return tuple(
        name for name in required_env_vars_for_model(model) if not environ.get(name)
    )


def env_placeholder(name: str) -> str:
    """Return the operator-facing placeholder for a required provider env var."""
    if name.endswith("_API_KEY"):
        return "<provider API key>"
    if name == "AZURE_API_BASE":
        return "<azure endpoint>"
    if name == "AZURE_API_VERSION":
        return "<api version>"
    return "<value>"


def format_missing_env_vars_message(
    target: str,
    missing_env_vars: tuple[str, ...] | list[str],
) -> str:
    """Return the canonical remediation message for missing provider env vars."""
    joined = ", ".join(missing_env_vars)
    noun = "variable" if len(missing_env_vars) == 1 else "variables"
    verb = "is" if len(missing_env_vars) == 1 else "are"
    exports = " ".join(f"{name}={env_placeholder(name)}" for name in missing_env_vars)
    return (
        f"environment {noun} {joined} {verb} not set for {target}; "
        f"run: export {exports}"
    )


class LiteLLMAdapter:
    """Adapter for provider-routed LiteLLM completions."""

    info = EngineInfo(
        name="litellm",
        display_name="LiteLLM",
        binary="python3",
        required_python_module="litellm",
        default_model=DEFAULT_LITELLM_MODEL,
        execution_status="shell-dispatch",
        quota_status="not-implemented",
        notes=(
            "Generic provider bridge. Pass provider-specific model strings via "
            "--model, for example gemini/gemini-2.5-pro or xai/<model>."
        ),
    )

    def build_command(
        self,
        prompt: str,
        *,
        model: str = "",
        role: str = "writer",
        reasoning_effort: str = "xhigh",
    ) -> EngineCommand:
        """Build the Python process that performs one LiteLLM completion."""
        del reasoning_effort
        runner = Path(__file__).resolve().parents[1] / "litellm_runner.py"
        return EngineCommand(
            (
                sys.executable,
                str(runner),
                "--model",
                model or self.info.default_model,
                "--role",
                role,
                "--prompt",
                prompt,
            ),
            "plain",
        )

    def required_env_vars_for_model(self, model: str) -> tuple[str, ...]:
        """Return known provider credential env vars for a LiteLLM model name."""
        return required_env_vars_for_model(model or self.info.default_model)

    def parse_usage(self, raw_log: str) -> dict:
        """Usage extraction is not available through the generic v1 adapter."""
        del raw_log
        return {}

    def quota_snapshot(self) -> dict:
        """LiteLLM provider quota is not available without provider-specific APIs."""
        return {}

    def detect_failure(self, exit_code: int, raw_tail: str) -> EngineFailure:
        """Classify a LiteLLM runner exit."""
        if exit_code == 0 or exit_code == 141:
            return EngineFailure(False)
        tail = raw_tail.strip()
        lower_tail = tail.lower()
        if "litellm' is not installed" in lower_tail or "no module named" in lower_tail:
            return EngineFailure(True, "engine:dependency_missing", tail)
        if "api key" in lower_tail or "authentication" in lower_tail:
            return EngineFailure(True, "engine:auth", tail)
        if "rate limit" in lower_tail or "quota" in lower_tail:
            return EngineFailure(True, "engine:quota", tail)
        return EngineFailure(True, "engine:exit_nonzero", tail)


class LiteLLMProviderAdapter:
    """Provider-specific adapter backed by the generic LiteLLM runner."""

    def __init__(
        self,
        *,
        name: str,
        display_name: str,
        default_model: str,
        required_env_vars: tuple[str, ...] = (),
        notes: str,
    ) -> None:
        self.info = EngineInfo(
            name=name,
            display_name=display_name,
            binary="python3",
            required_python_module="litellm",
            required_env_vars=required_env_vars,
            default_model=default_model,
            execution_status="shell-dispatch",
            quota_status="not-implemented",
            notes=notes,
        )
        self._runtime = LiteLLMAdapter()

    def build_command(
        self,
        prompt: str,
        *,
        model: str = "",
        role: str = "writer",
        reasoning_effort: str = "xhigh",
    ) -> EngineCommand:
        """Build the LiteLLM runner command for this provider."""
        return self._runtime.build_command(
            prompt,
            model=model or self.info.default_model,
            role=role,
            reasoning_effort=reasoning_effort,
        )

    def required_env_vars_for_model(self, model: str) -> tuple[str, ...]:
        """Return provider credential env vars for this provider/default model."""
        if not model or model == self.info.default_model:
            return self.info.required_env_vars
        return self._runtime.required_env_vars_for_model(model)

    def parse_usage(self, raw_log: str) -> dict:
        """Usage extraction is handled by the LiteLLM sidecar writer."""
        return self._runtime.parse_usage(raw_log)

    def quota_snapshot(self) -> dict:
        """Provider quotas are not available without provider-specific APIs."""
        return self._runtime.quota_snapshot()

    def detect_failure(self, exit_code: int, raw_tail: str) -> EngineFailure:
        """Classify provider failures through the shared LiteLLM rules."""
        return self._runtime.detect_failure(exit_code, raw_tail)


ADAPTER = LiteLLMAdapter()
INFO = ADAPTER.info
