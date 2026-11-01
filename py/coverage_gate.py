#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Dependency-free Python line coverage gate for Mainspring.

The v1.0 release checklist requires >=80% coverage on the Python helper
modules. This script uses the stdlib ``trace`` module so the gate does not add
another runtime dependency before extraction.
"""

from __future__ import annotations

from cli_runtime import run_cli

import argparse
import contextlib
import io
import json
import os
import runpy
import subprocess
import sys
import trace
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_THRESHOLD = 80.0
DEFAULT_TOP = 8
EXCLUDED_PARTS = {
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "mainspring.egg-info",
    "tests",
}


@dataclass(frozen=True)
class FileCoverage:
    path: Path
    executable: int
    covered: int

    @property
    def percent(self) -> float:
        if self.executable == 0:
            return 100.0
        return (self.covered / self.executable) * 100.0


@dataclass(frozen=True)
class CoverageReport:
    files: list[FileCoverage]
    threshold: float
    pytest_exit_code: int

    @property
    def executable(self) -> int:
        return sum(file.executable for file in self.files)

    @property
    def covered(self) -> int:
        return sum(file.covered for file in self.files)

    @property
    def percent(self) -> float:
        if self.executable == 0:
            return 100.0
        return (self.covered / self.executable) * 100.0

    @property
    def passed(self) -> bool:
        return self.pytest_exit_code == 0 and self.percent >= self.threshold


def iter_source_files(py_dir: Path) -> list[Path]:
    """Return Python source modules covered by the release gate."""
    root = py_dir.resolve()
    files: list[Path] = []
    for path in root.rglob("*.py"):
        relative_parts = set(path.relative_to(root).parts)
        if relative_parts.intersection(EXCLUDED_PARTS):
            continue
        files.append(path.resolve())
    return sorted(files)


def executable_lines(path: Path) -> set[int]:
    """Return executable source lines using the same parser as stdlib trace."""
    raw = trace._find_executable_linenos(str(path))
    lines: set[int] = set()
    for line in raw:
        try:
            line_number = int(line)
        except (TypeError, ValueError):
            continue
        if line_number > 0:
            lines.add(line_number)
    return lines


def normalize_counts(raw_counts: dict[tuple[str, int], int]) -> dict[Path, set[int]]:
    """Normalize trace count keys into resolved file paths."""
    covered: dict[Path, set[int]] = {}
    for (filename, line), count in raw_counts.items():
        if count <= 0 or line <= 0:
            continue
        covered.setdefault(Path(filename).resolve(), set()).add(int(line))
    return covered


def summarize_coverage(
    py_dir: Path,
    covered_lines: dict[Path, set[int]],
    *,
    threshold: float,
    pytest_exit_code: int,
) -> CoverageReport:
    files: list[FileCoverage] = []
    for path in iter_source_files(py_dir):
        executable = executable_lines(path)
        covered = executable.intersection(covered_lines.get(path.resolve(), set()))
        files.append(
            FileCoverage(
                path=path,
                executable=len(executable),
                covered=len(covered),
            )
        )
    return CoverageReport(
        files=files,
        threshold=threshold,
        pytest_exit_code=pytest_exit_code,
    )


def run_pytest_under_trace(
    py_dir: Path, pytest_args: list[str], *, stdout_to_stderr: bool = False
) -> tuple[int, dict[Path, set[int]]]:
    """Run pytest under stdlib trace and return exit code plus covered lines."""
    import pytest

    tracer = trace.Trace(
        count=True,
        trace=False,
        ignoredirs=[sys.prefix, sys.exec_prefix],
    )
    old_cwd = Path.cwd()
    py_dir = py_dir.resolve()
    sys.path.insert(0, str(py_dir))
    os.chdir(py_dir)
    try:
        stdout_context = (
            contextlib.redirect_stdout(sys.stderr)
            if stdout_to_stderr
            else contextlib.nullcontext()
        )
        with stdout_context, _trace_python_subprocesses(py_dir):
            exit_code = tracer.runfunc(pytest.main, pytest_args)
    finally:
        os.chdir(old_cwd)
        try:
            sys.path.remove(str(py_dir))
        except ValueError:
            pass
    return int(exit_code), normalize_counts(tracer.results().counts)


def _is_traceable_python_script(command: object, py_dir: Path) -> tuple[bool, Path]:
    """Return whether a subprocess command can be measured in-process."""
    if not isinstance(command, (list, tuple)) or len(command) < 2:
        return False, Path()
    if command[0] != sys.executable:
        return False, Path()
    script = Path(str(command[1])).resolve()
    py_root = py_dir.resolve()
    try:
        script.relative_to(py_root)
    except ValueError:
        return False, Path()
    if script.name == Path(__file__).name:
        return False, Path()
    if script.suffix != ".py":
        return False, Path()
    return True, script


class _CapturedStream(io.TextIOWrapper):
    """Text stream with a real ``buffer`` for CLI code that writes bytes."""

    def __init__(self) -> None:
        self._bytes = io.BytesIO()
        super().__init__(self._bytes, encoding="utf-8", newline="")

    def text_value(self) -> str:
        self.flush()
        return (
            self._bytes.getvalue()
            .decode("utf-8")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )

    def bytes_value(self) -> bytes:
        self.flush()
        return self._bytes.getvalue()


@contextlib.contextmanager
def _patched_argv_env_cwd(
    argv: list[str],
    *,
    env: dict[str, str] | None,
    cwd: str | os.PathLike[str] | None,
):
    """Temporarily emulate the process state that subprocess.run would provide."""
    old_argv = sys.argv[:]
    old_env = os.environ.copy()
    old_cwd = Path.cwd()
    sys.argv = argv
    try:
        if env is not None:
            os.environ.clear()
            os.environ.update(env)
        if cwd is not None:
            os.chdir(cwd)
        yield
    finally:
        os.chdir(old_cwd)
        os.environ.clear()
        os.environ.update(old_env)
        sys.argv = old_argv


def _run_python_script_in_process(
    command: list[Any] | tuple[Any, ...],
    *,
    env: dict[str, str] | None,
    cwd: str | os.PathLike[str] | None,
    text_mode: bool,
) -> tuple[int, str | bytes, str | bytes]:
    """Execute a helper script as ``__main__`` while stdlib trace is active."""
    script = Path(str(command[1])).resolve()
    argv = [str(script), *map(str, command[2:])]
    stdout = _CapturedStream()
    stderr = _CapturedStream()
    return_code = 0
    with (
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
        _patched_argv_env_cwd(argv, env=env, cwd=cwd),
    ):
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as exc:
            code = exc.code
            if code is None:
                return_code = 0
            elif isinstance(code, int):
                return_code = code
            else:
                print(code, file=sys.stderr)
                return_code = 1
        except BaseException:  # pragma: no cover - mirrors child process failure
            traceback.print_exc()
            return_code = 1
    return (
        return_code,
        stdout.text_value() if text_mode else stdout.bytes_value(),
        stderr.text_value() if text_mode else stderr.bytes_value(),
    )


@contextlib.contextmanager
def _trace_python_subprocesses(py_dir: Path):
    """Count first-party Python CLI tests without adding a coverage dependency.

    Many Mainspring tests validate helper CLIs via
    ``subprocess.run([sys.executable, script, ...])``. The stdlib ``trace``
    module cannot observe child interpreters, so the release gate would
    undercount already-tested code. During the gate only, run first-party helper
    scripts in-process under the active tracer while preserving the
    ``subprocess.run`` result shape used by the tests. Non-Python commands and
    the coverage gate itself still run as real subprocesses.
    """
    original_run = subprocess.run

    def run_wrapper(*popenargs: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        command = kwargs.get("args", popenargs[0] if popenargs else None)
        traceable, _script = _is_traceable_python_script(command, py_dir)
        if not traceable:
            return original_run(*popenargs, **kwargs)
        # Delegate deadlines and custom decoding; their child lines remain unobserved.
        if any(
            kwargs.get(key) is not None for key in ("timeout", "encoding", "errors")
        ):
            return original_run(*popenargs, **kwargs)
        if (
            kwargs.get("text") is not None
            and kwargs.get("universal_newlines") is not None
            and bool(kwargs["text"]) != bool(kwargs["universal_newlines"])
        ):
            return original_run(*popenargs, **kwargs)
        if kwargs.get("stdin") is not None or kwargs.get("input") is not None:
            return original_run(*popenargs, **kwargs)
        if kwargs.get("shell"):
            return original_run(*popenargs, **kwargs)

        capture_output = bool(kwargs.get("capture_output"))
        stdout_setting = kwargs.get("stdout")
        stderr_setting = kwargs.get("stderr")
        captures_stdout = capture_output or stdout_setting == subprocess.PIPE
        captures_stderr = capture_output or stderr_setting == subprocess.PIPE
        if not captures_stdout or not captures_stderr:
            return original_run(*popenargs, **kwargs)

        text_mode = bool(
            kwargs.get("text")
            or kwargs.get("universal_newlines")
            or kwargs.get("encoding")
            or kwargs.get("errors")
        )
        env = kwargs.get("env")
        cwd = kwargs.get("cwd")
        return_code, stdout, stderr = _run_python_script_in_process(
            list(command),
            env=env,
            cwd=cwd,
            text_mode=text_mode,
        )
        result = subprocess.CompletedProcess(
            args=command,
            returncode=return_code,
            stdout=stdout,
            stderr=stderr,
        )
        if kwargs.get("check") and return_code != 0:
            raise subprocess.CalledProcessError(
                return_code,
                command,
                output=stdout,
                stderr=stderr,
            )
        return result

    subprocess.run = run_wrapper
    try:
        yield
    finally:
        subprocess.run = original_run


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def format_text(report: CoverageReport, *, py_dir: Path, top: int = DEFAULT_TOP) -> str:
    """Render an operator-readable coverage report."""
    lines = [
        (
            "Python coverage: "
            f"{report.percent:.1f}% ({report.covered}/{report.executable} "
            "executable lines)"
        ),
        f"Threshold: {report.threshold:.1f}%",
        f"Pytest exit: {report.pytest_exit_code}",
    ]
    low_files = sorted(
        (file for file in report.files if file.executable > 0),
        key=lambda file: (file.percent, -file.executable, str(file.path)),
    )[:top]
    if low_files:
        lines.append("Lowest files:")
        for file in low_files:
            lines.append(
                "  "
                f"{file.percent:5.1f}% "
                f"{_relative(file.path, py_dir)} "
                f"({file.covered}/{file.executable})"
            )
    lines.append(f"COVERAGE_RESULT: {'PASS' if report.passed else 'FAIL'}")
    return "\n".join(lines)


def format_json(report: CoverageReport, *, py_dir: Path) -> str:
    """Render a stable JSON coverage report."""
    payload = {
        "threshold": report.threshold,
        "pytest_exit_code": report.pytest_exit_code,
        "percent": round(report.percent, 4),
        "covered": report.covered,
        "executable": report.executable,
        "passed": report.passed,
        "files": [
            {
                "path": _relative(file.path, py_dir),
                "percent": round(file.percent, 4),
                "covered": file.covered,
                "executable": file.executable,
            }
            for file in report.files
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Mainspring Python tests and enforce line coverage."
    )
    parser.add_argument(
        "--py-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Python helper directory to measure (default: this script's directory)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help="Minimum aggregate coverage percentage (default: 80)",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help="Number of lowest-coverage files to print in text mode",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Optional pytest args after -- (default: tests -q)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    py_dir = args.py_dir.resolve()
    pytest_args = list(args.pytest_args)
    if pytest_args and pytest_args[0] == "--":
        pytest_args = pytest_args[1:]
    if not pytest_args:
        pytest_args = ["tests", "-q"]

    pytest_exit_code, covered_lines = run_pytest_under_trace(
        py_dir, pytest_args, stdout_to_stderr=args.format == "json"
    )
    report = summarize_coverage(
        py_dir,
        covered_lines,
        threshold=args.threshold,
        pytest_exit_code=pytest_exit_code,
    )
    if args.format == "json":
        print(format_json(report, py_dir=py_dir))
    else:
        print(format_text(report, py_dir=py_dir, top=max(0, args.top)))
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    run_cli(main)
