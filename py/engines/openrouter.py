# SPDX-License-Identifier: Apache-2.0
"""OpenRouter engine adapter routed through LiteLLM."""

from __future__ import annotations

from engines.litellm_adapter import LiteLLMProviderAdapter


ADAPTER = LiteLLMProviderAdapter(
    name="openrouter",
    display_name="OpenRouter",
    default_model="openrouter/openai/gpt-5.5",
    required_env_vars=("OPENROUTER_API_KEY",),
    notes=(
        "Runtime dispatch uses LiteLLM with OPENROUTER_API_KEY provider auth. "
        "Missing litellm or provider credentials fail closed before auto-pass."
    ),
)
INFO = ADAPTER.info
