# SPDX-License-Identifier: Apache-2.0
"""Release-hygiene tests for Mainspring source license headers."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAINSPRING_DIR = REPO_ROOT
SPDX = "SPDX-License-Identifier: Apache-2.0"
EXCLUDED_PARTS = {
    ".git",
    ".mainspring",
    ".omx",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "mainspring.egg-info",
    "node_modules",
}
SOURCE_SUFFIXES = {".py", ".sh", ".bats"}
SOURCE_FILENAMES = {"Makefile"}


def _mainspring_source_files() -> list[Path]:
    files: list[Path] = []
    for path in MAINSPRING_DIR.rglob("*"):
        if not path.is_file():
            continue
        if EXCLUDED_PARTS.intersection(path.parts):
            continue
        if path.suffix in SOURCE_SUFFIXES or path.name in SOURCE_FILENAMES:
            files.append(path)
    return sorted(files)


# Scenario: P7 release hygiene requires every Mainspring source file to carry
# an Apache-2.0 SPDX marker before extraction.
# Expected: shebang-compatible source headers are present near the top of file.
def test_mainspring_source_files_have_apache_spdx_headers() -> None:
    missing = []
    for path in _mainspring_source_files():
        first_lines = path.read_text(encoding="utf-8").splitlines()[:5]
        if not any(SPDX in line for line in first_lines):
            missing.append(str(path.relative_to(REPO_ROOT)))

    assert missing == []
