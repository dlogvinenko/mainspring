# SPDX-License-Identifier: Apache-2.0
"""OpenAI engine adapter routed through LiteLLM."""

from __future__ import annotations

from engines.litellm_adapter import LiteLLMProviderAdapter


ADAPTER = LiteLLMProviderAdapter(
    name="openai",
    display_name="OpenAI",
    default_model="openai/gpt-5.5",
    required_env_vars=("OPENAI_API_KEY",),
    notes=(
        "Runtime dispatch uses LiteLLM with OPENAI_API_KEY provider auth. "
        "Missing litellm or provider credentials fail closed before auto-pass."
    ),
)
INFO = ADAPTER.info
