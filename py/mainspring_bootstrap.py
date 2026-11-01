# SPDX-License-Identifier: Apache-2.0
"""Console-script bootstrap for packaged Mainspring installs."""

from __future__ import annotations

import os
import shutil
import sys
from importlib import metadata
from pathlib import Path
from typing import Iterable

from cli_runtime import run_cli


def candidate_script_paths() -> list[Path]:
    """Return possible runtime script locations in preference order."""
    candidates: list[Path] = []
    script_override = os.environ.get("MAINSPRING_SCRIPT")
    if script_override:
        candidates.append(Path(script_override))

    home_override = os.environ.get("MAINSPRING_HOME")
    if home_override:
        candidates.append(Path(home_override) / "mainspring.sh")

    module_path = Path(__file__).resolve()
    candidates.append(module_path.parents[1] / "mainspring.sh")
    candidates.append(Path(sys.prefix) / "share" / "mainspring" / "mainspring.sh")
    return candidates


def resolve_script() -> Path:
    """Find the packaged or source-checkout shell runtime."""
    for candidate in candidate_script_paths():
        if candidate.is_file():
            return candidate.resolve()
    searched = ", ".join(str(path) for path in candidate_script_paths())
    raise FileNotFoundError(
        f"Could not find Mainspring runtime script. Searched: {searched}"
    )


def main(argv: Iterable[str] | None = None) -> int:
    """Exec the existing bash runtime with the caller's arguments."""
    args = list(sys.argv[1:] if argv is None else argv)
    script = resolve_script()
    bash = shutil.which("bash") or "/bin/bash"
    # The console script is the packaged-runtime bridge: every invocation should
    # target the project directory where the operator ran `mainspring`, even if
    # MAINSPRING_PROJECT_ROOT leaked from a parent process or prior packaged run.
    os.environ["MAINSPRING_PROJECT_ROOT"] = str(Path.cwd())
    os.environ["MAINSPRING_CONSOLE_ENTRYPOINT"] = "1"
    os.environ["MAINSPRING_RUNTIME_PYTHON"] = sys.executable
    try:
        os.environ["MAINSPRING_PACKAGE_VERSION"] = metadata.version("mainspring")
    except metadata.PackageNotFoundError:
        os.environ.pop("MAINSPRING_PACKAGE_VERSION", None)
    os.execv(bash, [bash, str(script), *args])
    return 127


if __name__ == "__main__":
    run_cli(main)
