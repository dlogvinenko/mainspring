# SPDX-License-Identifier: Apache-2.0
"""Native parser CLI plus exact shell admission consumer, synthetic reviewer only."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from parse_review import _extract_json_block

from .test_parse_review import FULL_JSON_REVIEW, FULL_MARKDOWN_REVIEW

HERE = Path(__file__).resolve().parent
ARM = HERE.parents[1]
PY = ARM / "py"
REVIEW_SH = ARM / "lib/review.sh"
FENCE = chr(96) * 3
ENV = {
    "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
    "PYTHONPATH": str(PY),
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUTF8": "1",
}
HARNESS = r"""
set -euo pipefail
source "$1"
MAINSPRING_PY_DIR="$2"
PAYLOAD="$3"
CASE_DIR="$4"
PARSER_INTERPRETER="$5"
PRODUCT_COUNT="$6"
WRITER_FILE="${7:-$PAYLOAD}"
ROOT_DIR="$CASE_DIR/project"
LOG_DIR="$CASE_DIR/logs"
SUMMARY_FILE="$CASE_DIR/summary.txt"
MODE=synthetic
AGENT_MODE=code
REVIEW_ENGINE=synthetic
REVIEW_MODEL_OVERRIDE=
mkdir -p "$ROOT_DIR" "$LOG_DIR"
: > "$SUMMARY_FILE"
mainspring_python() { printf '%s\n' "$PARSER_INTERPRETER"; }
count_product_file_changes() { printf '%s\n' "$PRODUCT_COUNT"; }
task_allows_docs_only() { return 1; }
agent_mode_allows_no_product_change() { return 1; }
build_review_prompt() { printf '%s\n' 'Synthetic review prompt; no provider.'; }
run_ai_turn() { cp "$PAYLOAD" "$4"; : > "$3"; return 0; }
append_review_ledgers() { :; }
write_review_repair_instructions() { printf '%s\n' 'SYNTHETIC_REPAIR_REQUESTED'; }
rc=0
if apply_review_gate synthetic synthetic-target src/synthetic.py "$WRITER_FILE" 1; then
  rc=0
else
  rc=$?
