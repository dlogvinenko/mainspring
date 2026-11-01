#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Scaffold a Method-shaped project tree for Mainspring.

Usage:
    mainspring init <name> [--force]

The command creates ``docs/<slug>/prd.md`` from the bundled Method PRD
template, creates local Mainspring runtime directories, and initializes
Taskmaster when ``.taskmaster/`` is absent.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cli_runtime import run_cli

HELP_TEXT = """Usage: mainspring init <name> [--force]

Create a starter Product Requirements Document (PRD) and local runtime state
for the current project.

Creates:
  docs/<slug>/prd.md
  .mainspring/state/
  .mainspring/logs/

Also initializes Taskmaster when .taskmaster/ is missing and task-master is on
PATH. Refuses to overwrite an existing PRD unless --force is explicit.

Examples:
  mainspring init billing-refactor
  mainspring init "Desktop app v1" --force
"""


@dataclass(frozen=True)
class InitResult:
    ok: bool
    name: str
    slug: str
    prd_path: Path
    runtime_dir: Path
    taskmaster_status: str
    message: str = ""


def slugify_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    slug = slug.strip("-")
    if not slug:
        raise ValueError("project name must contain at least one letter or number")
    return slug


def display_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name.strip())
    return cleaned or slugify_name(name)


def candidate_template_paths(root: Path) -> list[Path]:
    """Return Method PRD template candidates in source and packaged layouts."""
    candidates: list[Path] = []
    template_override = os.environ.get("MAINSPRING_METHOD_PRD_TEMPLATE")
    if template_override:
        candidates.append(Path(template_override))

    script_path = Path(__file__).resolve()
    candidates.extend(
        [
            root / "method/templates/prd.md",
            script_path.parents[1] / "method/templates/prd.md",
            Path(sys.prefix) / "share/mainspring/method/templates/prd.md",
        ]
    )
    return candidates


def template_path(root: Path) -> Path:
    for candidate in candidate_template_paths(root):
        if candidate.exists():
            return candidate
    return candidate_template_paths(root)[0]


def render_template(template: str, name: str) -> str:
    return re.sub(
        r"\{\{Project / Scope name\}\}|\{\{Project\}\}", lambda match: name, template
    )


def _find_taskmaster() -> str | None:
    return shutil.which("task-master") or shutil.which("taskmaster")


def _run_taskmaster_init(root: Path, binary: str) -> tuple[bool, str]:
    result = subprocess.run(
        [binary, "init"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True, f"initialized via {Path(binary).name}"
    detail = (result.stderr or result.stdout or "").strip()
    if detail:
        return False, f"taskmaster init failed: {detail}"
    return False, f"taskmaster init failed with exit code {result.returncode}"


def init_project(root: Path, name: str, force: bool = False) -> InitResult:
    root = root.resolve()
    project_name = display_name(name)
    slug = slugify_name(name)
    prd_path = root / "docs" / slug / "prd.md"
    runtime_dir = root / ".mainspring"
    taskmaster_dir = root / ".taskmaster"
    source_template = template_path(root)

    if prd_path.exists() and not force:
        return InitResult(
            ok=False,
            name=project_name,
            slug=slug,
            prd_path=prd_path,
            runtime_dir=runtime_dir,
            taskmaster_status="not-run",
            message=f"PRD already exists: {prd_path} (use --force to overwrite)",
        )

    if not source_template.exists():
        searched = ", ".join(str(path) for path in candidate_template_paths(root))
        return InitResult(
            ok=False,
            name=project_name,
            slug=slug,
            prd_path=prd_path,
            runtime_dir=runtime_dir,
            taskmaster_status="not-run",
            message=f"Method PRD template not found. Searched: {searched}",
        )

    taskmaster_status = "already present"
    if not taskmaster_dir.exists():
        taskmaster_bin = _find_taskmaster()
        if not taskmaster_bin:
            return InitResult(
                ok=False,
                name=project_name,
                slug=slug,
                prd_path=prd_path,
                runtime_dir=runtime_dir,
                taskmaster_status="missing",
                message=(
                    ".taskmaster/ is absent and neither task-master nor taskmaster "
                    "is available on PATH"
                ),
            )
        ok, taskmaster_status = _run_taskmaster_init(root, taskmaster_bin)
        if not ok:
            return InitResult(
                ok=False,
                name=project_name,
                slug=slug,
                prd_path=prd_path,
                runtime_dir=runtime_dir,
                taskmaster_status=taskmaster_status,
                message=taskmaster_status,
            )

    template = source_template.read_text()
    rendered = render_template(template, project_name)
    prd_path.parent.mkdir(parents=True, exist_ok=True)
    prd_path.write_text(rendered)
    (runtime_dir / "state").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "logs").mkdir(parents=True, exist_ok=True)
    active_prd_state = runtime_dir / "state" / "active-prd.json"
    active_prd_state.write_text(
        json.dumps(
            {
                "name": project_name,
                "slug": slug,
                "prd_path": str(prd_path.relative_to(root)),
                "active_phase": "",
                "phase_order": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    return InitResult(
        ok=True,
        name=project_name,
        slug=slug,
        prd_path=prd_path,
        runtime_dir=runtime_dir,
        taskmaster_status=taskmaster_status,
    )


def _format_result(result: InitResult) -> str:
    if not result.ok:
        return f"Mainspring init failed: {result.message}"
    return "\n".join(
        [
            f"Mainspring project initialized: {result.name}",
            f"- PRD: {result.prd_path}",
            f"- Runtime state: {result.runtime_dir}",
            f"- Taskmaster: {result.taskmaster_status}",
            "",
            "Next steps:",
            f"1. Fill in {result.prd_path}",
            f"2. mainspring validate-prd {result.prd_path}",
            "3. mainspring",
        ]
    )


def _cli_main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(HELP_TEXT, file=sys.stderr)
        return 2
    if args[0] in {"--help", "-h"}:
        print(HELP_TEXT)
        return 0

    name = args[0]
    root = Path.cwd()
    force = False
    index = 1
    while index < len(args):
        if args[index] == "--root" and index + 1 < len(args):
            root = Path(args[index + 1])
            index += 2
        elif args[index] == "--force":
            force = True
            index += 1
        else:
            print(f"Unknown flag: {args[index]}", file=sys.stderr)
            return 2

    try:
        result = init_project(root, name, force=force)
    except ValueError as exc:
        print(f"Mainspring init failed: {exc}", file=sys.stderr)
        return 2

    output = _format_result(result)
    print(output, file=sys.stdout if result.ok else sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    run_cli(_cli_main)
