# SPDX-License-Identifier: Apache-2.0
"""xAI Grok engine adapter routed through LiteLLM."""

from __future__ import annotations

from engines.litellm_adapter import LiteLLMProviderAdapter


ADAPTER = LiteLLMProviderAdapter(
    name="grok",
    display_name="xAI Grok",
    default_model="xai/grok-4.20-reasoning",
    required_env_vars=("XAI_API_KEY",),
    notes=(
        "Runtime dispatch uses LiteLLM with XAI_API_KEY provider auth. "
        "Missing litellm or provider credentials fail closed before auto-pass."
    ),
)
INFO = ADAPTER.info
