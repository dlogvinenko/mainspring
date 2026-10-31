# SPDX-License-Identifier: Apache-2.0
"""Synthetic last-run records and exact wizard consumer; no real settings."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from . import test_last_run as canonical

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "py/last_run.py"
ALLOWED = sorted(canonical.last_run.ALLOWED_KEYS)


def environment(settings=None):
    # Inherit identity unchanged; never print or record these protected values.
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
    env.update({key: "" for key in ALLOWED})
    env.update(
        MODE="taskmaster",
        ENGINE="codex",
        REVIEW_ENGINE="codex",
        TOPOLOGY="solo",
        MAX_AGENTS="4",
        AUTO_RETRY_CI="0",
        RUN_ONCE="false",
        AUTO_CHECKPOINT="false",
        PRD_PATH="docs/base.md",
    )
    env.update(settings or {})
    return env


def cli(*args, settings=None):
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *map(str, args)],
        env=environment(settings),
        capture_output=True,
        timeout=5,
        check=False,
    )


def fields(raw):
    return dict(line.split("\t", 1) for line in raw.decode().split("\n") if line)


WIZARD = r"""
set -euo pipefail
source "$1"
MAINSPRING_PY_DIR="$2"; NATIVE_PYTHON="$3"
mainspring_python() { printf '%s\n' "$NATIVE_PYTHON"; }
NATIVE_GUARD="$4"; NATIVE_GUARD_VALUE="$5"; NATIVE_INPUT="$6"; NATIVE_OPERATION="$7"
printf -v "$NATIVE_GUARD" '%s' "$NATIVE_GUARD_VALUE"
if [ "$NATIVE_OPERATION" = load ]; then
  _load_config_file "$NATIVE_INPUT"
else
  LAST_RUN_FILE="$NATIVE_INPUT"
  if [ "$NATIVE_OPERATION" = save-if ]; then
    if save_last_run_settings; then :; else exit "$?"; fi
  else
    save_last_run_settings
  fi
