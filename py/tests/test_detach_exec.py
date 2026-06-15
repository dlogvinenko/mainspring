# SPDX-License-Identifier: Apache-2.0
"""Tests for the detached process spawner."""

from __future__ import annotations

import os

import detach_exec


def test_main_requires_command(capsys) -> None:
    assert detach_exec.main([]) == 2
    assert "Usage: detach_exec.py <command>" in capsys.readouterr().err


def test_main_detaches_before_exec(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    def fake_setsid() -> None:
        calls.append(("setsid", None))

    def fake_execvp(command: str, args: list[str]) -> None:
        calls.append(("execvp", (command, args)))
        raise SystemExit(0)

    monkeypatch.setattr(os, "setsid", fake_setsid)
    monkeypatch.setattr(os, "execvp", fake_execvp)

    try:
        detach_exec.main(["python3", "notify_telegram.py", "watch"])
    except SystemExit:
        pass

    assert calls == [
        ("setsid", None),
        ("execvp", ("python3", ["python3", "notify_telegram.py", "watch"])),
    ]


def test_main_reports_exec_failure_without_traceback(monkeypatch, capsys) -> None:
    calls: list[str] = []

    def fake_setsid() -> None:
        calls.append("setsid")

    def fake_execvp(command: str, args: list[str]) -> None:
        raise FileNotFoundError(command)

    monkeypatch.setattr(os, "setsid", fake_setsid)
    monkeypatch.setattr(os, "execvp", fake_execvp)

    assert detach_exec.main(["missing-command"]) == 127

    assert calls == ["setsid"]
    captured = capsys.readouterr()
    assert "could not exec missing-command" in captured.err
    assert "Traceback" not in captured.err
