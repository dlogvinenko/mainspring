# SPDX-License-Identifier: Apache-2.0
"""Fail-closed SWE-bench Verified runner wrapper for Mainspring releases."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_DATASET = "princeton-nlp/SWE-bench_Verified"
DEFAULT_SPLIT = "test"
DEFAULT_RUN_ID = "mainspring-swe-bench-verified"
DEFAULT_CACHE_LEVEL = "env"
REQUIRED_PREDICTION_KEYS = ("instance_id", "model_name_or_path", "model_patch")
EVIDENCE_SCHEMA_VERSION = 1
BENCHMARK_ARTIFACT_TYPE = "swe-bench-verified-result"


class SweBenchError(ValueError):
    """Raised when benchmark input or runtime prerequisites are invalid."""


def load_predictions(path: Path) -> list[dict[str, str]]:
    """Load and validate SWE-bench prediction JSONL."""
    if not path.is_file():
        raise SweBenchError(f"predictions file does not exist: {path}")

    predictions: list[dict[str, str]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            raise SweBenchError(
                f"{path}:{line_number}: blank JSONL lines are not allowed"
            )
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SweBenchError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(item, dict):
            raise SweBenchError(f"{path}:{line_number}: prediction must be an object")

        prediction: dict[str, str] = {}
        for key in REQUIRED_PREDICTION_KEYS:
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                raise SweBenchError(
                    f"{path}:{line_number}: {key} must be a non-empty string"
                )
            prediction[key] = value
        predictions.append(prediction)

    if not predictions:
        raise SweBenchError(f"predictions file is empty: {path}")
    return predictions


def build_run_command(
    *,
    predictions_path: Path,
    dataset_name: str = DEFAULT_DATASET,
    split: str = DEFAULT_SPLIT,
    max_workers: int = 4,
    run_id: str = DEFAULT_RUN_ID,
    cache_level: str = DEFAULT_CACHE_LEVEL,
    instance_ids: list[str] | None = None,
    clean: bool = False,
    modal: bool = False,
) -> list[str]:
    """Build the official SWE-bench evaluation command."""
    if max_workers < 1:
        raise SweBenchError("--max-workers must be at least 1")
    command = [
        sys.executable,
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        dataset_name,
        "--split",
        split,
        "--predictions_path",
        str(predictions_path),
        "--max_workers",
        str(max_workers),
        "--run_id",
        run_id,
        "--cache_level",
        cache_level,
    ]
    if instance_ids:
        command.append("--instance_ids")
        command.extend(instance_ids)
    if clean:
        command.extend(["--clean", "True"])
    if modal:
        command.extend(["--modal", "true"])
    return command


def ensure_runtime_available(*, modal: bool) -> None:
    """Fail before a real benchmark run if local prerequisites are missing."""
    if importlib.util.find_spec("swebench") is None:
        raise SweBenchError(
            "swebench is not installed; install SWE-bench in the benchmark "
            "environment before running a real evaluation"
        )
    if not modal and shutil.which("docker") is None:
        raise SweBenchError(
            "docker is required for local SWE-bench evaluation; install Docker "
            "or rerun with --modal"
        )


def run_evaluation(args: argparse.Namespace) -> int:
    """Validate predictions and optionally launch the SWE-bench harness."""
    predictions_path = args.predictions.resolve()
    predictions = load_predictions(predictions_path)
    command = build_run_command(
        predictions_path=predictions_path,
        dataset_name=args.dataset_name,
        split=args.split,
        max_workers=args.max_workers,
        run_id=args.run_id,
        cache_level=args.cache_level,
        instance_ids=args.instance_id,
        clean=args.clean,
        modal=args.modal,
    )
    print(f"validated_predictions={len(predictions)}")
    print(shlex.join(command))
    if args.dry_run:
        return 0

    ensure_runtime_available(modal=args.modal)
    return subprocess.run(command, check=False).returncode


def _first_number(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _computed_rate(resolved: float | None, submitted: float | None) -> float | None:
    if resolved is None or submitted in (None, 0):
        return None
    return (resolved / submitted) * 100


def summarize_results(results_path: Path) -> dict[str, Any]:
    """Extract release-facing metrics from a SWE-bench results JSON file."""
    if not results_path.is_file():
        raise SweBenchError(f"results file does not exist: {results_path}")
    try:
        payload = json.loads(results_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SweBenchError(f"{results_path}: invalid JSON") from exc
    if not isinstance(payload, dict):
        raise SweBenchError(f"{results_path}: results must be a JSON object")

    submitted = _first_number(
        payload,
        ("instances_submitted", "submitted", "total_submitted", "total_instances"),
    )
    completed = _first_number(
        payload,
        ("instances_completed", "completed", "total_completed"),
    )
    resolved = _first_number(
        payload,
        ("instances_resolved", "resolved", "total_resolved"),
    )
    rate = _first_number(payload, ("resolution_rate", "resolved_rate", "score"))
    if rate is not None and rate <= 1:
        rate *= 100
    if rate is None:
        rate = _computed_rate(resolved, submitted)

    if submitted is None or resolved is None or rate is None:
        raise SweBenchError(
            f"{results_path}: missing submitted/resolved/rate metrics needed for benchmark publication"
        )

    return {
        "dataset": payload.get("dataset_name", DEFAULT_DATASET),
        "split": payload.get("split", DEFAULT_SPLIT),
        "run_id": payload.get("run_id", DEFAULT_RUN_ID),
        "instances_submitted": int(submitted),
        "instances_completed": int(completed) if completed is not None else None,
        "instances_resolved": int(resolved),
        "resolution_rate": rate,
    }


def format_summary_markdown(summary: dict[str, Any]) -> str:
    """Render a results summary for README/docs release updates."""
    completed = summary["instances_completed"]
    completed_text = "n/a" if completed is None else str(completed)
    return "\n".join(
        [
            "| Metric | Value |",
            "| --- | --- |",
            f"| Dataset | `{summary['dataset']}` |",
            f"| Split | `{summary['split']}` |",
            f"| Run ID | `{summary['run_id']}` |",
            f"| Submitted | {summary['instances_submitted']} |",
            f"| Completed | {completed_text} |",
            f"| Resolved | {summary['instances_resolved']} |",
            f"| Resolution rate | {summary['resolution_rate']:.2f}% |",
        ]
    )


def benchmark_evidence_payload(summary: dict[str, Any]) -> dict[str, Any]:
    """Return a machine-readable benchmark evidence payload for a verified result."""
    return {
        "artifact_type": BENCHMARK_ARTIFACT_TYPE,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        **summary,
    }


def summarize(args: argparse.Namespace) -> int:
    """Print a release-facing summary from a SWE-bench results JSON file."""
    summary = summarize_results(args.results)
    if args.format == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
    elif args.format == "evidence-json":
        print(json.dumps(benchmark_evidence_payload(summary), indent=2, sort_keys=True))
    else:
        print(format_summary_markdown(summary))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Run or summarize a fail-closed SWE-bench Verified evaluation."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    run_parser = subcommands.add_parser(
        "run", help="Validate predictions and run SWE-bench"
    )
    run_parser.add_argument("--predictions", type=Path, required=True)
    run_parser.add_argument("--dataset-name", default=DEFAULT_DATASET)
    run_parser.add_argument("--split", default=DEFAULT_SPLIT)
    run_parser.add_argument("--max-workers", type=int, default=4)
    run_parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    run_parser.add_argument("--cache-level", default=DEFAULT_CACHE_LEVEL)
    run_parser.add_argument("--instance-id", action="append")
    run_parser.add_argument("--clean", action="store_true")
    run_parser.add_argument("--modal", action="store_true")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate input and print the harness command without launching SWE-bench",
    )
    run_parser.set_defaults(func=run_evaluation)

    summarize_parser = subcommands.add_parser(
        "summarize", help="Summarize SWE-bench results JSON"
    )
    summarize_parser.add_argument("results", type=Path)
    summarize_parser.add_argument(
        "--format",
        choices=("markdown", "json", "evidence-json"),
        default="markdown",
    )
    summarize_parser.set_defaults(func=summarize)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    try:
        return args.func(args)
    except SweBenchError as exc:
        raise SystemExit(f"swe_bench: {exc}") from exc


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
