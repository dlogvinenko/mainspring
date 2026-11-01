# SPDX-License-Identifier: Apache-2.0
"""Tests for coverage_gate.py — dependency-free Python coverage release gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import coverage_gate

SCRIPT = HERE.parent / "coverage_gate.py"


def _write_sample_project(root: Path) -> None:
    (root / "tests").mkdir()
    (root / "sample.py").write_text(
        "\n".join(
            [
                "def used(value):",
                "    if value:",
                "        return 'yes'",
                "    return 'no'",
                "",
                "def unused():",
                "    return 'never'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "tests" / "test_sample.py").write_text(
        "\n".join(
            [
                "import sample",
                "",
                "def test_used_branch():",
                "    assert sample.used(True) == 'yes'",
                "",
            ]
        ),
        encoding="utf-8",
    )


# Scenario: Source discovery should include runtime modules but exclude tests and
# generated cache/build directories.
# Expected: only first-party helper source files are measured.
def test_iter_source_files_excludes_tests_and_generated_dirs(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "engines").mkdir()
    (tmp_path / "module.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_module.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "__pycache__" / "module.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "engines" / "adapter.py").write_text("x = 1\n", encoding="utf-8")

    files = [
        path.relative_to(tmp_path) for path in coverage_gate.iter_source_files(tmp_path)
    ]

    assert files == [Path("engines/adapter.py"), Path("module.py")]


# Scenario: Coverage counts are normalized to resolved file paths and aggregate
# math uses executable-line intersections only.
# Expected: aggregate pass/fail truth is deterministic.
def test_summarize_coverage_uses_executable_line_intersection(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text(
        "\n".join(
            [
                "def first():",
                "    return 1",
                "",
                "def second():",
                "    return 2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    executable = coverage_gate.executable_lines(source)
    covered_line = min(executable)

    report = coverage_gate.summarize_coverage(
        tmp_path,
        {source.resolve(): {covered_line, 9999}},
        threshold=1.0,
        pytest_exit_code=0,
    )

    assert report.executable == len(executable)
    assert report.covered == 1
    assert report.passed is True


# Scenario: Pytest fails even when line coverage would pass.
# Expected: the release gate fails closed.
def test_report_fails_when_pytest_fails(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    lines = coverage_gate.executable_lines(source)

    report = coverage_gate.summarize_coverage(
        tmp_path,
        {source.resolve(): lines},
        threshold=1.0,
        pytest_exit_code=1,
    )

    assert report.percent == 100.0
    assert report.passed is False
    assert "COVERAGE_RESULT: FAIL" in coverage_gate.format_text(report, py_dir=tmp_path)


def test_zero_executable_file_and_empty_report_percentages(tmp_path: Path) -> None:
    empty_file = coverage_gate.FileCoverage(tmp_path / "empty.py", 0, 0)
    empty_report = coverage_gate.CoverageReport(
        files=[],
        threshold=80,
        pytest_exit_code=0,
    )
    failing_report = coverage_gate.CoverageReport(
        files=[empty_file],
        threshold=80,
        pytest_exit_code=1,
    )

    assert empty_file.percent == 100.0
    assert empty_report.percent == 100.0
    assert empty_report.passed is True
    assert failing_report.passed is False


def test_normalize_counts_discards_non_executable_counts(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    raw_counts = {
        (str(source), 1): 3,
        (str(source), 2): 0,
        (str(source), -1): 3,
    }

    covered = coverage_gate.normalize_counts(raw_counts)

    assert covered == {source.resolve(): {1}}


def test_traceable_python_script_detection_branches(tmp_path: Path) -> None:
    script = tmp_path / "helper.py"
    text = tmp_path / "helper.txt"
    script.write_text("print('ok')\n", encoding="utf-8")
    text.write_text("not python\n", encoding="utf-8")

    assert coverage_gate._is_traceable_python_script("not-list", tmp_path)[0] is False
    assert (
        coverage_gate._is_traceable_python_script([sys.executable], tmp_path)[0]
        is False
    )
    assert (
        coverage_gate._is_traceable_python_script(["python3", str(script)], tmp_path)[0]
        is False
    )
    assert (
        coverage_gate._is_traceable_python_script(
            [sys.executable, str(text)], tmp_path
        )[0]
        is False
    )
    assert (
        coverage_gate._is_traceable_python_script(
            [sys.executable, str(HERE.parent / "coverage_gate.py")],
            HERE.parent,
        )[0]
        is False
    )
    assert coverage_gate._is_traceable_python_script(
        [sys.executable, str(script)], tmp_path
    ) == (
        True,
        script.resolve(),
    )


def test_relative_falls_back_for_external_path(tmp_path: Path) -> None:
    external = tmp_path.parent / "external.py"

    assert coverage_gate._relative(external, tmp_path) == str(external)


def test_patched_argv_env_cwd_restores_process_state(tmp_path: Path) -> None:
    old_argv = sys.argv[:]
    old_env = os.environ.copy()
    old_cwd = Path.cwd()

    with coverage_gate._patched_argv_env_cwd(
        ["helper.py", "arg"],
        env={"ONLY_TEST_ENV": "1"},
        cwd=tmp_path,
    ):
        assert sys.argv == ["helper.py", "arg"]
        assert os.environ == {"ONLY_TEST_ENV": "1"}
        assert Path.cwd() == tmp_path

    assert sys.argv == old_argv
    assert os.environ == old_env
    assert Path.cwd() == old_cwd


def test_run_python_script_in_process_handles_non_integer_system_exit(
    tmp_path: Path,
) -> None:
    script = tmp_path / "exit_message.py"
    script.write_text("raise SystemExit('bad exit')\n", encoding="utf-8")

    return_code, stdout, stderr = coverage_gate._run_python_script_in_process(
        [sys.executable, str(script)],
        env=None,
        cwd=None,
        text_mode=True,
    )

    assert return_code == 1
    assert stdout == ""
    assert "bad exit" in stderr


def test_run_python_script_in_process_handles_none_system_exit(
    tmp_path: Path,
) -> None:
    script = tmp_path / "exit_none.py"
    script.write_text("raise SystemExit\n", encoding="utf-8")

    return_code, stdout, stderr = coverage_gate._run_python_script_in_process(
        [sys.executable, str(script)],
        env=None,
        cwd=None,
        text_mode=True,
    )

    assert return_code == 0
    assert stdout == ""
    assert stderr == ""


def test_run_python_script_in_process_captures_exceptions(tmp_path: Path) -> None:
    script = tmp_path / "boom.py"
    script.write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    return_code, _stdout, stderr = coverage_gate._run_python_script_in_process(
        [sys.executable, str(script)],
        env=None,
        cwd=None,
        text_mode=True,
    )

    assert return_code == 1
    assert "RuntimeError: boom" in stderr


# Scenario: CLI tests often execute first-party helper scripts through
# subprocess.run. The coverage gate should trace those helpers in-process while
# preserving subprocess-like argv, cwd, env, text output, and binary stdout.
# Expected: captured results match subprocess.run's public result shape.
def test_trace_python_subprocesses_preserves_subprocess_result_shape(
    tmp_path: Path,
) -> None:
    text_script = tmp_path / "text_helper.py"
    text_script.write_text(
        "\n".join(
            [
                "import os",
                "import sys",
                "print(f'argv={sys.argv[1]}')",
                "print(f'cwd={os.getcwd()}')",
                "print(f'env={os.environ.get(\"TRACE_GATE_TEST\")}', file=sys.stderr)",
            ]
        ),
        encoding="utf-8",
    )
    binary_script = tmp_path / "binary_helper.py"
    binary_script.write_text(
        "import sys\nsys.stdout.buffer.write(b'display\\0mode')\n",
        encoding="utf-8",
    )

    with coverage_gate._trace_python_subprocesses(tmp_path):
        text_result = subprocess.run(
            [sys.executable, str(text_script), "hello"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={"TRACE_GATE_TEST": "configured"},
            check=False,
        )
        binary_result = subprocess.run(
            [sys.executable, str(binary_script)],
            capture_output=True,
            check=False,
        )

    assert text_result.returncode == 0
    assert "argv=hello" in text_result.stdout
    assert f"cwd={tmp_path}" in text_result.stdout
    assert text_result.stderr.strip() == "env=configured"
    assert binary_result.returncode == 0
    assert binary_result.stdout == b"display\x00mode"


def test_trace_python_subprocesses_fallbacks_and_check_error(tmp_path: Path) -> None:
    script = tmp_path / "fails.py"
    script.write_text("raise SystemExit(7)\n", encoding="utf-8")

    with coverage_gate._trace_python_subprocesses(tmp_path):
        no_capture = subprocess.run([sys.executable, str(script)], check=False)
        with_input = subprocess.run(
            [sys.executable, str(script)],
            input="ignored",
            capture_output=True,
            text=True,
            check=False,
        )
        with pytest.raises(subprocess.CalledProcessError) as exc:
            subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                check=True,
            )

    assert no_capture.returncode == 7
    assert with_input.returncode == 7
    assert exc.value.returncode == 7


def test_main_text_mode_failure_uses_default_pytest_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def fake_run_pytest_under_trace(
        py_dir: Path,
        pytest_args: list[str],
        *,
        stdout_to_stderr: bool = False,
    ) -> tuple[int, dict[Path, set[int]]]:
        assert py_dir == tmp_path.resolve()
        assert pytest_args == ["tests", "-q"]
        assert stdout_to_stderr is False
        return 0, {}

    monkeypatch.setattr(
        coverage_gate,
        "run_pytest_under_trace",
        fake_run_pytest_under_trace,
    )

    with pytest.raises(SystemExit) as exc:
        coverage_gate.main(
            ["--py-dir", str(tmp_path), "--threshold", "100", "--top", "0"]
        )

    assert exc.value.code == 1
    assert "COVERAGE_RESULT: FAIL" in capsys.readouterr().out


def test_main_json_mode_strips_separator_and_redirects_pytest_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    covered_line = min(coverage_gate.executable_lines(source))

    def fake_run_pytest_under_trace(
        py_dir: Path,
        pytest_args: list[str],
        *,
        stdout_to_stderr: bool = False,
    ) -> tuple[int, dict[Path, set[int]]]:
        assert py_dir == tmp_path.resolve()
        assert pytest_args == ["tests", "-q"]
        assert stdout_to_stderr is True
        return 0, {source.resolve(): {covered_line}}

    monkeypatch.setattr(
        coverage_gate,
        "run_pytest_under_trace",
        fake_run_pytest_under_trace,
    )

    coverage_gate.main(
        [
            "--py-dir",
            str(tmp_path),
            "--threshold",
            "100",
            "--format",
            "json",
            "--",
            "tests",
            "-q",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["files"][0]["path"] == "module.py"


# Scenario: JSON mode is intended for CI and shell consumers.
# Expected: pytest output is redirected away from stdout and JSON parses cleanly.
def test_cli_json_mode_is_clean(tmp_path: Path) -> None:
    _write_sample_project(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--py-dir",
            str(tmp_path),
            "--threshold",
            "1",
            "--format",
            "json",
            "--",
            "tests",
            "-q",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["passed"] is True
    assert payload["pytest_exit_code"] == 0
    assert payload["executable"] > 0
    assert {row["path"] for row in payload["files"]} == {"sample.py"}


# Scenario: Threshold failures should be visible from the CLI.
# Expected: nonzero exit and a clear coverage failure marker.
def test_cli_text_mode_fails_below_threshold(tmp_path: Path) -> None:
    _write_sample_project(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--py-dir",
            str(tmp_path),
            "--threshold",
            "99",
            "--",
            "tests",
            "-q",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "COVERAGE_RESULT: FAIL" in result.stdout
    assert "sample.py" in result.stdout
