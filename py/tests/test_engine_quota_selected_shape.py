# SPDX-License-Identifier: Apache-2.0
"""Selected malformed legacy quota maps must not become attribute errors."""

import pytest

from .test_engine_quota_native import _home, _run, _strict


@pytest.mark.parametrize("bad", ["used_percent", [{"used_percent": 20}]])
def test_selected_nonobject_rate_limits_stays_unknown(tmp_path, bad):
    home = _home(tmp_path, {}, whole=bad)
    result = _run(tmp_path, {"mode": "codex", "synthetic_home": str(home)})
    assert result.returncode == 0, result.stderr
    payload = _strict(result.stdout)
    assert payload["quota"]["short"]["remaining_pct"] is None
    assert payload["quota"]["long"]["remaining_pct"] is None
