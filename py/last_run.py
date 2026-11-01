# SPDX-License-Identifier: Apache-2.0
"""Safe last-run settings persistence for Mainspring.

Subcommands:
    save    Read setting values from env vars, emit safe KEY=VALUE lines.
    load    Read an env file or `.mainspring.yaml`, emit KEY<TAB>VALUE lines.

Usage:
    python3 last_run.py save          # reads env, prints to stdout
    python3 last_run.py load <path>   # reads .env or YAML, prints KEY<TAB>VALUE

Never ``source`` settings directly — this module parses values safely.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from datetime import datetime
from pathlib import Path

from cli_runtime import run_cli

ALLOWED_KEYS = frozenset(
    {
        "MODE",
        "PAIR_MODE",
        "ENGINE",
        "MODEL_OVERRIDE",
        "REVIEW_ENGINE",
        "REVIEW_MODEL_OVERRIDE",
        "CODEX_REASONING_EFFORT",
        "SPEED_PROFILE",
        "MAX_AGENTS",
        "AUTO_RETRY_CI",
        "AUTO_RETRY_CI_LOG",
        "AGENT_MODE",
        "TOPOLOGY",
        "RUN_ONCE",
        "PRD_PATH",
        "AUTO_CHECKPOINT",
    }
)

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "config.schema.json"
KEY_ALIASES = {
    "mode": "MODE",
    "pair_mode": "PAIR_MODE",
    "pair-mode": "PAIR_MODE",
    "engine": "ENGINE",
    "model_override": "MODEL_OVERRIDE",
    "model-override": "MODEL_OVERRIDE",
    "review_engine": "REVIEW_ENGINE",
    "review-engine": "REVIEW_ENGINE",
    "review_model_override": "REVIEW_MODEL_OVERRIDE",
    "review-model-override": "REVIEW_MODEL_OVERRIDE",
    "codex_reasoning_effort": "CODEX_REASONING_EFFORT",
    "codex-reasoning-effort": "CODEX_REASONING_EFFORT",
    "speed_profile": "SPEED_PROFILE",
    "speed-profile": "SPEED_PROFILE",
    "max_agents": "MAX_AGENTS",
    "max-agents": "MAX_AGENTS",
    "auto_retry_ci": "AUTO_RETRY_CI",
    "auto-retry-ci": "AUTO_RETRY_CI",
    "auto_retry_ci_log": "AUTO_RETRY_CI_LOG",
    "auto-retry-ci-log": "AUTO_RETRY_CI_LOG",
    "agent_mode": "AGENT_MODE",
    "agent-mode": "AGENT_MODE",
    "topology": "TOPOLOGY",
    "run_once": "RUN_ONCE",
    "run-once": "RUN_ONCE",
    "prd_path": "PRD_PATH",
    "prd-path": "PRD_PATH",
    "auto_checkpoint": "AUTO_CHECKPOINT",
    "auto-checkpoint": "AUTO_CHECKPOINT",
}


def _is_yaml_path(path: Path) -> bool:
    return path.suffix.lower() in {".yaml", ".yml"}


def _normalize_key(raw_key: str) -> str | None:
    if raw_key in ALLOWED_KEYS:
        return raw_key
    return KEY_ALIASES.get(raw_key.strip().lower())


def _load_schema() -> dict[str, object] | None:
    if not SCHEMA_PATH.is_file():
        return None
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _strip_yaml_comment(value: str) -> str:
    quote = value[0] if value and value[0] in {"'", '"'} else None
    index = 1 if quote else 0
    while quote and index < len(value):
        char = value[index]
        if quote == '"' and char == "\\":
            index += 2
            continue
        if char == quote:
            if quote == "'" and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            quote = None
        index += 1
    if quote:
        return value
    for pos in range(index, len(value)):
        if value[pos] == "#" and (pos == 0 or value[pos - 1].isspace()):
            return value[:pos].rstrip()
    return value


def _load_yaml(raw: str) -> dict[str, str]:
    # Minimal, non-nested YAML parser: top-level KEY: VALUE only.
    # This is intentionally narrow and safe for config file use.
    payload: dict[str, object] = {}
    for lineno, raw_line in enumerate(raw.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if raw_line[:1] in {" ", "\t"}:
            raise ValueError(f"line {lineno}: nested YAML is not supported")
        if ":" not in line:
            raise ValueError(f"line {lineno}: missing ':'")
        raw_key, raw_value = line.split(":", 1)
        key = raw_key.strip()
        value = raw_value.strip()
        if not key:
            raise ValueError(f"line {lineno}: missing key")
        value = _strip_yaml_comment(value)
        if not value:
            payload[key] = ""
            continue
        low = value.lower()
        if low == "true":
            payload[key] = True
            continue
        if low == "false":
            payload[key] = False
            continue
        if (
            value
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
            and len(value) >= 2
        ):
            payload[key] = value[1:-1]
            continue
        if re.fullmatch(r"-?\d+", value):
            payload[key] = int(value)
            continue
        if re.fullmatch(r"-?\d+\.\d+", value):
            payload[key] = float(value)
            continue
        if (value.startswith("{") and value.endswith("}")) or (
            value.startswith("[") and value.endswith("]")
        ):
            try:
                json.loads(value)
                raise ValueError(
                    f"line {lineno}: nested YAML/JSON values are not supported"
                )
            except json.JSONDecodeError:
                pass
        payload[key] = value
    return _normalize_yaml_payload(payload)


def _normalize_yaml_payload(payload: dict[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_key, raw_value in payload.items():
        key = _normalize_key(raw_key)
        if key is None:
            key = raw_key
        if isinstance(raw_value, bool):
            normalized[key] = "true" if raw_value else "false"
        else:
            normalized[key] = str(raw_value)
    return normalized


def _validate_schema(
    payload: dict[str, str], schema: dict[str, object] | None
) -> list[str]:
    if schema is None:
        return []
    errors: list[str] = []
    additional = schema.get("additionalProperties", True)
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    if not additional:
        for key in payload:
            if key not in properties:
                errors.append(f"unknown property: {key}")

    for key in required:
        if key not in payload:
            errors.append(f"missing required property: {key}")

    for key, value in payload.items():
        spec = properties.get(key, {})
        if not isinstance(spec, dict):
            continue
        spec_type = spec.get("type")
        if spec_type == "string" and not isinstance(value, str):
            errors.append(f"{key} must be a string")
            continue
        if spec_type == "integer":
            try:
                as_int = int(value)
            except (TypeError, ValueError):
                errors.append(f"{key} must be an integer")
                continue
            minimum = spec.get("minimum")
            maximum = spec.get("maximum")
            if minimum is not None and as_int < minimum:
                errors.append(f"{key} must be >= {minimum}")
            if maximum is not None and as_int > maximum:
                errors.append(f"{key} must be <= {maximum}")
        if spec_type == "boolean":
            if value not in {"true", "false"}:
                errors.append(f"{key} must be true/false")
                continue
        if "enum" in spec:
            allowed = list(spec["enum"])
            if value not in map(str, allowed):
                quoted = ", ".join(map(str, allowed))
                errors.append(f"{key} must be one of: {quoted}")
    return errors


def _old_multiline_record_end(lines: list[str], start: int, value: str) -> int | None:
    """Contain only complete multiline values in the old writer's exact quote form."""
    if not value.startswith("'"):
        return None
    combined = value
    for end in range(start, len(lines)):
        combined += "\n" + lines[end]
        try:
            parts = shlex.split(combined, posix=True)
        except ValueError:
            continue
        if len(parts) == 1 and "\n" in parts[0] and shlex.quote(parts[0]) == combined:
            return end + 1
        return None
    return None


