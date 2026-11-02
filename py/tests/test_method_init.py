# SPDX-License-Identifier: Apache-2.0
"""Tests for method_init.py — Mainspring Method project scaffolding."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import method_init

SCRIPT = str(HERE.parent / "method_init.py")


def _write_template(root: Path) -> None:
    template = root / "method/templates/prd.md"
    template.parent.mkdir(parents=True)
    template.write_text("# {{Project / Scope name}}\n\nOwner: {{Project}}\n")


# Scenario: project names are turned into stable doc directory slugs.
# Expected: punctuation collapses to one dash.
def test_slugify_name() -> None:
    assert method_init.slugify_name("Demo Feature!") == "demo-feature"


# Scenario: invalid project names contain no slug-safe characters.
# Expected: ValueError.
def test_slugify_name_rejects_empty() -> None:
    try:
        method_init.slugify_name(" !!! ")
    except ValueError as exc:
        assert "project name" in str(exc)
    else:
        raise AssertionError("expected ValueError")


# Scenario: the repo already has Taskmaster initialized.
# Expected: PRD template is rendered, runtime dirs are created, no external CLI runs.
def test_init_project_with_existing_taskmaster(tmp_path: Path) -> None:
    _write_template(tmp_path)
    (tmp_path / ".taskmaster").mkdir()

    result = method_init.init_project(tmp_path, "Demo Feature")

    assert result.ok is True
    assert result.slug == "demo-feature"
    assert result.taskmaster_status == "already present"
    assert (
        (tmp_path / "docs/demo-feature/prd.md").read_text().startswith("# Demo Feature")
    )
    assert "Owner: Demo Feature" in (tmp_path / "docs/demo-feature/prd.md").read_text()
    assert (tmp_path / ".mainspring/state").is_dir()
    assert (tmp_path / ".mainspring/logs").is_dir()
    active_prd = json.loads(
        (tmp_path / ".mainspring/state/active-prd.json").read_text()
    )
    assert active_prd["prd_path"] == "docs/demo-feature/prd.md"
    assert active_prd["active_phase"] == ""


# Scenario: source templates can be absent from an operator project when
# Mainspring is installed as a package.
# Expected: init resolves the bundled runtime template instead.
def test_init_project_uses_packaged_template_when_project_has_no_tools_tree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundled = tmp_path / "bundled/prd.md"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("# {{Project}}\n")
    project = tmp_path / "operator-project"
    project.mkdir()
    (project / ".taskmaster").mkdir()
    monkeypatch.setenv("MAINSPRING_METHOD_PRD_TEMPLATE", str(bundled))

    result = method_init.init_project(project, "Packaged Demo")

    assert result.ok is True
    assert (project / "docs/packaged-demo/prd.md").read_text() == "# Packaged Demo\n"
    monkeypatch.delenv("MAINSPRING_METHOD_PRD_TEMPLATE", raising=False)


# Scenario: no source or packaged Method template is available.
# Expected: init fails closed with every searched path visible.
def test_init_project_reports_all_template_candidates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "operator-project"
    project.mkdir()
    (project / ".taskmaster").mkdir()
    missing = tmp_path / "missing-prd.md"
    packaged_missing = tmp_path / "missing-runtime/method/templates/prd.md"
    monkeypatch.setattr(
        method_init,
        "candidate_template_paths",
        lambda root: [missing, packaged_missing],
    )

    result = method_init.init_project(project, "missing template")

    assert result.ok is False
    assert "Method PRD template not found" in result.message
    assert str(missing) in result.message
    assert str(packaged_missing) in result.message
    assert "method/templates/prd.md" in result.message
    assert not (project / "docs/missing-template/prd.md").exists()


# Scenario: a PRD already exists.
# Expected: init fails without overwriting the file.
def test_init_project_refuses_overwrite(tmp_path: Path) -> None:
    _write_template(tmp_path)
    (tmp_path / ".taskmaster").mkdir()
    existing = tmp_path / "docs/demo/prd.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("keep me")

    result = method_init.init_project(tmp_path, "demo")

    assert result.ok is False
    assert "already exists" in result.message
    assert existing.read_text() == "keep me"


# Scenario: --force is explicit.
# Expected: existing PRD is replaced by rendered template.
def test_init_project_force_overwrites(tmp_path: Path) -> None:
    _write_template(tmp_path)
    (tmp_path / ".taskmaster").mkdir()
    existing = tmp_path / "docs/demo/prd.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("old")

    result = method_init.init_project(tmp_path, "demo", force=True)

    assert result.ok is True
    assert existing.read_text().startswith("# demo")


# Scenario: Taskmaster is absent and no CLI is available.
# Expected: init fails closed before creating a partial PRD.
def test_init_project_requires_taskmaster_when_missing(
    tmp_path: Path, monkeypatch
) -> None:
    _write_template(tmp_path)
    monkeypatch.setattr(method_init, "_find_taskmaster", lambda: None)

    result = method_init.init_project(tmp_path, "demo")

    assert result.ok is False
    assert result.taskmaster_status == "missing"
    assert not (tmp_path / "docs/demo/prd.md").exists()


def test_init_project_initializes_taskmaster_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_template(tmp_path)
    monkeypatch.setattr(method_init, "_find_taskmaster", lambda: "/usr/bin/task-master")
    monkeypatch.setattr(
        method_init,
        "_run_taskmaster_init",
        lambda root, binary: (True, f"initialized via {Path(binary).name}"),
    )

    result = method_init.init_project(tmp_path, "Demo")

    assert result.ok is True
    assert result.taskmaster_status == "initialized via task-master"
    assert (tmp_path / "docs/demo/prd.md").exists()


def test_init_project_stops_when_taskmaster_init_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_template(tmp_path)
    monkeypatch.setattr(method_init, "_find_taskmaster", lambda: "/usr/bin/task-master")
    monkeypatch.setattr(
        method_init,
        "_run_taskmaster_init",
        lambda root, binary: (False, "taskmaster init failed: boom"),
    )

    result = method_init.init_project(tmp_path, "Demo")

    assert result.ok is False
    assert result.taskmaster_status == "taskmaster init failed: boom"
    assert not (tmp_path / "docs/demo/prd.md").exists()


@pytest.mark.parametrize(
    ("completed", "expected"),
    [
        (
            SimpleNamespace(returncode=0, stdout="ok", stderr=""),
            (True, "initialized via task-master"),
        ),
        (
            SimpleNamespace(returncode=3, stdout="", stderr="bad config\n"),
            (False, "taskmaster init failed: bad config"),
        ),
        (
            SimpleNamespace(returncode=4, stdout="", stderr=""),
            (False, "taskmaster init failed with exit code 4"),
        ),
    ],
)
def test_run_taskmaster_init_reports_success_and_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    completed: SimpleNamespace,
    expected: tuple[bool, str],
) -> None:
    monkeypatch.setattr(
        method_init.subprocess, "run", lambda *args, **kwargs: completed
    )

    assert method_init._run_taskmaster_init(tmp_path, "/bin/task-master") == expected


# Scenario: CLI help is requested.
# Expected: exit 0 without scaffolding.
def test_cli_help() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Usage" in result.stdout
    assert result.stderr == ""


# Scenario: CLI initializes into a temp root with existing Taskmaster state.
# Expected: exit 0 and next-step text.
def test_cli_init_existing_taskmaster(tmp_path: Path) -> None:
    _write_template(tmp_path)
    (tmp_path / ".taskmaster").mkdir()

    result = subprocess.run(
        [sys.executable, SCRIPT, "demo feature", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Mainspring project initialized" in result.stdout
    assert "mainspring validate-prd " in result.stdout
    assert "docs/demo-feature/prd.md" in result.stdout
    assert "3. mainspring" in result.stdout
    assert (tmp_path / "docs/demo-feature/prd.md").exists()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "Usage: mainspring init"),
        (["demo", "--root"], "Unknown flag: --root"),
        (["!!!"], "project name must contain"),
    ],
)
def test_cli_usage_errors(args: list[str], message: str) -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert message in result.stderr
