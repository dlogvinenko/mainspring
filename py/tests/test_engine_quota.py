# SPDX-License-Identifier: Apache-2.0
"""Tests for engine_quota.py — engine usage/quota snapshots."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import engine_quota  # noqa: E402
from engines._base import EngineInfo  # noqa: E402

SCRIPT = str(HERE.parent / "engine_quota.py")


# ── codex ───────────────────────────────────────────────────────────────


# Scenario: No ~/.codex/sessions directory.
# Expected: unknown values in output.
def test_codex_no_sessions(tmp_path: Path) -> None:
    # Use subprocess with HOME override so ~/.codex doesn't exist
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import sys
sys.path.insert(0, {str(HERE.parent)!r})
from pathlib import Path
Path.home = classmethod(lambda cls: Path({str(tmp_path)!r}))
import engine_quota
engine_quota.cmd_codex()
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Codex|" in result.stdout
    assert "short_remaining=unknown" in result.stdout


# Scenario: Valid codex session with rate_limits.
# Expected: parsed remaining percentages.
def test_codex_with_rate_limits(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions" / "test"
    sessions.mkdir(parents=True)
    payload = {
        "payload": {
            "rate_limits": {
                "primary": {
                    "used_percent": 30.0,
                    "window_minutes": 300,
                    "resets_at": "2026-04-27T00:00:00Z",
                },
                "secondary": {
                    "used_percent": 10.0,
                    "window_minutes": 10080,
                    "resets_at": "2026-05-01T00:00:00Z",
                },
                "plan_type": "pro",
            }
        }
    }
    (sessions / "session.jsonl").write_text(json.dumps(payload) + "\n")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import sys
sys.path.insert(0, {str(HERE.parent)!r})
from pathlib import Path
Path.home = classmethod(lambda cls: Path({str(tmp_path)!r}))
import engine_quota
engine_quota.cmd_codex()
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Codex|" in result.stdout
    assert "short_remaining=70.0" in result.stdout
    assert "long_remaining=90.0" in result.stdout
    assert "plan=pro" in result.stdout


def test_codex_skips_unreadable_session_lines(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions" / "test"
    sessions.mkdir(parents=True)
    (sessions / "broken.jsonl").write_text(
        '{"payload": {"rate_limits": {"primary": {"used_percent": bad}}}}\n'
        '{"payload": {"rate_limits": {"primary": {"used_percent": 25}}}}\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import sys
sys.path.insert(0, {str(HERE.parent)!r})
from pathlib import Path
Path.home = classmethod(lambda cls: Path({str(tmp_path)!r}))
import engine_quota
engine_quota.cmd_codex()
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "short_remaining=75.0" in result.stdout


# ── claude ──────────────────────────────────────────────────────────────


# Scenario: Probe file with rate_limit_event.
# Expected: parsed status, kind, reset.
def test_claude_with_rate_limit(tmp_path: Path) -> None:
    probe = tmp_path / "probe.jsonl"
    events = [
        {"type": "message_start"},
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "ok",
                "rateLimitType": "5min",
                "resetsAt": "2026-04-27T00:05:00Z",
            },
        },
    ]
    probe.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    result = subprocess.run(
        [sys.executable, SCRIPT, "claude", str(probe)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Claude Code|" in result.stdout
    assert "status=ok" in result.stdout
    assert "short_window=5min" in result.stdout
    assert "short_reset=2026-04-27T00:05:00Z" in result.stdout


# Scenario: Probe file with no rate_limit events.
# Expected: all unknown values.
def test_claude_no_rate_limit(tmp_path: Path) -> None:
    probe = tmp_path / "probe.jsonl"
    probe.write_text('{"type": "message_start"}\n')
    result = subprocess.run(
        [sys.executable, SCRIPT, "claude", str(probe)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Claude Code|" in result.stdout
    assert "status=unknown" in result.stdout


# Scenario: Empty probe file.
# Expected: all unknown values.
def test_claude_empty_probe(tmp_path: Path) -> None:
    probe = tmp_path / "probe.jsonl"
    probe.write_text("")
    result = subprocess.run(
        [sys.executable, SCRIPT, "claude", str(probe)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "status=unknown" in result.stdout


def test_claude_ignores_invalid_json_before_rate_event(tmp_path: Path) -> None:
    probe = tmp_path / "probe.jsonl"
    probe.write_text(
        "not json\n"
        + json.dumps(
            {
                "type": "rate_limit_event",
                "rate_limit_info": {"status": "limited"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert "status=limited" in engine_quota.claude_quota_line(str(probe))


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


# Scenario: claude without probe file.
# Expected: exit code 2.
def test_cli_claude_no_path() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "claude"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--engine"], "Unknown or incomplete flag: --engine"),
        (["--engine", "codex", "--format", "yaml"], "--format must be json or text"),
        (["--format", "json"], "Unknown subcommand: --format"),
        (["bogus"], "Unknown subcommand: bogus"),
    ],
)
def test_cli_usage_errors(args: list[str], message: str) -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert message in result.stderr


def test_cmd_engine_requires_engine_value(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        engine_quota.cmd_engine(["--format", "json"])

    assert excinfo.value.code == 2
    assert "--engine requires a value" in capsys.readouterr().err


# ── common --engine envelope ────────────────────────────────────────────


# Scenario: Common Codex envelope with no local sessions.
# Expected: JSON shape uses short/long quota objects with unknown values.
def test_common_engine_codex_json_no_sessions(tmp_path: Path) -> None:
    env = {**os.environ, "HOME": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, SCRIPT, "--engine", "codex", "--format", "json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["engine"] == "codex"
    assert payload["default_model"] == "gpt-5.5"
    assert payload["quota"]["short"]["remaining_pct"] is None
    assert payload["quota"]["long"]["window"] == "7d"
    assert payload["quota"]["source"] == "codex_sessions"


# Scenario: Common Claude envelope with a probe file.
# Expected: rate limit event is represented inside the common quota object.
def test_common_engine_claude_json_with_probe(tmp_path: Path) -> None:
    probe = tmp_path / "probe.jsonl"
    probe.write_text(
        json.dumps(
            {
                "type": "rate_limit_event",
                "rate_limit_info": {
                    "status": "ok",
                    "rateLimitType": "5min",
                    "resetsAt": "2026-04-27T00:05:00Z",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--engine",
            "claude",
            "--probe-file",
            str(probe),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["engine"] == "claude"
    assert payload["display_name"] == "Claude Code"
    assert payload["quota"]["short"]["window"] == "5min"
    assert payload["quota"]["short"]["reset"] == "2026-04-27T00:05:00Z"
    assert payload["quota"]["status"] == "ok"
    assert payload["quota"]["source"] == "claude_probe"


# Scenario: Gemini execution routes through LiteLLM but quota APIs are not wired.
# Expected: preflight returns a stable missing-quota envelope without provider calls.
def test_common_engine_gemini_json_litellm_dispatch() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "--engine", "gemini", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["engine"] == "gemini"
    assert payload["binary"] == "python3"
    assert payload["default_model"] == "gemini/gemini-2.5-pro"
    assert payload["execution_status"] == "shell-dispatch"
    assert payload["quota"]["source"] == "missing"


def test_common_engine_grok_json_litellm_dispatch() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "--engine", "grok", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["engine"] == "grok"
    assert payload["binary"] == "python3"
    assert payload["default_model"] == "xai/grok-4.20-reasoning"
    assert payload["execution_status"] == "shell-dispatch"
    assert payload["quota"]["source"] == "missing"


def test_common_engine_codex_text_output(tmp_path: Path) -> None:
    env = {**os.environ, "HOME": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, SCRIPT, "--engine", "codex", "--format", "text"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "Codex|engine=codex" in result.stdout
    assert "source=codex_sessions" in result.stdout


def test_common_litellm_provider_engines_json_dispatch_without_quota_calls() -> None:
    expected_defaults = {
        "anthropic": "anthropic/claude-opus-4.7",
        "azure": "azure/gpt-5.5",
        "mistral": "mistral/mistral-large-latest",
        "ollama": "ollama/llama3.1",
        "openai": "openai/gpt-5.5",
        "openrouter": "openrouter/openai/gpt-5.5",
    }

    for engine_name, default_model in expected_defaults.items():
        result = subprocess.run(
            [sys.executable, SCRIPT, "--engine", engine_name, "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["engine"] == engine_name
        assert payload["binary"] == "python3"
        assert payload["default_model"] == default_model
        assert payload["execution_status"] == "shell-dispatch"
        assert payload["quota"]["source"] == "missing"


# Scenario: LiteLLM is registered as a generic provider bridge.
# Expected: quota preflight stays stable and does not call provider APIs.
def test_common_engine_litellm_json_provider_bridge() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "--engine", "litellm", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["engine"] == "litellm"
    assert payload["default_model"] == "gpt-5.5"
    assert payload["execution_status"] == "shell-dispatch"
    assert payload["quota"]["source"] == "missing"


# Scenario: An adapter provides a native quota snapshot.
# Expected: the common engine path uses it before legacy fallbacks.
def test_engine_snapshot_uses_adapter_native_quota(monkeypatch) -> None:
    info = EngineInfo(
        name="native",
        display_name="Native Test Engine",
        binary="native-cli",
        default_model="native-model",
    )

    class NativeAdapter:
        def quota_snapshot(self) -> dict:
            return {
                "quota": {
                    "short": {
                        "remaining_pct": "88.5",
                        "window": "4h",
                        "reset": "2026-04-29T12:00:00Z",
                    },
                    "long": {
                        "remaining_pct": 71,
                        "window": "7d",
                        "reset": "2026-05-06T12:00:00Z",
                    },
                    "plan": "pro",
                    "status": "ok",
                    "source": "adapter-native",
                }
            }

    monkeypatch.setattr(engine_quota, "get_engine", lambda name: info)
    monkeypatch.setattr(engine_quota, "get_adapter", lambda name: NativeAdapter())

    snapshot = engine_quota.engine_snapshot("native")

    assert snapshot["engine"] == "native"
    assert snapshot["display_name"] == "Native Test Engine"
    assert snapshot["quota"]["short"]["remaining_pct"] == 88.5
    assert snapshot["quota"]["long"]["remaining_pct"] == 71.0
    assert snapshot["quota"]["plan"] == "pro"
    assert snapshot["quota"]["status"] == "ok"
    assert snapshot["quota"]["source"] == "adapter-native"


def test_normalize_adapter_quota_snapshot_rejects_empty_or_non_quota() -> None:
    assert engine_quota._normalize_adapter_quota_snapshot("codex", {}) is None
    assert (
        engine_quota._normalize_adapter_quota_snapshot("codex", {"other": {}}) is None
    )


def test_parse_percent_handles_unknown_invalid_and_numeric_values() -> None:
    assert engine_quota._parse_percent(None) is None
    assert engine_quota._parse_percent("unknown") is None
    assert engine_quota._parse_percent("not-number") is None
    assert engine_quota._parse_percent("12.34567") == 12.346


# Scenario: Unknown engine in common preflight.
# Expected: exits closed before callers can assume support.
def test_common_engine_unknown_fails() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "--engine", "grokx", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "unknown engine: grokx" in result.stderr
