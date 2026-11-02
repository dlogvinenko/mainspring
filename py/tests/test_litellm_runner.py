# SPDX-License-Identifier: Apache-2.0
"""Tests for litellm_runner.py."""

from __future__ import annotations

import builtins
import json
import os
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import litellm_runner


def test_extract_content_from_model_response_object() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Ship the slice"),
            )
        ]
    )

    assert litellm_runner.extract_content(response) == "Ship the slice"


def test_extract_content_from_dict_response() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "content": "Review passed",
                }
            }
        ]
    }

    assert litellm_runner.extract_content(response) == "Review passed"


def test_extract_content_strict_rejects_missing_choices() -> None:
    response = {"usage": {"total_tokens": 3}}

    with pytest.raises(litellm_runner.ResponseShapeError, match="missing choices"):
        litellm_runner.extract_content_strict(response)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({"choices": "not-list"}, "choices is not a list"),
        ({"choices": []}, "choices is empty"),
        ({"choices": [{"finish_reason": "stop"}]}, "first choice has no message"),
        (
            {"choices": [{"message": {"role": "assistant"}}]},
            "first message has no content",
        ),
    ],
)
def test_extract_content_strict_rejects_malformed_choice_shapes(
    response: object,
    message: str,
) -> None:
    with pytest.raises(litellm_runner.ResponseShapeError, match=message):
        litellm_runner.extract_content_strict(response)


def test_extract_content_returns_empty_string_on_shape_error() -> None:
    assert litellm_runner.extract_content({"choices": []}) == ""


def test_extract_content_strict_rejects_non_text_content() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "content": [{"type": "text", "text": "not normalized"}],
                }
            }
        ]
    }

    with pytest.raises(
        litellm_runner.ResponseShapeError,
        match="content is not text",
    ):
        litellm_runner.extract_content_strict(response)


def test_completion_text_uses_openai_style_messages() -> None:
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "Done"}}]}

    text = litellm_runner.completion_text(
        model="gemini/gemini-2.5-pro",
        prompt="Implement",
        completion_func=fake_completion,
    )

    assert text == "Done"
    assert captured == {
        "model": "gemini/gemini-2.5-pro",
        "messages": [{"role": "user", "content": "Implement"}],
        "stream": False,
    }


def test_completion_result_extracts_usage_and_completion_cost() -> None:
    response = {
        "choices": [{"message": {"content": "Done"}}],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 25,
            "total_tokens": 125,
        },
    }

    def fake_completion(**kwargs):
        del kwargs
        return response

    def fake_cost(payload):
        assert payload is response
        return 0.0125

    result = litellm_runner.completion_result(
        model="gpt-5.5",
        prompt="Implement",
        completion_func=fake_completion,
        cost_func=fake_cost,
    )

    assert result.text == "Done"
    assert result.usage == {
        "input_tokens": 100,
        "prompt_tokens": 100,
        "output_tokens": 25,
        "completion_tokens": 25,
        "total_tokens": 125,
    }
    assert result.cost_usd == 0.0125


def test_extract_usage_accepts_object_aliases_and_filters_invalid_values() -> None:
    usage = SimpleNamespace(
        input_tokens="12",
        output_tokens=5,
        total_tokens=-1,
        cached_input_tokens="bad",
    )
    response = SimpleNamespace(usage=usage)

    assert litellm_runner.extract_usage(response) == {
        "completion_tokens": 5,
        "input_tokens": 12,
        "output_tokens": 5,
        "prompt_tokens": 12,
        "total_tokens": 17,
    }


def test_extract_usage_accepts_google_token_count_aliases() -> None:
    response = {
        "usage": {
            "prompt_token_count": 4,
            "completion_token_count": 6,
            "total_token_count": 10,
            "cache_read_input_tokens": 2,
        }
    }

    assert litellm_runner.extract_usage(response) == {
        "cached_input_tokens": 2,
        "completion_tokens": 6,
        "input_tokens": 4,
        "output_tokens": 6,
        "prompt_tokens": 4,
        "total_tokens": 10,
    }


def test_extract_response_cost_uses_hidden_params_and_ignores_bad_cost_func() -> None:
    response = SimpleNamespace(_hidden_params={"response_cost": "0.25"})

    assert litellm_runner.extract_response_cost(response) == 0.25
    assert (
        litellm_runner.extract_response_cost(
            SimpleNamespace(),
            cost_func=lambda response: (_ for _ in ()).throw(RuntimeError("no cost")),
        )
        is None
    )


