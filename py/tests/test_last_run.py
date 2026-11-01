# SPDX-License-Identifier: Apache-2.0
"""Tests for last_run.py — safe last-run settings persistence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import last_run

SCRIPT = str(HERE.parent / "last_run.py")


# ── cmd_save ────────────────────────────────────────────────────────────


# Scenario: Env vars set for all allowed keys.
# Expected: output has one KEY='value' line per allowed key, sorted.
def test_save_outputs_all_keys(tmp_path: Path) -> None:
    env = {**os.environ, "MODE": "taskmaster", "ENGINE": "claude", "TOPOLOGY": "solo"}
    result = subprocess.run(
        [sys.executable, SCRIPT, "save"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    keys = [line.split("=", 1)[0] for line in lines]
    assert "MODE" in keys
    assert "ENGINE" in keys
    assert "TOPOLOGY" in keys
    assert len(keys) == len(last_run.ALLOWED_KEYS)
    # Verify keys are sorted
    assert keys == sorted(keys)


# Scenario: Empty env vars.
# Expected: all keys present with empty quoted values.
def test_save_empty_env(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k not in last_run.ALLOWED_KEYS}
    result = subprocess.run(
        [sys.executable, SCRIPT, "save"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    for line in result.stdout.strip().splitlines():
        key, value = line.split("=", 1)
        assert key in last_run.ALLOWED_KEYS
        assert value == "''"


# Scenario: Values with shell metacharacters.
# Expected: values are shell-quoted safely.
def test_save_quotes_metacharacters(tmp_path: Path) -> None:
    env = {**os.environ, "MODE": "task; rm -rf /", "ENGINE": "claude"}
    result = subprocess.run(
        [sys.executable, SCRIPT, "save"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    # Find MODE line and verify it's safely quoted
    for line in result.stdout.strip().splitlines():
        if line.startswith("MODE="):
            assert "rm -rf" not in line or "'" in line  # must be quoted


# ── cmd_load ────────────────────────────────────────────────────────────


# Scenario: Valid last-run file with typical values.
# Expected: output has KEY\tVALUE lines for allowed keys only.
def test_load_valid_file(tmp_path: Path) -> None:
    lr = tmp_path / "last-run.env"
    lr.write_text("MODE='taskmaster'\nENGINE='claude'\nTOPOLOGY='solo'\nBOGUS='nope'\n")
    result = subprocess.run(
        [sys.executable, SCRIPT, "load", str(lr)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    parsed = dict(line.split("\t", 1) for line in lines)
    assert parsed["MODE"] == "taskmaster"
    assert parsed["ENGINE"] == "claude"
    assert "BOGUS" not in parsed


# Scenario: File with unquoted values.
# Expected: values parsed correctly.
def test_load_unquoted_values(tmp_path: Path) -> None:
    lr = tmp_path / "last-run.env"
    lr.write_text("MODE=taskmaster\nENGINE=codex\n")
    result = subprocess.run(
        [sys.executable, SCRIPT, "load", str(lr)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    parsed = dict(line.split("\t", 1) for line in lines)
    assert parsed["MODE"] == "taskmaster"
    assert parsed["ENGINE"] == "codex"


# Scenario: File with shell metacharacter values.
# Expected: values with spaces or special chars are safely parsed.
def test_load_rejects_multiword_values(tmp_path: Path) -> None:
    lr = tmp_path / "last-run.env"
    lr.write_text("MODE=task master\nENGINE='claude'\n")
    result = subprocess.run(
        [sys.executable, SCRIPT, "load", str(lr)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    parsed = dict(line.split("\t", 1) for line in lines)
    # "task master" is two words after shlex.split, so it should be rejected
    assert "MODE" not in parsed
    assert parsed["ENGINE"] == "claude"


# Scenario: Roundtrip save -> load.
# Expected: loaded values match saved values.
def test_roundtrip(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "MODE": "night",
        "ENGINE": "codex",
        "TOPOLOGY": "team",
        "MAX_AGENTS": "4",
        "AUTO_RETRY_CI": "2",
        "AUTO_RETRY_CI_LOG": "ci/latest.log",
        "AGENT_MODE": "debug",
    }
    save_result = subprocess.run(
        [sys.executable, SCRIPT, "save"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    lr = tmp_path / "last-run.env"
    lr.write_text(save_result.stdout)

    load_result = subprocess.run(
        [sys.executable, SCRIPT, "load", str(lr)],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = load_result.stdout.strip().splitlines()
    parsed = dict(line.split("\t", 1) for line in lines)
    assert parsed["MODE"] == "night"
    assert parsed["ENGINE"] == "codex"
    assert parsed["TOPOLOGY"] == "team"
    assert parsed["MAX_AGENTS"] == "4"
    assert parsed["AUTO_RETRY_CI"] == "2"
    assert parsed["AUTO_RETRY_CI_LOG"] == "ci/latest.log"
    assert parsed["AGENT_MODE"] == "debug"


# Scenario: Valid project-local YAML with aliases and scalar types.
# Expected: output has normalized KEY\tVALUE lines and schema accepts values.
def test_load_valid_yaml_config(tmp_path: Path) -> None:
    config = tmp_path / ".mainspring.yaml"
    config.write_text(
        "\n".join(
            [
                "mode: taskmaster",
                "pair-mode: codex+codex",
                "speed_profile: fast",
                "max-agents: 2",
                "auto-retry-ci: 1",
                "auto-retry-ci-log: .omx/logs/latest-ci.log",
                "agent-mode: architect",
                "run-once: true",
                "topology: solo",
            ]
        )
    )
    result = subprocess.run(
        [sys.executable, SCRIPT, "load", str(config)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    parsed = dict(line.split("\t", 1) for line in result.stdout.strip().splitlines())
    assert parsed["MODE"] == "taskmaster"
    assert parsed["PAIR_MODE"] == "codex+codex"
    assert parsed["SPEED_PROFILE"] == "fast"
    assert parsed["MAX_AGENTS"] == "2"
    assert parsed["AUTO_RETRY_CI"] == "1"
    assert parsed["AUTO_RETRY_CI_LOG"] == ".omx/logs/latest-ci.log"
    assert parsed["AGENT_MODE"] == "architect"
    assert parsed["RUN_ONCE"] == "true"
    assert parsed["TOPOLOGY"] == "solo"


# Scenario: YAML has a schema violation.
# Expected: load fails closed before emitting settings.
def test_load_yaml_schema_violation_fails_closed(tmp_path: Path) -> None:
    config = tmp_path / ".mainspring.yaml"
    config.write_text("speed-profile: turbo\nmax-agents: 9\nagent-mode: improv\n")
    result = subprocess.run(
        [sys.executable, SCRIPT, "load", str(config)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "Configuration validation failed" in result.stderr
    assert "SPEED_PROFILE must be one of: standard, fast, max" in result.stderr
    assert "MAX_AGENTS must be <= 6" in result.stderr
    assert "AGENT_MODE must be one of: architect, code, debug, ask" in result.stderr


# Scenario: YAML contains an unknown property.
# Expected: JSON Schema additionalProperties=false rejects it.
def test_load_yaml_unknown_property_fails_closed(tmp_path: Path) -> None:
    config = tmp_path / ".mainspring.yaml"
    config.write_text("speed-profile: fast\nunknown-setting: yes\n")
    result = subprocess.run(
        [sys.executable, SCRIPT, "load", str(config)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unknown property: unknown-setting" in result.stderr


# Scenario: YAML uses unsupported syntax.
# Expected: load reports the exact parse problem instead of ignoring it.
def test_load_yaml_malformed_syntax_fails_closed(tmp_path: Path) -> None:
    config = tmp_path / ".mainspring.yaml"
    config.write_text("speed-profile = fast\n")
    result = subprocess.run(
        [sys.executable, SCRIPT, "load", str(config)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "line 1: missing ':'" in result.stderr


def test_load_yaml_handles_comments_quotes_booleans_and_numbers() -> None:
    loaded = last_run._load_yaml(
        "\n".join(
            [
                "# comment",
                "mode: taskmaster # inline comment",
                "model-override: 'gpt # keep hash'",
                "run-once: false",
                "max-agents: 3",
                "auto-retry-ci-log:",
            ]
        )
    )

    assert loaded == {
        "MODE": "taskmaster",
        "MODEL_OVERRIDE": "gpt # keep hash",
        "RUN_ONCE": "false",
        "MAX_AGENTS": "3",
        "AUTO_RETRY_CI_LOG": "",
    }


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("  mode: taskmaster\n", "nested YAML is not supported"),
        (": taskmaster\n", "missing key"),
        ('mode: ["taskmaster"]\n', "nested YAML/JSON values are not supported"),
    ],
)
def test_load_yaml_rejects_unsupported_shapes(raw: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        last_run._load_yaml(raw)


def test_validate_schema_reports_required_type_and_boolean_errors() -> None:
    schema = {
        "additionalProperties": False,
        "required": ["MODE"],
        "properties": {
            "MODE": {"type": "string"},
            "MAX_AGENTS": {"type": "integer", "minimum": 1, "maximum": 6},
            "RUN_ONCE": {"type": "boolean"},
        },
    }

    errors = last_run._validate_schema(
        {"MAX_AGENTS": "0", "RUN_ONCE": "yes", "EXTRA": "value"},
        schema,
    )

    assert "unknown property: EXTRA" in errors
    assert "missing required property: MODE" in errors
    assert "MAX_AGENTS must be >= 1" in errors
    assert "RUN_ONCE must be true/false" in errors


def test_load_schema_missing_file_returns_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(last_run, "SCHEMA_PATH", tmp_path / "missing.schema.json")

    assert last_run._load_schema() is None


def test_load_env_raw_ignores_invalid_quotes_and_multi_values(tmp_path: Path) -> None:
    path = tmp_path / "last-run.env"
    path.write_text(
        "MODE='unterminated\nENGINE=claude codex\nTOPOLOGY=solo\nUNKNOWN=ignored\n",
        encoding="utf-8",
    )

    assert last_run._load_env_raw(path) == {"TOPOLOGY": "solo"}


def test_show_outputs_project_summary_and_repeat_commands(tmp_path: Path) -> None:
    path = tmp_path / "last-run.env"
    path.write_text(
        "\n".join(
            [
                "MODE=taskmaster",
                "PAIR_MODE=codex+codex",
                "ENGINE=codex",
                "MODEL_OVERRIDE=gpt-5.5",
                "REVIEW_ENGINE=codex",
                "REVIEW_MODEL_OVERRIDE=gpt-5.5",
                "TOPOLOGY=team",
                "SPEED_PROFILE=max",
                "MAX_AGENTS=6",
                "AGENT_MODE=code",
                "RUN_ONCE=false",
                "AUTO_RETRY_CI=1",
                "AUTO_CHECKPOINT=true",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "show",
            str(path),
            "--project",
            "/tmp/demo project",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Mainspring Last Run" in result.stdout
    assert "Project:       /tmp/demo project" in result.stdout
    assert "Settings file:" in result.stdout
    assert "Mode:          taskmaster" in result.stdout
    assert "Topology:      team" in result.stdout
    assert "Pair:          codex+codex" in result.stdout
    assert "Writer:        codex (gpt-5.5)" in result.stdout
    assert "Run:           continuous loop" in result.stdout
    assert "mainspring --last-run" in result.stdout
    assert "mainspring --project '/tmp/demo project' --last-run" in result.stdout


def test_show_help_exits_zero_without_settings_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing-last-run.env"

    result = subprocess.run(
        [sys.executable, SCRIPT, "show", str(missing_path), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Mainspring Last Run" in result.stdout
    assert "mainspring last-run" in result.stdout
    assert "mainspring --last-run --dry-run" in result.stdout
    assert "Product Requirements Document (PRD)" in result.stdout
    assert "No last-run settings found" not in result.stderr


def test_show_json_outputs_machine_readable_summary(tmp_path: Path) -> None:
    path = tmp_path / "last-run.env"
    path.write_text(
        "MODE=night\nPRD_PATH=docs/prd.md\nRUN_ONCE=true\n", encoding="utf-8"
    )

    result = subprocess.run(
        [sys.executable, SCRIPT, "show", str(path), "--project", "/tmp/demo", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["project"] == "/tmp/demo"
    assert payload["summary"]["mode"] == "night"
    assert payload["summary"]["run"] == "one-shot"
    assert payload["summary"]["prd"] == "docs/prd.md"
    assert payload["commands"]["preview_here"] == "mainspring --last-run --dry-run"


# ── CLI error handling ──────────────────────────────────────────────────


# Scenario: No subcommand.
# Expected: exit code 2.
def test_cli_no_args() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


# Scenario: load without path.
# Expected: exit code 2.
def test_cli_load_no_path() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "load"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_cli_unknown_subcommand() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "bogus"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Unknown subcommand: bogus" in result.stderr
