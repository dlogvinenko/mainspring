# SPDX-License-Identifier: Apache-2.0
"""Build or apply Taskmaster tasks from a Method-shaped PRD phase.

``mainspring decompose`` validates the PRD, selects one phase, and prints
deterministic ``task-master add-task --prompt`` plans by default. With
``--apply``, it writes generated tasks into a Taskmaster tasks file using
backups and digest matching so repeat runs do not duplicate tasks.

Usage:
    mainspring decompose <prd-path> [--phase <id-or-title>] [--format text|json]
        [--include-done] [--active-prd <path>] [--apply]
        [--tasks-file <path>] [--backup-dir <path>]
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import prd_validate
from cli_runtime import run_cli
from taskmaster import MANUAL_BLOCKER_RE

PHASE_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
CHECKBOX_RE = re.compile(
    r"^(?P<indent>[ \t]*)-\s+\[(?P<mark>[ xX])\]\s+(?P<text>.+?)\s*$",
    re.MULTILINE,
)
PHASE_ID_RE = re.compile(r"\bP(?:-Comp|-Audit|[0-9]+(?:\.[0-9]+)?)\b")
TASK_ID_RE = re.compile(r"\bP(?:-Comp|-Audit|[0-9]+(?:\.[0-9]+)?)-[0-9]+[a-z]?\b")
PATH_RE = re.compile(
    r"`((?:\.taskmaster|apps|docs|e2e|scripts|server|shared|src|tests|tools|plugins)/[^`\s,)]+)`"
    r"|(?<![\w./-])((?:\.taskmaster|apps|docs|e2e|scripts|server|shared|src|tests|tools|plugins)/[A-Za-z0-9_./@+-]+)"
)


@dataclass(frozen=True)
class PrdTask:
    task_id: str
    title: str
    checked: bool
    body: str
    raw: str


@dataclass(frozen=True)
class PrdPhase:
    phase_id: str
    title: str
    body: str
    tasks: list[PrdTask]
    active: bool


@dataclass(frozen=True)
class TaskPromptPlan:
    source: str
    phase: str
    target_phase: str
    task_id: str
    title: str
    status: str
    manual_blocker: bool
    digest: str
    prompt: str


@dataclass(frozen=True)
class ApplySummary:
    tasks_file: str
    backup_file: str
    created: list[int]
    updated: list[int]
    unchanged: list[int]


def _section_text(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    next_match = re.search(r"^##\s+", text[match.end() :], re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(text)
    return text[match.end() : end]


def _clean_markdown(value: str) -> str:
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = value.replace("**", "").replace("__", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip().strip(".")


def _task_title(raw: str) -> str:
    bold = re.match(r"\*\*(.+?)\*\*", raw)
    if bold:
        return _clean_markdown(bold.group(1))
    return _clean_markdown(raw)


def _task_detail(task: PrdTask) -> str:
    detail = re.sub(r"^\*\*.+?\*\*\s*", "", task.raw).strip()
    parts = [part for part in (detail, task.body) if part]
    return "\n".join(parts)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _phase_id(title: str, fallback: int) -> str:
    match = PHASE_ID_RE.search(title)
    return match.group(0) if match else f"phase-{fallback}"


def _task_id(raw: str, phase: PrdPhase, ordinal: int) -> str:
    match = TASK_ID_RE.search(raw)
    return match.group(0) if match else f"{phase.phase_id}-{ordinal}"


def _manual_blocker_required(text: str) -> bool:
    """Classify real manual work while ignoring quoted rule examples."""
    sanitized = re.sub(
        r"any task body containing .*?(?:\)|\.)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"manual-blocker separation rule .*?automatically",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )
    return bool(MANUAL_BLOCKER_RE.search(sanitized))


def _is_active_phase(title: str, body: str) -> bool:
    marker_text = f"{title}\n{body}"
    return bool(re.search(r"\bACTIVE\b", marker_text, re.IGNORECASE))


def parse_phase_map(text: str) -> list[PrdPhase]:
    """Return phases parsed from the PRD Phase map section."""
    section = _section_text(text, "Phase map")
    if not section:
        return []

    headings = list(PHASE_HEADING_RE.finditer(section))
    phases: list[PrdPhase] = []
    for index, match in enumerate(headings):
        title = match.group(1).strip()
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(section)
        body = section[start:end].strip()
        phase = PrdPhase(
            phase_id=_phase_id(title, index + 1),
            title=_clean_markdown(title),
            body=body,
            tasks=[],
            active=_is_active_phase(title, body),
        )
        task_matches = [
            item for item in CHECKBOX_RE.finditer(body) if not item.group("indent")
        ]
        tasks: list[PrdTask] = []
        for task_index, task_match in enumerate(task_matches, start=1):
            raw = task_match.group("text").strip()
            task_start = task_match.end()
            task_end = (
                task_matches[task_index].start()
                if task_index < len(task_matches)
                else len(body)
            )
            task_body = body[task_start:task_end].strip()
            tasks.append(
                PrdTask(
                    task_id=_task_id(raw, phase, task_index),
                    title=_task_title(raw),
                    checked=task_match.group("mark").lower() == "x",
                    body=task_body,
                    raw=raw,
                )
            )
        phases.append(
            PrdPhase(
                phase_id=phase.phase_id,
                title=phase.title,
                body=body,
                tasks=tasks,
                active=phase.active,
            )
        )
    return phases


def _read_active_phase(active_prd_file: Path | None) -> str:
    if not active_prd_file or not active_prd_file.exists():
        return ""
    try:
        data = json.loads(active_prd_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("active_phase") or data.get("current_phase") or "").strip()


def select_phase(
    phases: list[PrdPhase],
    requested: str = "",
    active_prd_file: Path | None = None,
) -> PrdPhase:
    """Select a phase by explicit request, active state, active marker, or first open."""
    if not phases:
        raise ValueError("PRD has no parseable Phase map phases")

    def match_phase(value: str) -> PrdPhase | None:
        if not value:
            return None
        wanted = _normalize(value)
        for phase in phases:
            if wanted in {_normalize(phase.phase_id), _normalize(phase.title)}:
                return phase
            if wanted and wanted in _normalize(f"{phase.phase_id} {phase.title}"):
                return phase
        return None

    explicit = match_phase(requested)
    if requested and not explicit:
        raise ValueError(f"Phase not found: {requested}")
    if explicit:
        return explicit

    active = match_phase(_read_active_phase(active_prd_file))
    if active:
        return active

    marked_active = next((phase for phase in phases if phase.active), None)
    if marked_active:
        return marked_active

    first_open = next(
        (phase for phase in phases if any(not task.checked for task in phase.tasks)),
        None,
    )
    if first_open:
        return first_open
    raise ValueError("No open phase found")


def _extract_paths(text: str) -> list[str]:
    paths: set[str] = set()
    for match in PATH_RE.finditer(text):
        path = (match.group(1) or match.group(2) or "").rstrip(".,;:")
        if path:
            paths.add(path)
    return sorted(paths)


def _digest(phase: PrdPhase, task: PrdTask) -> str:
    payload = f"{phase.phase_id}\n{task.raw}\n{task.body}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def _summary_text(phase: PrdPhase, task: PrdTask) -> str:
    clean_detail = _clean_markdown(_task_detail(task))
    if clean_detail:
        return clean_detail[:240]
    return f"Implement the PRD task from {phase.phase_id}: {task.title}."


def _render_scope(paths: list[str]) -> str:
    if paths:
        return "\n".join(
            f"- `{path}` - update only as required by the PRD task." for path in paths
        )
    return (
        "- `TBD` - PRD task does not name concrete files; map the codebase first "
        "and narrow scope before implementation."
    )


def _render_prompt(
    prd_path: Path,
    phase: PrdPhase,
    task: PrdTask,
    target_phase: str,
    manual_blocker: bool,
    digest: str,
) -> str:
    task_text = f"{task.raw}\n{_task_detail(task)}"
    paths = _extract_paths(task_text)
    manual_answer = "yes" if manual_blocker else "no"
    status_note = (
        "This task is a manual blocker and should be created as blocked in the final phase."
        if manual_blocker
        else "This task is autonomous unless implementation discovers a credential, billing, deployment, or live-account step."
    )
    return f"""## Title
{task.title}