def test_main_writes_completion_text_without_network() -> None:
    def fake_completion(**kwargs):
        del kwargs
        return {"choices": [{"message": {"content": "PASS"}}]}

    stdout = StringIO()
    stderr = StringIO()
    exit_code = litellm_runner.main(
        ["--model", "xai/test", "--role", "reviewer", "--prompt", "Review"],
        completion_func=fake_completion,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stdout.getvalue() == "PASS\n"
    assert stderr.getvalue() == ""


def test_main_writes_usage_sidecar_without_polluting_stdout(tmp_path: Path) -> None:
    usage_file = tmp_path / "usage.jsonl"

    def fake_completion(**kwargs):
        del kwargs
        return {
            "choices": [{"message": {"content": "PASS"}}],
            "usage": {"input_tokens": 10, "output_tokens": 3},
        }

    def fake_cost(response):
        del response
        return 0.0042

    old_value = os.environ.get("MAINSPRING_ENGINE_USAGE_FILE")
    os.environ["MAINSPRING_ENGINE_USAGE_FILE"] = str(usage_file)
    try:
        stdout = StringIO()
        stderr = StringIO()
        exit_code = litellm_runner.main(
            ["--model", "gpt-5.5", "--role", "reviewer", "--prompt", "Review"],
            completion_func=fake_completion,
            cost_func=fake_cost,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        if old_value is None:
            os.environ.pop("MAINSPRING_ENGINE_USAGE_FILE", None)
        else:
            os.environ["MAINSPRING_ENGINE_USAGE_FILE"] = old_value

    assert exit_code == 0
    assert stdout.getvalue() == "PASS\n"
    assert stderr.getvalue() == ""
    rows = [json.loads(line) for line in usage_file.read_text().splitlines()]
    assert rows == [
        {
            "cost_source": "litellm.completion_cost",
            "cost_usd": 0.0042,
            "engine": "litellm",
            "model": "gpt-5.5",
            "role": "reviewer",
            "usage": {
                "completion_tokens": 3,
                "input_tokens": 10,
                "output_tokens": 3,
                "prompt_tokens": 10,
                "total_tokens": 13,
            },
        }
    ]


def test_write_usage_sidecar_skips_empty_payload(tmp_path: Path) -> None:
    usage_file = tmp_path / "usage.jsonl"

    litellm_runner.write_usage_sidecar(
        str(usage_file),
        role="writer",
        model="gpt-5.5",
        result=litellm_runner.CompletionResult(text="ok", usage={}, cost_usd=None),
    )
    litellm_runner.write_usage_sidecar(
        None,
        role="writer",
        model="gpt-5.5",
        result=litellm_runner.CompletionResult(
            text="ok",
            usage={"input_tokens": 1},
            cost_usd=None,
        ),
    )

    assert not usage_file.exists()


def test_main_preserves_provider_newline_without_extra_blank_line() -> None:
    def fake_completion(**kwargs):
        del kwargs
        return {"choices": [{"message": {"content": "PASS\n"}}]}

    stdout = StringIO()
    exit_code = litellm_runner.main(
        ["--model", "gpt-5.5", "--prompt", "Review"],
        completion_func=fake_completion,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert stdout.getvalue() == "PASS\n"


def test_main_fails_closed_on_missing_text() -> None:
    def fake_completion(**kwargs):
        del kwargs
        return {"choices": [{"message": {"content": ""}}]}

    stdout = StringIO()
    stderr = StringIO()
    exit_code = litellm_runner.main(
        ["--model", "gpt-5.5", "--prompt", "Write"],
        completion_func=fake_completion,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert "returned no text content" in stderr.getvalue()


def test_main_fails_closed_on_malformed_response_shape() -> None:
    def fake_completion(**kwargs):
        del kwargs
        return {"choices": []}

    stdout = StringIO()
    stderr = StringIO()
    exit_code = litellm_runner.main(
        ["--model", "gpt-5.5", "--prompt", "Write"],
        completion_func=fake_completion,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert "response shape invalid: choices is empty" in stderr.getvalue()


def test_main_fails_closed_on_completion_exception() -> None:
    def fake_completion(**kwargs):
        del kwargs
        raise RuntimeError("provider unavailable")

    stderr = StringIO()
    exit_code = litellm_runner.main(
        ["--model", "gpt-5.5", "--prompt", "Write"],
        completion_func=fake_completion,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 1
    assert "provider unavailable" in stderr.getvalue()


def test_provider_env_error_names_exact_gemini_setup(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    message = litellm_runner.provider_env_error(
        "gemini/gemini-2.5-pro",
        os.environ,
    )

    assert (
        "environment variable GOOGLE_API_KEY is not set for LiteLLM model "
        "gemini/gemini-2.5-pro"
    ) in message
    assert "run: export GOOGLE_API_KEY=<provider API key>" in message


def test_main_fails_closed_before_provider_call_when_env_missing(
    monkeypatch,
) -> None:
    original_import = builtins.__import__
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "should not run"}}]}

    def fake_import(name, *args, **kwargs):
        if name == "litellm":
            return SimpleNamespace(
                completion=fake_completion,
                completion_cost=lambda response: None,
            )
        return original_import(name, *args, **kwargs)

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    stdout = StringIO()
    stderr = StringIO()

    exit_code = litellm_runner.main(
        ["--model", "gemini/gemini-2.5-pro", "--prompt", "Write"],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert calls == []
    assert stdout.getvalue() == ""
    assert "GOOGLE_API_KEY is not set" in stderr.getvalue()
    assert "export GOOGLE_API_KEY=<provider API key>" in stderr.getvalue()


def test_main_missing_litellm_message_names_provider_extra(
    monkeypatch,
) -> None:
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "litellm":
            raise ModuleNotFoundError("No module named 'litellm'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    stderr = StringIO()

    exit_code = litellm_runner.main(
        ["--model", "gemini/gemini-2.5-pro", "--prompt", "Write"],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    message = stderr.getvalue()
    assert "install provider extras with Python 3.11-3.13" in message
    assert (
        "MAINSPRING_PROVIDERS_PYTHON=python3.13 make install-user-providers" in message
    )
    old_editable_provider_install = "python3.13 -m pip install -e '." + "[providers]'"
    assert old_editable_provider_install not in message
    assert "scripts/" + "mainspring/requirements.txt" not in message
