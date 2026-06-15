# SPDX-License-Identifier: Apache-2.0
"""Tests for shared CLI process-boundary behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from cli_runtime import run_cli


PY_DIR = Path(__file__).resolve().parents[1]


def test_run_cli_maps_none_return_to_success() -> None:
    def ok() -> None:
        return None

    with pytest.raises(SystemExit) as exc_info:
        run_cli(ok)

    assert exc_info.value.code == 0


def test_run_cli_preserves_integer_return_code() -> None:
    def usage_error() -> int:
        return 2

    with pytest.raises(SystemExit) as exc_info:
        run_cli(usage_error)

    assert exc_info.value.code == 2


def test_run_cli_maps_keyboard_interrupt_to_quiet_130() -> None:
    def interrupted() -> int:
        raise KeyboardInterrupt

    with pytest.raises(SystemExit) as exc_info:
        run_cli(interrupted)

    assert exc_info.value.code == 130


def test_python_entrypoints_normalize_keyboard_interrupts() -> None:
    offenders: list[str] = []
    for path in sorted(PY_DIR.rglob("*.py")):
        relative = path.relative_to(PY_DIR)
        if relative.parts[0] == "tests" or path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        if 'if __name__ == "__main__"' not in text:
            continue
        if "run_cli(" in text or "except KeyboardInterrupt" in text:
            continue
        offenders.append(str(relative))

    assert offenders == []