## Summary
{_summary_text(phase, task)}

Source PRD: `{prd_path}`
Source phase: `{phase.phase_id}` - {phase.title}
Target Taskmaster phase: `{target_phase}`

## Scope

**Touch these files:**

{_render_scope(paths)}

**Do NOT touch:**

- Files outside the source PRD task scope without first narrowing the task.
- Secrets, credentials, billing configuration, deployment targets, or legal/licensing/authorship files.

## Acceptance criteria

- [ ] The implementation satisfies source task `{task.task_id}` from `{prd_path}`.
- [ ] Manual-blocker status is preserved as `{manual_answer}`.
- [ ] Targeted tests or explicit manual verification named below pass.
- [ ] The final close-out reports chapter delta, competitor delta, launch blocker reduction, changed files, simplifications, verification, and remaining gap.

## Test plan

**Targeted tests** (must add or update):

- Run the smallest relevant automated test for the touched files.
- For Mainspring CLI changes, run `make all` from the repository root.

**Manual verification** (if any):

- None unless the source task explicitly requires live credentials, external sign-off, submission, or a live account.

## Dependencies

- Depends on: none stated in the PRD task.
- Blocks: none stated in the PRD task.

## Manual blocker check

**Does this task require any human action?** (`{manual_answer}`)

{status_note}

