# SPDX-License-Identifier: Apache-2.0
"""Owned subprocess parity and tracing-observability controls."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from . import test_coverage_gate as canonical

HERE = Path(__file__).resolve().parent
coverage_gate = canonical.coverage_gate


_NATIVE_CONTRACT_PROBE = r"""
import importlib.util,json,os,subprocess,sys
from pathlib import Path
payload=json.loads(sys.argv[1])
sys.path.insert(0,str(Path(payload["source"]).parent))
spec=importlib.util.spec_from_file_location("coverage_gate",payload["source"])
gate=importlib.util.module_from_spec(spec);sys.modules[spec.name]=gate;spec.loader.exec_module(gate)
folder=Path(payload["folder"]);folder.mkdir(parents=True,exist_ok=True)
inside=folder/"inside";inside.mkdir()
helper=folder/"helper.py";helper.write_text(payload["body"])
command=[sys.executable,str(helper),"synthetic-arg"]
opts=payload["options"]
if opts.pop("_synthetic_env_cwd",False):
    opts["env"]={"SYNTHETIC_GATE_ENV":"synthetic-value"};opts["cwd"]=str(inside)
old=Path.cwd()
def value(x):
    return {"kind":"bytes","hex":x.hex()} if isinstance(x,bytes) else {"kind":"text","value":x} if isinstance(x,str) else None
def call(fn):
    try:
        result=fn(command,**opts)
        return {"kind":"completed","returncode":result.returncode,"args":result.args,"stdout":value(result.stdout),"stderr":value(result.stderr)}
    except subprocess.TimeoutExpired as error:
        return {"kind":"TimeoutExpired","cmd":error.cmd,"timeout":error.timeout}
    except subprocess.CalledProcessError as error:
        return {"kind":"CalledProcessError","cmd":error.cmd,"returncode":error.returncode,"stdout":value(error.stdout),"stderr":value(error.stderr)}
    except (UnicodeError,LookupError,subprocess.SubprocessError) as error:
        return {"kind":type(error).__name__}
original=subprocess.run
in_process_calls=0
original_helper=gate._run_python_script_in_process
def counted_helper(*args,**kwargs):
    global in_process_calls
    in_process_calls+=1
    return original_helper(*args,**kwargs)
gate._run_python_script_in_process=counted_helper
expected=call(original)
reference_cwd=Path.cwd()==old
with gate._trace_python_subprocesses(folder):
    actual=call(subprocess.run)
actual_cwd=Path.cwd()==old
os.chdir(old)
print(json.dumps({"case":payload["case"],"genuine":expected,"intercepted":actual,"genuine_parent_cwd_preserved":reference_cwd,"intercepted_parent_cwd_preserved":actual_cwd,"contract_match":expected==actual and reference_cwd==actual_cwd,"in_process_calls":in_process_calls}))

