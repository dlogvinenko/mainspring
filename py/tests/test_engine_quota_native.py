# SPDX-License-Identifier: Apache-2.0
"""No provider calls: actual quota CLI and usage consumer with synthetic backends."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ARM = HERE.parents[1]
PY = ARM / "py"
DRIVER = HERE / "offline_quota_driver.py"
ENV = {
    "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
    "PYTHONPATH": str(PY),
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUTF8": "1",
    "PYTHONNOUSERSITE": "1",
}
BAD_USED = [
    True,
    False,
    "bad",
    {},
    [],
    "NaN",
    "Infinity",
    "-Infinity",
    -50,
    float("nan"),
    float("inf"),
    float("-inf"),
]
BAD_REMAINING = [
    "nan",
    "inf",
    "-inf",
    "1e400",
    float("nan"),
    float("inf"),
    float("-inf"),
    -5,
    250,
    100.0001,
]
BAD_WINDOW = [None, [], [1], "bad", True, 1]
USAGE = r"""
set -euo pipefail
source "$1"
CODEX_LINE_FILE="$2"
codex() { printf '%s\n' PROVIDER_FORBIDDEN >&2; return 97; }
claude() { printf '%s\n' PROVIDER_FORBIDDEN >&2; return 97; }
codex_usage_snapshot() { cat "$CODEX_LINE_FILE"; }
claude_usage_snapshot() { printf '%s\n' 'Claude Code|short_remaining=unknown|short_window=unknown|short_reset=unknown|long_remaining=unknown|long_window=unknown|long_reset=unknown|status=unknown'; }
format_epoch_local() { printf '%s\n' "$1"; }
print_usage_snapshot
"""


def _run(tmp_path, case):
    casefile = tmp_path / "case.json"
    casefile.write_text(json.dumps(case))
    return subprocess.run(
        [sys.executable, "-B", str(DRIVER), str(casefile), str(PY / "engine_quota.py")],
        cwd=tmp_path,
        env=ENV,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _strict(text):
    def invalid(_value):
        raise ValueError("nonfinite output")

    return json.loads(text, parse_constant=invalid)


def _home(tmp_path, primary, secondary=None, whole=None):
    home = tmp_path / "synthetic-home"
    session = home / ".codex/sessions/session.jsonl"
    session.parent.mkdir(parents=True)
    value = (
        whole
        if whole is not None
        else {"primary": primary, "secondary": secondary or {"used_percent": 25}}
    )
    session.write_text(json.dumps({"payload": {"rate_limits": value}}) + "\n")
    return home


def _display(tmp_path, line):
    file = tmp_path / "line.txt"
    file.write_text(line)
    shell = tmp_path / "usage.sh"
    shell.write_text(USAGE)
    return subprocess.run(
        [
            "/bin/bash",
            "--noprofile",
            "--norc",
            str(shell),
            str(ARM / "lib/usage.sh"),
            str(file),
        ],
        cwd=tmp_path,
        env=ENV,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("bad", BAD_USED)
def test_malformed_used_is_unknown_in_cli_and_usage(tmp_path, bad):
    home = _home(tmp_path, {"used_percent": bad})
    legacy = _run(
        tmp_path, {"mode": "codex", "legacy": True, "synthetic_home": str(home)}
    )
    shown = _display(tmp_path, legacy.stdout)
    assert legacy.returncode == 0, legacy.stderr
    assert "short_remaining=unknown" in legacy.stdout
    assert shown.returncode == 0 and "Short window remaining: unknown%" in shown.stdout
    assert "PROVIDER_FORBIDDEN" not in shown.stderr
    common = _run(tmp_path, {"mode": "codex", "synthetic_home": str(home)})
    assert common.returncode == 0, common.stderr
    payload = _strict(common.stdout)
    assert payload["quota"]["short"]["remaining_pct"] is None
    assert payload["quota"]["long"]["remaining_pct"] == 75.0


@pytest.mark.parametrize("bad", BAD_REMAINING)
def test_malformed_remaining_is_null_in_actual_common_cli(tmp_path, bad):
    result = _run(
        tmp_path,
        {
            "adapter": {
                "quota": {
                    "short": {"remaining_pct": bad},
                    "long": {"remaining_pct": 50},
                    "status": "ok",
                    "source": "synthetic",
                }
            }
        },
    )
    assert result.returncode == 0, result.stderr
    payload = _strict(result.stdout)
    assert payload["quota"]["short"]["remaining_pct"] is None
    assert payload["quota"]["long"]["remaining_pct"] == 50.0
    assert payload["quota"]["status"] == "ok"
    shown = _run(
        tmp_path,
        {"format": "text", "adapter": {"quota": {"short": {"remaining_pct": bad}}}},
    )
    assert shown.returncode == 0 and "short_remaining=unknown" in shown.stdout


@pytest.mark.parametrize("role", ["short", "long"])
@pytest.mark.parametrize("bad", BAD_WINDOW)
def test_malformed_nested_window_is_stable_unknown_envelope(tmp_path, role, bad):
    other = "long" if role == "short" else "short"
    result = _run(
        tmp_path,
        {
            "adapter": {
                "quota": {role: bad, other: {"remaining_pct": 70}, "status": "ok"}
            }
        },
    )
    assert result.returncode == 0, result.stderr
    payload = _strict(result.stdout)
    assert payload["quota"][role] == {
        "remaining_pct": None,
        "window": "unknown",
        "reset": "unknown",
    }
    assert payload["quota"][other]["remaining_pct"] == 70.0
    assert payload["quota"]["status"] == "ok"


@pytest.mark.parametrize("slot", ["rate_limits", "primary", "secondary"])
@pytest.mark.parametrize("bad", [True, "bad", [1]])
def test_malformed_legacy_mappings_do_not_crash(tmp_path, slot, bad):
    if slot == "rate_limits":
        home = _home(tmp_path, {}, whole=bad)
    elif slot == "primary":
        home = _home(tmp_path, bad)
    else:
        home = _home(tmp_path, {"used_percent": 20}, secondary=bad)
    result = _run(tmp_path, {"mode": "codex", "synthetic_home": str(home)})
    assert result.returncode == 0, result.stderr
    payload = _strict(result.stdout)
    role = "long" if slot == "secondary" else "short"
    assert payload["quota"][role]["remaining_pct"] is None


@pytest.mark.parametrize("bad", [True, 1, "bad", [1]])
def test_malformed_claude_rate_info_does_not_crash_offline(tmp_path, bad):
    probe = tmp_path / "synthetic-probe.jsonl"
    probe.write_text(
        json.dumps({"type": "rate_limit_event", "rate_limit_info": bad}) + "\n"
    )
    result = _run(tmp_path, {"mode": "claude", "synthetic_probe": str(probe)})
    assert result.returncode == 0, result.stderr
    assert (
        "status=unknown" in result.stdout and "short_remaining=unknown" in result.stdout
    )


@pytest.mark.parametrize("available", [True, False])
def test_binary_availability_does_not_define_quota_or_follow_adapter_flag(
    tmp_path, available
):
    result = _run(
        tmp_path,
        {
            "binary_available": available,
            "adapter": {
                "available": not available,
                "quota": {"short": None, "status": "ok"},
            },
        },
    )
    assert result.returncode == 0, result.stderr
    payload = _strict(result.stdout)
    assert payload["available"] is available
    assert payload["quota"]["short"]["remaining_pct"] is None
    assert payload["quota"]["status"] == "ok"


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, 0.0),
        (100, 100.0),
        ("12.34567", 12.346),
        (None, None),
        (True, None),
        (False, None),
    ],
)
def test_remaining_valid_and_unknown_controls(tmp_path, value, expected):
    result = _run(
        tmp_path,
        {
            "adapter": {
                "quota": {
                    "short": {"remaining_pct": value, "window": None, "reset": None}
                }
            }
        },
    )
    assert result.returncode == 0, result.stderr
    window = _strict(result.stdout)["quota"]["short"]
    assert window == {
        "remaining_pct": expected,
        "window": "unknown",
        "reset": "unknown",
    }


def test_missing_denominator_does_not_invent_percentage(tmp_path):
    result = _run(
        tmp_path,
        {
            "binary_available": True,
            "adapter": {"quota": {"short": {"used": 2, "limit": None}, "status": "ok"}},
        },
    )
    assert result.returncode == 0, result.stderr
    assert _strict(result.stdout)["quota"]["short"]["remaining_pct"] is None


@pytest.mark.parametrize(
    "used,expected",
    [(0, "100.0"), (100, "0.0"), (125, "0.0"), (30.12345, str(100.0 - 30.12345))],
)
def test_valid_used_precision_and_existing_overlimit_saturation_are_preserved(
    tmp_path, used, expected
):
    home = _home(tmp_path, {"used_percent": used})
    result = _run(
        tmp_path, {"mode": "codex", "legacy": True, "synthetic_home": str(home)}
    )
    assert result.returncode == 0, result.stderr
    assert "short_remaining=" + expected + "|" in result.stdout


def test_usage_valid_control_preserves_remaining_and_does_not_probe(tmp_path):
    result = _display(
        tmp_path,
        "Codex|short_remaining=70.0|short_window=300m|short_reset=unknown|long_remaining=90.0|long_window=10080m|long_reset=unknown|plan=synthetic\n",
    )
    assert result.returncode == 0, result.stderr
    assert "Short window remaining: 70.0%" in result.stdout
    assert "Long window remaining:  90.0%" in result.stdout
    assert "PROVIDER_FORBIDDEN" not in result.stderr
