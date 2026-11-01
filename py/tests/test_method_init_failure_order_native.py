# SPDX-License-Identifier: Apache-2.0
"""Owned Method refusal/failure-order and CLI result regressions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from . import test_method_init as canonical

TEMPLATE = "# {{Project / Scope name}}\n\nOwner: {{Project}}\n"
PRD_BYTES = b"OWNED PRD\r\nKeep this complete document.\r\n"
ACTIVE_BYTES = b'{"owner":"synthetic-existing-project","phase":"keep"}\n'
BACKEND_FAILURE = "taskmaster init failed: controlled failure"


@dataclass(frozen=True)
class OwnedProject:
    root: Path
    template: Path
    prd: Path
    active: Path


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OwnedProject:
    root = tmp_path / "project"
    root.mkdir()
    template = tmp_path / "templates/prd.md"
    template.parent.mkdir()
    template.write_text(TEMPLATE)

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("backend lookup or invocation must be explicitly stubbed")

    monkeypatch.setattr(
        canonical.method_init, "candidate_template_paths", lambda _root: [template]
    )
    monkeypatch.setattr(canonical.method_init, "_find_taskmaster", unexpected)
    monkeypatch.setattr(canonical.method_init, "_run_taskmaster_init", unexpected)
    return OwnedProject(
        root,
        template,
        root / "docs/demo/prd.md",
        root / ".mainspring/state/active-prd.json",
    )


def seed_prd(project: OwnedProject) -> None:
    project.prd.parent.mkdir(parents=True)
    project.prd.write_bytes(PRD_BYTES)


def seed_active(project: OwnedProject, present: bool) -> None:
    if present:
        project.active.parent.mkdir(parents=True)
        project.active.write_bytes(ACTIVE_BYTES)


def assert_active_preserved(project: OwnedProject, present: bool) -> None:
    if present:
        assert project.active.read_bytes() == ACTIVE_BYTES
    else:
        assert not (project.root / ".mainspring").exists()


def controlled_failure(
    project: OwnedProject, monkeypatch: pytest.MonkeyPatch, phase: str
) -> list[str]:
    calls: list[str] = []

    def find() -> str | None:
        calls.append("find")
        return (
            None if phase == "binary" else str(project.root / "synthetic-task-master")
        )

    def backend(_root: Path, _binary: str) -> tuple[bool, str]:
        calls.append("backend")
        return False, BACKEND_FAILURE

    monkeypatch.setattr(canonical.method_init, "_find_taskmaster", find)
    monkeypatch.setattr(canonical.method_init, "_run_taskmaster_init", backend)
    if phase == "template":
        monkeypatch.setattr(
            canonical.method_init,
            "candidate_template_paths",
            lambda _root: [project.root / "missing-controlled-template.md"],
        )
    return calls


def assert_failure(result: object, phase: str) -> None:
    assert isinstance(result, canonical.method_init.InitResult)
    assert result.ok is False
    if phase == "existing":
        assert result.taskmaster_status == "not-run"
        assert "PRD already exists:" in result.message
    elif phase == "template":
        assert result.taskmaster_status == "not-run"
        assert "Method PRD template not found." in result.message
    elif phase == "binary":
        assert result.taskmaster_status == "missing"
        assert "neither task-master nor taskmaster" in result.message
    else:
        assert result.taskmaster_status == result.message == BACKEND_FAILURE


@pytest.mark.parametrize("active_present", [False, True])
@pytest.mark.parametrize("phase", ["existing", "template", "binary", "backend"])
def test_early_refusal_keeps_owned_runtime_and_avoids_premature_backend(
    project: OwnedProject,
    monkeypatch: pytest.MonkeyPatch,
    active_present: bool,
    phase: str,
) -> None:
    seed_active(project, active_present)
    if phase == "existing":
        seed_prd(project)
    calls = controlled_failure(project, monkeypatch, phase)
    assert not (project.root / ".taskmaster").exists()

    result = canonical.method_init.init_project(project.root, "demo")

    assert_failure(result, phase)
    assert (
        calls
        == {
            "existing": [],
            "template": [],
            "binary": ["find"],
            "backend": ["find", "backend"],
        }[phase]
    )
    if phase == "existing":
        assert project.prd.read_bytes() == PRD_BYTES
    else:
        assert not project.prd.exists()
    assert_active_preserved(project, active_present)


@pytest.mark.parametrize("active_present", [False, True])
@pytest.mark.parametrize("phase", ["template", "binary", "backend"])
def test_force_does_not_prewrite_existing_prd_on_controlled_failure(
    project: OwnedProject,
    monkeypatch: pytest.MonkeyPatch,
    active_present: bool,
    phase: str,
) -> None:
    seed_prd(project)
    seed_active(project, active_present)
    calls = controlled_failure(project, monkeypatch, phase)

    result = canonical.method_init.init_project(project.root, "demo", force=True)

    assert_failure(result, phase)
    assert (
        calls
        == {"template": [], "binary": ["find"], "backend": ["find", "backend"]}[phase]
    )
    assert project.prd.read_bytes() == PRD_BYTES
    assert_active_preserved(project, active_present)


def test_successful_force_still_replaces_prd_and_selects_new_active_project(
    project: OwnedProject,
) -> None:
    seed_prd(project)
    seed_active(project, True)
    (project.root / ".taskmaster").mkdir()

    result = canonical.method_init.init_project(project.root, "demo", force=True)

    assert result.ok is True and result.taskmaster_status == "already present"
    assert project.prd.read_bytes() == b"# demo\n\nOwner: demo\n"
    assert json.loads(project.active.read_bytes()) == {
        "name": "demo",
        "slug": "demo",
        "prd_path": "docs/demo/prd.md",
        "active_phase": "",
        "phase_order": [],
    }


@pytest.mark.parametrize("stage", ["backend", "template-read", "render"])
def test_prewrite_exceptions_propagate_instead_of_becoming_failed_results(
    project: OwnedProject, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    seed_prd(project)
    seed_active(project, True)
    expected = RuntimeError("controlled prewrite exception")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise expected

    if stage == "backend":
        monkeypatch.setattr(
            canonical.method_init, "_find_taskmaster", lambda: "owned-backend-stub"
        )
        monkeypatch.setattr(canonical.method_init, "_run_taskmaster_init", fail)
    else:
        (project.root / ".taskmaster").mkdir()
        if stage == "template-read":
            original = Path.read_text

            def read(path: Path, *args: object, **kwargs: object) -> str:
                if path == project.template:
                    raise expected
                return original(path, *args, **kwargs)

            monkeypatch.setattr(Path, "read_text", read)
        else:
            monkeypatch.setattr(canonical.method_init, "render_template", fail)

    with pytest.raises(RuntimeError) as caught:
        canonical.method_init.init_project(project.root, "demo", force=True)

    assert caught.value is expected
    assert project.prd.read_bytes() == PRD_BYTES
    assert_active_preserved(project, True)


@pytest.mark.parametrize("phase", ["existing", "template", "binary", "backend"])
def test_cli_failed_result_uses_stderr_and_exit_one(
    project: OwnedProject,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    phase: str,
) -> None:
    seed_active(project, True)
    if phase == "existing":
        seed_prd(project)
    calls = controlled_failure(project, monkeypatch, phase)

    status = canonical.method_init._cli_main(["demo", "--root", str(project.root)])
    captured = capsys.readouterr()

    assert status == 1
    assert captured.out == ""
    assert (
        calls
        == {
            "existing": [],
            "template": [],
            "binary": ["find"],
            "backend": ["find", "backend"],
        }[phase]
    )
    expected_error = {
        "existing": "PRD already exists:",
        "template": "Method PRD template not found.",
        "binary": ".taskmaster/ is absent and neither task-master nor taskmaster",
        "backend": BACKEND_FAILURE,
    }[phase]
    assert captured.err.startswith(f"Mainspring init failed: {expected_error}")
    assert captured.err.endswith("\n")
    assert_active_preserved(project, True)
    if phase == "existing":
        assert project.prd.read_bytes() == PRD_BYTES


def test_cli_success_remains_stdout_and_exit_zero(
    project: OwnedProject, capsys: pytest.CaptureFixture[str]
) -> None:
    (project.root / ".taskmaster").mkdir()

    status = canonical.method_init._cli_main(["demo", "--root", str(project.root)])
    captured = capsys.readouterr()

    assert status == 0 and captured.err == ""
    assert captured.out.startswith("Mainspring project initialized: demo\n")
    assert project.prd.read_bytes() == b"# demo\n\nOwner: demo\n"
