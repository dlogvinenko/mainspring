# SPDX-License-Identifier: Apache-2.0
"""Exercise the exact FNM consumer with owned producer and helper stubs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fnm_env import ALLOWED_FNM_KEYS

ROOT = Path(__file__).resolve().parents[2]
INITIAL_PATH = "/synthetic/base"
SENTINEL = "unchanged synthetic value"


def extract():
    text = (ROOT / "mainspring.sh").read_text()
    start = text.index("mainspring_load_fnm_env_json() {\n")
    end = text.index("\n}\n", start) + 3
    function = text[start:end]
    start = text.index("if ! mainspring_load_fnm_env_json; then\n", end)
    end = text.index("\nfi\n", start) + 4
    fallback = text[start:end]
    fallback = fallback.replace(
        "if ! mainspring_load_fnm_env_json; then",
        "if mainspring_load_fnm_env_json; then\n  NATIVE_LOAD_RC=0\nelse\n  NATIVE_LOAD_RC=$?\n  NATIVE_FALLBACK_USED=true",
    ).replace('"$HOME"', '"$NATIVE_FALLBACK_ROOT"')
    return function, fallback


SHELL = r"""
set -euo pipefail
source "$1"
MAINSPRING_PY_DIR="$2"; NATIVE_PYTHON="$3"; NATIVE_JSON="$4"
NATIVE_MODE="$5"; NATIVE_HELPER_RC="$6"; NATIVE_PRODUCER_RC="$7"
NATIVE_MULTISHELL="$8"; NATIVE_FALLBACK_ROOT="$9"; NATIVE_CALLS="${10}"
fnm() {
  [ "$*" = 'env --json' ] || return 90
  printf 'synthetic-fnm\n' >> "$NATIVE_CALLS"
  printf '%s\n' "$NATIVE_JSON"
  return "$NATIVE_PRODUCER_RC"
}
python3() {
  if [ "$NATIVE_MODE" = prefix-failure ]; then
    IFS= read -r NATIVE_UNUSED_INPUT || true
    printf 'MAINSPRING_FNM_BIN=%s/bin\nFNM_MULTISHELL_PATH=%s\n' "$NATIVE_MULTISHELL" "$NATIVE_MULTISHELL"
    return "$NATIVE_HELPER_RC"
  fi
  "$NATIVE_PYTHON" -B "$@"
}
for NATIVE_KEY in FNM_COREPACK_ENABLED FNM_NODE_DIST_MIRROR FNM_VERSION_FILE_STRATEGY FNM_RESOLVE_ENGINES FNM_ARCH FNM_MULTISHELL_PATH FNM_DIR FNM_LOGLEVEL; do
  export "$NATIVE_KEY=unchanged synthetic value"
