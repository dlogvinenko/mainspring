#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tiny LiteLLM completion runner for Mainspring engine dispatch.

The shell engine dispatcher needs a process-shaped command. This module keeps
LiteLLM calls behind that boundary so the existing writer/reviewer plumbing can
capture stdout exactly like the CLI-backed engines.
"""

from __future__ import annotations

from cli_runtime import run_cli

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from engines.litellm_adapter import (
    format_missing_env_vars_message,
    missing_env_vars_for_model,
)


class ResponseShapeError(ValueError):
    """Raised when a provider response lacks the text completion contract."""


def _read_attr(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


_MISSING = object()


def extract_content_strict(response: Any) -> str:
    """Extract assistant content, failing closed on malformed responses."""
    choices = _read_attr(response, "choices", _MISSING)
    if choices is _MISSING:
        raise ResponseShapeError("missing choices")
    if not isinstance(choices, (list, tuple)):
        raise ResponseShapeError("choices is not a list")
    if not choices:
        raise ResponseShapeError("choices is empty")

    first = choices[0]
    message = _read_attr(first, "message", _MISSING)
    if message is _MISSING or message is None:
        raise ResponseShapeError("first choice has no message")
    content = _read_attr(message, "content", _MISSING)
    if content is _MISSING:
        raise ResponseShapeError("first message has no content")
    if not isinstance(content, str):
        raise ResponseShapeError("first message content is not text")
    return content


def extract_content(response: Any) -> str:
    """Extract the assistant content from a LiteLLM ModelResponse-like object."""
    try:
        return extract_content_strict(response)
    except ResponseShapeError:
        return ""


def _as_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def extract_usage(response: Any) -> dict[str, int]:
    """Extract OpenAI-style usage counters from a LiteLLM response."""
    usage = _read_attr(response, "usage", {}) or {}
    if not isinstance(usage, dict):
        usage = {
            "prompt_tokens": _read_attr(usage, "prompt_tokens"),
            "completion_tokens": _read_attr(usage, "completion_tokens"),
            "total_tokens": _read_attr(usage, "total_tokens"),
            "input_tokens": _read_attr(usage, "input_tokens"),
            "output_tokens": _read_attr(usage, "output_tokens"),
            "cached_input_tokens": _read_attr(usage, "cached_input_tokens"),
        }

    input_tokens = _as_int(
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or usage.get("prompt_token_count")
    )
    output_tokens = _as_int(
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or usage.get("completion_token_count")
    )
    total_tokens = _as_int(usage.get("total_tokens") or usage.get("total_token_count"))
    cached_input_tokens = _as_int(
        usage.get("cached_input_tokens")
        or usage.get("cache_read_input_tokens")
        or usage.get("cached_tokens")
    )

    result: dict[str, int] = {}
    if input_tokens is not None:
        result["input_tokens"] = input_tokens
        result["prompt_tokens"] = input_tokens
    if output_tokens is not None:
        result["output_tokens"] = output_tokens
        result["completion_tokens"] = output_tokens
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
    if total_tokens is not None:
        result["total_tokens"] = total_tokens
    if cached_input_tokens is not None:
        result["cached_input_tokens"] = cached_input_tokens
    return result


def extract_response_cost(
    response: Any,
    *,
    cost_func: Callable[..., Any] | None = None,
) -> float | None:
    """Extract or compute LiteLLM response cost without fabricating it."""
    for value in (
        _read_attr(response, "response_cost"),
        _read_attr(_read_attr(response, "_hidden_params", {}) or {}, "response_cost"),
    ):
        parsed = _as_float(value)
        if parsed is not None:
            return parsed

    if cost_func is None:
        return None
    try:
        return _as_float(cost_func(response))
    except Exception:
        return None


@dataclass(frozen=True)
class CompletionResult:
    """One LiteLLM response normalised for Mainspring runtime capture."""

    text: str
    usage: dict[str, int]
    cost_usd: float | None


def completion_result(
    *,
    model: str,
    prompt: str,
    completion_func: Callable[..., Any],
    cost_func: Callable[..., Any] | None = None,
) -> CompletionResult:
    """Run one non-streaming LiteLLM completion and return content + metadata."""
    response = completion_func(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
    )
    return CompletionResult(
        text=extract_content_strict(response),
        usage=extract_usage(response),
        cost_usd=extract_response_cost(response, cost_func=cost_func),
    )


def completion_text(
    *,
    model: str,
    prompt: str,
    completion_func: Callable[..., Any],
) -> str:
    """Run one non-streaming LiteLLM completion and return text content."""
    return completion_result(
        model=model,
        prompt=prompt,
        completion_func=completion_func,
    ).text


def write_usage_sidecar(
    path: str | None,
    *,
    role: str,
    model: str,
    result: CompletionResult,
) -> None:
    """Append usage/cost metadata for the shell wave ledger."""
    if not path or (not result.usage and result.cost_usd is None):
        return
    payload: dict[str, Any] = {
        "engine": "litellm",
        "role": role,
        "model": model,
        "usage": result.usage,
    }
    if result.cost_usd is not None:
        payload["cost_usd"] = result.cost_usd
        payload["cost_source"] = "litellm.completion_cost"
    usage_path = Path(path)
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    with usage_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _usage_sidecar_from_env() -> str:
    return os.environ.get("MAINSPRING_ENGINE_USAGE_FILE") or ""


def provider_env_error(model: str, environ: Mapping[str, str] = os.environ) -> str:
    """Return an actionable setup error when a known provider key is absent."""
    missing_env_vars = missing_env_vars_for_model(model, environ)
    if not missing_env_vars:
        return ""
    return format_missing_env_vars_message(
        f"LiteLLM model {model}",
        missing_env_vars,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one Mainspring LiteLLM turn")
    parser.add_argument("--model", required=True)
    parser.add_argument("--role", choices=("writer", "reviewer"), default="writer")
    parser.add_argument("--prompt", required=True)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    completion_func: Callable[..., Any] | None = None,
    cost_func: Callable[..., Any] | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """CLI entry point.

    ``completion_func`` is injectable so tests can prove the command shape and
    response parsing without credentials or network calls.
    """
    args = _parser().parse_args(argv)
    role = args.role

    if completion_func is None:
        try:
            from litellm import completion as completion_func
            from litellm import completion_cost as cost_func
        except ModuleNotFoundError:
            print(
                "mainspring: python module 'litellm' is not installed; "
                "install provider extras with Python 3.11-3.13: "
                "cd /path/to/mainspring && "
                "MAINSPRING_PROVIDERS_PYTHON=python3.13 make install-user-providers",
                file=stderr,
            )
            return 2
        if setup_error := provider_env_error(args.model):
            print(f"mainspring: {setup_error}", file=stderr)
            return 2

    try:
        result = completion_result(
            model=args.model,
            prompt=args.prompt,
            completion_func=completion_func,
            cost_func=cost_func,
        )
    except ResponseShapeError as exc:
        print(f"mainspring: litellm response shape invalid: {exc}", file=stderr)
        return 1
    except Exception as exc:
        print(f"mainspring: litellm completion failed: {exc}", file=stderr)
        return 1

    if not result.text:
        print("mainspring: litellm completion returned no text content", file=stderr)
        return 1

    write_usage_sidecar(
        _usage_sidecar_from_env(),
        role=role,
        model=args.model,
        result=result,
    )

    stdout.write(result.text)
    if not result.text.endswith("\n"):
        stdout.write("\n")
    return 0


if __name__ == "__main__":
    run_cli(main)