"""

_NATIVE_CONTRACT_CASES = json.loads(r"""
[
  {
    "case": "control_supported",
    "body": "import os,sys\nfrom pathlib import Path\nprint(sys.argv[1])\nprint(os.environ[\"SYNTHETIC_GATE_ENV\"])\nprint(Path.cwd().name)\nprint(\"synthetic-err\",file=sys.stderr)\n",
    "options": {
      "capture_output": true,
      "text": true,
      "check": true,
      "_synthetic_env_cwd": true
    },
    "expected_in_process_calls": 1
  },
  {
    "case": "control_bytes",
    "body": "import sys\nsys.stdout.buffer.write(b\"a\\r\\nb\\rc\\n\\x00\")\nsys.stderr.buffer.write(b\"err\\x00\")\n",
    "options": {
      "capture_output": true
    },
    "expected_in_process_calls": 1
  },
  {
    "case": "control_check",
    "body": "print(\"before-error\")\nraise SystemExit(7)\n",
    "options": {
      "capture_output": true,
      "text": true,
      "check": true
    },
    "expected_in_process_calls": 1
  },
  {
    "case": "timeout",
    "body": "import time\ntime.sleep(0.25)\nprint(\"late-output\")\n",
    "options": {
      "capture_output": true,
      "text": true,
      "timeout": 0.05
    },
    "expected_in_process_calls": 0
  },
  {
    "case": "cwd_success",
    "body": "import os\nfrom pathlib import Path\nos.chdir(Path(__file__).parent/\"inside\")\nprint(\"changed\")\n",
    "options": {
      "capture_output": true,
      "text": true
    },
    "expected_in_process_calls": 1
  },
  {
    "case": "cwd_check_error",
    "body": "import os\nfrom pathlib import Path\nos.chdir(Path(__file__).parent/\"inside\")\nprint(\"changed\")\nraise SystemExit(7)\n",
    "options": {
      "capture_output": true,
      "text": true,
      "check": true
    },
    "expected_in_process_calls": 1
  },
  {
    "case": "newline_text",
    "body": "import sys\nsys.stdout.buffer.write(b\"a\\r\\nb\\rc\\n\")\nsys.stderr.buffer.write(b\"x\\r\\ny\\rz\\n\")\n",
    "options": {
      "capture_output": true,
      "text": true
    },
    "expected_in_process_calls": 1
  },
  {
    "case": "newline_universal",
    "body": "import sys\nsys.stdout.buffer.write(b\"a\\r\\nb\\rc\\n\")\n",
    "options": {
      "capture_output": true,
      "universal_newlines": true
    },
    "expected_in_process_calls": 1
  },
  {
    "case": "encoding",
    "body": "import sys\nsys.stdout.buffer.write(b\"\\xe9\\r\\n\")\n",
    "options": {
      "capture_output": true,
      "encoding": "latin-1"
    },
    "expected_in_process_calls": 0
  },
  {
    "case": "errors",
    "body": "import sys\nsys.stdout.buffer.write(b\"\\xff\\r\\n\")\n",
    "options": {
      "capture_output": true,
      "errors": "replace"
    },
    "expected_in_process_calls": 0
  },
  {
    "case": "bad_encoding",
    "body": "print(\"synthetic\")\n",
    "options": {
      "capture_output": true,
      "encoding": "invalid-synthetic-codec"
    },
    "expected_in_process_calls": 0
  },
  {
    "case": "conflicting_text_flags",
    "body": "print(\"synthetic\")\n",
    "options": {
      "capture_output": true,
      "text": true,
      "universal_newlines": false
    },
    "expected_in_process_calls": 0
  },
  {
    "case": "explicit_stdout_pipe",
    "body": "import sys\nsys.stdout.buffer.write(b\"a\\r\\nb\\rc\\n\")\nsys.stderr.buffer.write(b\"x\\r\\ny\\rz\\n\")\n",
    "options": {
      "stdout": -1,
      "stderr": null,
      "text": true
    },
    "expected_in_process_calls": 0
  },
  {
    "case": "explicit_stderr_stdout",
    "body": "import sys\nsys.stdout.buffer.write(b\"a\\r\\nb\\rc\\n\")\nsys.stderr.buffer.write(b\"x\\r\\ny\\rz\\n\")\n",
    "options": {
      "stdout": -1,
      "stderr": -2,
      "text": true
    },
    "expected_in_process_calls": 0
  },
  {
    "case": "explicit_both_pipe",
    "body": "import sys\nsys.stdout.buffer.write(b\"a\\r\\nb\\rc\\n\")\nsys.stderr.buffer.write(b\"x\\r\\ny\\rz\\n\")\n",
    "options": {
      "stdout": -1,
      "stderr": -1,
      "text": true
    },
    "expected_in_process_calls": 1
  }
]
""")


@pytest.mark.parametrize("case", _NATIVE_CONTRACT_CASES, ids=lambda item: item["case"])
def test_intercept_matches_genuine_subprocess_contract_in_bounded_child(tmp_path, case):
    env = {
        "PYTHONPATH": str(HERE.parent),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    payload = {
        **case,
        "source": str(Path(coverage_gate.__file__).resolve()),
        "folder": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "-B", "-c", _NATIVE_CONTRACT_PROBE, json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["contract_match"], observed
    assert observed["in_process_calls"] == case["expected_in_process_calls"], observed


@pytest.mark.parametrize(
    ("options", "observed"),
    [
        ({}, True),
        ({"timeout": None}, True),
        ({"timeout": 2}, False),
        ({"encoding": "utf-8"}, False),
        ({"errors": "strict"}, False),
    ],
)
def test_fallback_observability_does_not_weaken_coverage_threshold(
    tmp_path, options, observed
):
    helper = tmp_path / "observability.py"
    helper.write_text("print('synthetic')\n", encoding="utf-8")
    tracer = coverage_gate.trace.Trace(
        count=True,
        trace=False,
        ignoredirs=[sys.prefix, sys.exec_prefix],
    )
    previous_trace = sys.gettrace()
    try:
        with coverage_gate._trace_python_subprocesses(tmp_path):
            result = tracer.runfunc(
                subprocess.run,
                [sys.executable, str(helper)],
                capture_output=True,
                text=True,
                **options,
            )
    finally:
        sys.settrace(previous_trace)
    assert result.returncode == 0 and result.stdout == "synthetic\n"
    covered = coverage_gate.normalize_counts(tracer.results().counts)
    assert bool(covered.get(helper.resolve())) is observed
    report = coverage_gate.summarize_coverage(
        tmp_path,
        covered,
        threshold=coverage_gate.DEFAULT_THRESHOLD,
        pytest_exit_code=0,
    )
    assert report.threshold == 80
    assert report.passed is observed


@pytest.mark.parametrize("exceptional", [False, True])
def test_trace_context_restores_run_identity_on_each_exit(tmp_path, exceptional):
    before = subprocess.run
    try:
        if exceptional:
            with (
                pytest.raises(RuntimeError, match="synthetic context exit"),
                coverage_gate._trace_python_subprocesses(tmp_path),
            ):
                assert subprocess.run is not before
                raise RuntimeError("synthetic context exit")
        else:
            with coverage_gate._trace_python_subprocesses(tmp_path):
                assert subprocess.run is not before
        assert subprocess.run is before
    finally:
        # Keep a failed synthetic mutant from contaminating later test cases.
        subprocess.run = before
