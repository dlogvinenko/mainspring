# SPDX-License-Identifier: Apache-2.0
"""Tests for safe fnm JSON environment parsing."""

from __future__ import annotations

from io import StringIO

import fnm_env


# Scenario: fnm's JSON output is converted without evaluating shell code.
# Expected: only allowlisted keys and the derived bin path are emitted.
def test_emit_assignments_outputs_allowlisted_keys_only() -> None:
    stdin = StringIO(
        """
        {
          "FNM_MULTISHELL_PATH": "/tmp/fnm-shell",
          "FNM_LOGLEVEL": "quiet",
          "PATH": "/malicious/path",
          "UNRELATED": "ignored"
        }
        """
    )
    stdout = StringIO()

    assert fnm_env.emit_assignments(stdin, stdout) == 0

    lines = stdout.getvalue().splitlines()
    assert "MAINSPRING_FNM_BIN=/tmp/fnm-shell/bin" in lines
    assert "FNM_MULTISHELL_PATH=/tmp/fnm-shell" in lines
    assert "FNM_LOGLEVEL=quiet" in lines
    assert all(not line.startswith("PATH=") for line in lines)
    assert all(not line.startswith("UNRELATED=") for line in lines)


# Scenario: fnm values can contain accidental newlines.
# Expected: output remains one assignment per line for shell parsing.
def test_emit_assignments_strips_newlines_from_values() -> None:
    stdin = StringIO('{"FNM_DIR": "/tmp/fnm\\nINJECTED=1"}')
    stdout = StringIO()

    assert fnm_env.emit_assignments(stdin, stdout) == 0

    assert stdout.getvalue() == "FNM_DIR=/tmp/fnmINJECTED=1\n"


# Scenario: malformed fnm output should not alter PATH setup.
# Expected: the helper exits non-zero and prints no assignments.
def test_emit_assignments_rejects_malformed_json() -> None:
    stdout = StringIO()

    assert fnm_env.emit_assignments(StringIO("{not-json"), stdout) == 1

    assert stdout.getvalue() == ""


# Scenario: CLI invocation is intentionally tiny for shell use.
# Expected: unknown arguments fail with usage instead of silently succeeding.
def test_main_rejects_arguments(capsys) -> None:
    assert fnm_env.main(["--bogus"]) == 2

    assert "Usage: fnm_env.py" in capsys.readouterr().err
