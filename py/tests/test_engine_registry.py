# SPDX-License-Identifier: Apache-2.0
"""Tests for engine registry preflight."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from engines import claude, codex, registry

SCRIPT = str(HERE.parent / "engine_registry.py")
LEGACY_ENV_PREFIX = "OMX" + "_LOOP_"

LITELLM_PROVIDER_ENGINE_EXPECTATIONS = {
    "anthropic": ("anthropic/claude-opus-4.7", ("ANTHROPIC_API_KEY",)),
    "azure": (
        "azure/gpt-5.5",
        ("AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION"),
    ),
    "gemini": ("gemini/gemini-2.5-pro", ("GOOGLE_API_KEY",)),
    "grok": ("xai/grok-4.20-reasoning", ("XAI_API_KEY",)),
    "mistral": ("mistral/mistral-large-latest", ("MISTRAL_API_KEY",)),
    "ollama": ("ollama/llama3.1", ()),
    "openai": ("openai/gpt-5.5", ("OPENAI_API_KEY",)),
    "openrouter": ("openrouter/openai/gpt-5.5", ("OPENROUTER_API_KEY",)),
}

EXPECTED_ENGINES = {
    "claude",
    "codex",
    "litellm",
    *LITELLM_PROVIDER_ENGINE_EXPECTATIONS,
}


def test_registry_loads_known_engines() -> None:
    engines = registry.load_engines()

    assert set(engines) == EXPECTED_ENGINES
    assert engines["codex"].default_model == "gpt-5.5"
    assert engines["claude"].default_model == "opus"
    assert engines["gemini"].default_model == "gemini/gemini-2.5-pro"
    assert engines["gemini"].required_python_module == "litellm"
    assert engines["gemini"].required_env_vars == ("GOOGLE_API_KEY",)
    assert engines["gemini"].execution_status == "shell-dispatch"
    assert engines["litellm"].required_python_module == "litellm"
    assert engines["litellm"].required_env_vars == ()
    assert engines["litellm"].execution_status == "shell-dispatch"


def test_codex_and_claude_default_model_overrides_flow_through_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAINSPRING_DEFAULT_CODEX_MODEL", "gpt-fixture-frontier")
    monkeypatch.setenv("MAINSPRING_DEFAULT_CLAUDE_MODEL", "claude-fixture-opus")

    engines = registry.load_engines()

    assert engines["codex"].default_model == "gpt-fixture-frontier"
    assert engines["claude"].default_model == "claude-fixture-opus"


def test_mainspring_default_model_env_names_ignore_legacy_registry_aliases(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MAINSPRING_DEFAULT_CODEX_MODEL", "gpt-main-frontier")
    monkeypatch.setenv(f"{LEGACY_ENV_PREFIX}DEFAULT_CODEX_MODEL", "gpt-legacy-frontier")
    monkeypatch.setenv("MAINSPRING_DEFAULT_CLAUDE_MODEL", "claude-main-opus")
    monkeypatch.setenv(
        f"{LEGACY_ENV_PREFIX}DEFAULT_CLAUDE_MODEL",
        "claude-legacy-opus",
    )

    engines = registry.load_engines()

    assert engines["codex"].default_model == "gpt-main-frontier"
    assert engines["claude"].default_model == "claude-main-opus"
    assert capsys.readouterr().err == ""


def test_legacy_default_model_registry_aliases_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        f"{LEGACY_ENV_PREFIX}DEFAULT_CODEX_MODEL", "gpt-fixture-frontier"
    )
    monkeypatch.setenv(
        f"{LEGACY_ENV_PREFIX}DEFAULT_CLAUDE_MODEL",
        "claude-fixture-opus",
    )

    engines = registry.load_engines()
    registry.load_engines()

    assert engines["codex"].default_model == "gpt-5.5"
    assert engines["claude"].default_model == "opus"
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("engine_name", "default_model", "required_env_vars"),
    [
        (name, default_model, required_env_vars)
        for name, (default_model, required_env_vars) in sorted(
            LITELLM_PROVIDER_ENGINE_EXPECTATIONS.items()
        )
    ],
)
def test_registry_loads_litellm_provider_engines(
    engine_name: str,
    default_model: str,
    required_env_vars: tuple[str, ...],
) -> None:
    engines = registry.load_engines()

    assert engines[engine_name].default_model == default_model
    assert engines[engine_name].required_python_module == "litellm"
    assert engines[engine_name].required_env_vars == required_env_vars
    assert engines[engine_name].execution_status == "shell-dispatch"


def test_registry_scan_excludes_registry_module() -> None:
    assert "registry" not in registry._iter_engine_module_names()


def test_registry_fails_closed_on_malformed_engine_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "_iter_engine_module_names", lambda: ["broken"])
    monkeypatch.setattr(
        registry.importlib,
        "import_module",
        lambda name: SimpleNamespace(ADAPTER=SimpleNamespace(info=object())),
    )

    with pytest.raises(RuntimeError, match="ADAPTER.info as EngineInfo"):
        registry.load_adapters()


def test_registry_wraps_engine_import_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "_iter_engine_module_names", lambda: ["broken"])

    def fail_import(name: str) -> object:
        raise ImportError(f"{name} exploded")

    monkeypatch.setattr(registry.importlib, "import_module", fail_import)

    with pytest.raises(RuntimeError, match="failed to import engine module"):
        registry.load_adapters()


def test_registry_loads_adapters() -> None:
    adapters = registry.load_adapters()

    assert set(adapters) == EXPECTED_ENGINES
    assert adapters["codex"].info.default_model == "gpt-5.5"
    assert adapters["claude"].info.default_model == "opus"
    assert adapters["grok"].info.default_model == "xai/grok-4.20-reasoning"
    assert adapters["grok"].info.required_python_module == "litellm"
    assert adapters["grok"].info.required_env_vars == ("XAI_API_KEY",)
    assert adapters["grok"].info.execution_status == "shell-dispatch"


def test_inventory_reports_availability_shape() -> None:
    rows = registry.engine_inventory()

    names = {row["name"] for row in rows}
    assert names == EXPECTED_ENGINES
    for row in rows:
        assert "available" in row
        assert "binary_path" in row
        assert "python_module_available" in row
        assert "environment_configured" in row
        assert "missing_env_vars" in row
        assert row["supported_roles"] == ["writer", "reviewer"]


def test_cli_json_outputs_registered_engines() -> None:
    env = os.environ.copy()
    for _, required_env_vars in LITELLM_PROVIDER_ENGINE_EXPECTATIONS.values():
        for env_var in required_env_vars:
            env.pop(env_var, None)
    result = subprocess.run(
        [sys.executable, SCRIPT, "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    names = {row["name"] for row in payload["engines"]}
    assert names == EXPECTED_ENGINES
    for engine_name, (
        _,
        required_env_vars,
    ) in LITELLM_PROVIDER_ENGINE_EXPECTATIONS.items():
        row = next(row for row in payload["engines"] if row["name"] == engine_name)
        assert row["execution_status"] == "shell-dispatch"
        assert row["required_python_module"] == "litellm"
        assert row["required_env_vars"] == list(required_env_vars)
        for env_var in required_env_vars:
            assert env_var in row["missing_env_vars"]
    litellm = next(row for row in payload["engines"] if row["name"] == "litellm")
    assert litellm["required_python_module"] == "litellm"
    assert litellm["required_env_vars"] == []


def test_cli_text_names_execution_status() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Mainspring engine inventory" in result.stdout
    assert "gemini" in result.stdout
    assert "openrouter" in result.stdout
    assert "execution=shell-dispatch" in result.stdout
    assert "litellm" in result.stdout
    assert "module=litellm:" in result.stdout
    assert "env=GOOGLE_API_KEY:" in result.stdout
    assert "env=OPENROUTER_API_KEY:" in result.stdout


def test_inventory_text_includes_provider_setup_remediation() -> None:
    old_editable_provider_install = "python3.13 -m pip install -e '." + "[providers]'"
    text = registry.format_inventory_text(
        [
            {
                "name": "gemini",
                "display_name": "Google Gemini",
                "binary": "python3",
                "default_model": "gemini/gemini-2.5-pro",
                "required_python_module": "litellm",
                "required_env_vars": ["GOOGLE_API_KEY"],
                "supported_roles": ["writer", "reviewer"],
                "execution_status": "shell-dispatch",
                "quota_status": "unknown",
                "notes": "",
                "available": True,
                "binary_path": "/usr/bin/python3",
                "python_module_available": False,
                "environment_configured": False,
                "missing_env_vars": ["GOOGLE_API_KEY"],
            }
        ]
    )

    assert "setup: python module litellm not installed for engine gemini" in text
    assert "install provider extras with Python 3.11-3.13" in text
    assert "MAINSPRING_PROVIDERS_PYTHON=python3.13 make install-user-providers" in text
    assert old_editable_provider_install not in text
    assert "setup: environment variable GOOGLE_API_KEY is not set" in text
    assert "export GOOGLE_API_KEY=<provider API key>" in text


def test_inventory_text_includes_generic_module_remediation() -> None:
    text = registry.format_inventory_text(
        [
            {
                "name": "custom",
                "display_name": "Custom",
                "binary": "custom-bin",
                "default_model": "custom-model",
                "required_python_module": "custom_module",
                "required_env_vars": [],
                "supported_roles": ["writer"],
                "execution_status": "shell-dispatch",
                "quota_status": "unknown",
                "notes": "experimental",
                "available": False,
                "binary_path": None,
                "python_module_available": False,
                "environment_configured": None,
                "missing_env_vars": [],
            }
        ]
    )

    assert "custom: missing (custom-bin)" in text
    assert "note: experimental" in text
    assert "setup: python module custom_module not installed for engine custom" in text
    assert "install Python module custom_module" in text


def test_build_codex_command_uses_reasoning_and_model() -> None:
    command = registry.build_command(
        "codex",
        prompt="Ship it",
        role="writer",
        model="gpt-5.5",
        reasoning_effort="xhigh",
    )

    assert command.display_mode == "plain"
    assert command.argv == (
        "codex",
        "exec",
        "--ignore-user-config",
        "--yolo",
        "-c",
        "features.codex_hooks=false",
        "-c",
        'model_reasoning_effort="xhigh"',
        "-m",
        "gpt-5.5",
        "Ship it",
    )


def test_codex_adapter_usage_quota_and_failure_classification() -> None:
    adapter = codex.ADAPTER

    assert adapter.parse_usage("tokens=10") == {}
    assert adapter.quota_snapshot() == {}
    assert adapter.detect_failure(0, "").failed is False
    assert adapter.detect_failure(141, "broken pipe").failed is False

    quota = adapter.detect_failure(1, "Rate limit reached")
    assert quota.failed is True
    assert quota.reason == "engine:quota"
    assert quota.detail == "Rate limit reached"

    nonzero = adapter.detect_failure(2, "  crashed  ")
    assert nonzero.failed is True
    assert nonzero.reason == "engine:exit_nonzero"
    assert nonzero.detail == "crashed"


def test_build_codex_command_auto_model_omits_model_flag() -> None:
    command = registry.build_command(
        "codex",
        prompt="Ship it",
        role="writer",
        model="auto",
        reasoning_effort="high",
    )

    assert "-m" not in command.argv
    assert command.argv[-1] == "Ship it"


def test_build_claude_command_uses_stream_json_display() -> None:
    command = registry.build_command(
        "claude",
        prompt="Review it",
        role="reviewer",
        model="opus",
        reasoning_effort="xhigh",
    )

    assert command.display_mode == "stream-json"
    assert command.argv[:7] == (
        "claude",
        "-p",
        "--dangerously-skip-permissions",
        "--verbose",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
    )
    assert command.argv[-3:] == ("--model", "opus", "Review it")


def test_claude_adapter_usage_quota_and_failure_classification() -> None:
    adapter = claude.ADAPTER

    assert adapter.parse_usage("tokens=10") == {}
    assert adapter.quota_snapshot() == {}
    assert adapter.detect_failure(0, "").failed is False
    assert adapter.detect_failure(141, "broken pipe").failed is False

    quota = adapter.detect_failure(1, "quota exceeded")
    assert quota.failed is True
    assert quota.reason == "engine:quota"
    assert quota.detail == "quota exceeded"

    nonzero = adapter.detect_failure(2, "  failed  ")
    assert nonzero.failed is True
    assert nonzero.reason == "engine:exit_nonzero"
    assert nonzero.detail == "failed"


def test_build_gemini_command_routes_to_litellm_runner() -> None:
    command = registry.build_command("gemini", prompt="Ship it", role="writer")

    assert command.display_mode == "plain"
    assert command.argv[0] == sys.executable
    assert command.argv[1].endswith("litellm_runner.py")
    assert command.argv[-6:] == (
        "--model",
        "gemini/gemini-2.5-pro",
        "--role",
        "writer",
        "--prompt",
        "Ship it",
    )


def test_build_grok_command_routes_to_litellm_runner() -> None:
    command = registry.build_command(
        "grok",
        prompt="Review it",
        role="reviewer",
        model="xai/grok-4",
    )

    assert command.display_mode == "plain"
    assert command.argv[0] == sys.executable
    assert command.argv[1].endswith("litellm_runner.py")
    assert command.argv[-6:] == (
        "--model",
        "xai/grok-4",
        "--role",
        "reviewer",
        "--prompt",
        "Review it",
    )


@pytest.mark.parametrize(
    ("engine_name", "default_model"),
    [
        (name, default_model)
        for name, (default_model, _) in sorted(
            LITELLM_PROVIDER_ENGINE_EXPECTATIONS.items()
        )
        if name not in {"gemini", "grok"}
    ],
)
def test_build_provider_command_routes_to_litellm_runner(
    engine_name: str,
    default_model: str,
) -> None:
    command = registry.build_command(engine_name, prompt="Ship it", role="writer")

    assert command.display_mode == "plain"
    assert command.argv[0] == sys.executable
    assert command.argv[1].endswith("litellm_runner.py")
    assert command.argv[-6:] == (
        "--model",
        default_model,
        "--role",
        "writer",
        "--prompt",
        "Ship it",
    )


def test_build_litellm_command_routes_to_python_runner() -> None:
    command = registry.build_command(
        "litellm",
        prompt="Ship it",
        role="writer",
        model="gemini/gemini-2.5-pro",
    )

    assert command.display_mode == "plain"
    assert command.argv[0] == sys.executable
    assert command.argv[1].endswith("litellm_runner.py")
    assert command.argv[-6:] == (
        "--model",
        "gemini/gemini-2.5-pro",
        "--role",
        "writer",
        "--prompt",
        "Ship it",
    )


def test_build_command_rejects_unknown_engine() -> None:
    with pytest.raises(ValueError, match="unknown engine"):
        registry.build_command("missing", prompt="Ship it", role="writer")


def test_build_command_rejects_unsupported_role() -> None:
    with pytest.raises(ValueError, match="does not support role"):
        registry.build_command("codex", prompt="Ship it", role="operator")


def test_build_command_rejects_non_executable_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = registry.EngineInfo(
        name="registered-only",
        display_name="Registered Only",
        binary="registered-only",
        default_model="model",
        execution_status="planned",
    )
    adapter = SimpleNamespace(info=info)
    monkeypatch.setattr(registry, "get_adapter", lambda name: adapter)

    with pytest.raises(ValueError, match="execution_status=planned"):
        registry.build_command("registered-only", prompt="Ship it", role="writer")


def test_validate_engine_checks_required_python_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = registry.EngineInfo(
        name="requires-module",
        display_name="Requires Module",
        binary="python3",
        default_model="test-model",
        required_python_module="missing_module",
    )
    monkeypatch.setattr(registry, "get_engine", lambda name: info)
    monkeypatch.setattr(registry.shutil, "which", lambda binary: "/usr/bin/python3")
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: None)

    with pytest.raises(ValueError, match="missing_module not installed"):
        registry.validate_engine(
            "requires-module",
            require_executable=True,
            require_execution=True,
        )


def test_validate_engine_accepts_present_required_python_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = registry.EngineInfo(
        name="requires-module",
        display_name="Requires Module",
        binary="python3",
        default_model="test-model",
        required_python_module="present_module",
    )
    monkeypatch.setattr(registry, "get_engine", lambda name: info)
    monkeypatch.setattr(registry.shutil, "which", lambda binary: "/usr/bin/python3")
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: object())

    registry.validate_engine(
        "requires-module",
        require_executable=True,
        require_execution=True,
    )


def test_validate_engine_checks_required_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = registry.EngineInfo(
        name="requires-env",
        display_name="Requires Env",
        binary="python3",
        default_model="test-model",
        required_python_module="present_module",
        required_env_vars=("PROVIDER_API_KEY",),
    )
    monkeypatch.delenv("PROVIDER_API_KEY", raising=False)
    monkeypatch.setattr(registry, "get_engine", lambda name: info)
    monkeypatch.setattr(registry.shutil, "which", lambda binary: "/usr/bin/python3")
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: object())

    with pytest.raises(
        ValueError,
        match="environment variable PROVIDER_API_KEY is not set",
    ):
        registry.validate_engine(
            "requires-env",
            require_executable=True,
            require_execution=True,
        )


def test_validate_engine_accepts_present_required_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = registry.EngineInfo(
        name="requires-env",
        display_name="Requires Env",
        binary="python3",
        default_model="test-model",
        required_python_module="present_module",
        required_env_vars=("PROVIDER_API_KEY",),
    )
    monkeypatch.setenv("PROVIDER_API_KEY", "configured")
    monkeypatch.setattr(registry, "get_engine", lambda name: info)
    monkeypatch.setattr(registry.shutil, "which", lambda binary: "/usr/bin/python3")
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: object())

    registry.validate_engine(
        "requires-env",
        require_executable=True,
        require_execution=True,
    )


def test_validate_litellm_model_checks_provider_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(registry.shutil, "which", lambda binary: "/usr/bin/python3")
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: object())

    with pytest.raises(
        ValueError,
        match="environment variable GOOGLE_API_KEY is not set",
    ):
        registry.validate_engine(
            "litellm",
            role="writer",
            model="gemini/gemini-2.5-pro",
            require_executable=True,
            require_execution=True,
        )


def test_validate_litellm_model_accepts_provider_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "configured")
    monkeypatch.setattr(registry.shutil, "which", lambda binary: "/usr/bin/python3")
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: object())

    registry.validate_engine(
        "litellm",
        role="reviewer",
        model="xai/grok-4",
        require_executable=True,
        require_execution=True,
    )


@pytest.mark.parametrize(
    ("model", "env_vars"),
    [
        ("openai/gpt-4o", ("OPENAI_API_KEY",)),
        ("anthropic/claude-sonnet-4-20250514", ("ANTHROPIC_API_KEY",)),
        ("gemini/gemini-2.5-pro", ("GOOGLE_API_KEY",)),
        ("xai/grok-4", ("XAI_API_KEY",)),
        ("openrouter/openai/gpt-4o", ("OPENROUTER_API_KEY",)),
        ("mistral/mistral-large-latest", ("MISTRAL_API_KEY",)),
        (
            "azure/gpt-4o-prod",
            ("AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION"),
        ),
    ],
)
def test_validate_litellm_model_checks_common_provider_env_vars(
    model: str,
    env_vars: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for env_var in env_vars:
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setattr(registry.shutil, "which", lambda binary: "/usr/bin/python3")
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: object())

    with pytest.raises(ValueError) as excinfo:
        registry.validate_engine(
            "litellm",
            role="writer",
            model=model,
            require_executable=True,
            require_execution=True,
        )

    message = str(excinfo.value)
    for env_var in env_vars:
        assert env_var in message


@pytest.mark.parametrize(
    ("model", "env_vars"),
    [
        ("openai/gpt-4o", ("OPENAI_API_KEY",)),
        ("anthropic/claude-sonnet-4-20250514", ("ANTHROPIC_API_KEY",)),
        ("gemini/gemini-2.5-pro", ("GOOGLE_API_KEY",)),
        ("xai/grok-4", ("XAI_API_KEY",)),
        ("openrouter/openai/gpt-4o", ("OPENROUTER_API_KEY",)),
        ("mistral/mistral-large-latest", ("MISTRAL_API_KEY",)),
        (
            "azure/gpt-4o-prod",
            ("AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION"),
        ),
    ],
)
def test_validate_litellm_model_accepts_common_provider_env_vars(
    model: str,
    env_vars: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for env_var in env_vars:
        monkeypatch.setenv(env_var, "configured")
    monkeypatch.setattr(registry.shutil, "which", lambda binary: "/usr/bin/python3")
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: object())

    registry.validate_engine(
        "litellm",
        role="writer",
        model=model,
        require_executable=True,
        require_execution=True,
    )


def test_validate_litellm_ollama_model_does_not_require_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry.shutil, "which", lambda binary: "/usr/bin/python3")
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: object())

    registry.validate_engine(
        "litellm",
        role="writer",
        model="ollama/llama3.1",
        require_executable=True,
        require_execution=True,
    )


@pytest.mark.parametrize(
    ("engine_name", "required_env_vars"),
    [
        (name, required_env_vars)
        for name, (_, required_env_vars) in sorted(
            LITELLM_PROVIDER_ENGINE_EXPECTATIONS.items()
        )
        if required_env_vars
    ],
)
def test_validate_provider_engine_checks_declared_env_vars(
    engine_name: str,
    required_env_vars: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for env_var in required_env_vars:
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setattr(registry.shutil, "which", lambda binary: "/usr/bin/python3")
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: object())

    with pytest.raises(ValueError) as excinfo:
        registry.validate_engine(
            engine_name,
            role="writer",
            require_executable=True,
            require_execution=True,
        )

    message = str(excinfo.value)
    for env_var in required_env_vars:
        assert env_var in message


def test_validate_provider_engine_reports_all_remediation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_editable_provider_install = "python3.13 -m pip install -e '." + "[providers]'"
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(registry.shutil, "which", lambda binary: "/usr/bin/python3")
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: None)

    with pytest.raises(ValueError) as excinfo:
        registry.validate_engine(
            "gemini",
            role="writer",
            require_executable=True,
            require_execution=True,
        )

    message = str(excinfo.value)
    assert "python module litellm not installed for engine gemini" in message
    assert "install provider extras with Python 3.11-3.13" in message
    assert (
        "MAINSPRING_PROVIDERS_PYTHON=python3.13 make install-user-providers" in message
    )
    assert old_editable_provider_install not in message
    assert "environment variable GOOGLE_API_KEY is not set for engine gemini" in message
    assert "export GOOGLE_API_KEY=<provider API key>" in message


def test_validate_ollama_provider_engine_does_not_require_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry.shutil, "which", lambda binary: "/usr/bin/python3")
    monkeypatch.setattr(registry.importlib.util, "find_spec", lambda name: object())

    registry.validate_engine(
        "ollama",
        role="writer",
        require_executable=True,
        require_execution=True,
    )


def test_readiness_errors_reports_unknown_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "get_adapter", lambda name: None)
    monkeypatch.setattr(registry, "get_engine", lambda name: None)

    assert registry.readiness_errors("missing") == ["unknown engine: missing"]


def test_readiness_errors_reports_missing_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = registry.EngineInfo(
        name="missing-binary",
        display_name="Missing Binary",
        binary="missing-binary",
        default_model="model",
    )
    adapter = SimpleNamespace(info=info)
    monkeypatch.setattr(registry, "get_adapter", lambda name: adapter)
    monkeypatch.setattr(registry.shutil, "which", lambda binary: None)

    errors = registry.readiness_errors("missing-binary", require_executable=True)

    assert errors == [
        "missing-binary not found in PATH for engine missing-binary; install missing-binary and ensure it is on PATH"
    ]


def test_cli_command_json_outputs_adapter_command() -> None:
    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "command",
            "--engine",
            "claude",
            "--role",
            "writer",
            "--prompt",
            "Hello",
            "--model",
            "opus",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["display_mode"] == "stream-json"
    assert payload["argv"][-3:] == ["--model", "opus", "Hello"]


def test_cli_command_nul_preserves_multiline_prompt(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Line 1\nLine 2\tTabbed", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "command",
            "--engine",
            "codex",
            "--role",
            "writer",
            "--prompt-file",
            str(prompt_file),
            "--model",
            "auto",
            "--format",
            "nul",
        ],
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    records = result.stdout.split(b"\0")
    assert records[0] == b"display_mode=plain"
    assert records[-2] == b"Line 1\nLine 2\tTabbed"


def test_cmd_command_text_outputs_shell_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = registry._cmd_command(
        [
            "--engine",
            "codex",
            "--role",
            "writer",
            "--prompt",
            "Hello world",
            "--model",
            "auto",
            "--format",
            "text",
        ]
    )

    assert exit_code == 0
    assert "codex exec" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "requires --engine"),
        (["--engine", "codex"], "requires --prompt-file or --prompt"),
        (
            ["--engine", "codex", "--prompt", "Hello", "--format", "yaml"],
            "--format must be json, text, or nul",
        ),
        (["--engine"], "Unknown or incomplete flag"),
    ],
)
def test_cmd_command_usage_errors(
    args: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert registry._cmd_command(args) == 2
    assert message in capsys.readouterr().err


def test_cli_validate_accepts_provider_execution_status() -> None:
    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "validate",
            "--engine",
            "gemini",
            "--role",
            "writer",
            "--require-execution",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0


def test_cli_default_model() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "default-model", "gemini"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "gemini/gemini-2.5-pro"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "Usage: engine_registry.py default-model <engine>"),
        (["missing"], "unknown engine: missing"),
    ],
)
def test_cmd_default_model_usage_errors(
    args: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert registry._cmd_default_model(args) == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "validate requires --engine"),
        (["--engine"], "Unknown or incomplete flag"),
        (["--engine", "missing"], "unknown engine: missing"),
    ],
)
def test_cmd_validate_usage_errors(
    args: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert registry._cmd_validate(args) == 2
    assert message in capsys.readouterr().err


def test_classify_failure_detects_quota_tail() -> None:
    failure = registry.classify_failure(
        "codex",
        exit_code=1,
        raw_tail="Rate limit exceeded for this model",
    )

    assert failure["failed"] is True
    assert failure["reason"] == "engine:quota"


def test_classify_failure_treats_zero_as_ok() -> None:
    failure = registry.classify_failure("claude", exit_code=0, raw_tail="")

    assert failure == {"failed": False, "reason": "", "detail": ""}


def test_cli_failure_reason_from_tail_file(tmp_path: Path) -> None:
    tail = tmp_path / "tail.txt"
    tail.write_text("Quota exhausted\nTry later", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "failure",
            "--engine",
            "claude",
            "--exit-code",
            "1",
            "--raw-tail-file",
            str(tail),
            "--format",
            "reason",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "engine:quota"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "failure requires --engine"),
        (["--engine", "codex"], "failure requires --exit-code"),
        (
            ["--engine", "codex", "--exit-code", "0", "--format", "yaml"],
            "--format must be json, reason, or text",
        ),
        (["--engine"], "Unknown or incomplete flag"),
        (["--engine", "missing", "--exit-code", "1"], "unknown engine: missing"),
    ],
)
def test_cmd_failure_usage_errors(
    args: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert registry._cmd_failure(args) == 2
    assert message in capsys.readouterr().err


def test_cmd_failure_text_outputs_failed_detail(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = registry._cmd_failure(
        [
            "--engine",
            "codex",
            "--exit-code",
            "1",
            "--raw-tail",
            "rate limit exceeded",
            "--format",
            "text",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.startswith("engine:quota:")


def test_cmd_failure_text_outputs_ok_for_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = registry._cmd_failure(
        ["--engine", "claude", "--exit-code", "0", "--format", "text"]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "ok"


def test_cli_failure_rejects_bad_exit_code() -> None:
    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "failure",
            "--engine",
            "codex",
            "--exit-code",
            "nope",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--exit-code must be an integer" in result.stderr


def test_main_help_and_unknown_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert registry.main(["--help"]) == 0
    assert "Usage: mainspring engines" in capsys.readouterr().out

    assert registry.main(["--bogus"]) == 2
    assert "Unknown argument: --bogus" in capsys.readouterr().err
