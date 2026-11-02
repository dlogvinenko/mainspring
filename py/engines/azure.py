# SPDX-License-Identifier: Apache-2.0
"""Azure OpenAI engine adapter routed through LiteLLM."""

from __future__ import annotations

from engines.litellm_adapter import LiteLLMProviderAdapter

ADAPTER = LiteLLMProviderAdapter(
    name="azure",
    display_name="Azure OpenAI",
    default_model="azure/gpt-5.5",
    required_env_vars=("AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION"),
    notes=(
        "Runtime dispatch uses LiteLLM with Azure OpenAI deployment auth. "
        "Override --model when the Azure deployment name differs from gpt-5.5."
    ),
)
INFO = ADAPTER.info
