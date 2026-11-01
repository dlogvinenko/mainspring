# SPDX-License-Identifier: Apache-2.0
"""Run the release smoke gate from a clean fresh clone of HEAD."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cli_runtime import run_cli


class FreshCloneSmokeError(RuntimeError):
    """Raised when the fresh-clone smoke gate cannot produce trustworthy evidence."""


def _run_capture(command: list[str], *, cwd: Path, timeout: int) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise FreshCloneSmokeError(
            f"command failed with exit {result.returncode}: {' '.join(command)}"
            + (f"\n{detail}" if detail else "")
        )
    return result.stdout.strip()


def _run_passthrough(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str],
) -> None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise FreshCloneSmokeError(
            f"command timed out after {timeout}s: {' '.join(command)}"
        ) from exc
    # Re-emit through Python streams so the stdlib coverage harness observes the
    # same stdout/stderr shape as a real subprocess invocation.
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise FreshCloneSmokeError(
            f"command failed with exit {result.returncode}: {' '.join(command)}"
        )


def _repo_root(repo: Path, timeout: int) -> Path:
    root = _run_capture(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=repo,
        timeout=timeout,
    )
    return Path(root).resolve()


def _head_sha(repo: Path, timeout: int) -> str:
    return _run_capture(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo,
        timeout=timeout,
    )


def _dirty_status(repo: Path, timeout: int) -> list[str]:
    status = _run_capture(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        timeout=timeout,
    )
    return [line for line in status.splitlines() if line.strip()]


def _require_clean_worktree(repo: Path, timeout: int) -> None:
    dirty = _dirty_status(repo, timeout)
    if not dirty:
        return

    sample = "\n".join(f"  {line}" for line in dirty[:20])
    remaining = len(dirty) - 20
    if remaining > 0:
        sample += f"\n  ... {remaining} more"
    raise FreshCloneSmokeError(
        "fresh-clone smoke requires a clean git worktree so the cloned evidence "
        "matches release source.\n"
        f"{sample}"
    )


def _write_evidence(path: Path, evidence: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _nested_make_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("MAINSPRING_NOTIFY_ENABLED", None)
    return env


def run_fresh_clone_smoke(
    repo: Path,
    *,
    target: str,
    timeout: int,
    keep: bool = False,
    evidence_json: Path | None = None,
) -> None:
    root = _repo_root(repo.resolve(), timeout)
    _require_clean_worktree(root, timeout)
    head = _head_sha(root, timeout)
    evidence_path = None
    if evidence_json is not None:
        evidence_path = (
            evidence_json if evidence_json.is_absolute() else root / evidence_json
        )

    temp_root = Path(tempfile.mkdtemp(prefix="mainspring-fresh-clone-"))
    clone_dir = temp_root / "repo"
    try:
        print(
            f"fresh-clone-smoke: cloning {root} @ {head[:12]} into {clone_dir}",
            flush=True,
        )
        _run_capture(
            ["git", "clone", "--quiet", "--no-local", str(root), str(clone_dir)],
            cwd=root,
            timeout=timeout,
        )
        _run_capture(
            ["git", "checkout", "--quiet", head],
            cwd=clone_dir,
            timeout=timeout,
        )

        print(f"fresh-clone-smoke: running make {target}", flush=True)
        _run_passthrough(
            ["make", target],
            cwd=clone_dir,
            timeout=timeout,
            env=_nested_make_env(),
        )
        if evidence_path is not None:
            _write_evidence(
                evidence_path,
                {
                    "artifact_type": "fresh-clone-smoke-result",
                    "clone_kept": keep,
                    "command": ["make", target],
                    "evidence_schema_version": 1,
                    "result": "passed",
                    "source_head": head,
                    "source_repo": str(root),
                    "target": target,
                },
            )
            print(f"fresh-clone-smoke: wrote evidence {evidence_path}", flush=True)
        print("fresh-clone-smoke: OK", flush=True)
    finally:
        if keep:
            print(f"fresh-clone-smoke: kept clone at {clone_dir}", flush=True)
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Clone clean HEAD into a temporary directory and run a Make target "
            "there. Refuses dirty worktrees so release evidence cannot include "
            "uncommitted local edits."
        )
    )
    parser.add_argument(
        "--repo",
        default=".",
        type=Path,
        help="source git repository to clone (default: current directory)",
    )
    parser.add_argument(
        "--target",
        default="all",
        help="Make target to run inside the fresh clone (default: all)",
    )
    parser.add_argument(
        "--timeout",
        default=900,
        type=int,
        help="timeout in seconds for clone, checkout, and make steps",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the temporary clone for inspection after the run",
    )
    parser.add_argument(
        "--evidence-json",
        type=Path,
        help=(
            "write a JSON evidence artifact after a successful clean-clone run. "
            "Relative paths are resolved from the source repo root."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_fresh_clone_smoke(
            args.repo,
            target=args.target,
            timeout=args.timeout,
            keep=args.keep,
            evidence_json=args.evidence_json,
        )
    except (FreshCloneSmokeError, subprocess.TimeoutExpired) as exc:
        print(f"fresh-clone-smoke: FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    run_cli(main)