fi
shift 7
"$NATIVE_PYTHON" -B -c 'import json,os,sys;print(json.dumps({key:os.environ.get(key) for key in sys.argv[1:]}))' "$@"
"""


def wizard(path, *, settings=None, guard="MODE", explicit=False, operation="load"):
    return subprocess.run(
        [
            "/bin/bash",
            "-c",
            WIZARD,
            "lastrun-native",
            str(ROOT / "lib/wizard.sh"),
            str(ROOT / "py"),
            sys.executable,
            "USER_SET_" + guard,
            "true" if explicit else "false",
            str(path),
            operation,
            *ALLOWED,
        ],
        env=environment(settings),
        capture_output=True,
        timeout=5,
        check=False,
    )


@pytest.mark.parametrize(
    "separator",
    ["\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"],
)
def test_save_load_cannot_turn_path_into_mode_record(tmp_path, separator):
    value = "docs/a" + separator + "MODE=night" + separator + "tail"
    saved = cli("save", settings={"PRD_PATH": value})
    if saved.returncode:
        assert not saved.stdout
        return
    path = tmp_path / "last-run.env"
    path.write_bytes(saved.stdout)
    loaded = cli("load", path)
    if loaded.returncode:
        assert not loaded.stdout
        return
    data = fields(loaded.stdout)
    assert data.get("MODE") == "taskmaster" and data.get("PRD_PATH") == value


@pytest.mark.parametrize(
    "value",
    [
        "docs/a b.md",
        "docs/run#2.md",
        "docs/it's.md",
        r"docs/a\b.md",
        "docs/$(literal).md",
    ],
)
def test_existing_single_line_values_roundtrip(tmp_path, value):
    saved = cli("save", settings={"PRD_PATH": value})
    path = tmp_path / "last-run.env"
    path.write_bytes(saved.stdout)
    loaded = cli("load", path)
    assert saved.returncode == loaded.returncode == 0
    assert fields(loaded.stdout)["PRD_PATH"] == value


@pytest.mark.parametrize(
    "line,key,expected",
    [
        ("prd-path: docs/phase#1.md\n", "PRD_PATH", "docs/phase#1.md"),
        ("auto-retry-ci-log: logs/run#2.log\n", "AUTO_RETRY_CI_LOG", "logs/run#2.log"),
        ("prd-path: 'docs/my prd#1.md' # primary\n", "PRD_PATH", "docs/my prd#1.md"),
        ('prd-path: "docs/my prd#1.md" # primary\n', "PRD_PATH", "docs/my prd#1.md"),
        ("prd-path: docs/it's#draft.md # outside\n", "PRD_PATH", "docs/it's#draft.md"),
    ],
)
def test_flat_yaml_comment_boundaries_preserve_path(tmp_path, line, key, expected):
    path = tmp_path / "synthetic.yaml"
    path.write_text(line)
    loaded = cli("load", path)
    assert loaded.returncode == 0, loaded.stderr
    assert fields(loaded.stdout)[key] == expected
    consumed = wizard(path)
    assert consumed.returncode == 0, consumed.stderr
    assert json.loads(consumed.stdout)[key] == expected


def test_yaml_existing_comment_and_numeric_policies(tmp_path):
    path = tmp_path / "synthetic.yaml"
    path.write_text(
        "mode: night # note\nmax-agents: 3\nrun-once: false\nmodel-override: 'gpt # literal'\n"
    )
    loaded = cli("load", path)
    assert loaded.returncode == 0
    assert fields(loaded.stdout) == {
        "MODE": "night",
        "MAX_AGENTS": "3",
        "RUN_ONCE": "false",
        "MODEL_OVERRIDE": "gpt # literal",
    }
    path.write_text("max-agents: 7\n")
    assert cli("load", path).returncode == 2


@pytest.mark.parametrize("key", ALLOWED)
def test_exact_wizard_preserves_every_explicit_user_guard(tmp_path, key):
    path = tmp_path / "last-run.env"
    path.write_text(key + "='saved-value'\n")
    result = wizard(path, settings={key: "explicit-value"}, guard=key, explicit=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[key] == "explicit-value"


def test_unprotected_wizard_loads_saved_record(tmp_path):
    path = tmp_path / "last-run.env"
    path.write_text("MODE=night\n")
    result = wizard(path)
    assert result.returncode == 0 and json.loads(result.stdout)["MODE"] == "night"


@pytest.mark.parametrize("operation", ["save", "save-if"])
def test_exact_writer_does_not_replace_existing_cache_with_unsafe_record(
    tmp_path, operation
):
    path = tmp_path / "last-run.env"
    original = b"MODE=taskmaster\nPRD_PATH='docs/safe.md'\n"
    path.write_bytes(original)
    result = wizard(
        path, settings={"PRD_PATH": "docs/a\nMODE=night\ntail"}, operation=operation
    )
    if result.returncode:
        assert path.read_bytes() == original
        assert not result.stdout
    else:
        loaded = cli("load", path)
        assert loaded.returncode == 0
        assert fields(loaded.stdout).get("MODE") == "taskmaster"
        assert fields(loaded.stdout).get("PRD_PATH") == "docs/a\nMODE=night\ntail"


@pytest.mark.parametrize(
    "value", ["\tdocs/a.md", "docs/a.md\t", "docs/a\tb.md", "docs/a\t\tb.md"]
)
def test_tab_delimited_wizard_preserves_all_proven_single_line_values(tmp_path, value):
    saved = cli("save", settings={"PRD_PATH": value})
    path = tmp_path / "last-run.env"
    path.write_bytes(saved.stdout)
    assert (
        saved.returncode == 0 and fields(cli("load", path).stdout)["PRD_PATH"] == value
    )
    consumed = wizard(path)
    assert consumed.returncode == 0 and json.loads(consumed.stdout)["PRD_PATH"] == value


@pytest.mark.parametrize("codepoint", [10, 13, 133, 8232])
def test_old_complete_multiline_record_cannot_inject_interior_mode(tmp_path, codepoint):
    value = "docs/a" + chr(codepoint) + "MODE=night" + chr(codepoint) + "tail"
    values = environment({"PRD_PATH": value})
    legacy = "".join(f"{key}={shlex.quote(values[key])}\n" for key in ALLOWED)
    path = tmp_path / "old-last-run.env"
    path.write_bytes(legacy.encode("utf-8") + b"TOPOLOGY=team\n")
    loaded = cli("load", path)
    if loaded.returncode:
        assert not loaded.stdout
        return
    parsed = fields(loaded.stdout)
    assert parsed.get("MODE") == "taskmaster" and parsed.get("TOPOLOGY") == "team"
    assert "PRD_PATH" not in parsed
    consumed = wizard(path)
    assert (
        consumed.returncode == 0 and json.loads(consumed.stdout)["MODE"] == "taskmaster"
    )


@pytest.mark.parametrize(
    "value", ["docs/it's\nMODE=night\ntail", "docs/a\\b\nMODE=night\ntail"]
)
def test_old_canonical_quote_concatenation_and_backslash_record_is_contained(
    tmp_path, value
):
    path = tmp_path / "old-last-run.env"
    path.write_text(
        "MODE=taskmaster\nPRD_PATH=" + shlex.quote(value) + "\nTOPOLOGY=team\n"
    )
    loaded = cli("load", path)
    if loaded.returncode:
        assert not loaded.stdout
        return
    assert fields(loaded.stdout) == {"MODE": "taskmaster", "TOPOLOGY": "team"}


def test_legacy_unterminated_row_still_allows_later_independent_records(tmp_path):
    path = tmp_path / "last-run.env"
    path.write_text(
        "MODE='unterminated\nENGINE=claude codex\nTOPOLOGY='solo'\nUNKNOWN=ignored\n"
    )
    result = cli("load", path)
    assert result.returncode == 0 and fields(result.stdout) == {"TOPOLOGY": "solo"}


def test_flat_yaml_backslash_literal_survives_trailing_comment(tmp_path):
    path = tmp_path / "synthetic.yaml"
    path.write_text("prd-path: 'docs/a\\b#1.md' # outside\n")
    result = wizard(path)
    assert (
        result.returncode == 0
        and json.loads(result.stdout)["PRD_PATH"] == r"docs/a\b#1.md"
    )


def test_valid_writer_bytes_equal_existing_single_line_format(tmp_path):
    path = tmp_path / "last-run.env"
    value = "docs/my # path\\name.md"
    expected = cli("save", settings={"PRD_PATH": value})
    result = wizard(path, settings={"PRD_PATH": value}, operation="save")
    assert (
        expected.returncode == result.returncode == 0
        and path.read_bytes() == expected.stdout
    )


def test_env_allowed_key_and_numeric_policy_is_unchanged(tmp_path):
    path = tmp_path / "last-run.env"
    path.write_text("MODE=operator-literal\nMAX_AGENTS=999\nUNKNOWN=ignored\n")
    result = cli("load", path)
    assert result.returncode == 0 and fields(result.stdout) == {
        "MODE": "operator-literal",
        "MAX_AGENTS": "999",
    }


def test_noncanonical_double_quoted_multiline_is_outside_legacy_containment(tmp_path):
    """Known narrow compatibility limit, not a supported multiline save format."""
    path = tmp_path / "manually-edited.env"
    path.write_text(
        'MODE=taskmaster\nPRD_PATH="docs/a\nMODE=night\ntail"\nTOPOLOGY=team\n'
    )
    result = cli("load", path)
    assert result.returncode == 0
    assert fields(result.stdout) == {"MODE": "night", "TOPOLOGY": "team"}
