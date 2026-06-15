# SPDX-License-Identifier: Apache-2.0
"""Anthropic engine adapter routed through LiteLLM."""

from __future__ import annotations

from engines.litellm_adapter import LiteLLMProviderAdapter


ADAPTER = LiteLLMProviderAdapter(
    name="anthropic",
    display_name="Anthropic",
    default_model="anthropic/claude-opus-4.7",
    required_env_vars=("ANTHROPIC_API_KEY",),
    notes=(
        "Runtime dispatch uses LiteLLM with ANTHROPIC_API_KEY provider auth. "
        "Missing litellm or provider credentials fail closed before auto-pass."
    ),
)
INFO = ADAPTER.info
