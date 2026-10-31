# SPDX-License-Identifier: Apache-2.0
"""Offline actual CLI driver: synthetic registry/adapter/filesystem only."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

casefile = Path(sys.argv[1])
target = Path(sys.argv[2])
case = json.loads(casefile.read_text())
info = SimpleNamespace(
    display_name="Codex",
    binary="codex",
    default_model="synthetic",
    execution_status="shell-dispatch",
)
registry = ModuleType("engines.registry")
registry.get_engine = lambda name: info if name == "codex" else None
registry.get_adapter = lambda _name: None
package = ModuleType("engines")
package.__path__ = []
sys.modules["engines"] = package
sys.modules["engines.registry"] = registry
spec = importlib.util.spec_from_file_location("_offline_engine_quota", target)
quota = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quota)
quota.shutil.which = lambda _name: (
    "/synthetic/bin/engine" if case.get("binary_available", False) else None
)
home = Path(case.get("synthetic_home", str(casefile.parent / "unused-synthetic-home")))
quota.Path.home = classmethod(lambda cls: home)
mode = case.get("mode", "adapter")
if mode == "adapter":

    class Adapter:
        def quota_snapshot(self):
            return case["adapter"]

    quota.get_adapter = lambda _name: Adapter()
    quota.codex_quota_line = lambda: (
        "Codex|short_remaining=unknown|short_window=5h|short_reset=unknown|long_remaining=unknown|long_window=7d|long_reset=unknown|plan=unknown"
    )
    quota.main(["--engine", "codex", "--format", case.get("format", "json")])
elif mode == "codex":
    quota.get_adapter = lambda _name: None
    quota.main(
        ["codex"]
        if case.get("legacy", False)
        else ["--engine", "codex", "--format", case.get("format", "json")]
    )
elif mode == "claude":
    quota.main(["claude", case["synthetic_probe"]])
else:
    raise AssertionError("unknown synthetic mode")
