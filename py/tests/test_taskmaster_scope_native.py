# SPDX-License-Identifier: Apache-2.0
"""Synthetic scope identity controls; no path existence or dispatch policy."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def environment():
    env = {
        key: os.environ[key]
        for key in ("HOME", "home", "CODEX_HOME")
        if key in os.environ
    }
    env.update(PATH="/usr/bin:/bin:/opt/homebrew/bin", PYTHONDONTWRITEBYTECODE="1")
    return env


def task(identifier, path):
    return {
        "id": identifier,
        "title": "Synthetic task " + str(identifier),
        "status": "pending",
        "dependencies": [],
        "subtasks": [],
        "description": path,
    }


def collect(tmp_path, items, limit=4):
    path = tmp_path / "synthetic-tasks.json"
    raw = (json.dumps({"master": {"tasks": items}}) + "\n").encode()
    path.write_bytes(raw)
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "py/taskmaster.py"),
            "collect-parallel",
            str(path),
            "--limit",
            str(limit),
        ],
        cwd=tmp_path,
        env=environment(),
        check=False,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert path.read_bytes() == raw
    return [json.loads(line) for line in result.stdout.splitlines()]


@pytest.mark.parametrize(
    "longer,suffix",
    [
        ("packages/web/src/index.ts", "src/index.ts"),
        ("frontend/tests/a.spec.ts", "tests/a.spec.ts"),
        ("mysrc/a.py", "src/a.py"),
    ],
)
def test_longer_token_does_not_advertise_inner_supported_root(tmp_path, longer, suffix):
    result = collect(tmp_path, [task(1, "Edit " + longer), task(2, "Edit " + suffix)])
    assert [item["id"] for item in result] == ["1", "2"]
    assert result[0]["scope"] == [".taskmaster/1"]
    assert result[1]["scope"] == [suffix]


@pytest.mark.parametrize(
    "path,scope",
    [
        ("apps/web/src/index.ts", "apps/web/src/index.ts"),
        ("src/nested/src/index.ts", "src/nested/src/index.ts"),
        ("./src/index.ts", "src/index.ts"),
        ("././src/index.ts", "src/index.ts"),
        ("(src/index.ts)", "src/index.ts"),
        ("`src/index.ts`", "src/index.ts"),
        ("src/.hidden", "src/.hidden"),
        ("src/name.", "src/name."),
        ("`src/name.`", "src/name."),
    ],
)
def test_existing_path_spellings_and_literal_dots_are_preserved(tmp_path, path, scope):
    result = collect(tmp_path, [task(1, "Edit " + path)])
    assert result[0]["scope"] == [scope]


def test_unquoted_final_period_is_not_assumed_punctuation(tmp_path):
    result = collect(
        tmp_path, [task(1, "Fix src/main.tsx."), task(2, "Fix src/main.tsx")]
    )
    assert len(result) == 2
    assert result[0]["scope"] == ["src/main.tsx."] and result[1]["scope"] == [
        "src/main.tsx"
    ]


def test_existing_explicit_path_followed_by_period_already_conflicts(tmp_path):
    result = collect(
        tmp_path, [task(1, "Fix `src/main.tsx`."), task(2, "Fix src/main.tsx")]
    )
    assert len(result) == 1 and result[0]["scope"] == ["src/main.tsx"]


def test_greedy_list_order_and_one_child_per_parent_remain(tmp_path):
    parent = task(10, "Parent synthetic task")
    parent["subtasks"] = [task(1, "src/child1.py"), task(2, "src/child2.py")]
    result = collect(
        tmp_path, [task(3, "src/first.py"), parent, task(2, "src/last.py")]
    )
    assert [item["id"] for item in result] == ["3", "10.1", "2"]


@pytest.mark.parametrize("limit,expected", [(0, 1), (1, 1), (4, 4), (6, 6), (99, 6)])
def test_existing_limit_clamp_is_unchanged(tmp_path, limit, expected):
    result = collect(
        tmp_path, [task(i, "src/f" + str(i) + ".py") for i in range(1, 8)], limit
    )
    assert len(result) == expected


def test_existing_team_exclusion_still_precedes_scope_selection(tmp_path):
    result = collect(
        tmp_path,
        [task(1, ".claude/tool.py src/forbidden.py"), task(2, "src/allowed.py")],
    )
    assert [item["id"] for item in result] == ["2"]
