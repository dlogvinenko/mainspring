# SPDX-License-Identifier: Apache-2.0
"""Tests for the fresh-clone release smoke gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "py" / "fresh_clone_smoke.py"
MAKEFILE = ROOT / "Makefile"
sys.path.insert(0, str(ROOT / "py"))

import fresh_clone_smoke  # noqa: E402


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(repo: Path, *args: str) -> None:
    result = _run(["git", *args], cwd=repo)
    assert result.returncode == 0, result.stdout + result.stderr


def _make_clean_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text(
        "# SPDX-License-Identifier: Apache-2.0\n"
        ".PHONY: all envcheck\n"
        "all:\n"
        "\t@echo fresh-ok\n"
        "envcheck:\n"
        '\t@test -z "$${MAINSPRING_NOTIFY_ENABLED+x}"\n'
        "\t@echo env-clean\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Mainspring Tests")
    _git(repo, "add", "Makefile")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def test_fresh_clone_smoke_runs_make_target_from_clean_head(tmp_path: Path) -> None:
    repo = _make_clean_repo(tmp_path)

    result = _run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--target",
            "all",
            "--timeout",
            "30",
        ],
        cwd=ROOT,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "fresh-clone-smoke: running make all" in result.stdout
    assert "fresh-ok" in result.stdout
    assert "fresh-clone-smoke: OK" in result.stdout


def test_fresh_clone_smoke_writes_success_evidence(tmp_path: Path) -> None:
    repo = _make_clean_repo(tmp_path)
    evidence = tmp_path / "evidence.json"
    head = subprocess.check_output(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo,
        text=True,
    ).strip()

    result = _run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--target",
            "all",
            "--timeout",
            "30",
            "--evidence-json",
            str(evidence),
        ],
        cwd=ROOT,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload == {
        "artifact_type": "fresh-clone-smoke-result",
        "clone_kept": False,
        "command": ["make", "all"],
        "evidence_schema_version": 1,
        "result": "passed",
        "source_head": head,
        "source_repo": str(repo.resolve()),
        "target": "all",
    }
    assert f"fresh-clone-smoke: wrote evidence {evidence}" in result.stdout


def test_fresh_clone_smoke_does_not_inherit_notify_enable_flags(
    tmp_path: Path,
) -> None:
    repo = _make_clean_repo(tmp_path)
    env = {
        **os.environ,
        "MAINSPRING_NOTIFY_ENABLED": "0",
    }

    result = _run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--target",
            "envcheck",
            "--timeout",
            "30",
        ],
        cwd=ROOT,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "env-clean" in result.stdout


def test_fresh_clone_smoke_fails_closed_on_dirty_worktree(tmp_path: Path) -> None:
    repo = _make_clean_repo(tmp_path)
    (repo / "untracked.txt").write_text("not in HEAD\n", encoding="utf-8")
    evidence = tmp_path / "evidence.json"

    result = _run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--target",
            "all",
            "--timeout",
            "30",
            "--evidence-json",
            str(evidence),
        ],
        cwd=ROOT,
    )

    assert result.returncode == 1
    assert "requires a clean git worktree" in result.stderr
    assert "untracked.txt" in result.stderr
    assert "fresh-ok" not in result.stdout
    assert not evidence.exists()


def test_run_capture_and_passthrough_error_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(fresh_clone_smoke.FreshCloneSmokeError, match="exit 2") as exc:
        fresh_clone_smoke._run_capture(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('bad detail'); sys.exit(2)",
            ],
            cwd=tmp_path,
            timeout=10,
        )
    assert "bad detail" in str(exc.value)

    with pytest.raises(fresh_clone_smoke.FreshCloneSmokeError, match="exit 3"):
        fresh_clone_smoke._run_passthrough(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "sys.stdout.write('out text\\n'); "
                    "sys.stderr.write('err text\\n'); "
                    "sys.exit(3)"
                ),
            ],
            cwd=tmp_path,
            timeout=10,
            env=os.environ.copy(),
        )

    captured = capsys.readouterr()
    assert "out text" in captured.out
    assert "err text" in captured.err


def test_run_passthrough_timeout_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout_run(
        *args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["make", "all"], timeout=5)

    monkeypatch.setattr(fresh_clone_smoke.subprocess, "run", timeout_run)

    with pytest.raises(fresh_clone_smoke.FreshCloneSmokeError, match="timed out"):
        fresh_clone_smoke._run_passthrough(
            ["make", "all"],
            cwd=tmp_path,
            timeout=5,
            env={},
        )


def test_require_clean_worktree_truncates_dirty_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        fresh_clone_smoke,
        "_dirty_status",
        lambda repo, timeout: [f"?? file-{index}.txt" for index in range(25)],
    )

    with pytest.raises(fresh_clone_smoke.FreshCloneSmokeError) as exc:
        fresh_clone_smoke._require_clean_worktree(tmp_path, 10)

    message = str(exc.value)
    assert "file-0.txt" in message
    assert "... 5 more" in message


def test_run_fresh_clone_smoke_keep_and_relative_evidence_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    temp_root = tmp_path / "fresh"

    monkeypatch.setattr(fresh_clone_smoke, "_repo_root", lambda repo, timeout: repo)
    monkeypatch.setattr(
        fresh_clone_smoke, "_require_clean_worktree", lambda repo, timeout: None
    )
    monkeypatch.setattr(
        fresh_clone_smoke, "_head_sha", lambda repo, timeout: "abcdef123456"
    )
    monkeypatch.setattr(
        fresh_clone_smoke.tempfile, "mkdtemp", lambda prefix: str(temp_root)
    )
    monkeypatch.setattr(fresh_clone_smoke, "_run_capture", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        fresh_clone_smoke, "_run_passthrough", lambda *args, **kwargs: None
    )

    fresh_clone_smoke.run_fresh_clone_smoke(
        repo,
        target="all",
        timeout=10,
        keep=True,
        evidence_json=Path(".mainspring/state/evidence.json"),
    )

    evidence = json.loads((repo / ".mainspring/state/evidence.json").read_text())
    assert evidence["clone_kept"] is True
    assert evidence["source_head"] == "abcdef123456"
    assert "kept clone at" in capsys.readouterr().out


def test_makefile_exposes_fresh_clone_smoke_release_gate() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")

    assert "fresh-clone-smoke" in text
    assert "py/fresh_clone_smoke.py" in text
    assert "--target all" in text
    assert "--evidence-json .mainspring/state/fresh-clone-smoke-evidence.json" in text
    assert "--proof-" + "json" not in text


def test_makefile_uses_extracted_repo_root() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")

    assert "# Usage: make all" in text
    assert "ROOT := $(HERE)" in text
    assert "cd scripts/" + "mainspring" not in text


def test_makefile_bootstraps_repo_local_python_dev_environment() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")

    assert "bootstrap-dev" in text
    assert "BOOTSTRAP_PYTHON ?= python3" in text
    assert '$(VENV_PYTHON) -m pip install -e ".[dev]"' in text
    assert "$(PYTHON) -m ruff check $(PY_DIR)" in text
    assert "$(PYTHON) -m pytest tests/" in text


def test_makefile_shell_lint_prunes_local_agent_worktrees(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(
        MAKEFILE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "good.sh").write_text(
        "#!/usr/bin/env bash\ntrue\n", encoding="utf-8"
    )
    agent_worktree = tmp_path / ".claude" / "worktrees" / "agent-copy"
    agent_worktree.mkdir(parents=True)
    (agent_worktree / "foreign.sh").write_text(
        "#!/usr/bin/env bash\nfalse\n", encoding="utf-8"
    )

    result = _run(["make", "-n", "shell-lint"], cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "lib/good.sh" in result.stdout
    assert ".claude" not in result.stdout