fi
exit "$rc"
"""


def _review_file(tmp_path, payload):
    file = tmp_path / "review.txt"
    if isinstance(payload, dict):
        file.write_text(FENCE + "json\n" + json.dumps(payload) + "\n" + FENCE + "\n")
    else:
        file.write_text(payload)
    return file


def _cli(file, command, *extra):
    return subprocess.run(
        [sys.executable, "-B", str(PY / "parse_review.py"), command, str(file), *extra],
        cwd=file.parent,
        env=ENV,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _gate(tmp_path, file, *, silent_status=None, product_count=1, writer_file=None):
    work = tmp_path / "gate"
    work.mkdir()
    script = tmp_path / "consumer.sh"
    script.write_text(HARNESS)
    interpreter = sys.executable
    if silent_status is not None:
        launcher = tmp_path / "silent-validator.sh"
        launcher.write_text(
            '#!/bin/bash\nif [ "$2" = validate ]; then exit '
            + str(silent_status)
            + "; fi\nexec "
            + sys.executable
            + ' "$@"\n'
        )
        launcher.chmod(0o700)
        interpreter = str(launcher)
    return subprocess.run(
        [
            "/bin/bash",
            "--noprofile",
            "--norc",
            str(script),
            str(REVIEW_SH),
            str(PY),
            str(file),
            str(work),
            interpreter,
            str(product_count),
            *([str(writer_file)] if writer_file is not None else []),
        ],
        cwd=tmp_path,
        env=ENV,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


@pytest.mark.parametrize("status", [1, 17, 137])
def test_silent_nonzero_validator_cannot_admit_review(tmp_path, status):
    file = _review_file(tmp_path, FULL_JSON_REVIEW)
    assert _cli(file, "validate").returncode == 0
    result = _gate(tmp_path, file, silent_status=status)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "parser" in (result.stdout + result.stderr).lower()


@pytest.mark.parametrize(
    "field", ["verification_evidence", "tests_to_run", "required_changes"]
)
@pytest.mark.parametrize("value", [[], {}, False])
def test_required_text_evidence_rejects_nontext_json(tmp_path, field, value):
    payload = _extract_json_block(FULL_JSON_REVIEW)
    payload[field] = value
    file = _review_file(tmp_path, payload)
    cli = _cli(file, "validate")
    gate = _gate(tmp_path, file)
    assert cli.returncode != 0 and gate.returncode != 0, {
        "cli_stdout": cli.stdout,
        "cli_stderr": cli.stderr,
        "gate_stdout": gate.stdout,
        "gate_stderr": gate.stderr,
    }
    assert _cli(file, "field", field).stdout == ""


def test_required_strengths_false_is_not_text_evidence(tmp_path):
    payload = _extract_json_block(FULL_JSON_REVIEW)
    payload["strengths"] = False
    file = _review_file(tmp_path, payload)
    assert _cli(file, "validate").returncode != 0
    assert _gate(tmp_path, file).returncode != 0


@pytest.mark.parametrize(
    "text",
    [
        FULL_JSON_REVIEW,
        FULL_MARKDOWN_REVIEW,
        FENCE + "json\n{broken json\n" + FENCE + "\n" + FULL_MARKDOWN_REVIEW,
    ],
)
def test_documented_valid_modes_still_admit(tmp_path, text):
    file = _review_file(tmp_path, text)
    assert _cli(file, "validate").returncode == 0
    assert _gate(tmp_path, file).returncode == 0
    assert _cli(file, "field", "PRODUCT_SCORE").stdout == "720\n"


@pytest.mark.parametrize(
    "field,value",
    [
        ("verification_evidence", None),
        ("product_score", "high"),
        ("verdict", "FAIL"),
    ],
)
def test_existing_rejection_controls_stay_closed(tmp_path, field, value):
    payload = _extract_json_block(FULL_JSON_REVIEW)
    payload[field] = value
    file = _review_file(tmp_path, payload)
    assert _cli(file, "validate").returncode != 0
    assert _gate(tmp_path, file).returncode != 0


def test_product_change_guard_stays_independent(tmp_path):
    file = _review_file(tmp_path, FULL_JSON_REVIEW)
    assert _cli(file, "validate").returncode == 0
    result = _gate(tmp_path, file, product_count=0)
    assert result.returncode != 0
    assert "no product/source file changes" in result.stdout


@pytest.mark.parametrize("reviewer_pass", [False, True])
def test_gate_validates_reviewer_instead_of_writer(tmp_path, reviewer_pass):
    reviewer = _extract_json_block(FULL_JSON_REVIEW)
    if not reviewer_pass:
        reviewer["verdict"] = "FAIL"
    file = _review_file(tmp_path, reviewer)
    writer = tmp_path / "writer.txt"
    writer.write_text("writer output\n" if reviewer_pass else FULL_JSON_REVIEW)

    assert (_cli(file, "validate").returncode == 0) is reviewer_pass
    result = _gate(tmp_path, file, writer_file=writer)

    assert (result.returncode == 0) is reviewer_pass, result.stdout + result.stderr


@pytest.mark.parametrize(
    "field", ["verification_evidence", "tests_to_run", "required_changes", "strengths"]
)
@pytest.mark.parametrize("value", [True, ["vitest run passes"], {"cmd": "npm test"}])
def test_truthy_nontext_evidence_is_not_coerced_into_text(tmp_path, field, value):
    payload = _extract_json_block(FULL_JSON_REVIEW)
    payload[field] = value
    file = _review_file(tmp_path, payload)

    cli = _cli(file, "validate")
    gate = _gate(tmp_path, file)

    assert cli.returncode != 0 and gate.returncode != 0, {
        "cli_stdout": cli.stdout,
        "cli_stderr": cli.stderr,
        "gate_stdout": gate.stdout,
        "gate_stderr": gate.stderr,
    }
    assert _cli(file, "field", field).stdout == ""
