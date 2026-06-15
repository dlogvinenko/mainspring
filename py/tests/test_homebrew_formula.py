# SPDX-License-Identifier: Apache-2.0
"""Tests for Homebrew release formula generation."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import homebrew_formula  # noqa: E402


VALID_SHA = "0123456789abcdef" * 4
VALID_URL = "https://github.com/dlogvinenko/mainspring/archive/refs/tags/v1.0.0.tar.gz"
VALID_HOMEPAGE = "https://github.com/dlogvinenko/mainspring"
VALID_PYTHON_DEPENDENCY = "python@3.11"
PYPROJECT = HERE.parent.parent / "pyproject.toml"
HOMEBREW_RUNBOOK = HERE.parent.parent / "packaging" / "homebrew" / "README.md"


def build_valid_formula() -> str:
    return homebrew_formula.build_formula(
        version="v1.0.0",
        url=VALID_URL,
        sha256=VALID_SHA,
        homepage=VALID_HOMEPAGE,
        python_dependency=VALID_PYTHON_DEPENDENCY,
    )


def test_build_formula_contains_release_and_homebrew_contract() -> None:
    formula = build_valid_formula()

    assert formula.startswith("# SPDX-License-Identifier: Apache-2.0\n")
    assert "class Mainspring < Formula" in formula
    assert "include Language::Python::Virtualenv" in formula
    assert f'homepage "{VALID_HOMEPAGE}"' in formula
    assert f'url "{VALID_URL}"' in formula
    assert f'sha256 "{VALID_SHA}"' in formula
    assert 'license "Apache-2.0"' in formula
    assert 'version "1.0.0"' in formula
    assert 'depends_on "python@3.11"' in formula
    assert 'depends_on "bash"' in formula
    assert 'depends_on "git"' in formula
    assert "=> :recommended" not in formula
    assert "=> :test" not in formula
    assert "brew update-python-resources mainspring" in formula
    assert "virtualenv_install_with_resources" in formula
    assert 'system bin/"mainspring", "doctor"' in formula


def test_formula_desc_stays_within_homebrew_limit() -> None:
    assert (
        len(homebrew_formula.FORMULA_DESC) <= homebrew_formula.HOMEBREW_DESC_MAX_LENGTH
    )
    assert homebrew_formula.FORMULA_DESC == "PRD-first AI coding agent orchestration"
    assert f'desc "{homebrew_formula.FORMULA_DESC}"' in build_valid_formula()


def test_homebrew_runbook_hashes_the_same_archive_used_by_formula() -> None:
    text = HOMEBREW_RUNBOOK.read_text(encoding="utf-8")

    assert (
        "url=https://github.com/dlogvinenko/mainspring/archive/refs/tags/v1.0.0.tar.gz"
        in text
    )
    assert 'curl -fL "$url" -o dist/mainspring-v1.0.0-source.tar.gz' in text
    assert '--url "$url"' in text
    assert "dist/mainspring-v1.0.0-source.tar.gz" in text
    assert "dist/mainspring-1.0.0.tar.gz" not in text


def test_release_metadata_normalizers_accept_publishable_variants() -> None:
    assert homebrew_formula.normalize_version("1.0.0-rc1") == "1.0.0-rc1"
    assert homebrew_formula.validate_sha256(VALID_SHA.upper()) == VALID_SHA
    assert homebrew_formula.validate_url(
        "https://github.com/dlogvinenko/mainspring/releases/download/v1.0.0/mainspring.tar.gz"
    ).endswith("mainspring.tar.gz")


def test_formula_python_dependency_matches_project_requires_python() -> None:
    assert homebrew_formula.python_dependency_from_pyproject(PYPROJECT) == (
        VALID_PYTHON_DEPENDENCY
    )


def test_python_dependency_from_pyproject_accepts_future_floor(
    tmp_path: Path,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "mainspring"\nrequires-python = ">=3.12,<4"\n',
        encoding="utf-8",
    )

    assert homebrew_formula.python_dependency_from_pyproject(pyproject) == "python@3.12"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not toml = [\n", "is not valid TOML"),
        ("[tool.demo]\nname = 'x'\n", "is missing \\[project\\]"),
        ("[project]\nname = 'x'\n", "requires-python"),
    ],
)
def test_python_dependency_from_pyproject_rejects_invalid_project_metadata(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(content, encoding="utf-8")

    with pytest.raises(homebrew_formula.FormulaInputError, match=message):
        homebrew_formula.python_dependency_from_pyproject(pyproject)


def test_python_dependency_from_pyproject_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(homebrew_formula.FormulaInputError, match="does not exist"):
        homebrew_formula.python_dependency_from_pyproject(tmp_path / "missing.toml")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"version": "release"}, "version must look like"),
        ({"url": "http://example.com/mainspring.tar.gz"}, "url must be an https"),
        ({"url": "https://example.com/mainspring.tar.gz"}, "tagged GitHub"),
        ({"sha256": "abc"}, "sha256 must be"),
        ({"homepage": "http://example.com"}, "homepage must be an https"),
        ({"python_dependency": "python3"}, "python dependency must look like"),
    ],
)
def test_build_formula_rejects_unpublishable_inputs(
    kwargs: dict[str, str],
    message: str,
) -> None:
    args = {
        "version": "v1.0.0",
        "url": VALID_URL,
        "sha256": VALID_SHA,
        "homepage": VALID_HOMEPAGE,
        "python_dependency": VALID_PYTHON_DEPENDENCY,
    }
    args.update(kwargs)

    with pytest.raises(homebrew_formula.FormulaInputError, match=message):
        homebrew_formula.build_formula(**args)


def test_validate_desc_rejects_overlong_description() -> None:
    with pytest.raises(homebrew_formula.FormulaInputError, match="characters or fewer"):
        homebrew_formula.validate_desc("x" * 81)


@pytest.mark.parametrize(
    ("requires_python", "message"),
    [
        ("3.11", "requires-python must include"),
        (">=3", "requires-python must include"),
    ],
)
def test_python_dependency_rejects_ambiguous_python_floor(
    requires_python: str,
    message: str,
) -> None:
    with pytest.raises(homebrew_formula.FormulaInputError, match=message):
        homebrew_formula.python_dependency_from_requires_python(requires_python)


def test_cli_writes_formula_file(tmp_path: Path) -> None:
    output = tmp_path / "Formula" / "mainspring.rb"

    rc = homebrew_formula.main(
        [
            "--version",
            "v1.0.0",
            "--url",
            VALID_URL,
            "--sha256",
            VALID_SHA,
            "--homepage",
            VALID_HOMEPAGE,
            "--pyproject",
            str(PYPROJECT),
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    assert output.is_file()
    assert f'url "{VALID_URL}"' in output.read_text(encoding="utf-8")


def test_cli_prints_formula_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    rc = homebrew_formula.main(
        [
            "--version",
            "v1.0.0",
            "--url",
            VALID_URL,
            "--sha256",
            VALID_SHA,
            "--homepage",
            VALID_HOMEPAGE,
            "--pyproject",
            str(PYPROJECT),
        ]
    )

    assert rc == 0
    assert "class Mainspring < Formula" in capsys.readouterr().out


def test_cli_fails_closed_for_invalid_formula_input(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nrequires-python = '>=3.11'\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="homebrew_formula: url must"):
        homebrew_formula.main(
            [
                "--version",
                "v1.0.0",
                "--url",
                "http://example.com/archive.tar.gz",
                "--sha256",
                VALID_SHA,
                "--pyproject",
                str(pyproject),
            ]
        )


def test_generated_formula_has_valid_ruby_syntax_when_ruby_exists(
    tmp_path: Path,
) -> None:
    ruby = shutil.which("ruby")
    if not ruby:
        pytest.skip("ruby is not installed")
    output = tmp_path / "mainspring.rb"
    output.write_text(
        build_valid_formula(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [ruby, "-c", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
