# SPDX-License-Identifier: Apache-2.0
"""Producer-reachable quota classification using owned paths and guarded imports."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import urllib.request
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)


@pytest.fixture
def offline(tmp_path):
    owned_home = tmp_path / "owned-session-root"
    owned_home.mkdir()
    owned_bin = tmp_path / "owned-bin"
    owned_bin.mkdir()
    for name in ("codex", "claude", "python3"):
        path = owned_bin / name
        path.write_text("synthetic non-executed adapter marker\n")
        path.chmod(0o700)
    ledger = tmp_path / "owned-empty-ledger.jsonl"
    ledger.write_text("")
    visible = {"codex", "claude", "python3"}
    original_which = shutil.which
    forbidden_calls = []

    def only_owned_binary(command, *_args, **_kwargs):
        if command not in visible:
            return None
        return original_which(command, path=str(owned_bin))

    def no_external_calls(*_args, **_kwargs):
        forbidden_calls.append("unexpected process or network call")
        raise AssertionError(
            "external operation forbidden in synthetic quota classification tests"
        )

    def missing_optional_module(name, *_args, **_kwargs):
        assert name == "litellm", name

    with ExitStack() as stack:
        # Swap the child process's mapping without reading or changing host values.
        stack.enter_context(patch.object(os, "environ", {}))
        stack.enter_context(patch.object(Path, "home", return_value=owned_home))
        stack.enter_context(patch.object(shutil, "which", only_owned_binary))
        stack.enter_context(
            patch.object(importlib.util, "find_spec", missing_optional_module)
        )
        for name in ("run", "Popen", "call", "check_call", "check_output"):
            stack.enter_context(patch.object(subprocess, name, no_external_calls))
        stack.enter_context(patch.object(os, "system", no_external_calls))
        stack.enter_context(
            patch.object(socket, "create_connection", no_external_calls)
        )
        stack.enter_context(patch.object(socket, "socket", no_external_calls))
        stack.enter_context(patch.object(socket, "getaddrinfo", no_external_calls))
        stack.enter_context(patch.object(urllib.request, "urlopen", no_external_calls))
        consumer = importlib.import_module("limits")
        producer = importlib.import_module("engine_quota")
        registry = importlib.import_module("engines.registry")
        for module in (consumer, producer, registry):
            assert (
                Path(module.__file__).resolve().is_relative_to((ROOT / "py").resolve())
            )
        adapter = registry.get_adapter("codex")
        assert type(adapter).__name__ == "CodexAdapter"
        assert adapter.quota_snapshot() == {}
        case = SimpleNamespace(
            consumer=consumer,
            producer=producer,
            registry=registry,
            home=owned_home,
            ledger=ledger,
            visible=visible,
            folder=tmp_path,
            forbidden_calls=forbidden_calls,
        )
        yield case
        assert not forbidden_calls


def session(case, *, used=25.0):
    folder = case.home / ".codex/sessions"
    folder.mkdir(parents=True)
    raw = {
        "payload": {
            "rate_limits": {
                "primary": {"used_percent": used, "window_minutes": 300},
                "secondary": {"used_percent": 50.0, "window_minutes": 10080},
                "plan_type": "synthetic-plan",
            }
        },
    }
    (folder / "owned-session.jsonl").write_text(json.dumps(raw) + "\n")


def render(case, engine="codex"):
    # Both producer and report functions are the exact supplied code, unmocked.
    snapshot = case.producer.engine_snapshot(engine)
    payload = case.consumer.build_limits(
        engine_names=[engine],
        ledger_path=case.ledger,
        now=NOW,
    )
    row = payload["engines"][0]
    text = case.consumer.format_text(payload)
    proof = {
        "snapshot": snapshot,
        "row": row,
        "text": text,
        "registered_adapters": list(case.registry.load_engines()),
        "codex_adapter_return": case.registry.get_adapter("codex").quota_snapshot(),
        "ledger_path": str(case.ledger),
        "external_calls": case.forbidden_calls,
    }
    (case.folder / "proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    return snapshot, row, text


@pytest.mark.parametrize("layout", ["missing", "empty", "no-rate-limits"])
def test_unknown_codex_fallback_source_is_not_a_local_signal(offline, layout):
    folder = offline.home / ".codex/sessions"
    if layout != "missing":
        folder.mkdir(parents=True)
    if layout == "no-rate-limits":
        (folder / "owned-no-quota.jsonl").write_text(
            '{"type":"synthetic","payload":{}}\n'
        )
    snapshot, row, text = render(offline)
    quota = snapshot["quota"]
    assert snapshot["available"] is True
    assert quota["source"] == "codex_sessions"
    assert quota["status"] == quota["plan"] == "unknown"
    assert all(
        quota[name]["remaining_pct"] is None and quota[name]["reset"] == "unknown"
        for name in ("short", "long")
    )
    assert row["readiness_blockers"] == []
    assert row["status"] == "adapter-only"
    assert row["quota_source"] == "codex_sessions"
    assert "credentials/quota not proven" in row["status_reason"]
    assert "note: adapter visible; credentials/quota not proven" in text


def test_owned_session_measurement_remains_ready(offline):
    session(offline, used=25.0)
    snapshot, row, _text = render(offline)
    assert snapshot["quota"]["short"]["remaining_pct"] == 75.0
    assert row["status"] == "ready" and row["readiness_blockers"] == []


def test_short_exhaustion_precedence_remains_throttled(offline):
    session(offline, used=100.0)
    _snapshot, row, _text = render(offline)
    assert row["short"]["remaining_pct"] == 0.0
    assert row["status"] == "throttled"
    assert row["status_reason"] == "short-window quota is exhausted"


def test_missing_binary_still_precedes_exhaustion(offline):
    session(offline, used=100.0)
    offline.visible.remove("codex")
    snapshot, row, _text = render(offline)
    assert snapshot["available"] is False
    assert row["status"] == "not-configured"
    assert any(
        "codex not found in PATH" in value for value in row["readiness_blockers"]
    )


def test_claude_without_probe_remains_adapter_only(offline):
    snapshot, row, _text = render(offline, "claude")
    assert snapshot["quota"]["source"] == "missing"
    assert row["status"] == "adapter-only"


def test_registered_provider_blockers_remain_not_configured(offline):
    snapshot, row, _text = render(offline, "openai")
    assert snapshot["available"] is True
    assert row["status"] == "not-configured"
    assert any("litellm" in value for value in row["readiness_blockers"])
    assert any("OPENAI_API_KEY" in value for value in row["readiness_blockers"])


def test_owned_primary_only_remaining_is_a_readiness_signal(offline):
    folder = offline.home / ".codex/sessions"
    folder.mkdir(parents=True)
    raw = {
        "payload": {
            "rate_limits": {
                "primary": {"used_percent": 25.0, "window_minutes": 300},
            }
        }
    }
    (folder / "owned-primary-only.jsonl").write_text(json.dumps(raw) + "\n")

    snapshot, row, _text = render(offline)

    quota = snapshot["quota"]
    assert quota["short"]["remaining_pct"] == 75.0
    assert quota["long"]["remaining_pct"] is None
    assert quota["status"] == quota["plan"] == "unknown"
    assert quota["short"]["reset"] == quota["long"]["reset"] == "unknown"
    assert row["short"]["remaining_pct"] == 75.0
    assert row["long"]["remaining_pct"] is None
    assert row["quota_status"] == row["plan"] == "unknown"
    assert row["short"]["reset"] == row["long"]["reset"] == "unknown"
    assert row["status"] == "ready" and row["readiness_blockers"] == []
