# SPDX-License-Identifier: Apache-2.0
"""Tests for parse_review.py — structured review JSON parser with markdown fallback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parse_review import (
    ALL_FIELDS,
    _extract_json_block,
    _normalize_json_keys,
    _parse_markdown_fallback,
    get_field,
    parse_review,
    validate_review,
    _cli_main,
    fields_as_shell_vars,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FULL_JSON_REVIEW = """\
Some preamble text from the reviewer.

```json
{
  "verdict": "PASS",
  "chapters": "Ch6 Web Product",
  "chapter_delta": "+40",
  "competitor_delta": "+15",
  "launch_delta": "+10",
  "product_score": 720,
  "strengths": "solid vertical slice",
  "gaps": "missing e2e",
  "next_actions": "add integration tests",
  "verification_evidence": "vitest run passes",
  "rationale": "real product improvement",
  "fail_reason_category": "none",
  "files_to_touch": "src/App.tsx",
  "required_changes": "none",
  "tests_to_run": "npm test",
  "pass_bar": "all four gates green"
}
```

Some trailing text.
"""

FULL_MARKDOWN_REVIEW = """\
REVIEW_VERDICT: PASS
CHAPTERS: Ch6 Web Product
CHAPTER_SCORE_DELTA: +40
COMPETITOR_DELTA: +15
LAUNCH_DELTA: +10
PRODUCT_SCORE: 720
STRENGTHS: solid vertical slice
GAPS: missing e2e
NEXT_ACTIONS: add integration tests
VERIFICATION_EVIDENCE: vitest run passes
FAIL_REASON_CATEGORY: none
FILES_TO_TOUCH: src/App.tsx
REQUIRED_CHANGES: none
TESTS_TO_RUN: npm test
PASS_BAR: all four gates green
RATIONALE: real product improvement
"""

FAIL_JSON_REVIEW = """\
```json
{
  "verdict": "FAIL",
  "chapters": "Ch6 Web Product",
  "chapter_delta": "0",
  "competitor_delta": "0",
  "launch_delta": "0",
  "product_score": 300,
  "strengths": "none",
  "gaps": "scaffolding only",
  "next_actions": "implement real feature",
  "verification_evidence": "no tests run",
  "rationale": "shallow work",
  "fail_reason_category": "shallow",
  "files_to_touch": "src/App.tsx",
  "required_changes": "add real behavior",
  "tests_to_run": "vitest run",
  "pass_bar": "product file changes + tests"
}
```
"""


# ---------------------------------------------------------------------------
# _extract_json_block
# ---------------------------------------------------------------------------


class TestExtractJsonBlock:
    # Scenario: fenced JSON block with valid JSON.
    # Expected: returns parsed dict.
    def test_valid_fenced_json(self) -> None:
        text = '```json\n{"verdict": "PASS"}\n```'
        result = _extract_json_block(text)
        assert result == {"verdict": "PASS"}

    # Scenario: no fenced block.
    # Expected: returns None.
    def test_no_fence(self) -> None:
        assert _extract_json_block("just plain text") is None

    # Scenario: fenced block with invalid JSON.
    # Expected: returns None.
    def test_invalid_json(self) -> None:
        text = "```json\n{not valid json}\n```"
        assert _extract_json_block(text) is None

    # Scenario: fenced block with array instead of object.
    # Expected: returns None (must be dict).
    def test_array_not_dict(self) -> None:
        text = "```json\n[1, 2, 3]\n```"
        assert _extract_json_block(text) is None

    # Scenario: multiple fenced blocks — uses first.
    # Expected: returns first block's content.
    def test_first_fence_wins(self) -> None:
        text = '```json\n{"a": "1"}\n```\n\n```json\n{"b": "2"}\n```'
        result = _extract_json_block(text)
        assert result == {"a": "1"}

    # Scenario: fenced block surrounded by other text.
    # Expected: extracts correctly from full review output.
    def test_full_review_extraction(self) -> None:
        result = _extract_json_block(FULL_JSON_REVIEW)
        assert result is not None
        assert result["verdict"] == "PASS"
        assert result["product_score"] == 720


# ---------------------------------------------------------------------------
# _normalize_json_keys
# ---------------------------------------------------------------------------


class TestNormalizeJsonKeys:
    # Scenario: snake_case keys pass through.
    def test_snake_case_passthrough(self) -> None:
        obj = {"verdict": "PASS", "chapter_delta": "+40"}
        result = _normalize_json_keys(obj)
        assert result["verdict"] == "PASS"
        assert result["chapter_delta"] == "+40"

    # Scenario: LEGACY_KEY format maps to snake_case.
    def test_legacy_key_mapping(self) -> None:
        obj = {"REVIEW_VERDICT": "PASS", "CHAPTER_SCORE_DELTA": "+40"}
        result = _normalize_json_keys(obj)
        assert result["verdict"] == "PASS"
        assert result["chapter_delta"] == "+40"

    # Scenario: numeric value coerced to string.
    def test_numeric_coercion(self) -> None:
        obj = {"product_score": 720}
        result = _normalize_json_keys(obj)
        assert result["product_score"] == "720"

    # Scenario: None value becomes empty string.
    def test_none_to_empty(self) -> None:
        obj = {"verdict": None}
        result = _normalize_json_keys(obj)
        assert result["verdict"] == ""


# ---------------------------------------------------------------------------
# _parse_markdown_fallback
# ---------------------------------------------------------------------------


class TestParseMarkdownFallback:
    # Scenario: full legacy review.
    # Expected: all 16 fields parsed correctly.
    def test_full_legacy_review(self) -> None:
        result = _parse_markdown_fallback(FULL_MARKDOWN_REVIEW)
        assert result["verdict"] == "PASS"
        assert result["chapters"] == "Ch6 Web Product"
        assert result["chapter_delta"] == "+40"
        assert result["product_score"] == "720"
        assert result["rationale"] == "real product improvement"

    # Scenario: empty input.
    # Expected: empty dict.
    def test_empty_input(self) -> None:
        assert _parse_markdown_fallback("") == {}

    # Scenario: partial fields.
    # Expected: only found fields in result.
    def test_partial_fields(self) -> None:
        text = "REVIEW_VERDICT: FAIL\nRATIONALE: bad work"
        result = _parse_markdown_fallback(text)
        assert result["verdict"] == "FAIL"
        assert result["rationale"] == "bad work"
        assert "chapters" not in result

    # Scenario: field with colon in value.
    # Expected: only first colon splits key from value.
    def test_colon_in_value(self) -> None:
        text = "RATIONALE: reason: this was bad: very bad"
        result = _parse_markdown_fallback(text)
        assert result["rationale"] == "reason: this was bad: very bad"


# ---------------------------------------------------------------------------
# parse_review (integration)
# ---------------------------------------------------------------------------


class TestParseReview:
    # Scenario: JSON review file.
    # Expected: parses via JSON mode.
    def test_json_mode(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FULL_JSON_REVIEW)
        result = parse_review(f)
        assert result["_parse_mode"] == "json"
        assert result["verdict"] == "PASS"
        assert result["chapter_delta"] == "+40"

    # Scenario: markdown review file.
    # Expected: parses via markdown fallback.
    def test_markdown_mode(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FULL_MARKDOWN_REVIEW)
        result = parse_review(f)
        assert result["_parse_mode"] == "markdown"
        assert result["verdict"] == "PASS"

    # Scenario: empty file.
    # Expected: markdown mode, empty fields.
    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text("")
        result = parse_review(f)
        assert result["_parse_mode"] == "markdown"
        assert result.get("verdict", "") == ""

    # Scenario: JSON with LEGACY_KEY format in JSON.
    # Expected: normalizes to snake_case.
    def test_json_with_legacy_keys(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text('```json\n{"REVIEW_VERDICT": "PASS", "CHAPTERS": "Ch1"}\n```')
        result = parse_review(f)
        assert result["_parse_mode"] == "json"
        assert result["verdict"] == "PASS"
        assert result["chapters"] == "Ch1"


# ---------------------------------------------------------------------------
# validate_review
# ---------------------------------------------------------------------------


class TestValidateReview:
    # Scenario: fully valid PASS review (JSON).
    # Expected: no errors.
    def test_valid_json_pass(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FULL_JSON_REVIEW)
        reasons = validate_review(f)
        assert reasons == []

    # Scenario: fully valid PASS review (markdown).
    # Expected: no errors.
    def test_valid_markdown_pass(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FULL_MARKDOWN_REVIEW)
        reasons = validate_review(f)
        assert reasons == []

    # Scenario: FAIL verdict.
    # Expected: first reason is "review verdict is not PASS".
    def test_fail_verdict(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FAIL_JSON_REVIEW)
        reasons = validate_review(f)
        assert "review verdict is not PASS" in reasons

    # Scenario: missing required fields.
    # Expected: specific missing field errors.
    def test_missing_fields(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text('```json\n{"verdict": "PASS"}\n```')
        reasons = validate_review(f)
        assert "missing CHAPTERS" in reasons
        assert "missing RATIONALE" in reasons
        assert "missing PRODUCT_SCORE" in reasons

    # Scenario: product_score is present but not an integer.
    # Expected: the hard review gate reports a typed validation failure.
    def test_invalid_product_score_type(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text(
            FULL_JSON_REVIEW.replace('"product_score": 720', '"product_score": "high"')
        )
        reasons = validate_review(f)
        assert "invalid_type:PRODUCT_SCORE" in reasons

    # Scenario: product_score is an integer outside the documented 0-1000 rubric.
    # Expected: the hard review gate reports a range validation failure.
    def test_invalid_product_score_range(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text(
            FULL_JSON_REVIEW.replace('"product_score": 720', '"product_score": 1001')
        )
        reasons = validate_review(f)
        assert "invalid_range:PRODUCT_SCORE" in reasons

    # Scenario: delta fields are present but not signed integers.
    # Expected: the hard review gate reports typed validation failures.
    @pytest.mark.parametrize(
        ("field_name", "json_key", "bad_value", "reason"),
        [
            (
                "chapter_delta",
                "chapter_delta",
                "forty",
                "invalid_type:CHAPTER_SCORE_DELTA",
            ),
            (
                "competitor_delta",
                "competitor_delta",
                "better",
                "invalid_type:COMPETITOR_DELTA",
            ),
            ("launch_delta", "launch_delta", "ready", "invalid_type:LAUNCH_DELTA"),
        ],
    )
    def test_invalid_delta_type(
        self,
        tmp_path: Path,
        field_name: str,
        json_key: str,
        bad_value: str,
        reason: str,
    ) -> None:
        payload = _extract_json_block(FULL_JSON_REVIEW)
        assert payload is not None
        payload[json_key] = bad_value
        f = tmp_path / "review.txt"
        f.write_text("```json\n" + json.dumps(payload) + "\n```\n")

        reasons = validate_review(f)

        assert payload[field_name] == bad_value
        assert reason in reasons

    # Scenario: empty file.
    # Expected: all fields missing + verdict not PASS.
    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text("")
        reasons = validate_review(f)
        assert "review verdict is not PASS" in reasons
        assert len(reasons) >= len(ALL_FIELDS)  # all fields missing + verdict


# ---------------------------------------------------------------------------
# get_field
# ---------------------------------------------------------------------------


class TestGetField:
    # Scenario: get field by canonical name from JSON review.
    def test_canonical_name_json(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FULL_JSON_REVIEW)
        assert get_field(f, "verdict") == "PASS"
        assert get_field(f, "next_actions") == "add integration tests"

    # Scenario: get field by legacy name from JSON review.
    def test_legacy_name_json(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FULL_JSON_REVIEW)
        assert get_field(f, "REVIEW_VERDICT") == "PASS"
        assert get_field(f, "NEXT_ACTIONS") == "add integration tests"

    # Scenario: get field from markdown review.
    def test_markdown_field(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FULL_MARKDOWN_REVIEW)
        assert get_field(f, "STRENGTHS") == "solid vertical slice"

    # Scenario: get nonexistent field.
    # Expected: empty string.
    def test_missing_field(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FULL_JSON_REVIEW)
        assert get_field(f, "NONEXISTENT") == ""


# ---------------------------------------------------------------------------
# fields_as_shell_vars
# ---------------------------------------------------------------------------


class TestFieldsAsShellVars:
    # Scenario: full JSON review produces shell-safe output.
    def test_shell_vars_output(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FULL_JSON_REVIEW)
        output = fields_as_shell_vars(f)
        assert "REVIEW_VERDICT='PASS'" in output
        assert "CHAPTERS='Ch6 Web Product'" in output
        assert "_PARSE_MODE='json'" in output

    # Scenario: value with single quote is escaped.
    def test_single_quote_escaping(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text('```json\n{"rationale": "it\'s good"}\n```')
        output = fields_as_shell_vars(f)
        assert "RATIONALE='it'\\''s good'" in output


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCli:
    # Scenario: parse command outputs JSON.
    def test_parse_command(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FULL_JSON_REVIEW)
        rc = _cli_main(["parse", str(f)])
        assert rc == 0
        captured = capsys.readouterr()
        obj = json.loads(captured.out)
        assert obj["verdict"] == "PASS"
        assert obj["_parse_mode"] == "json"

    # Scenario: validate command on valid review.
    def test_validate_pass(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FULL_JSON_REVIEW)
        rc = _cli_main(["validate", str(f)])
        assert rc == 0

    # Scenario: validate command on FAIL review.
    def test_validate_fail(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FAIL_JSON_REVIEW)
        rc = _cli_main(["validate", str(f)])
        assert rc == 1
        captured = capsys.readouterr()
        assert "review verdict is not PASS" in captured.err

    # Scenario: field command extracts single value.
    def test_field_command(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FULL_JSON_REVIEW)
        rc = _cli_main(["field", str(f), "NEXT_ACTIONS"])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "add integration tests"

    # Scenario: shell-vars command produces shell-safe output.
    def test_shell_vars_command(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        f = tmp_path / "review.txt"
        f.write_text(FULL_JSON_REVIEW)
        rc = _cli_main(["shell-vars", str(f)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "REVIEW_VERDICT='PASS'" in captured.out

    # Scenario: missing file.
    def test_missing_file(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _cli_main(["parse", "/nonexistent/file.txt"])
        assert rc == 2

    # Scenario: no args.
    def test_no_args(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = _cli_main([])
        assert rc == 2

    # Scenario: unknown command.
    def test_unknown_command(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        f.write_text("test")
        rc = _cli_main(["bogus", str(f)])
        assert rc == 2


# ---------------------------------------------------------------------------
# Regression: parse mode consistency
# ---------------------------------------------------------------------------


class TestParseModePriority:
    # Scenario: file has both JSON fence and FIELD: VALUE lines.
    # Expected: JSON wins (JSON-strict is preferred).
    def test_json_preferred_over_markdown(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        text = (
            "REVIEW_VERDICT: FAIL\n"
            "```json\n"
            '{"verdict": "PASS", "chapters": "Ch1"}\n'
            "```\n"
        )
        f.write_text(text)
        result = parse_review(f)
        assert result["_parse_mode"] == "json"
        assert result["verdict"] == "PASS"  # JSON wins over markdown FAIL

    # Scenario: broken JSON fence falls back to markdown.
    def test_broken_json_falls_back(self, tmp_path: Path) -> None:
        f = tmp_path / "review.txt"
        text = (
            "```json\n"
            "{broken json\n"
            "```\n"
            "REVIEW_VERDICT: PASS\n"
            "RATIONALE: fallback worked\n"
        )
        f.write_text(text)
        result = parse_review(f)
        assert result["_parse_mode"] == "markdown"
        assert result["verdict"] == "PASS"
        assert result["rationale"] == "fallback worked"
