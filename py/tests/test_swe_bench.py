# SPDX-License-Identifier: Apache-2.0
"""Tests for the SWE-bench Verified release harness."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bench import swe_bench


def write_predictions(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "instance_id": "sympy__sympy-20590",
                "model_name_or_path": "mainspring",
                "model_patch": "diff --git a/example.py b/example.py\n",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_load_predictions_accepts_official_jsonl_shape(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions.jsonl"
    write_predictions(predictions)

    loaded = swe_bench.load_predictions(predictions)

    assert loaded == [
        {
            "instance_id": "sympy__sympy-20590",
            "model_name_or_path": "mainspring",
            "model_patch": "diff --git a/example.py b/example.py\n",
        }
    ]


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("", "blank JSONL lines"),
        ("not json", "invalid JSON"),
        (json.dumps(["not", "object"]), "prediction must be an object"),
        (
            json.dumps(
                {
                    "instance_id": "sympy__sympy-20590",
                    "model_name_or_path": "mainspring",
                }
            ),
            "model_patch must be a non-empty string",
        ),
        (
            json.dumps(
                {
                    "instance_id": "sympy__sympy-20590",
                    "model_name_or_path": "mainspring",
                    "model_patch": "",
                }
            ),
            "model_patch must be a non-empty string",
        ),
    ],
)
def test_load_predictions_fails_closed_on_invalid_jsonl(
    tmp_path: Path,
    line: str,
    message: str,
) -> None:
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(line + "\n", encoding="utf-8")

    with pytest.raises(swe_bench.SweBenchError, match=message):
        swe_bench.load_predictions(predictions)


def test_build_run_command_defaults_to_swe_bench_verified(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions.jsonl"
    command = swe_bench.build_run_command(
        predictions_path=predictions,
        max_workers=2,
        run_id="benchmark-evidence",
        instance_ids=["sympy__sympy-20590"],
        clean=True,
    )

    assert command[:3] == [sys.executable, "-m", "swebench.harness.run_evaluation"]
    assert "--dataset_name" in command
    assert swe_bench.DEFAULT_DATASET in command
    assert "--split" in command
    assert swe_bench.DEFAULT_SPLIT in command
    assert "--predictions_path" in command
    assert str(predictions) in command
    assert "--max_workers" in command
    assert "2" in command
    assert "--instance_ids" in command
    assert "sympy__sympy-20590" in command
    assert "--clean" in command
    assert "True" in command


def test_run_dry_run_validates_and_prints_command(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    predictions = tmp_path / "predictions.jsonl"
    write_predictions(predictions)

    rc = swe_bench.main(["run", "--predictions", str(predictions), "--dry-run"])

    output = capsys.readouterr().out
    assert rc == 0
    assert "validated_predictions=1" in output
    assert "swebench.harness.run_evaluation" in output
    assert swe_bench.DEFAULT_DATASET in output


def test_real_run_fails_without_runtime_prerequisites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predictions = tmp_path / "predictions.jsonl"
    write_predictions(predictions)
    monkeypatch.setattr(swe_bench.importlib.util, "find_spec", lambda _name: None)

    with pytest.raises(SystemExit, match="swebench is not installed"):
        swe_bench.main(["run", "--predictions", str(predictions)])


def test_summarize_results_accepts_official_metric_names(tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps(
            {
                "dataset_name": swe_bench.DEFAULT_DATASET,
                "split": "test",
                "run_id": "benchmark-evidence",
                "total_instances": 500,
                "instances_completed": 500,
                "instances_resolved": 123,
                "resolution_rate": 0.246,
            }
        ),
        encoding="utf-8",
    )

    summary = swe_bench.summarize_results(results)

    assert summary == {
        "dataset": swe_bench.DEFAULT_DATASET,
        "split": "test",
        "run_id": "benchmark-evidence",
        "instances_submitted": 500,
        "instances_completed": 500,
        "instances_resolved": 123,
        "resolution_rate": 24.6,
    }


def test_summarize_results_rejects_boolean_metric_values(tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps(
            {
                "total_instances": True,
                "instances_resolved": 1,
                "resolution_rate": 1,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(swe_bench.SweBenchError, match="missing submitted"):
        swe_bench.summarize_results(results)


def test_summarize_markdown_is_release_ready() -> None:
    markdown = swe_bench.format_summary_markdown(
        {
            "dataset": swe_bench.DEFAULT_DATASET,
            "split": "test",
            "run_id": "benchmark-evidence",
            "instances_submitted": 500,
            "instances_completed": 500,
            "instances_resolved": 123,
            "resolution_rate": 24.6,
        }
    )

    assert "| Dataset | `princeton-nlp/SWE-bench_Verified` |" in markdown
    assert "| Resolved | 123 |" in markdown
    assert "| Resolution rate | 24.60% |" in markdown


def test_benchmark_evidence_payload_names_artifact_type() -> None:
    payload = swe_bench.benchmark_evidence_payload(
        {
            "dataset": swe_bench.DEFAULT_DATASET,
            "split": "test",
            "run_id": "benchmark-evidence",
            "instances_submitted": 500,
            "instances_completed": 500,
            "instances_resolved": 123,
            "resolution_rate": 24.6,
        }
    )

    assert payload["artifact_type"] == "swe-bench-verified-result"
    assert payload["evidence_schema_version"] == 1
    assert payload["resolution_rate"] == 24.6


def test_summarize_can_emit_benchmark_evidence_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps(
            {
                "dataset_name": swe_bench.DEFAULT_DATASET,
                "split": "test",
                "run_id": "benchmark-evidence",
                "total_instances": 500,
                "instances_completed": 500,
                "instances_resolved": 123,
                "resolution_rate": 0.246,
            }
        ),
        encoding="utf-8",
    )

    rc = swe_bench.main(["summarize", str(results), "--format", "evidence-json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["artifact_type"] == "swe-bench-verified-result"
    assert payload["dataset"] == swe_bench.DEFAULT_DATASET
    assert payload["resolution_rate"] == 24.6
