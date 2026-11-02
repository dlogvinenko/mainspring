# SPDX-License-Identifier: Apache-2.0
"""Tests for the shared LiteLLM engine adapter."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from engines import litellm_adapter


def test_required_env_vars_for_model_known_unknown_and_default() -> None:
    assert litellm_adapter.required_env_vars_for_model("gemini/gemini-2.5-pro") == (
        "GOOGLE_API_KEY",
    )
    assert litellm_adapter.required_env_vars_for_model("custom/local-model") == ()
    assert litellm_adapter.required_env_vars_for_model("") == ("OPENAI_API_KEY",)


def test_missing_env_vars_for_model_reports_only_unset_values() -> None:
    missing = litellm_adapter.missing_env_vars_for_model(
        "azure/gpt-5.5",
        {"AZURE_API_KEY": "set"},
    )

    assert missing == ("AZURE_API_BASE", "AZURE_API_VERSION")


def test_env_placeholders_and_missing_env_message() -> None:
    assert litellm_adapter.env_placeholder("GOOGLE_API_KEY") == "<provider API key>"
    assert litellm_adapter.env_placeholder("AZURE_API_BASE") == "<azure endpoint>"
    assert litellm_adapter.env_placeholder("AZURE_API_VERSION") == "<api version>"
    assert litellm_adapter.env_placeholder("CUSTOM_VALUE") == "<value>"

    one = litellm_adapter.format_missing_env_vars_message(
        "gemini",
        ("GOOGLE_API_KEY",),
    )
    many = litellm_adapter.format_missing_env_vars_message(
        "azure",
        ("AZURE_API_KEY", "AZURE_API_BASE"),
    )

    assert "environment variable GOOGLE_API_KEY is not set" in one
    assert "environment variables AZURE_API_KEY, AZURE_API_BASE are not set" in many
    assert "export AZURE_API_KEY=<provider API key>" in many


def test_litellm_adapter_command_usage_quota_and_failures() -> None:
    adapter = litellm_adapter.LiteLLMAdapter()

    command = adapter.build_command("ship it", model="", role="reviewer")

    assert command.argv[0] == sys.executable
    assert command.argv[1].endswith("litellm_runner.py")
    assert "--model" in command.argv
    assert litellm_adapter.DEFAULT_LITELLM_MODEL in command.argv
    assert "--role" in command.argv
    assert "reviewer" in command.argv
    assert adapter.required_env_vars_for_model("gemini/gemini-2.5-pro") == (
        "GOOGLE_API_KEY",
    )
    assert adapter.parse_usage("anything") == {}
    assert adapter.quota_snapshot() == {}
    assert adapter.detect_failure(0, "").failed is False
    assert adapter.detect_failure(141, "").failed is False
    assert (
        adapter.detect_failure(1, "ModuleNotFoundError: No module named litellm").reason
        == "engine:dependency_missing"
    )
    assert adapter.detect_failure(1, "API key missing").reason == "engine:auth"
    assert adapter.detect_failure(1, "rate limit exceeded").reason == "engine:quota"
    assert adapter.detect_failure(1, "unexpected").reason == "engine:exit_nonzero"


def test_provider_adapter_uses_default_and_delegates_override() -> None:
    adapter = litellm_adapter.LiteLLMProviderAdapter(
        name="fixture",
        display_name="Fixture",
        default_model="fixture/default",
        required_env_vars=("FIXTURE_API_KEY",),
        notes="test adapter",
    )

    default_command = adapter.build_command("prompt")
    override_command = adapter.build_command("prompt", model="gemini/gemini-2.5-pro")

    assert "fixture/default" in default_command.argv
    assert "gemini/gemini-2.5-pro" in override_command.argv
    assert adapter.required_env_vars_for_model("") == ("FIXTURE_API_KEY",)
    assert adapter.required_env_vars_for_model("fixture/default") == (
        "FIXTURE_API_KEY",
    )
    assert adapter.required_env_vars_for_model("gemini/gemini-2.5-pro") == (
        "GOOGLE_API_KEY",
    )
    assert adapter.parse_usage("raw") == {}
    assert adapter.quota_snapshot() == {}
    assert adapter.detect_failure(1, "quota").reason == "engine:quota"
