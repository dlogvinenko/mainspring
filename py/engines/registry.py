# SPDX-License-Identifier: Apache-2.0
"""Pure-stdlib engine inventory for Mainspring preflight."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import pkgutil
import shutil
import shlex
import sys
from pathlib import Path

from engines._base import EngineAdapter, EngineCommand, EngineInfo
from engines.litellm_adapter import format_missing_env_vars_message


def _iter_engine_module_names() -> list[str]:
    package_dir = Path(__file__).resolve().parent
    names = []
    for module in pkgutil.iter_modules([str(package_dir)]):
        if module.ispkg or module.name.startswith("_") or module.name == "registry":
            continue
        names.append(module.name)
    return sorted(names)


def load_adapters() -> dict[str, EngineAdapter]:
    """Load all engine adapter modules from this package."""
    adapters: dict[str, EngineAdapter] = {}
    for name in _iter_engine_module_names():
        try:
            module = importlib.import_module(f"engines.{name}")
        except Exception as exc:  # pragma: no cover - exercised by direct tests
            raise RuntimeError(
                f"failed to import engine module engines.{name}: {exc}"
            ) from exc
        adapter = getattr(module, "ADAPTER", None)
        info = getattr(adapter, "info", None)
        if not isinstance(info, EngineInfo):
            raise RuntimeError(
                f"engine module engines.{name} must expose ADAPTER.info as EngineInfo"
            )
        adapters[info.name] = adapter
    return dict(sorted(adapters.items()))


def load_engines() -> dict[str, EngineInfo]:
    """Load all engine metadata modules from this package."""
    return {name: adapter.info for name, adapter in load_adapters().items()}


def get_engine(name: str) -> EngineInfo | None:
    """Return a registered engine by name."""
    return load_engines().get(name)


def get_adapter(name: str) -> EngineAdapter | None:
    """Return a registered engine adapter by name."""
    return load_adapters().get(name)


def engine_inventory() -> list[dict]:
    """Return runtime availability for every registered engine."""
    rows = []
    for info in load_engines().values():
        binary_path = shutil.which(info.binary)
        module_name = info.required_python_module
        module_available = (
            importlib.util.find_spec(module_name) is not None if module_name else None
        )
        missing_env_vars = [
            name for name in info.required_env_vars if not os.environ.get(name)
        ]
        rows.append(
            {
                **info.to_dict(),
                "available": binary_path is not None,
                "binary_path": binary_path,
                "python_module_available": module_available,
                "environment_configured": (
                    None if not info.required_env_vars else not missing_env_vars
                ),
                "missing_env_vars": missing_env_vars,
            }
        )
    return rows


def _inventory_row_info(row: dict) -> EngineInfo:
    """Rebuild enough EngineInfo metadata from an inventory row for messages."""
    return EngineInfo(
        name=str(row.get("name") or ""),
        display_name=str(row.get("display_name") or row.get("name") or ""),
        binary=str(row.get("binary") or ""),
        default_model=str(row.get("default_model") or ""),
        required_python_module=str(row.get("required_python_module") or ""),
        required_env_vars=tuple(row.get("required_env_vars") or ()),
        supported_roles=tuple(row.get("supported_roles") or ("writer", "reviewer")),
        execution_status=str(row.get("execution_status") or ""),
        quota_status=str(row.get("quota_status") or ""),
        notes=str(row.get("notes") or ""),
    )


def _inventory_setup_messages(row: dict) -> list[str]:
    """Return exact setup steps for missing provider-engine prerequisites."""
    info = _inventory_row_info(row)
    messages: list[str] = []
    if info.required_python_module and row.get("python_module_available") is False:
        messages.append(_missing_python_module_message(info))
    missing_env_vars = list(row.get("missing_env_vars") or [])
    if missing_env_vars:
        messages.append(_missing_env_vars_message(info, missing_env_vars))
    return messages


def format_inventory_text(rows: list[dict]) -> str:
    """Render inventory for terminals and doctor-style preflight."""
    lines = ["Mainspring engine inventory"]
    for row in rows:
        availability = "available" if row["available"] else "missing"
        path = row["binary_path"] or row["binary"]
        module_status = ""
        if row.get("required_python_module"):
            module_availability = (
                "available" if row.get("python_module_available") else "missing"
            )
            module_status = (
                f" module={row['required_python_module']}:{module_availability}"
            )
        env_status = ""
        if row.get("required_env_vars"):
            missing_env_vars = row.get("missing_env_vars") or []
            env_availability = "available" if not missing_env_vars else "missing"
            env_status = f" env={','.join(row['required_env_vars'])}:{env_availability}"
        lines.append(
            f"- {row['name']}: {availability} ({path}) "
            f"default={row['default_model']} "
            f"execution={row['execution_status']} "
            f"quota={row['quota_status']}"
            f"{module_status}"
            f"{env_status}"
        )
        if row.get("notes"):
            lines.append(f"  note: {row['notes']}")
        for message in _inventory_setup_messages(row):
            lines.append(f"  setup: {message}")
    return "\n".join(lines)


def build_command(
    engine_name: str,
    *,
    prompt: str,
    role: str,
    model: str = "",
    reasoning_effort: str = "xhigh",
) -> EngineCommand:
    """Build a command through the registered adapter."""
    adapter = get_adapter(engine_name)
    if adapter is None:
        raise ValueError(f"unknown engine: {engine_name}")
    if role not in adapter.info.supported_roles:
        raise ValueError(f"engine {engine_name} does not support role: {role}")
    if adapter.info.execution_status != "shell-dispatch":
        raise ValueError(
            f"engine {engine_name} is registered but "
            f"execution_status={adapter.info.execution_status}"
        )
    return adapter.build_command(
        prompt,
        model=model,
        role=role,
        reasoning_effort=reasoning_effort,
    )


def _missing_binary_message(info: EngineInfo) -> str:
    return (
        f"{info.binary} not found in PATH for engine {info.name}; "
        f"install {info.binary} and ensure it is on PATH"
    )


def _missing_python_module_message(info: EngineInfo) -> str:
    module = info.required_python_module
    if module == "litellm":
        return (
            f"python module {module} not installed for engine {info.name}; "
            "install provider extras with Python 3.11-3.13: "
            "cd /path/to/mainspring && "
            "MAINSPRING_PROVIDERS_PYTHON=python3.13 make install-user-providers"
        )
    return (
        f"python module {module} not installed for engine {info.name}; "
        f"install Python module {module}"
    )


def _missing_env_vars_message(info: EngineInfo, missing_env_vars: list[str]) -> str:
    return format_missing_env_vars_message(f"engine {info.name}", missing_env_vars)


def readiness_errors(
    engine_name: str,
    *,
    role: str = "writer",
    model: str = "",
    require_executable: bool = False,
    require_execution: bool = False,
) -> list[str]:
    """Return all readiness blockers for an engine selection."""
    adapter = get_adapter(engine_name)
    info = adapter.info if adapter is not None else get_engine(engine_name)
    if info is None:
        return [f"unknown engine: {engine_name}"]
    if role not in info.supported_roles:
        return [f"engine {engine_name} does not support role: {role}"]

    errors: list[str] = []
    if require_execution and info.execution_status != "shell-dispatch":
        errors.append(
            f"engine {engine_name} is registered but "
            f"execution_status={info.execution_status}"
        )
    if require_executable and shutil.which(info.binary) is None:
        errors.append(_missing_binary_message(info))
    if (
        require_executable
        and info.required_python_module
        and importlib.util.find_spec(info.required_python_module) is None
    ):
        errors.append(_missing_python_module_message(info))
    if require_executable:
        required_env_vars = info.required_env_vars
        env_method = getattr(adapter, "required_env_vars_for_model", None)
        if callable(env_method):
            required_env_vars = tuple(env_method(model or info.default_model))
        missing_env_vars = [
            name for name in required_env_vars if not os.environ.get(name)
        ]
        if missing_env_vars:
            errors.append(_missing_env_vars_message(info, missing_env_vars))
    return errors


def validate_engine(
    engine_name: str,
    *,
    role: str = "writer",
    model: str = "",
    require_executable: bool = False,
    require_execution: bool = False,
) -> None:
    """Fail loudly when a selected engine cannot run for a requested role."""
    errors = readiness_errors(
        engine_name,
        role=role,
        model=model,
        require_executable=require_executable,
        require_execution=require_execution,
    )
    if errors:
        raise ValueError("\n".join(errors))


def classify_failure(engine_name: str, *, exit_code: int, raw_tail: str = "") -> dict:
    """Classify one engine process result through the adapter."""
    adapter = get_adapter(engine_name)
    if adapter is None:
        raise ValueError(f"unknown engine: {engine_name}")
    return adapter.detect_failure(exit_code, raw_tail).to_dict()


def _read_prompt(prompt_file: str | None, prompt_value: str | None) -> str:
    if prompt_file:
        return Path(prompt_file).read_text(encoding="utf-8")
    return prompt_value or ""


def _cmd_command(args: list[str]) -> int:
    engine_name = ""
    role = "writer"
    model = ""
    prompt_file = None
    prompt_value = None
    reasoning_effort = "xhigh"
    output_format = "json"
    i = 0
    while i < len(args):
        if args[i] == "--engine" and i + 1 < len(args):
            engine_name = args[i + 1]
            i += 2
        elif args[i] == "--role" and i + 1 < len(args):
            role = args[i + 1]
            i += 2
        elif args[i] == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 2
        elif args[i] == "--prompt-file" and i + 1 < len(args):
            prompt_file = args[i + 1]
            i += 2
        elif args[i] == "--prompt" and i + 1 < len(args):
            prompt_value = args[i + 1]
            i += 2
        elif args[i] == "--reasoning-effort" and i + 1 < len(args):
            reasoning_effort = args[i + 1]
            i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            output_format = args[i + 1]
            i += 2
        else:
            print(f"Unknown or incomplete flag: {args[i]}", file=sys.stderr)
            return 2

    if not engine_name:
        print("engine_registry.py command requires --engine", file=sys.stderr)
        return 2
    if prompt_file is None and prompt_value is None:
        print(
            "engine_registry.py command requires --prompt-file or --prompt",
            file=sys.stderr,
        )
        return 2
    if output_format not in {"json", "text", "nul"}:
        print(
            "engine_registry.py command --format must be json, text, or nul",
            file=sys.stderr,
        )
        return 2

    try:
        command = build_command(
            engine_name,
            prompt=_read_prompt(prompt_file, prompt_value),
            role=role,
            model=model,
            reasoning_effort=reasoning_effort,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if output_format == "json":
        print(json.dumps(command.to_dict(), indent=2, sort_keys=True))
    elif output_format == "text":
        print(shlex.join(command.argv))
    else:
        records = [f"display_mode={command.display_mode}", *command.argv]
        sys.stdout.buffer.write(
            b"".join(record.encode("utf-8") + b"\0" for record in records)
        )
    return 0


def _cmd_default_model(args: list[str]) -> int:
    if len(args) != 1:
        print("Usage: engine_registry.py default-model <engine>", file=sys.stderr)
        return 2
    info = get_engine(args[0])
    if info is None:
        print(f"unknown engine: {args[0]}", file=sys.stderr)
        return 2
    print(info.default_model)
    return 0


def _cmd_validate(args: list[str]) -> int:
    engine_name = ""
    role = "writer"
    model = ""
    require_executable = False
    require_execution = False
    i = 0
    while i < len(args):
        if args[i] == "--engine" and i + 1 < len(args):
            engine_name = args[i + 1]
            i += 2
        elif args[i] == "--role" and i + 1 < len(args):
            role = args[i + 1]
            i += 2
        elif args[i] == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 2
        elif args[i] == "--require-executable":
            require_executable = True
            i += 1
        elif args[i] == "--require-execution":
            require_execution = True
            i += 1
        else:
            print(f"Unknown or incomplete flag: {args[i]}", file=sys.stderr)
            return 2
    if not engine_name:
        print("engine_registry.py validate requires --engine", file=sys.stderr)
        return 2
    try:
        validate_engine(
            engine_name,
            role=role,
            model=model,
            require_executable=require_executable,
            require_execution=require_execution,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def _cmd_failure(args: list[str]) -> int:
    engine_name = ""
    exit_code: int | None = None
    raw_tail = ""
    raw_tail_file = None
    output_format = "json"
    i = 0
    while i < len(args):
        if args[i] == "--engine" and i + 1 < len(args):
            engine_name = args[i + 1]
            i += 2
        elif args[i] == "--exit-code" and i + 1 < len(args):
            try:
                exit_code = int(args[i + 1])
            except ValueError:
                print(
                    "engine_registry.py failure --exit-code must be an integer",
                    file=sys.stderr,
                )
                return 2
            i += 2
        elif args[i] == "--raw-tail" and i + 1 < len(args):
            raw_tail = args[i + 1]
            i += 2
        elif args[i] == "--raw-tail-file" and i + 1 < len(args):
            raw_tail_file = args[i + 1]
            i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            output_format = args[i + 1]
            i += 2
        else:
            print(f"Unknown or incomplete flag: {args[i]}", file=sys.stderr)
            return 2
    if not engine_name:
        print("engine_registry.py failure requires --engine", file=sys.stderr)
        return 2
    if exit_code is None:
        print("engine_registry.py failure requires --exit-code", file=sys.stderr)
        return 2
    if output_format not in {"json", "reason", "text"}:
        print(
            "engine_registry.py failure --format must be json, reason, or text",
            file=sys.stderr,
        )
        return 2
    if raw_tail_file:
        raw_tail = Path(raw_tail_file).read_text(encoding="utf-8", errors="replace")
    try:
        failure = classify_failure(engine_name, exit_code=exit_code, raw_tail=raw_tail)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if output_format == "json":
        print(json.dumps(failure, indent=2, sort_keys=True))
    elif output_format == "reason":
        print(failure["reason"] if failure["failed"] else "")
    else:
        if failure["failed"]:
            print(f"{failure['reason']}: {failure['detail']}".rstrip())
        else:
            print("ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    output_json = False
    if args in (["--help"], ["-h"]):
        print(
            "Usage: mainspring engines [--json]\n\n"
            "List registered Mainspring writer/reviewer adapters without "
            "launching a model.\n\n"
            "Shows:\n"
            "  engine key, default model, binary/provider availability,\n"
            "  execution support, quota support, and missing setup.\n\n"
            "Examples:\n"
            "  mainspring engines\n"
            "  mainspring engines --json"
        )
        return 0
    if args and args[0] == "command":
        return _cmd_command(args[1:])
    if args and args[0] == "default-model":
        return _cmd_default_model(args[1:])
    if args and args[0] == "validate":
        return _cmd_validate(args[1:])
    if args and args[0] == "failure":
        return _cmd_failure(args[1:])
    if args == ["--json"]:
        output_json = True
    elif args:
        print(f"Unknown argument: {args[0]}", file=sys.stderr)
        print("Usage: mainspring engines [--json]", file=sys.stderr)
        return 2

    rows = engine_inventory()
    if output_json:
        print(json.dumps({"engines": rows}, indent=2, sort_keys=True))
    else:
        print(format_inventory_text(rows))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
