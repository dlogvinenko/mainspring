# SPDX-License-Identifier: Apache-2.0
"""Command-boundary controls with every session/exec operation stubbed."""

from __future__ import annotations

from pathlib import Path

import pytest

from . import test_detach_exec as canonical


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "empty-first",
        "empty-first-later",
        "transfer",
        "empty-later",
        "whitespace-command",
        "missing-command",
        "session-error",
    ],
)
def test_command_boundary_preserves_existing_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, case: str
) -> None:
    marker = tmp_path / "never-created-executable"
    assert not marker.exists()
    command = str(marker)
    argv = [command]
    if case == "missing":
        argv = []
    elif case == "empty-first":
        argv = [""]
    elif case == "empty-first-later":
        argv = ["", "later"]
    elif case == "empty-later":
        argv = [command, "", "arg with spaces"]
    elif case == "whitespace-command":
        argv = [" "]
    original = list(argv)
    calls = []

    def fake_setsid():
        calls.append(("setsid", None))
        if case == "session-error":
            raise PermissionError("synthetic session failure")

    def fake_execvp(value, args):
        calls.append(("execvp", (value, list(args))))
        if not args[0]:
            # Historical interpreter validation is data, never a real exec here.
            raise ValueError("execv() arg 2 first element cannot be empty")
        if case in {"whitespace-command", "missing-command"}:
            raise FileNotFoundError(2, "synthetic missing command")
        raise SystemExit(0)

    # This fixture cannot create a session or execute any requested command.
    monkeypatch.setattr(canonical.detach_exec.os, "setsid", fake_setsid)
    monkeypatch.setattr(canonical.detach_exec.os, "execvp", fake_execvp)
    if case in {"missing", "empty-first", "empty-first-later"}:
        assert canonical.detach_exec.main(argv) == 2
        assert calls == []
        assert "Usage: detach_exec.py <command>" in capsys.readouterr().err
    elif case == "session-error":
        with pytest.raises(PermissionError, match="synthetic session failure"):
            canonical.detach_exec.main(argv)
        assert calls == [("setsid", None)]
        assert capsys.readouterr().err == ""
    elif case in {"whitespace-command", "missing-command"}:
        assert canonical.detach_exec.main(argv) == 127
        assert calls == [("setsid", None), ("execvp", (argv[0], argv))]
        error = capsys.readouterr().err
        assert f"could not exec {argv[0]}" in error
        assert "synthetic missing command" in error
        assert "Traceback" not in error
    else:
        with pytest.raises(SystemExit) as transfer:
            canonical.detach_exec.main(argv)
        assert transfer.value.code == 0
        assert calls == [("setsid", None), ("execvp", (argv[0], argv))]
        assert capsys.readouterr().err == ""
    assert argv == original
