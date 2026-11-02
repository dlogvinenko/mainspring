# SPDX-License-Identifier: Apache-2.0
"""Local Ollama engine adapter routed through LiteLLM."""

from __future__ import annotations

from engines.litellm_adapter import LiteLLMProviderAdapter

ADAPTER = LiteLLMProviderAdapter(
    name="ollama",
    display_name="Ollama",
    default_model="ollama/llama3.1",
    notes=(
        "Runtime dispatch uses LiteLLM against the local Ollama provider. "
        "No cloud API key is required; local Ollama availability is checked at runtime."
    ),
)
INFO = ADAPTER.info