## Priority

high

**Reason:** This task is part of the selected PRD phase `{phase.phase_id}`.

## Estimated effort

30 min - 2 hrs

## Notes for the LLM agent

GeneratedBy: decompose
Source: {prd_path}
Phase: {phase.phase_id}
TargetPhase: {target_phase}
Digest: {digest}
"""


def build_plan(
    prd_path: Path,
    phase: PrdPhase,
    all_phases: list[PrdPhase],
    include_done: bool = False,
) -> list[TaskPromptPlan]:
    """Build task prompt plans for one phase."""
    last_phase = all_phases[-1].phase_id if all_phases else phase.phase_id
    plans: list[TaskPromptPlan] = []
    for task in phase.tasks:
        if task.checked and not include_done:
            continue
        source_text = f"{task.raw}\n{_task_detail(task)}"
        manual_blocker = _manual_blocker_required(source_text)
        target_phase = (
            last_phase
            if manual_blocker and phase.phase_id != last_phase
            else phase.phase_id
        )
        digest = _digest(phase, task)
        prompt = _render_prompt(
            prd_path=prd_path,
            phase=phase,
            task=task,
            target_phase=target_phase,
            manual_blocker=manual_blocker,
            digest=digest,
        )
        plans.append(
            TaskPromptPlan(
                source=str(prd_path),
                phase=phase.phase_id,
                target_phase=target_phase,
                task_id=task.task_id,
                title=task.title,
                status="blocked" if manual_blocker else "pending",
                manual_blocker=manual_blocker,
                digest=digest,
                prompt=prompt,
            )
        )
    return plans


def _format_text(prd_path: Path, phase: PrdPhase, plans: list[TaskPromptPlan]) -> str:
    lines = [
        f"decompose: {prd_path}",
        f"selected phase: {phase.phase_id} - {phase.title}",
        f"tasks: {len(plans)}",
        "mode: dry-run (no Taskmaster files changed)",
    ]
    if not plans:
        lines.append("No unchecked tasks found for this phase.")
        return "\n".join(lines)

    for index, plan in enumerate(plans, start=1):
        lines.extend(
            [
                "",
                f"[{index}] {plan.status} {plan.task_id}: {plan.title}",
                f"target phase: {plan.target_phase}",
                f"digest: {plan.digest}",
                "command:",
                "task-master add-task --prompt @- <<'TASK'",
                plan.prompt.rstrip(),
                "TASK",
            ]
        )
    return "\n".join(lines)


def _prompt_section(prompt: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(prompt)
    if not match:
        return ""
    next_match = re.search(r"^##\s+", prompt[match.end() :], re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(prompt)
    return prompt[match.end() : end].strip()


def _task_text(task: dict) -> str:
    parts: list[str] = []
    for key in ("title", "description", "details", "testStrategy"):
        value = task.get(key)
        if value:
            parts.append(str(value))
    mainspring = task.get("mainspring")
    if isinstance(mainspring, dict):
        parts.append(json.dumps(mainspring, sort_keys=True))
    return "\n".join(parts)


def _generated_task_matches(task: dict, plan: TaskPromptPlan) -> bool:
    mainspring = task.get("mainspring")
    if isinstance(mainspring, dict):
        return (
            mainspring.get("generatedBy") == "decompose"
            and mainspring.get("source") == plan.source
            and mainspring.get("digest") == plan.digest
            and mainspring.get("taskId") == plan.task_id
        )
    lines = set(_task_text(task).splitlines())
    return {
        "GeneratedBy: decompose",
        f"Source: {plan.source}",
        f"Digest: {plan.digest}",
    } <= lines


def _find_generated_task(tasks: list[dict], plan: TaskPromptPlan) -> dict | None:
    return next((task for task in tasks if _generated_task_matches(task, plan)), None)


def _next_task_id(tasks: list[dict]) -> int:
    ids: list[int] = []
    for task in tasks:
        try:
            ids.append(int(str(task.get("id"))))
        except (TypeError, ValueError):
            continue
    return max(ids, default=0) + 1


def _task_from_plan(plan: TaskPromptPlan, task_id: int) -> dict:
    summary = _prompt_section(plan.prompt, "Summary")
    test_plan = _prompt_section(plan.prompt, "Test plan")
    return {
        "id": task_id,
        "title": plan.title,
        "description": summary,
        "priority": "high",
        "dependencies": [],
        "status": plan.status,
        "details": plan.prompt,
        "testStrategy": test_plan,
        "subtasks": [],
        "mainspring": {
            "generatedBy": "decompose",
            "source": plan.source,
            "phase": plan.phase,
            "targetPhase": plan.target_phase,
            "taskId": plan.task_id,
            "digest": plan.digest,
        },
    }


def _load_taskmaster(tasks_file: Path) -> dict:
    if not tasks_file.exists():
        raise FileNotFoundError(f"Taskmaster file not found: {tasks_file}")
    data = json.loads(tasks_file.read_text(encoding="utf-8"))
    # These validate JSON content, not the valid Path argument. ValueError
    # preserves the existing controlled CLI diagnostic for malformed files.
    if not isinstance(data, dict):
        raise ValueError("Taskmaster file must contain an object")  # noqa: TRY004
    master = data.setdefault("master", {})
    if not isinstance(master, dict):
        raise ValueError("Taskmaster master must be an object")  # noqa: TRY004
    tasks = master.setdefault("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError("Taskmaster file must contain master.tasks array")
    if any(not isinstance(task, dict) for task in tasks):
        raise ValueError("Taskmaster master.tasks entries must be objects")
    return data


def _write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def apply_plans(
    tasks_file: Path,
    plans: list[TaskPromptPlan],
    backup_dir: Path,
) -> ApplySummary:
    """Apply generated task plans to a Taskmaster tasks.json file."""
    data = _load_taskmaster(tasks_file)
    tasks: list[dict] = data["master"]["tasks"]

    identities: dict[tuple[str, str], set[str]] = {}
    for plan in plans:
        identities.setdefault((plan.source, plan.digest), set()).add(plan.task_id)
    for plan in plans:
        if len(identities[(plan.source, plan.digest)]) > 1 and any(
            not isinstance(task.get("mainspring"), dict)
            and _generated_task_matches(task, plan)
            for task in tasks
        ):
            raise ValueError(
                "ambiguous legacy generated task identity; explicit taskId evidence is required"
            )

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_file = backup_dir / f"tasks-{timestamp}.json.bak"
    counter = 1
    while backup_file.exists():
        backup_file = backup_dir / f"tasks-{timestamp}-{counter}.json.bak"
        counter += 1
    shutil.copy2(tasks_file, backup_file)

    created: list[int] = []
    updated: list[int] = []
    unchanged: list[int] = []
    next_id = _next_task_id(tasks)
    updated_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    for plan in plans:
        existing = _find_generated_task(tasks, plan)
        if existing is None:
            task = _task_from_plan(plan, next_id)
            task["updatedAt"] = updated_at
            tasks.append(task)
            created.append(next_id)
            next_id += 1
            continue

        desired = _task_from_plan(plan, int(existing.get("id") or 0))
        changed = False
        for key in (
            "title",
            "description",
            "priority",
            "details",
            "testStrategy",
            "mainspring",
        ):
            if existing.get(key) != desired[key]:
                existing[key] = desired[key]
                changed = True
        existing.setdefault("dependencies", desired["dependencies"])
        existing.setdefault("subtasks", desired["subtasks"])
        existing.setdefault("status", desired["status"])
        if changed:
            existing["updatedAt"] = updated_at
            updated.append(int(existing.get("id") or 0))
        else:
            unchanged.append(int(existing.get("id") or 0))

    if created or updated:
        _write_json_atomic(tasks_file, data)
    return ApplySummary(
        tasks_file=str(tasks_file),
        backup_file=str(backup_file),
        created=created,
        updated=updated,
        unchanged=unchanged,
    )


def _format_apply_text(summary: ApplySummary) -> str:
    return "\n".join(
        [
            f"decompose apply: {summary.tasks_file}",
            f"backup: {summary.backup_file}",
            f"created: {len(summary.created)} {summary.created}",
            f"updated: {len(summary.updated)} {summary.updated}",
            f"unchanged: {len(summary.unchanged)} {summary.unchanged}",
        ]
    )


def _usage(stream=sys.stderr) -> None:
    print(
        """Usage: mainspring decompose <prd-path> [--phase <id-or-title>] [--apply]

