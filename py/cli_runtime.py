# SPDX-License-Identifier: Apache-2.0
"""Shared CLI process-boundary helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import NoReturn


def run_cli(entrypoint: Callable[[], int | None]) -> NoReturn:
    """Run a CLI entrypoint and normalize operator interrupts."""
    try:
        result = entrypoint()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    raise SystemExit(0 if result is None else result)
