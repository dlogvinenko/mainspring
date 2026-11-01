# SPDX-License-Identifier: Apache-2.0
"""CLI wrapper for the Mainspring engine registry."""

from __future__ import annotations

import sys

from cli_runtime import run_cli
from engines.registry import main

if __name__ == "__main__":
    run_cli(lambda: main(sys.argv[1:]))