done
NATIVE_FALLBACK_USED=false
"""
REPORT = r"""
"$NATIVE_PYTHON" -B -c 'import json,os,sys; print(json.dumps({"load_rc":int(sys.argv[1]),"fallback":sys.argv[2],"bash_version":sys.argv[3],"values":{key:os.environ.get(key) for key in sys.argv[4:]}}))' "$NATIVE_LOAD_RC" "$NATIVE_FALLBACK_USED" "$BASH_VERSION" PATH UNRELATED FNM_COREPACK_ENABLED FNM_NODE_DIST_MIRROR FNM_VERSION_FILE_STRATEGY FNM_RESOLVE_ENGINES FNM_ARCH FNM_MULTISHELL_PATH FNM_DIR FNM_LOGLEVEL
"""


def shell(tmp_path, case, *, helper_rc=0, producer_rc=0):
    multishell = tmp_path / "multishell space=back\\slash"
    (multishell / "bin").mkdir(parents=True)
    fallback_root = tmp_path / "owned-fallback-root"
    for version in ("v1", "v2"):
        (
            fallback_root
            / ".local/share/fnm/node-versions"
            / version
            / "installation/bin"
        ).mkdir(parents=True)
    payload = {key: " value = literal\\tail " + key + " " for key in ALLOWED_FNM_KEYS}
    payload["FNM_MULTISHELL_PATH"] = str(multishell) + "\r\n"
    payload["FNM_DIR"] = "dir\r\nwith\nlines=\\literal "
    payload.update(PATH="/not-allowed", UNRELATED="not-allowed")
    mode, raw = "actual-helper", json.dumps(payload)
    if case == "malformed":
        raw = "{not-json"
    elif case == "nonobject":
        raw = "[]"
    elif case == "missing-multishell":
        del payload["FNM_MULTISHELL_PATH"]
        raw = json.dumps(payload)
    elif case == "missing-directory":
        payload["FNM_MULTISHELL_PATH"] = str(tmp_path / "missing-owned-directory")
        raw = json.dumps(payload)
    elif case == "prefix-failure":
        mode = case
    else:
        assert case == "normal"
    function, fallback = extract()
    function_file = tmp_path / "consumer.sh"
    function_file.write_text(function)
    calls = tmp_path / "calls"
    calls.write_text("")
    command = [
        "/bin/bash",
        "--noprofile",
        "--norc",
        "-c",
        SHELL + fallback + "\n" + REPORT,
        "isolated-fnm",
        str(function_file),
        str(ROOT / "py"),
        sys.executable,
        raw,
        mode,
        str(helper_rc),
        str(producer_rc),
        str(multishell),
        str(fallback_root),
        str(calls),
    ]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        cwd=tmp_path,
        env={"PATH": INITIAL_PATH},
    )
    assert result.returncode == 0, result.stderr
    assert calls.read_text().splitlines() == ["synthetic-fnm"]
    report = json.loads(result.stdout)
    report["case"] = case
    report["helper_rc"] = helper_rc
    report["producer_rc"] = producer_rc
    report["stderr"] = result.stderr
    (tmp_path / "proof.json").write_text(json.dumps(report, indent=2) + "\n")
    fallback_bin = fallback_root / ".local/share/fnm/node-versions/v1/installation/bin"
    return report, payload, multishell, fallback_bin


@pytest.mark.parametrize(
    "case",
    ["normal", "malformed", "nonobject", "missing-multishell", "missing-directory"],
)
def test_baseline_normal_and_fallback_contract(tmp_path, case):
    report, payload, multishell, fallback_bin = shell(tmp_path, case)
    values = report["values"]
    assert values["UNRELATED"] is None
    assert not report["stderr"]
    if case == "normal":
        assert report["load_rc"] == 0 and report["fallback"] == "false"
        assert values["PATH"] == str(multishell / "bin") + ":" + INITIAL_PATH
    else:
        assert report["load_rc"] == 1 and report["fallback"] == "true"
        assert values["PATH"] == str(fallback_bin) + ":" + INITIAL_PATH
    for key in ALLOWED_FNM_KEYS:
        expected = (
            SENTINEL
            if case in ("malformed", "nonobject") or key not in payload
            else payload[key].replace("\r", "").replace("\n", "")
        )
        assert values[key] == expected


def test_baseline_successful_helper_keeps_existing_producer_status_behavior(tmp_path):
    report, _payload, multishell, _fallback = shell(tmp_path, "normal", producer_rc=9)
    assert report["load_rc"] == 0 and report["fallback"] == "false"
    assert report["values"]["PATH"] == str(multishell / "bin") + ":" + INITIAL_PATH


@pytest.mark.parametrize("helper_rc", [7, 130])
def test_helper_failure_cannot_commit_valid_prefix(tmp_path, helper_rc):
    report, _payload, _multishell, fallback_bin = shell(
        tmp_path, "prefix-failure", helper_rc=helper_rc
    )
    assert report["load_rc"] == 1
    assert report["fallback"] == "true"
    assert report["values"]["PATH"] == str(fallback_bin) + ":" + INITIAL_PATH
    assert all(report["values"][key] == SENTINEL for key in ALLOWED_FNM_KEYS)