def _load_env_raw(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        index += 1
        match = re.match(r"^([A-Z_]+)=(.*)$", raw.strip())
        if not match:
            continue
        key, raw_value = match.groups()
        if key not in ALLOWED_KEYS:
            continue
        try:
            parts = shlex.split(raw_value, posix=True)
        except ValueError:
            exact = re.match(r"^([A-Z_]+)=(.*)$", raw.lstrip())
            end = (
                _old_multiline_record_end(lines, index, exact.group(2))
                if exact
                else None
            )
            if end is not None:
                index = end
            continue
        if len(parts) != 1:
            continue
        loaded[key] = parts[0]
    return loaded


def cmd_save() -> None:
    """Emit KEY=<shell-quoted-value> lines for all allowed keys from env."""
    values = {key: os.environ.get(key, "") for key in sorted(ALLOWED_KEYS)}
    for key, value in values.items():
        if any(char in value for char in "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"):
            print(
                f"Cannot save {key}: record separators are unsupported.",
                file=sys.stderr,
            )
            raise SystemExit(2)
    for key, value in values.items():
        print(f"{key}={shlex.quote(value)}")


def load_settings(path: Path) -> dict[str, str]:
    """Parse a settings file into validated key/value pairs."""
    is_yaml = _is_yaml_path(path)
    if is_yaml:
        try:
            loaded = _load_yaml(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print("Configuration validation failed:", file=sys.stderr)
            print(f"- {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    else:
        loaded = _load_env_raw(path)

    errors = _validate_schema(loaded, _load_schema() if is_yaml else None)
    if errors:
        print("Configuration validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        raise SystemExit(2)
    return {key: value for key, value in loaded.items() if key in ALLOWED_KEYS}


def cmd_load(path_str: str) -> None:
    """Parse a settings file and emit KEY\\tVALUE lines."""
    for key, value in load_settings(Path(path_str)).items():
        print(f"{key}\t{value}")


def _display(value: str | None, fallback: str = "default") -> str:
    value = (value or "").strip()
    return value if value else fallback


def _run_style(settings: dict[str, str]) -> str:
    return "one-shot" if settings.get("RUN_ONCE") == "true" else "continuous loop"


def _pair(settings: dict[str, str]) -> str:
    pair = settings.get("PAIR_MODE") or ""
    if pair:
        return pair
    writer = settings.get("ENGINE") or "default"
    reviewer = settings.get("REVIEW_ENGINE") or "default"
    return f"{writer}+{reviewer}"


def _saved_at(path: Path) -> str:
    try:
        return (
            datetime.fromtimestamp(path.stat().st_mtime)
            .astimezone()
            .isoformat(timespec="seconds")
        )
    except OSError:
        return "unknown"


def _show_payload(
    path: Path, project: str, settings: dict[str, str]
) -> dict[str, object]:
    project_path = project or os.getcwd()
    project_q = shlex.quote(project_path)
    return {
        "project": project_path,
        "settings_file": str(path),
        "saved_at": _saved_at(path),
        "settings": settings,
        "summary": {
            "mode": _display(settings.get("MODE"), "taskmaster"),
            "topology": _display(settings.get("TOPOLOGY"), "solo"),
            "pair": _pair(settings),
            "writer": _display(settings.get("ENGINE")),
            "writer_model": _display(settings.get("MODEL_OVERRIDE")),
            "reviewer": _display(settings.get("REVIEW_ENGINE")),
            "reviewer_model": _display(settings.get("REVIEW_MODEL_OVERRIDE")),
            "writer_mode": _display(settings.get("AGENT_MODE"), "code"),
            "speed": _display(settings.get("SPEED_PROFILE"), "max"),
            "agents": _display(settings.get("MAX_AGENTS"), "6"),
            "run": _run_style(settings),
            "prd": _display(settings.get("PRD_PATH"), "none"),
            "ci_retry": _display(settings.get("AUTO_RETRY_CI"), "0"),
            "ci_log": _display(settings.get("AUTO_RETRY_CI_LOG"), "none"),
            "auto_checkpoint": _display(settings.get("AUTO_CHECKPOINT"), "true"),
        },
        "commands": {
            "resume_here": "mainspring --last-run",
            "resume_anywhere": f"mainspring --project {project_q} --last-run",
            "preview_here": "mainspring --last-run --dry-run",
            "preview_anywhere": f"mainspring --project {project_q} --last-run --dry-run",
        },
    }


def _show_usage(stream=sys.stdout) -> None:
    print(
        """Mainspring Last Run

Shows the saved setup for this project without launching work.

Use it when you want to see how Mainspring last ran here, then either repeat
that setup or preview it before starting agents again.

Usage:
  mainspring last-run [--format text|json]
  mainspring --last-run
  mainspring --last-run --dry-run

Output includes:
  settings file, saved timestamp, mode, topology, pair, writer/reviewer models,
  speed, agent count, Product Requirements Document (PRD) path, CI retry
  settings, and exact repeat/preview commands.""",
        file=stream,
    )


def cmd_show(path_str: str, args: list[str]) -> None:
    """Print a human-readable or JSON summary of saved last-run settings."""
    path = Path(path_str)
    project = ""
    output_format = "text"
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--project" and index + 1 < len(args):
            project = args[index + 1]
            index += 2
        elif arg == "--format" and index + 1 < len(args):
            output_format = args[index + 1]
            index += 2
        elif arg == "--json":
            output_format = "json"
            index += 1
        elif arg in {"--help", "-h"}:
            _show_usage()
            return
        else:
            print(f"Unknown show option: {arg}", file=sys.stderr)
            raise SystemExit(2)

    if output_format not in {"text", "json"}:
        print("show --format must be text or json", file=sys.stderr)
        raise SystemExit(2)
    if not path.is_file():
        print(f"No last-run settings found at {path}", file=sys.stderr)
        print(
            "Run `mainspring` once, or use explicit flags for the first run.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    payload = _show_payload(path, project, load_settings(path))
    if output_format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    summary = payload["summary"]
    commands = payload["commands"]
    assert isinstance(summary, dict)
    assert isinstance(commands, dict)
    print("Mainspring Last Run")
    print(f"Project:       {payload['project']}")
    print(f"Settings file: {payload['settings_file']}")
    print(f"Saved:         {payload['saved_at']}")
    print("")
    print(f"Mode:          {summary['mode']}")
    print(f"Topology:      {summary['topology']}")
    print(f"Pair:          {summary['pair']}")
    print(f"Writer:        {summary['writer']} ({summary['writer_model']})")
    print(f"Reviewer:      {summary['reviewer']} ({summary['reviewer_model']})")
    print(f"Writer mode:   {summary['writer_mode']}")
    print(f"Speed:         {summary['speed']}")
    print(f"Agents:        {summary['agents']}")
    print(f"Run:           {summary['run']}")
    print(f"PRD:           {summary['prd']}")
    print(f"CI retry:      {summary['ci_retry']}")
    print(f"CI log:        {summary['ci_log']}")
    print(f"Checkpoint:    {summary['auto_checkpoint']}")
    print("")
    print("Repeat:")
    print(f"  {commands['resume_here']}")
    print(f"  {commands['resume_anywhere']}")
    print("Preview:")
    print(f"  {commands['preview_here']}")
    print(f"  {commands['preview_anywhere']}")


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: last_run.py <save|load> [args]", file=sys.stderr)
        raise SystemExit(2)

    subcmd = args[0]
    if subcmd == "save":
        cmd_save()
    elif subcmd == "load":
        if len(args) < 2:
            print("Usage: last_run.py load <path>", file=sys.stderr)
            raise SystemExit(2)
        cmd_load(args[1])
    elif subcmd == "show":
        if len(args) < 2:
            print(
                "Usage: last_run.py show <path> [--project path] [--format text|json]",
                file=sys.stderr,
            )
            raise SystemExit(2)
        cmd_show(args[1], args[2:])
    else:
        print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    run_cli(main)
