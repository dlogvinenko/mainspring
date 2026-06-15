# SPDX-License-Identifier: Apache-2.0
"""Mistral engine adapter routed through LiteLLM."""

from __future__ import annotations

from engines.litellm_adapter import LiteLLMProviderAdapter


ADAPTER = LiteLLMProviderAdapter(
    name="mistral",
    display_name="Mistral",
    default_model="mistral/mistral-large-latest",
    required_env_vars=("MISTRAL_API_KEY",),
    notes=(
        "Runtime dispatch uses LiteLLM with MISTRAL_API_KEY provider auth. "
        "Missing litellm or provider credentials fail closed before auto-pass."
    ),
)
INFO = ADAPTER.info
