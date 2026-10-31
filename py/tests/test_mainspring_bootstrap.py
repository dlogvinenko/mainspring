# SPDX-License-Identifier: Apache-2.0
"""Tests for the packaged Mainspring console bootstrap."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import mainspring_bootstrap  # noqa: E402
from engines import registry  # noqa: E402

MAINSPRING_DIR = HERE.parent.parent
PYPROJECT = MAINSPRING_DIR / "pyproject.toml"
MAKEFILE = MAINSPRING_DIR / "Makefile"
PRD = MAINSPRING_DIR / "docs" / "prd.md"
SOURCE_METHOD_DIR = MAINSPRING_DIR / "method"
PACKAGING_SOURCE_IGNORE = shutil.ignore_patterns(
    ".git",
    ".claude",
    ".mainspring",
    ".omx",
    ".taskmaster",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "*.egg-info",
)
PACKAGED_RUNTIME_ENV_LEAK_KEYS = (
    "MAINSPRING_CONSOLE_ENTRYPOINT",
    "MAINSPRING_PROJECT_ROOT",
    "MAINSPRING_RUNTIME_PYTHON",
    "MAINSPRING_RUNTIME_DIR",
    "MAINSPRING_STATE_DIR",
    "MAINSPRING_ENGINE_USAGE_FILE",
    "MAINSPRING_WAVE_USAGE_FILE",
)
TEXT_PAYLOAD_SUFFIXES = (
    ".cast",
    ".env",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".svg",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
)
PUBLIC_SURFACE_FORBIDDEN_MARKERS = (
    "release-" + "blockers",
    "release_" + "blockers",
    "release-" + "notes",
    "release_" + "notes",
    "use-standard-" + "proof-" + "state",
    "proof-" + "state",
    "emit-live-provider-" + "proof",
    "emit-pair-matrix-" + "proof",
    "release-" + "fresh-box",
    ".omx",
    "OMX" + "_",
    "omx-" + "loop",
    "legacy-" + "runtime",
    "Global " + "HUD",
    "Mainspring " + "runtimes",
)


def clean_packaged_runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in PACKAGED_RUNTIME_ENV_LEAK_KEYS:
        env.pop(key, None)
    return env


def copy_packaging_source(tmp_path: Path) -> Path:
    package_dir = tmp_path / "mainspring-src"
    shutil.copytree(
        MAINSPRING_DIR,
        package_dir,
        ignore=PACKAGING_SOURCE_IGNORE,
    )
    return package_dir


def assert_dist_payload_is_public(names: list[str]) -> None:
    forbidden_fragments = (
        "method/memory",
        "share/mainspring/py/" + "bench",
        "history_" + "hygiene",
        "history-" + "hygiene",
        "release-" + "blocker",
        "release_" + "blocker",
        "release-" + "notes",
        "release_" + "notes",
        "proof-" + "state",
        "proof_" + "state",
        "__pycache__",
        ".pyc",
        ".mainspring/",
        ".omx/",
        ".taskmaster/",
        ".venv/",
        "node_modules/",
    )
    required_suffixes = (
        "mainspring.sh",
        "lib/help.sh",
        "lib/team_supervision.sh",
        "py/hud.py",
        "docs/architecture.md",
        "docs/competitive-analysis.md",
        "docs/guide.md",
        "docs/method.md",
        "docs/metrics.md",
        "docs/playbook.md",
        "docs/prd.md",
        "docs/assets/hud-demo.cast",
        "docs/assets/hud-preview.svg",
        "docs/assets/readme-hero.svg",
        "method/templates/prd.md",
    )

    forbidden = [
        name
        for name in names
        if any(fragment in name for fragment in forbidden_fragments)
    ]
    missing = [
        suffix
        for suffix in required_suffixes
        if not any(name.endswith(suffix) for name in names)
    ]

    assert forbidden == []
    assert missing == []


def assert_payload_text_is_public_clean(items: list[tuple[str, str]]) -> None:
    failures = [
        f"{name}: {marker}"
        for name, text in items
        for marker in PUBLIC_SURFACE_FORBIDDEN_MARKERS
        if marker in text
    ]

    assert failures == []


def assert_no_public_surface_junk_text(text: str) -> None:
    assert [
        marker for marker in PUBLIC_SURFACE_FORBIDDEN_MARKERS if marker in text
    ] == []


def assert_sdist_payload_has_public_docs(names: list[str]) -> None:
    required_suffixes = (
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "docs/architecture.md",
        "docs/competitive-analysis.md",
        "docs/guide.md",
        "docs/method.md",
        "docs/metrics.md",
        "docs/playbook.md",
        "docs/prd.md",
        "docs/assets/readme-hero.svg",
        "docs/assets/hud-preview.svg",
        "docs/assets/hud-demo.cast",
    )
    forbidden_suffixes = (
        "py/golden_run.py",
        "py/history_" + "hygiene.py",
        "py/fresh_clone_smoke.py",
        "py/homebrew_formula.py",
        "py/bench/swe_bench.py",
        "docs/release-" + "blockers.md",
        "py/release_" + "blockers.py",
        "py/release_" + "notes.py",
    )

    missing = [
        suffix
        for suffix in required_suffixes
        if not any(name.endswith(suffix) for name in names)
    ]
    forbidden = [
        suffix
        for suffix in forbidden_suffixes
        if any(name.endswith(suffix) for name in names)
    ]

    assert missing == []
    assert forbidden == []


def test_resolve_script_prefers_explicit_runtime_script(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "mainspring.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setenv("MAINSPRING_SCRIPT", str(script))

    assert mainspring_bootstrap.resolve_script() == script.resolve()


def test_candidate_script_paths_include_home_override_after_script_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit = tmp_path / "explicit.sh"
    home = tmp_path / "home"
    monkeypatch.setenv("MAINSPRING_SCRIPT", str(explicit))
    monkeypatch.setenv("MAINSPRING_HOME", str(home))

    candidates = mainspring_bootstrap.candidate_script_paths()

    assert candidates[0] == explicit
    assert candidates[1] == home / "mainspring.sh"


def test_resolve_script_reports_all_searched_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit = tmp_path / "missing-explicit.sh"
    home = tmp_path / "missing-home"
    monkeypatch.setenv("MAINSPRING_SCRIPT", str(explicit))
    monkeypatch.setenv("MAINSPRING_HOME", str(home))
    monkeypatch.setattr(
        mainspring_bootstrap,
        "candidate_script_paths",
        lambda: [explicit, home / "mainspring.sh"],
    )

    with pytest.raises(FileNotFoundError) as excinfo:
        mainspring_bootstrap.resolve_script()

    message = str(excinfo.value)
    assert str(explicit) in message
    assert str(home / "mainspring.sh") in message


def test_main_execs_bash_runtime_with_passthrough_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "mainspring.sh"
    project = tmp_path / "project"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    project.mkdir()
    monkeypatch.setenv("MAINSPRING_SCRIPT", str(script))
    monkeypatch.delenv("MAINSPRING_PACKAGE_VERSION", raising=False)
    monkeypatch.delenv("MAINSPRING_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(project)
    monkeypatch.setattr(mainspring_bootstrap.shutil, "which", lambda name: "/bin/bash")
    monkeypatch.setattr(mainspring_bootstrap.metadata, "version", lambda name: "9.8.7")

    captured: dict[str, list[str] | str | None] = {}

    def fake_execv(binary: str, argv: list[str]) -> None:
        captured["binary"] = binary
        captured["argv"] = argv
        captured["project_root"] = os.environ.get("MAINSPRING_PROJECT_ROOT")
        captured["runtime_python"] = os.environ.get("MAINSPRING_RUNTIME_PYTHON")
        captured["package_version"] = os.environ.get("MAINSPRING_PACKAGE_VERSION")
        raise RuntimeError("stop before exec")

    monkeypatch.setattr(os, "execv", fake_execv)

    with pytest.raises(RuntimeError, match="stop before exec"):
        mainspring_bootstrap.main(["--doctor", "--status"])

    assert captured["binary"] == "/bin/bash"
    assert captured["argv"] == [
        "/bin/bash",
        str(script.resolve()),
        "--doctor",
        "--status",
    ]
    assert captured["project_root"] == str(project)
    assert captured["runtime_python"] == sys.executable
    assert captured["package_version"] == "9.8.7"
    monkeypatch.delenv("MAINSPRING_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("MAINSPRING_RUNTIME_PYTHON", raising=False)
    monkeypatch.delenv("MAINSPRING_PACKAGE_VERSION", raising=False)


def test_main_falls_back_to_bin_bash_when_path_lookup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "mainspring.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setenv("MAINSPRING_SCRIPT", str(script))
    monkeypatch.setattr(mainspring_bootstrap.shutil, "which", lambda name: None)

    captured: dict[str, str] = {}

    def fake_execv(binary: str, argv: list[str]) -> None:
        captured["binary"] = binary
        captured["script"] = argv[1]
        raise RuntimeError("stop before exec")

    monkeypatch.setattr(os, "execv", fake_execv)

    with pytest.raises(RuntimeError, match="stop before exec"):
        mainspring_bootstrap.main([])

    assert captured == {"binary": "/bin/bash", "script": str(script.resolve())}


def test_main_overrides_leaked_project_root_with_caller_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "mainspring.sh"
    project = tmp_path / "operator-project"
    leaked_project = tmp_path / "leaked-project"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    project.mkdir()
    leaked_project.mkdir()
    monkeypatch.setenv("MAINSPRING_SCRIPT", str(script))
    monkeypatch.setenv("MAINSPRING_PROJECT_ROOT", str(leaked_project))
    monkeypatch.chdir(project)
    monkeypatch.setattr(mainspring_bootstrap.shutil, "which", lambda name: "/bin/bash")

    captured: dict[str, str | None] = {}

    def fake_execv(binary: str, argv: list[str]) -> None:
        captured["project_root"] = os.environ.get("MAINSPRING_PROJECT_ROOT")
        raise RuntimeError("stop before exec")

    monkeypatch.setattr(os, "execv", fake_execv)

    with pytest.raises(RuntimeError, match="stop before exec"):
        mainspring_bootstrap.main(["--doctor"])

    assert captured["project_root"] == str(project)


def test_direct_source_checkout_ignores_leaked_project_root_env(
    tmp_path: Path,
) -> None:
    leaked_project = tmp_path / "leaked-project"
    leaked_project.mkdir()
    source_root = MAINSPRING_DIR
    env = os.environ.copy()
    env.pop("MAINSPRING_CONSOLE_ENTRYPOINT", None)
    env["MAINSPRING_PROJECT_ROOT"] = str(leaked_project)
    env["MAINSPRING_NOTIFY_ENABLED"] = "0"

    result = subprocess.run(
        [str(MAINSPRING_DIR / "mainspring.sh"), "--status"],
        cwd=leaked_project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Root: {source_root}" in result.stdout
    assert not (leaked_project / ".omx").exists()
    assert not (leaked_project / ".mainspring").exists()


def test_direct_source_archive_without_git_ignores_leaked_project_root_env(
    tmp_path: Path,
) -> None:
    source_archive = tmp_path / "mainspring-source-archive"
    leaked_project = tmp_path / "leaked-project"
    leaked_project.mkdir()
    shutil.copytree(MAINSPRING_DIR, source_archive, ignore=PACKAGING_SOURCE_IGNORE)

    env = os.environ.copy()
    env.pop("MAINSPRING_CONSOLE_ENTRYPOINT", None)
    env["MAINSPRING_PROJECT_ROOT"] = str(leaked_project)
    env["MAINSPRING_NOTIFY_ENABLED"] = "0"

    result = subprocess.run(
        [str(source_archive / "mainspring.sh"), "--status"],
        cwd=leaked_project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Root: {source_archive}" in result.stdout
    assert not (leaked_project / ".omx").exists()
    assert not (leaked_project / ".mainspring").exists()


def test_direct_source_checkout_accepts_explicit_project_flag(
    tmp_path: Path,
) -> None:
    project = tmp_path / "operator-project"
    leaked_project = tmp_path / "leaked-project"
    project.mkdir()
    leaked_project.mkdir()
    env = os.environ.copy()
    env.pop("MAINSPRING_CONSOLE_ENTRYPOINT", None)
    env["MAINSPRING_PROJECT_ROOT"] = str(leaked_project)
    env["MAINSPRING_NOTIFY_ENABLED"] = "0"

    result = subprocess.run(
        [str(MAINSPRING_DIR / "mainspring.sh"), "--project", str(project), "--status"],
        cwd=leaked_project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Root: {project}" in result.stdout
    assert not (leaked_project / ".omx").exists()
    assert not (leaked_project / ".mainspring").exists()


def test_console_entrypoint_marker_targets_caller_project_for_editable_pipx(
    tmp_path: Path,
) -> None:
    project = tmp_path / "operator-project"
    project.mkdir()
    env = os.environ.copy()
    env["MAINSPRING_PROJECT_ROOT"] = str(project)
    env["MAINSPRING_CONSOLE_ENTRYPOINT"] = "1"
    env["MAINSPRING_NOTIFY_ENABLED"] = "0"

    result = subprocess.run(
        [str(MAINSPRING_DIR / "mainspring.sh"), "--status"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Root: {project}" in result.stdout
    assert (project / ".mainspring").is_dir()
    assert not (tmp_path / ".mainspring").exists()


def test_packaged_hud_uses_runtime_python_not_project_venv(
    tmp_path: Path,
) -> None:
    project = tmp_path / "operator-project"
    project.mkdir()
    project_python = project / ".venv" / "bin" / "python3"
    project_python.parent.mkdir(parents=True)
    project_python.write_text(
        "#!/bin/sh\necho PROJECT_VENV_PYTHON_WAS_USED >&2\nexit 86\n",
        encoding="utf-8",
    )
    project_python.chmod(0o755)

    env = clean_packaged_runtime_env()
    env["MAINSPRING_CONSOLE_ENTRYPOINT"] = "1"
    env["MAINSPRING_PROJECT_ROOT"] = str(project)
    env["MAINSPRING_RUNTIME_PYTHON"] = sys.executable
    env["MAINSPRING_NOTIFY_ENABLED"] = "0"

    result = subprocess.run(
        [
            str(MAINSPRING_DIR / "mainspring.sh"),
            "hud",
            "--local",
            "--rich",
            "--watch",
            "--iterations",
            "1",
            "--interval",
            "0",
            "--width",
            "120",
            "--no-ansi",
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROJECT_VENV_PYTHON_WAS_USED" not in result.stderr
    assert "Mainspring |" in result.stdout
    assert "Folder" in result.stdout
    assert "Runtime" in result.stdout
    assert "Telegram" in result.stdout


def test_pyproject_declares_pipx_console_entry_and_runtime_payload() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert data["project"]["name"] == "mainspring"
    assert data["project"]["version"] == "1.0.0"
    assert data["project"]["readme"] == "README.md"
    assert data["project"]["license"] == "Apache-2.0"
    assert data["project"]["description"] == (
        "Product Requirements Document (PRD)-first AI coding agent orchestration "
        "for production-grade software delivery."
    )
    assert data["project"]["urls"] == {
        "Homepage": "https://github.com/dlogvinenko/mainspring",
        "Source": "https://github.com/dlogvinenko/mainspring",
        "Documentation": (
            "https://github.com/dlogvinenko/mainspring/blob/main/docs/guide.md"
        ),
        "Changelog": "https://github.com/dlogvinenko/mainspring/blob/main/CHANGELOG.md",
        "Issues": "https://github.com/dlogvinenko/mainspring/issues",
    }
    assert data["project"]["scripts"]["mainspring"] == "mainspring_bootstrap:main"
    public_discovery_keywords = {
        "agent-orchestration",
        "ai-coding-agent",
        "claude",
        "codex",
        "coding-agent",
        "developer-tools",
        "ai-code-review",
        "litellm",
        "local-ai-agents",
        "llm-agents",
        "ollama",
        "prd",
        "prd-first",
        "product-requirements-document",
        "taskmaster",
    }
    assert public_discovery_keywords.issubset(set(data["project"]["keywords"]))
    assert "autonomous-coding" in data["project"]["keywords"]
    assert "Environment :: Console" in data["project"]["classifiers"]
    assert (
        "Development Status :: 5 - Production/Stable" in data["project"]["classifiers"]
    )
    assert "Development Status :: 4 - Beta" not in data["project"]["classifiers"]
    assert "Programming Language :: Python :: 3.14" in data["project"]["classifiers"]
    assert all(
        not classifier.startswith("License ::")
        for classifier in data["project"]["classifiers"]
    )
    assert "rich>=13.7,<15" in data["project"]["dependencies"]
    assert "build>=1.2,<2" in data["project"]["optional-dependencies"]["dev"]
    assert all("litellm" not in dep for dep in data["project"]["dependencies"])
    assert (
        "litellm>=1.83.11,<2; python_version < '3.14'"
        in data["project"]["optional-dependencies"]["providers"]
    )
    assert (
        "aiohttp>=3.14.0; python_version < '3.14'"
        in data["project"]["optional-dependencies"]["providers"]
    )
    assert (
        "python-dotenv>=1.2.2; python_version < '3.14'"
        in data["project"]["optional-dependencies"]["providers"]
    )
    assert "cli_runtime" in data["tool"]["setuptools"]["py-modules"]
    assert "mainspring_bootstrap" in data["tool"]["setuptools"]["py-modules"]

    manifest = (MAINSPRING_DIR / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include LICENSE" in manifest
    assert "include NOTICE" in manifest

    data_files = data["tool"]["setuptools"]["data-files"]
    assert "mainspring.sh" in data_files["share/mainspring"]
    assert "lib/common.sh" in data_files["share/mainspring/lib"]
    assert "lib/work_mode_help.sh" in data_files["share/mainspring/lib"]
    assert "lib/team_supervision.sh" in data_files["share/mainspring/lib"]
    assert "py/cli_runtime.py" in data_files["share/mainspring/py"]
    assert "py/fd_lock.py" in data_files["share/mainspring/py"]
    assert "py/backlog_source.py" in data_files["share/mainspring/py"]
    assert "py/engine_registry.py" in data_files["share/mainspring/py"]
    assert "py/fnm_env.py" in data_files["share/mainspring/py"]
    assert "py/coverage_gate.py" not in data_files["share/mainspring/py"]
    assert "py/history_" + "hygiene.py" not in data_files["share/mainspring/py"]
    assert "py/golden_run.py" not in data_files["share/mainspring/py"]
    benchmark_runtime_payload = "share/mainspring/py/" + "bench"
    assert benchmark_runtime_payload not in data_files
    assert "py/engines/registry.py" in data_files["share/mainspring/py/engines"]
    assert {
        "docs/architecture.md",
        "docs/competitive-analysis.md",
        "docs/guide.md",
        "docs/method.md",
        "docs/metrics.md",
        "docs/playbook.md",
        "docs/prd.md",
    } <= set(data_files["share/mainspring/docs"])
    assert {
        "docs/assets/hud-demo.cast",
        "docs/assets/hud-preview.svg",
        "docs/assets/readme-hero.svg",
    } <= set(data_files["share/mainspring/docs/assets"])
    assert "schema/config.schema.json" in data_files["share/mainspring/schema"]
    assert "method/README.md" in data_files["share/mainspring/method"]
    assert "method/install.sh" in data_files["share/mainspring/method"]
    assert "method/skill/SKILL.md" in data_files["share/mainspring/method/skill"]
    assert "share/mainspring/method/memory" not in data_files
    assert {
        "method/templates/adr.md",
        "method/templates/audit-prompt.md",
        "method/templates/prd.md",
        "method/templates/reality-reset-prompt.md",
        "method/templates/task.md",
    } <= set(data_files["share/mainspring/method/templates"])


def test_makefile_exposes_user_editable_install_target() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")

    assert "install-user:" in text
    assert "install-user-providers:" in text
    assert "dev-install: install-user" in text
    assert "pipx ensurepath" in text
    assert "pipx uninstall mainspring >/dev/null 2>&1 || true" in text
    assert "pipx install --force -e ." in text
    assert (
        'pipx install --force --python "$(MAINSPRING_PROVIDERS_PYTHON)" -e ".[providers]"'
        in text
    )
    assert "MAINSPRING_PROVIDERS_PYTHON ?= python3.13" in text
    assert "mainspring from your project directory" in text
    assert "mainspring engines from any project" in text


def test_makefile_all_runs_dependency_audit_without_public_history_gate() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    history_target = "history-" + "hygiene"
    history_script = "history_" + "hygiene.py"

    assert "audit:" in text
    assert "$(PYTHON) -m pip_audit -r $(ROOT)/requirements.txt" in text
    assert "all: lint test audit" in text
    assert "release-check" in text
    assert "release-check: all package-smoke coverage" in text
    assert history_target not in text
    assert history_script not in text
    assert f"all: lint test audit {history_target}" not in text

    _, release_target = text.split("\nrelease-check:", maxsplit=1)
    release_target = release_target.split("\n\nlint:", maxsplit=1)[0]
    assert "$(PYTHON) $(PY_DIR)/prd_validate.py $(ROOT)/docs/prd.md" in release_target
    assert "git diff --check" in release_target
    assert "release check: OK" in release_target
    assert "release-" + "blockers" not in release_target


def test_makefile_package_smoke_builds_sdist_and_wheel() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    _, package_target = text.split("package-smoke:", maxsplit=1)
    package_target = package_target.split("\npipx-smoke:", maxsplit=1)[0]

    assert "$(PYTHON) -m build --sdist --wheel" in package_target
    assert "find \"$(PY_DIR)\" -maxdepth 1 -name '*.egg-info'" in package_target
    assert "rm -rf -- {} +" in package_target
    assert "mainspring-1.0.0.tar.gz" in package_target
    assert "mainspring-1.0.0-py3-none-any.whl" in package_target


def test_makefile_clean_removes_generated_release_artifacts_only() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    _, clean_target = text.split("\nclean:", maxsplit=1)

    for fragment in (
        'find "$(PY_DIR)" -name __pycache__',
        'rm -rf -- "$(HERE)/build" "$(HERE)/dist"',
        'rm -rf -- "$(HERE)/.pytest_cache" "$(HERE)/.ruff_cache" "$(HERE)/.mypy_cache"',
        "find \"$(PY_DIR)\" -name '*.egg-info' -type d",
        "find \"$(HERE)\" -maxdepth 1 -name '*.egg-info' -type d",
        'find "$(PY_DIR)" -maxdepth 1',
        "-name '*.egg-info'",
        "-name '.mainspring'",
        "-name '.omx'",
        "rm -rf -- {} +",
    ):
        assert fragment in clean_target

    assert "$(HERE)/.mainspring" not in clean_target
    assert "$(HERE)/.omx" not in clean_target
    assert "$(HERE)/.taskmaster" not in clean_target
    assert "$(HERE)/.claude" not in clean_target


def test_prd_source_map_points_to_makefile_without_embedding_old_snippets() -> None:
    prd_text = PRD.read_text(encoding="utf-8")
    appendix = prd_text.split("## Appendix A — Source-of-knowledge recipes", 1)[1]
    appendix = appendix.split("## Appendix B — Verification commands", 1)[0]

    assert "Public docs and payload checks" in appendix
    assert "`make release-check`" in appendix
    assert "`make all`" in appendix
    assert "`make package-smoke`" in appendix
    assert "$(PY_DIR)" not in appendix
    assert "legacy-runtime" not in appendix


def test_bash_entrypoints_stay_inside_prd_line_count_contract() -> None:
    main_lines = (
        (MAINSPRING_DIR / "mainspring.sh").read_text(encoding="utf-8").splitlines()
    )
    module_counts = {
        path.relative_to(MAINSPRING_DIR).as_posix(): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in sorted((MAINSPRING_DIR / "lib").glob("*.sh"))
    }

    assert len(main_lines) <= 500
    assert module_counts
    assert max(module_counts.values()) <= 600
    assert module_counts["lib/help.sh"] <= 600


# Scenario: public smoke targets should exercise the fresh Mainspring runtime
# layout.
# Expected: hud-rich-smoke points at .mainspring state and ledger paths.
def test_makefile_hud_smoke_uses_fresh_runtime_layout() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    _, hud_target = text.split("hud-rich-smoke:", maxsplit=1)
    hud_target = hud_target.split("\nlint:", maxsplit=1)[0]

    assert "$(ROOT)/.mainspring/logs/waves.jsonl" in hud_target
    assert "$(ROOT)/.mainspring/state" in hud_target
    assert "$(ROOT)/.omx" not in hud_target


def test_pyproject_packages_every_engine_module() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    packaged_engine_files = set(
        data["tool"]["setuptools"]["data-files"]["share/mainspring/py/engines"]
    )
    source_engine_files = {
        f"py/engines/{path.name}"
        for path in (MAINSPRING_DIR / "py" / "engines").glob("*.py")
    }

    assert source_engine_files <= packaged_engine_files


def test_pyproject_packages_every_method_template() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    packaged_template_files = set(
        data["tool"]["setuptools"]["data-files"]["share/mainspring/method/templates"]
    )
    source_template_files = {
        f"method/templates/{path.name}"
        for path in (SOURCE_METHOD_DIR / "templates").glob("*.md")
    }
    packaged_skill_template_files = set(
        data["tool"]["setuptools"]["data-files"][
            "share/mainspring/method/skill/templates"
        ]
    )
    source_skill_template_files = {
        f"method/skill/templates/{path.name}"
        for path in (SOURCE_METHOD_DIR / "skill/templates").glob("*.md")
    }

    assert source_template_files <= packaged_template_files
    assert source_skill_template_files <= packaged_skill_template_files


def test_packaged_method_templates_match_source_templates() -> None:
    source_templates = SOURCE_METHOD_DIR / "templates"
    packaged_templates = MAINSPRING_DIR / "method/templates"

    for source_template in source_templates.glob("*.md"):
        packaged_template = packaged_templates / source_template.name
        assert packaged_template.read_text(
            encoding="utf-8"
        ) == source_template.read_text(encoding="utf-8")


def test_packaged_method_package_matches_source_package() -> None:
    expected_files = [
        ("README.md", "README.md"),
        ("install.sh", "install.sh"),
        ("skill/SKILL.md", "skill/SKILL.md"),
    ]
    expected_files.extend(
        (f"skill/templates/{path.name}", f"skill/templates/{path.name}")
        for path in (SOURCE_METHOD_DIR / "skill/templates").glob("*.md")
    )

    for source_relative, packaged_relative in expected_files:
        source_file = SOURCE_METHOD_DIR / source_relative
        packaged_file = MAINSPRING_DIR / "method" / packaged_relative
        assert packaged_file.read_text(encoding="utf-8") == source_file.read_text(
            encoding="utf-8"
        )


def test_built_wheel_console_script_uses_caller_project_root(tmp_path: Path) -> None:
    package_dir = copy_packaging_source(tmp_path)
    dist_dir = tmp_path / "dist"
    venv_dir = tmp_path / "venv"
    project_dir = tmp_path / "operator-project"
    leaked_project_root = tmp_path / "leaked-project-root"
    dist_dir.mkdir()
    project_dir.mkdir()
    leaked_project_root.mkdir()

    def run(
        command: list[str],
        *,
        cwd: Path | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = clean_packaged_runtime_env()
        if env_overrides:
            env.update(env_overrides)
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            str(package_dir),
            "-w",
            str(dist_dir),
        ]
    )
    wheels = sorted(dist_dir.glob("mainspring-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        assert_dist_payload_is_public(names)
        assert_payload_text_is_public_clean(
            [
                (name, wheel.read(name).decode("utf-8", errors="replace"))
                for name in names
                if name.endswith(TEXT_PAYLOAD_SUFFIXES)
            ]
        )

    run([sys.executable, "-m", "venv", str(venv_dir)])
    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    venv_mainspring = venv_dir / (
        "Scripts/mainspring.exe" if os.name == "nt" else "bin/mainspring"
    )
    packaged_script = venv_dir / "share/mainspring/mainspring.sh"

    run([str(venv_python), "-m", "pip", "install", "--no-deps", str(wheels[0])])

    short_help = run([str(venv_mainspring), "--help"], cwd=project_dir)
    assert "Daily use:" in short_help.stdout
    assert "mainspring hud" in short_help.stdout
    assert "mainspring help --full" in short_help.stdout
    assert_no_public_surface_junk_text(short_help.stdout)

    full_help = run([str(venv_mainspring), "help", "--full"], cwd=project_dir)
    assert "Copy/paste commands:" in full_help.stdout
    assert (
        "Every command line below is a complete runnable invocation" in full_help.stdout
    )
    assert "Options used by commands:" in full_help.stdout
    old_details_header = "Command details " + "and flags:"
    assert old_details_header not in full_help.stdout
    assert (
        "- mainspring hud => live dashboard for every Mainspring run"
        in full_help.stdout
    )
    copy_paste_section = full_help.stdout.split("Copy/paste commands:", maxsplit=1)[
        1
    ].split("Options used by commands:", maxsplit=1)[0]
    assert "<" not in copy_paste_section
    assert "..." not in copy_paste_section
    assert "mainspring init checkout-redesign" in copy_paste_section
    assert (
        "mainspring replay show last .mainspring/logs/waves.jsonl" in copy_paste_section
    )
    assert (
        "mainspring replay run last .mainspring/logs/waves.jsonl --dry-run"
        in copy_paste_section
    )
    assert "mainspring notify-health --format json" in full_help.stdout
    assert_no_public_surface_junk_text(full_help.stdout)

    replay_help = run([str(venv_mainspring), "replay", "--help"], cwd=project_dir)
    assert "Examples:" in replay_help.stdout
    assert (
        "mainspring replay show last .mainspring/logs/waves.jsonl" in replay_help.stdout
    )
    assert (
        "mainspring replay run last .mainspring/logs/waves.jsonl --dry-run --save-as replay-smoke"
        in replay_help.stdout
    )
    assert_no_public_surface_junk_text(replay_help.stdout)

    hud = run(
        [str(venv_mainspring), "hud", "--once", "--width", "120"], cwd=project_dir
    )
    assert "Mainspring" in hud.stdout
    assert_no_public_surface_junk_text(hud.stdout)

    last_run_help = run([str(venv_mainspring), "last-run", "--help"], cwd=project_dir)
    assert "mainspring last-run [--format text|json]" in last_run_help.stdout
    assert "mainspring --last-run --dry-run" in last_run_help.stdout
    assert_no_public_surface_junk_text(last_run_help.stdout)

    notify_health = run(
        [str(venv_mainspring), "notify-health", "--format", "json"],
        cwd=project_dir,
        env_overrides={
            "MAINSPRING_NOTIFY_ENABLED": "0",
        },
    )
    notify_payload = json.loads(notify_health.stdout)
    assert notify_payload["status"] == "disabled"
    assert notify_payload["next_step"] == "enable-notifications"

    probe = run(
        [
            str(venv_python),
            "-c",
            (
                "import mainspring_bootstrap, sys; "
                "from pathlib import Path; "
                "script=mainspring_bootstrap.resolve_script(); "
                "print(script); "
                "print(Path(sys.prefix) / 'share' / 'mainspring' / 'mainspring.sh'); "
                "print(script.is_file())"
            ),
        ],
        cwd=project_dir,
    )
    resolved, expected, exists = probe.stdout.strip().splitlines()
    assert resolved == expected == str(packaged_script)
    assert exists == "True"

    packaged_templates = venv_dir / "share/mainspring/method/templates"
    source_templates = SOURCE_METHOD_DIR / "templates"
    for source_template in source_templates.glob("*.md"):
        installed_template = packaged_templates / source_template.name
        assert installed_template.is_file()
        assert installed_template.read_text(
            encoding="utf-8"
        ) == source_template.read_text(encoding="utf-8")
        installed_skill_template = (
            venv_dir / "share/mainspring/method/skill/templates" / source_template.name
        )
        assert installed_skill_template.is_file()
        assert installed_skill_template.read_text(
            encoding="utf-8"
        ) == source_template.read_text(encoding="utf-8")
    assert (venv_dir / "share/mainspring/method/README.md").is_file()
    assert (venv_dir / "share/mainspring/method/skill/SKILL.md").is_file()
    assert not (venv_dir / "share/mainspring/method/memory").exists()
    for relative_doc in (
        "architecture.md",
        "competitive-analysis.md",
        "guide.md",
        "method.md",
        "metrics.md",
        "playbook.md",
        "prd.md",
    ):
        assert (venv_dir / "share/mainspring/docs" / relative_doc).is_file()
    for relative_asset in ("hud-demo.cast", "hud-preview.svg", "readme-hero.svg"):
        assert (venv_dir / "share/mainspring/docs/assets" / relative_asset).is_file()

    status = run(
        [str(venv_mainspring), "--status"],
        cwd=project_dir,
        env_overrides={"MAINSPRING_PROJECT_ROOT": str(leaked_project_root)},
    )
    assert f"Root: {project_dir}" in status.stdout
    assert (project_dir / ".mainspring").is_dir()
    assert not (leaked_project_root / ".omx").exists()
    assert not (leaked_project_root / ".mainspring").exists()
    assert not (venv_dir / "share/mainspring/.omx").exists()
    assert not (venv_dir / "share/mainspring/.mainspring").exists()

    engines = run([str(venv_mainspring), "engines", "--json"], cwd=project_dir)
    payload = json.loads(engines.stdout)
    installed_engine_names = {row["name"] for row in payload["engines"]}
    source_engine_names = set(registry.load_engines())
    assert source_engine_names <= installed_engine_names

    (project_dir / ".taskmaster").mkdir()
    init = run([str(venv_mainspring), "init", "Packaged Method"], cwd=project_dir)
    assert "Mainspring project initialized: Packaged Method" in init.stdout
    scaffolded_prd = project_dir / "docs/packaged-method/prd.md"
    assert scaffolded_prd.is_file()
    assert scaffolded_prd.read_text().startswith(
        "# Packaged Method — Product Requirements Document"
    )


def test_built_sdist_omits_internal_and_runtime_artifacts(tmp_path: Path) -> None:
    package_dir = copy_packaging_source(tmp_path)
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--sdist",
            "--outdir",
            str(dist_dir),
            str(package_dir),
        ],
        env=clean_packaged_runtime_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    sdists = sorted(dist_dir.glob("mainspring-*.tar.gz"))
    assert len(sdists) == 1
    with tarfile.open(sdists[0]) as sdist:
        names = sdist.getnames()
        assert_dist_payload_is_public(names)
        assert_sdist_payload_has_public_docs(names)
        text_items: list[tuple[str, str]] = []
        for member in sdist.getmembers():
            if not member.isfile() or not member.name.endswith(TEXT_PAYLOAD_SUFFIXES):
                continue
            extracted = sdist.extractfile(member)
            if extracted is None:
                continue
            text_items.append(
                (member.name, extracted.read().decode("utf-8", errors="replace"))
            )
        assert_payload_text_is_public_clean(text_items)


def test_isolated_pipx_install_uses_caller_project_root(tmp_path: Path) -> None:
    if os.environ.get("MAINSPRING_RUN_PIPX_SMOKE") != "1":
        pytest.skip(
            "set MAINSPRING_RUN_PIPX_SMOKE=1 to run the pipx fresh-box release smoke"
        )
    pipx = shutil.which("pipx")
    if not pipx:
        pytest.skip("pipx is not installed")

    package_dir = copy_packaging_source(tmp_path)
    pipx_home = tmp_path / "pipx-home"
    pipx_bin = tmp_path / "pipx-bin"
    pipx_man = tmp_path / "pipx-man"
    project_dir = tmp_path / "operator-project"
    pipx_bin.mkdir()
    pipx_man.mkdir()
    project_dir.mkdir()

    env = clean_packaged_runtime_env()
    env["PIPX_HOME"] = str(pipx_home)
    env["PIPX_BIN_DIR"] = str(pipx_bin)
    env["PIPX_MAN_DIR"] = str(pipx_man)
    env["PIPX_DISABLE_SHARED_LIBS_AUTO_UPGRADE"] = "true"
    env["MAINSPRING_NOTIFY_ENABLED"] = "0"

    install = subprocess.run(
        [pipx, "install", str(package_dir), "--python", sys.executable],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert install.returncode == 0, install.stdout + install.stderr

    mainspring_bin = pipx_bin / ("mainspring.exe" if os.name == "nt" else "mainspring")
    assert mainspring_bin.is_file()

    leaked_project_root = tmp_path / "leaked-pipx-project-root"
    leaked_project_root.mkdir()
    status_env = env.copy()
    status_env["MAINSPRING_PROJECT_ROOT"] = str(leaked_project_root)

    status = subprocess.run(
        [str(mainspring_bin), "--status"],
        cwd=project_dir,
        env=status_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert status.returncode == 0, status.stdout + status.stderr
    assert f"Root: {project_dir}" in status.stdout
    assert (project_dir / ".mainspring").is_dir()
    assert not (leaked_project_root / ".omx").exists()
    assert not (leaked_project_root / ".mainspring").exists()
    assert not (pipx_home / "venvs/mainspring/share/mainspring/.omx").exists()
    assert not (pipx_home / "venvs/mainspring/share/mainspring/.mainspring").exists()


@pytest.mark.parametrize(
    ("python_version", "enabled"),
    [("3.11", True), ("3.12", True), ("3.13", True), ("3.14", False)],
)
def test_filelock_security_floor_matches_optional_provider_install_paths(
    python_version: str,
    enabled: bool,
) -> None:
    from packaging.requirements import Requirement

    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    runtime = [
        Requirement(line.strip())
        for line in (MAINSPRING_DIR / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    providers = [
        Requirement(value) for value in project["optional-dependencies"]["providers"]
    ]
    assert project["requires-python"] == ">=3.11"
    assert all(
        Requirement(value).name != "filelock" for value in project["dependencies"]
    )
    constraints = []
    for requirements in (runtime, providers):
        locks = [value for value in requirements if value.name == "filelock"]
        assert len(locks) == 1, "both provider installation paths need a filelock floor"
        lock = locks[0]
        for vulnerable in ("3.20.4", "3.32.7", "4.2.0"):
            assert vulnerable not in lock.specifier
        assert "4.2.1" in lock.specifier and "4.2.5" in lock.specifier
        assert "5.0.0" not in lock.specifier
        assert lock.marker is not None
        assert lock.marker.evaluate({"python_version": python_version}) is enabled
        constraints.append((str(lock.specifier), str(lock.marker)))
    assert constraints[0] == constraints[1]
