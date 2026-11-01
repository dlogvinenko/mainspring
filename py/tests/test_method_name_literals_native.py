# SPDX-License-Identifier: Apache-2.0
"""Direct synthetic Method name-rendering regressions, without scaffolding."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest

from . import test_method_init as canonical

SYNTHETIC_TEMPLATE = "# {{Project / Scope name}}\n\nOwner: {{Project}}\n"


@pytest.fixture
def method(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = canonical.method_init

    def prohibited(*args: object, **kwargs: object) -> None:
        raise AssertionError("filesystem or external initialization is outside scope")

    for name in (
        "init_project",
        "template_path",
        "candidate_template_paths",
        "_find_taskmaster",
        "_run_taskmaster_init",
    ):
        monkeypatch.setattr(module, name, prohibited)
    return module


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("X{{Project}}", "x-project"),
        ("{{Project}}X", "project-x"),
        ("X{{Project / Scope name}}", "x-project-scope-name"),
        ("X{{Project}}{{Project / Scope name}}", "x-project-project-scope-name"),
        (r"X\1{{Project}}", "x-1-project"),
        ("{{Project}}", "project"),
    ],
)
def test_accepted_marker_name_is_inserted_literally(
    method: ModuleType, name: str, slug: str
) -> None:
    assert method.display_name(name) == name
    assert method.slugify_name(name) == slug
    expected = f"# {name}\n\nOwner: {name}\n".encode()
    assert method.render_template(SYNTHETIC_TEMPLATE, name).encode() == expected


@pytest.mark.parametrize(
    ("raw", "display", "slug"),
    [
        (" Demo \t Feature ", "Demo Feature", "demo-feature"),
        ("Billing  V2", "Billing V2", "billing-v2"),
        ("Caf\u00e9 A", "Caf\u00e9 A", "caf-a"),
        (r"Quoted \1 project", r"Quoted \1 project", "quoted-1-project"),
    ],
)
def test_plain_normalized_names_preserve_exact_fixture_bytes(
    method: ModuleType, raw: str, display: str, slug: str
) -> None:
    assert method.display_name(raw) == display
    assert method.slugify_name(raw) == slug
    expected = f"# {display}\n\nOwner: {display}\n".encode()
    assert method.render_template(SYNTHETIC_TEMPLATE, display).encode() == expected


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("", ""),
        ("No markers: Caf\u00e9\r\n", "No markers: Caf\u00e9\r\n"),
        (
            "{{Project}}{{Project / Scope name}}{{Project}}\r\n",
            "DemoDemoDemo\r\n",
        ),
        (
            "{{project}} {{ Project }} {{Project / Scope name }}\n",
            "{{project}} {{ Project }} {{Project / Scope name }}\n",
        ),
        ("{{{Project}}} {{Project / Scope name}}", "{Demo} Demo"),
    ],
)
def test_only_exact_known_markers_change(
    method: ModuleType, template: str, expected: str
) -> None:
    assert method.render_template(template, "Demo").encode() == expected.encode()


def test_result_reports_the_same_literal_display_name(method: ModuleType) -> None:
    name = method.display_name("X{{Project}}")
    result = method.InitResult(
        ok=True,
        name=name,
        slug=method.slugify_name(name),
        prd_path=Path("owned/docs/x-project/prd.md"),
        runtime_dir=Path("owned/.mainspring"),
        taskmaster_status="synthetic",
    )
    assert result.name == "X{{Project}}"
    assert method._format_result(result).splitlines()[0] == (
        "Mainspring project initialized: X{{Project}}"
    )
