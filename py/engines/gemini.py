# SPDX-License-Identifier: Apache-2.0
"""Gemini engine adapter routed through LiteLLM."""

from __future__ import annotations

from engines.litellm_adapter import LiteLLMProviderAdapter

ADAPTER = LiteLLMProviderAdapter(
    name="gemini",
    display_name="Google Gemini",
    default_model="gemini/gemini-2.5-pro",
    required_env_vars=("GOOGLE_API_KEY",),
    notes=(
        "Runtime dispatch uses LiteLLM with GOOGLE_API_KEY provider auth. "
        "Missing litellm or provider credentials fail closed before auto-pass."
    ),
)
INFO = ADAPTER.info
