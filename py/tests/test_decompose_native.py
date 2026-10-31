# SPDX-License-Identifier: Apache-2.0
"""Decompose provenance and mutation-free refusal regressions with synthetic tasks."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import decompose as d
import prd_validate as validator
import pytest

from . import test_decompose as canonical

ROOT = Path(__file__).resolve().parents[2]


def environment():
    env = {
        key: os.environ[key]
        for key in ("HOME", "home", "CODEX_HOME")
        if key in os.environ
    }
    env.update(
        PATH="/usr/bin:/bin",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONIOENCODING="utf-8",
        PYTHONNOUSERSITE="1",
    )
    return env


def prd(tmp_path, *, duplicate=False, mixed=False):
    rows = ["- [ ] Update `src/docs.py`."]
    if duplicate:
        rows.append("- [ ] Update `src/docs.py`.")
    if mixed:
        rows[0] = "- [x] Update `src/docs.py`."
    path = tmp_path / "prd.md"
    path.write_text(
        canonical._valid_prd(
            "### P1 - Current phase (ACTIVE)\n\n" + "\n".join(rows) + "\n"
        )
    )
    assert validator.validate_prd(path) == []
    return path


def cli(prd_path, *args):
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "py/decompose.py"),
            str(prd_path),
            "--phase",
            "P1",
            "--format",
            "json",
            *map(str, args),
        ],
        cwd=prd_path.parent,
        env=environment(),
        capture_output=True,
        timeout=10,
        check=False,
    )


DISPATCH = r"""
set -euo pipefail
source "$1"; source "$2"
MAINSPRING_PY_DIR="$3"; NATIVE_PYTHON="$4"
LIST_PRESETS=false; PRESET=''; CONFIG_FILE=synthetic-absent-config; LAST_RUN_INFO=false; LAST_RUN=false
WIZARD=false; PAIR_MODE=''; TOPOLOGY=solo; AUTO_RETRY_CI=0; AGENT_MODE=code; AUTO_RETRY_CI_LOG=''
METRICS=false; METRICS_DAYS=''; METRICS_ROUTING=false; METRICS_FORMAT=''; METRICS_SINCE=''; MODE=taskmaster
DRY_RUN=false; REPAIR_STATE=false; NOTIFY_TEST=false; NOTIFY_HEALTH=false; NOTIFY_RESTART=false
HUD=false; ENGINES=false; REPLAY=false; VALIDATE_PRD=false; LIMITS=false; METHOD_INIT=false; METHOD_DECOMPOSE=false
load_mainspring_yaml() { :; }
apply_default_models_for_current_pair() { :; }
agent_mode_is_valid() { [ "$1" = code ]; }
mainspring_python() { printf '%s\n' "$NATIVE_PYTHON"; }
backend_forbidden() { printf '%s\n' BACKEND_FORBIDDEN >&2; return 97; }
run_ai_turn() { backend_forbidden; }
run_wave_loop() { backend_forbidden; }
acquire_lock() { backend_forbidden; }
ensure_notify_daemon() { backend_forbidden; }
task-master() { backend_forbidden; }
codex() { backend_forbidden; }
claude() { backend_forbidden; }
omx() { backend_forbidden; }
shift 4
parse_cli_args decompose "$@"
run_mainspring
"""


def dispatch(prd_path, *args):
    return subprocess.run(
        [
            "/bin/bash",
            "-c",
            DISPATCH,
            "decompose-native",
            str(ROOT / "lib/cli.sh"),
            str(ROOT / "lib/dispatch.sh"),
            str(ROOT / "py"),
            sys.executable,
            str(prd_path),
            "--phase",
            "P1",
            "--format",
            "json",
            *map(str, args),
        ],
        cwd=prd_path.parent,
        env=environment(),
        capture_output=True,
        timeout=10,
        check=False,
    )


def task_file(tmp_path, data):
    path = tmp_path / "synthetic-tasks.json"
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def apply(prd_path, path, backup, *, through_dispatch=False, include_done=False):
    args = ["--apply", "--tasks-file", path, "--backup-dir", backup]
    if include_done:
        args.append("--include-done")
    result = (dispatch if through_dispatch else cli)(prd_path, *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_actual_published_validator_and_public_dispatch_accept_idless_checkboxes(
    tmp_path,
):
    path = prd(tmp_path, duplicate=True)
    valid = subprocess.run(
        [sys.executable, "-B", str(ROOT / "py/prd_validate.py"), str(path)],
        cwd=tmp_path,
        env=environment(),
        capture_output=True,
        timeout=5,
        check=False,
    )
    result = dispatch(path)
    assert valid.returncode == result.returncode == 0, (valid.stderr, result.stderr)
    plans = json.loads(result.stdout)["tasks"]
    assert len(plans) == 2 and len({p["task_id"] for p in plans}) == 2


@pytest.mark.parametrize("mixed", [False, True])
def test_distinct_supported_idless_occurrences_apply_and_repeat_without_flip(
    tmp_path, mixed
):
    path = prd(tmp_path, duplicate=True, mixed=mixed)
    tasks = task_file(tmp_path, {"master": {"tasks": []}})
    backups = tmp_path / "backups"
    first = apply(path, tasks, backups, through_dispatch=True, include_done=mixed)
    data = json.loads(tasks.read_bytes())
    assert len(data["master"]["tasks"]) == 2
    assert len(first["apply"]["created"]) == 2 and first["apply"]["updated"] == []
    for index, item in enumerate(data["master"]["tasks"]):
        item.update(
            status="review" if index == 0 else "done",
            dependencies=[90 + index],
            subtasks=[{"id": index + 1, "status": "done"}],
        )
    tasks.write_text(json.dumps(data, indent=2) + "\n")
    unchanged_bytes = tasks.read_bytes()
    second = apply(path, tasks, backups, through_dispatch=True, include_done=mixed)
    assert second["apply"]["created"] == second["apply"]["updated"] == []
    assert (
        len(second["apply"]["unchanged"]) == 2 and tasks.read_bytes() == unchanged_bytes
    )
    assert len(list(backups.glob("*.bak"))) == 2
    assert Path(second["apply"]["backup_file"]).read_bytes() == unchanged_bytes


def test_legacy_other_prd_prefix_is_not_reassigned(tmp_path):
    path = prd(tmp_path)
    plan = json.loads(cli(path).stdout)["tasks"][0]
    other = Path(str(path) + ".v2")
    other.write_bytes(path.read_bytes())
    assert validator.validate_prd(other) == []
    legacy = {
        "id": 7,
        "title": "Other PRD legacy",
        "details": "GeneratedBy: decompose\nSource: "
        + str(other)
        + "\nDigest: "
        + plan["digest"]
        + "\n",
        "status": "review",
        "dependencies": [91],
        "subtasks": [{"id": 1, "status": "done"}],
        "custom": "retain",
    }
    manual = {
        "id": 3,
        "title": "Manual item",
        "status": "blocked",
        "dependencies": [7],
        "subtasks": [],
        "details": "User-authored synthetic task",
    }
    data = {
        "master": {"tasks": [legacy, manual]},
        "other-tag": {"tasks": [{"id": 1, "status": "done"}]},
    }
    tasks = task_file(tmp_path, data)
    result = apply(path, tasks, tmp_path / "backups")
    after = json.loads(tasks.read_bytes())
    assert after["master"]["tasks"][:2] == data["master"]["tasks"]
    assert after["other-tag"] == data["other-tag"]
    assert len(result["apply"]["created"]) == 1 and result["apply"]["updated"] == []


def test_same_source_legacy_control_updates_only_managed_fields(tmp_path):
    path = prd(tmp_path)
    plan = json.loads(cli(path).stdout)["tasks"][0]
    legacy = {
        "id": 2,
        "title": "Old generated title",
        "details": "GeneratedBy: decompose\nSource: "
        + str(path)
        + "\nDigest: "
        + plan["digest"]
        + "\n",
        "status": "review",
        "dependencies": [91],
        "subtasks": [{"id": 1, "status": "done"}],
        "custom": "retain",
    }
    tasks = task_file(tmp_path, {"master": {"tasks": [legacy]}})
    result = apply(path, tasks, tmp_path / "backups")
    after = json.loads(tasks.read_bytes())["master"]["tasks"][0]
    assert result["apply"]["updated"] == [2]
    for key in ("id", "status", "dependencies", "subtasks", "custom"):
        assert after[key] == legacy[key]


@pytest.mark.parametrize(
    "data",
    [
        [],
        None,
        {"master": None},
        {"master": []},
        {"master": "bad"},
        {"master": {"tasks": [1]}},
        {"master": {"tasks": [None]}},
        {"master": {"tasks": [[]]}},
    ],
)
def test_bad_shapes_are_controlled_and_unchanged_before_backup(tmp_path, data):
    path = prd(tmp_path)
    tasks = task_file(tmp_path, data)
    original = tasks.read_bytes()
    backups = tmp_path / "backups"
    result = dispatch(path, "--apply", "--tasks-file", tasks, "--backup-dir", backups)
    assert result.returncode == 1
    assert (
        b"decompose apply failed:" in result.stderr
        and b"Traceback" not in result.stderr
    )
    assert tasks.read_bytes() == original and not list(backups.glob("*.bak"))


def test_manual_other_source_and_status_dependency_subtask_controls_survive(tmp_path):
    path = prd(tmp_path)
    manual = {
        "id": 40,
        "title": "Manual task",
        "status": "blocked",
        "dependencies": [39],
        "subtasks": [{"id": 1, "status": "pending"}],
        "custom": {"keep": True},
    }
    other = {
        "id": 41,
        "title": "Other generated task",
        "status": "review",
        "dependencies": [40],
        "subtasks": [],
        "mainspring": {
            "generatedBy": "decompose",
            "source": "other-source.md",
            "digest": "different",
            "taskId": "P8-1",
        },
    }
    expected = copy.deepcopy([manual, other])
    tasks = task_file(tmp_path, {"master": {"tasks": [manual, other]}})
    first = apply(path, tasks, tmp_path / "backups")
    assert first["apply"]["created"] == [42]
    assert json.loads(tasks.read_bytes())["master"]["tasks"][:2] == expected


def test_ambiguous_text_only_legacy_identity_refuses_before_any_apply_or_backup(
    tmp_path,
):
    path = prd(tmp_path, duplicate=True)
    plans = json.loads(cli(path).stdout)["tasks"]
    assert len(plans) == 2 and plans[0]["digest"] == plans[1]["digest"]
    legacy = {
        "id": 7,
        "title": "Unresolved legacy owner",
        "status": "review",
        "dependencies": [91],
        "subtasks": [{"id": 1, "status": "done"}],
        "details": "GeneratedBy: decompose\nSource: "
        + str(path)
        + "\nDigest: "
        + plans[0]["digest"]
        + "\n",
    }
    tasks = task_file(tmp_path, {"master": {"tasks": [legacy]}})
    original = tasks.read_bytes()
    backups = tmp_path / "backups"
    result = dispatch(path, "--apply", "--tasks-file", tasks, "--backup-dir", backups)
    assert result.returncode == 1 and b"ambiguous legacy" in result.stderr.lower()
    assert tasks.read_bytes() == original and not list(backups.glob("*.bak"))


def test_existing_distinct_structured_task_ids_preserve_exact_noop_records(tmp_path):
    path = prd(tmp_path, duplicate=True)
    phases = d.parse_phase_map(path.read_text())
    plans = d.build_plan(path, phases[0], phases)
    items = [d._task_from_plan(plan, index + 1) for index, plan in enumerate(plans)]
    for index, item in enumerate(items):
        item.update(
            status="done" if index else "review",
            dependencies=[90 + index],
            subtasks=[{"id": 1, "status": "blocked"}],
            updatedAt="synthetic-original-time",
        )
    tasks = task_file(tmp_path, {"master": {"tasks": items}})
    original = tasks.read_bytes()
    backups = tmp_path / "backups"
    result = apply(path, tasks, backups, through_dispatch=True)
    assert result["apply"]["created"] == result["apply"]["updated"] == []
    assert result["apply"]["unchanged"] == [1, 2] and tasks.read_bytes() == original
    assert len(list(backups.glob("*.bak"))) == 1


def plans_for(tmp_path, duplicate=False):
    path = prd(tmp_path, duplicate=duplicate)
    phases = d.parse_phase_map(path.read_text())
    return path, d.build_plan(path, phases[0], phases)


def test_structured_task_id_prevents_fallback_to_matching_text(tmp_path):
    _path, plans = plans_for(tmp_path, duplicate=True)
    assert plans[0].digest == plans[1].digest and plans[0].task_id != plans[1].task_id
    task = d._task_from_plan(plans[1], 9)
    task["details"] = plans[0].prompt
    assert d._generated_task_matches(task, plans[0]) is False
    assert d._generated_task_matches(task, plans[1]) is True


def test_structured_record_without_task_id_is_not_blessed_by_text(tmp_path):
    _path, plans = plans_for(tmp_path)
    task = d._task_from_plan(plans[0], 9)
    del task["mainspring"]["taskId"]
    assert d._generated_task_matches(task, plans[0]) is False


@pytest.mark.parametrize("marker", ["source", "generated_by", "digest"])
def test_legacy_markers_require_complete_exact_lines(tmp_path, marker):
    path, plans = plans_for(tmp_path)
    lines = [
        "GeneratedBy: decompose",
        "Source: " + str(path),
        "Digest: " + plans[0].digest,
    ]
    index = {"generated_by": 0, "source": 1, "digest": 2}[marker]
    lines[index] += ".v2" if marker == "source" else "-suffix"
    legacy = {"id": 9, "details": "\n".join(lines)}
    assert d._generated_task_matches(legacy, plans[0]) is False


def test_exact_legacy_crlf_markers_still_update_only_managed_fields(tmp_path):
    path, plans = plans_for(tmp_path)
    task = {
        "id": 9,
        "title": "Old synthetic title",
        "details": "GeneratedBy: decompose\r\nSource: "
        + str(path)
        + "\r\nDigest: "
        + plans[0].digest
        + "\r\n",
        "status": "review",
        "dependencies": [91],
        "subtasks": [{"id": 1, "status": "done"}],
        "custom": {"retain": True},
    }
    original = copy.deepcopy(task)
    tasks = task_file(tmp_path, {"master": {"tasks": [task]}})
    summary = d.apply_plans(tasks, plans, tmp_path / "backups")
    after = json.loads(tasks.read_bytes())["master"]["tasks"][0]
    assert summary.updated == [9] and summary.created == []
    for key in ("id", "status", "dependencies", "subtasks", "custom"):
        assert after[key] == original[key]


@pytest.mark.parametrize(
    "data",
    [
        False,
        "bad",
        {"master": True},
        {"master": {"tasks": {}}},
        {"master": {"tasks": False}},
        {"master": {"tasks": [False]}},
        {"master": {"tasks": ["bad"]}},
    ],
)
def test_additional_json_shapes_refuse_before_backup_directory_creation(tmp_path, data):
    path, _plans = plans_for(tmp_path)
    tasks = task_file(tmp_path, data)
    original = tasks.read_bytes()
    backups = tmp_path / "backups"
    result = dispatch(path, "--apply", "--tasks-file", tasks, "--backup-dir", backups)
    assert result.returncode == 1
    assert (
        b"decompose apply failed:" in result.stderr
        and b"Traceback" not in result.stderr
    )
    assert tasks.read_bytes() == original and not backups.exists()


@pytest.mark.parametrize("legacy_first", [False, True])
def test_ambiguous_legacy_refuses_even_beside_valid_structured_match(
    tmp_path, legacy_first
):
    path, plans = plans_for(tmp_path, duplicate=True)
    structured = d._task_from_plan(plans[0], 3)
    legacy = {
        "id": 9,
        "details": "GeneratedBy: decompose\nSource: "
        + str(path)
        + "\nDigest: "
        + plans[0].digest
        + "\n",
        "status": "review",
    }
    rows = [legacy, structured] if legacy_first else [structured, legacy]
    tasks = task_file(tmp_path, {"master": {"tasks": rows}})
    original = tasks.read_bytes()
    backups = tmp_path / "backups"
    result = dispatch(path, "--apply", "--tasks-file", tasks, "--backup-dir", backups)
    assert result.returncode == 1 and b"ambiguous legacy" in result.stderr
    assert tasks.read_bytes() == original and not backups.exists()