Turn one Product Requirements Document (PRD) phase into deterministic
Taskmaster task plans. By default this prints the task-master add-task prompts
without mutating files. Use the apply example below only when you want to merge
generated tasks into .taskmaster/tasks/tasks.json with a backup.

Useful flags:
  --phase <id-or-title>     select a specific PRD phase
  --format text|json        choose operator text or machine JSON
  --include-done            include checked PRD tasks
  --active-prd <path>       read the active phase state file
  --tasks-file <path>       override the Taskmaster tasks file
  --backup-dir <path>       override the backup directory

Examples:
  mainspring decompose docs/prd.md --phase P1
  mainspring decompose docs/prd.md --phase P1 --apply
""",
        file=stream,
    )


def _cli_main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] in {"--help", "-h"}:
        _usage(sys.stdout if args else sys.stderr)
        return 0 if args else 2

    prd_path = Path(args[0])
    phase_request = ""
    output_format = "text"
    include_done = False
    active_prd_file: Path | None = None
    apply = False
    tasks_file = Path(".taskmaster/tasks/tasks.json")
    backup_dir = Path(".mainspring/state/decompose")

    index = 1
    while index < len(args):
        arg = args[index]
        if arg == "--phase" and index + 1 < len(args):
            phase_request = args[index + 1]
            index += 2
        elif arg == "--format" and index + 1 < len(args):
            output_format = args[index + 1]
            index += 2
        elif arg == "--include-done":
            include_done = True
            index += 1
        elif arg == "--active-prd" and index + 1 < len(args):
            active_prd_file = Path(args[index + 1])
            index += 2
        elif arg == "--apply":
            apply = True
            index += 1
        elif arg == "--tasks-file" and index + 1 < len(args):
            tasks_file = Path(args[index + 1])
            index += 2
        elif arg == "--backup-dir" and index + 1 < len(args):
            backup_dir = Path(args[index + 1])
            index += 2
        else:
            print(f"Unknown or incomplete flag: {arg}", file=sys.stderr)
            _usage()
            return 2

    issues = prd_validate.validate_prd(prd_path)
    if issues:
        print(prd_validate._format_text(prd_path, issues), file=sys.stderr)
        return 1

    text = prd_path.read_text(errors="ignore")
    phases = parse_phase_map(text)
    try:
        phase = select_phase(phases, phase_request, active_prd_file)
    except ValueError as exc:
        print(f"decompose: {exc}", file=sys.stderr)
        return 1

    plans = build_plan(prd_path, phase, phases, include_done=include_done)
    apply_summary: ApplySummary | None = None
    if apply:
        try:
            apply_summary = apply_plans(tasks_file, plans, backup_dir)
        except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError) as exc:
            print(f"decompose apply failed: {exc}", file=sys.stderr)
            return 1

    if output_format == "json":
        print(
            json.dumps(
                {
                    "source": str(prd_path),
                    "phase": asdict(phase),
                    "tasks": [asdict(plan) for plan in plans],
                    "mode": "apply" if apply else "dry-run",
                    "apply": asdict(apply_summary) if apply_summary else None,
                },
                indent=2,
            )
        )
    elif output_format == "text":
        if apply_summary:
            print(_format_apply_text(apply_summary))
        else:
            print(_format_text(prd_path, phase, plans))
    else:
        print(f"Unknown format: {output_format}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    run_cli(_cli_main)
