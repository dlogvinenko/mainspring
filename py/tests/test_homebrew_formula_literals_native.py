# SPDX-License-Identifier: Apache-2.0
"""Owned synthetic Ruby data round-trips, never executing a formula."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from . import test_homebrew_formula as canonical

homebrew_formula = canonical.homebrew_formula

HERE = Path(__file__).resolve().parent

RUBY = shutil.which("ruby")
BASE = {
    "version": "v1.0.0",
    "url": "https://github.com/dlogvinenko/mainspring/archive/refs/tags/v1.0.0.tar.gz",
    "sha256": "0123456789abcdef" * 4,
    "homepage": "https://github.com/dlogvinenko/mainspring",
    "python_dependency": "python@3.11",
}
NORMAL_FORMULA = '# SPDX-License-Identifier: Apache-2.0\nclass Mainspring < Formula\n  include Language::Python::Virtualenv\n\n  desc "PRD-first AI coding agent orchestration"\n  homepage "https://github.com/dlogvinenko/mainspring"\n  url "https://github.com/dlogvinenko/mainspring/archive/refs/tags/v1.0.0.tar.gz"\n  sha256 "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"\n  license "Apache-2.0"\n  version "1.0.0"\n\n  depends_on "bash"\n  depends_on "python@3.11"\n  depends_on "git"\n\n  # Before publishing the tap, run `brew update-python-resources mainspring`\n  # from the tap checkout so rich/litellm transitive resources are vendored.\n\n  def install\n    virtualenv_install_with_resources\n  end\n\n  test do\n    system bin/"mainspring", "doctor"\n  end\nend\n'
SUFFIXES = [
    pytest.param("ordinary", id="ordinary"),
    pytest.param('embedded"quote', id="double-quote"),
    pytest.param('trailing"', id="trailing-quote"),
    pytest.param(r"literal\tsequence", id="literal-backslash-t"),
    pytest.param(r"literal\nsequence", id="literal-backslash-n"),
    pytest.param(r"literal\u0041sequence", id="literal-backslash-u"),
    pytest.param("trailing\\", id="trailing-backslash"),
    pytest.param("#{1+1}", id="braced-interpolation"),
    pytest.param("#@fixture", id="instance-interpolation"),
    pytest.param("#$fixture", id="global-interpolation"),
    pytest.param("#@@fixture", id="class-interpolation"),
    pytest.param(r"literal\#{1+1}", id="backslash-before-interpolation"),
    pytest.param("before\nafter", id="internal-lf"),
    pytest.param("before\r\nafter", id="internal-crlf"),
    pytest.param(
        "before" + "".join(map(chr, range(32))) + "after", id="all-c0-controls"
    ),
    pytest.param("before\x7fafter", id="del"),
    pytest.param("café-日本-🙂", id="non-ascii"),
    pytest.param("before\u0085\u2028after", id="unicode-separators"),
    pytest.param("ordinary#fragment", id="non-interpolating-hash"),
]


def ruby_args() -> list[str]:
    if not RUBY:
        pytest.skip("Ruby is not available for native literal proof")
    return [RUBY, "--disable=gems", "--disable=rubyopt", "-EUTF-8:UTF-8"]


def field_literal(formula: str, field: str) -> str:
    terminator = "\n  url " if field == "homepage" else "\n  sha256 "
    return formula.split(f"  {field} ", 1)[1].split(terminator, 1)[0]


def ruby_literal_value(literal: str) -> str:
    # Only our synthetic literals are evaluated. Formula class/install/test
    # bodies are never executed, and no Homebrew API is loaded.
    script = (
        "class LiteralFixture\n"
        '  @@fixture = "expanded-class"\n'
        "  def self.read\n"
        '    @fixture = "expanded-instance"\n'
        '    $fixture = "expanded-global"\n'
        f"    STDOUT.write(JSON.generate({literal}))\n"
        "  end\n"
        "end\n"
        "LiteralFixture.read\n"
    )
    result = subprocess.run(
        [*ruby_args(), "-rjson", "-"],
        input=script.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return json.loads(result.stdout.decode("utf-8"))


@pytest.mark.parametrize("field", ["url", "homepage"])
@pytest.mark.parametrize("suffix", SUFFIXES)
def test_accepted_metadata_is_literal_ruby_data(field: str, suffix: str) -> None:
    prefix = (
        "https://example.test/project/archive/refs/tags/"
        if field == "url"
        else "https://example.test/"
    )
    value = f" \t{prefix}{suffix}\r\n "
    args = {**BASE, field: value}
    formula = homebrew_formula.build_formula(**args)
    assert ruby_literal_value(field_literal(formula, field)) == value.strip()


def test_ordinary_formula_is_byte_identical() -> None:
    assert homebrew_formula.build_formula(**BASE).encode() == NORMAL_FORMULA.encode()


@pytest.mark.parametrize("field", ["url", "homepage"])
@pytest.mark.parametrize("suffix", ['quote"end', "#{1+1}", "control\r\n\x00end"])
def test_owned_formula_syntax_is_valid(field: str, suffix: str) -> None:
    prefix = (
        "https://example.test/project/archive/refs/tags/"
        if field == "url"
        else "https://example.test/"
    )
    formula = homebrew_formula.build_formula(**{**BASE, field: prefix + suffix})
    result = subprocess.run(
        [*ruby_args(), "-c", "-"],
        input=formula.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")


def test_cli_stdout_preserves_accepted_stripped_metadata(
    capsys: pytest.CaptureFixture[str],
) -> None:
    url = ' \thttps://example.test/project/archive/refs/tags/a"b\\t#{1+1}\r\n'
    homepage = ' \thttps://example.test/#@fixture/#$fixture/quoted"\r\n'
    rc = homebrew_formula.main(
        [
            "--version",
            BASE["version"],
            "--url",
            url,
            "--sha256",
            BASE["sha256"],
            "--homepage",
            homepage,
            "--pyproject",
            str(HERE.parent.parent / "pyproject.toml"),
        ]
    )
    assert rc == 0
    formula = capsys.readouterr().out
    assert ruby_literal_value(field_literal(formula, "url")) == url.strip()
    assert ruby_literal_value(field_literal(formula, "homepage")) == homepage.strip()
