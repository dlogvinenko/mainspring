#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate Homebrew tap formula metadata for Mainspring releases."""

from __future__ import annotations

from cli_runtime import run_cli

import argparse
import re
import tomllib
from pathlib import Path


FORMULA_DESC = "PRD-first AI coding agent orchestration"
HOMEBREW_DESC_MAX_LENGTH = 80
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:[.-][0-9A-Za-z]+)?$")
PYTHON_FLOOR_RE = re.compile(r"(?:^|,)\s*>=\s*(\d+)\.(\d+)(?:\.\d+)?\b")
PYTHON_DEPENDENCY_RE = re.compile(r"^python@\d+\.\d+$")


class FormulaInputError(ValueError):
    """Raised when release metadata is not publishable."""


def normalize_version(version: str) -> str:
    """Return a Homebrew-compatible version string."""
    cleaned = version.strip()
    if not VERSION_RE.match(cleaned):
        raise FormulaInputError(
            "version must look like a SemVer release, for example v1.0.0"
        )
    return cleaned[1:] if cleaned.startswith("v") else cleaned


def validate_url(url: str) -> str:
    """Reject non-release URLs so the formula cannot be generated from a draft."""
    cleaned = url.strip()
    if not cleaned.startswith("https://"):
        raise FormulaInputError("url must be an https release tarball URL")
    if "archive/refs/tags/" not in cleaned and "/releases/download/" not in cleaned:
        raise FormulaInputError(
            "url must point at a tagged GitHub source archive or release asset"
        )
    return cleaned


def validate_sha256(sha256: str) -> str:
    """Return a lowercase sha256 digest or fail before a placeholder ships."""
    cleaned = sha256.strip().lower()
    if not SHA256_RE.match(cleaned):
        raise FormulaInputError("sha256 must be a 64-character lowercase hex digest")
    return cleaned


def validate_desc(desc: str) -> str:
    """Return a Homebrew-compatible short description."""
    cleaned = desc.strip()
    if len(cleaned) > HOMEBREW_DESC_MAX_LENGTH:
        raise FormulaInputError(
            f"desc must be {HOMEBREW_DESC_MAX_LENGTH} characters or fewer"
        )
    return cleaned


def python_dependency_from_requires_python(requires_python: str) -> str:
    """Map pyproject's Python floor to Homebrew's versioned python formula."""
    match = PYTHON_FLOOR_RE.search(requires_python.strip())
    if not match:
        raise FormulaInputError(
            "requires-python must include a >= major.minor floor, for example >=3.11"
        )
    return f"python@{match.group(1)}.{match.group(2)}"


def python_dependency_from_pyproject(pyproject_path: Path) -> str:
    """Read the Python Homebrew dependency from pyproject.toml."""
    try:
        with pyproject_path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise FormulaInputError(f"{pyproject_path} does not exist") from exc
    except tomllib.TOMLDecodeError as exc:
        raise FormulaInputError(f"{pyproject_path} is not valid TOML") from exc

    project = data.get("project")
    if not isinstance(project, dict):
        raise FormulaInputError(f"{pyproject_path} is missing [project]")
    requires_python = project.get("requires-python")
    if not isinstance(requires_python, str):
        raise FormulaInputError(
            f"{pyproject_path} is missing [project].requires-python"
        )
    return python_dependency_from_requires_python(requires_python)


def validate_python_dependency(dependency: str) -> str:
    """Return a versioned Homebrew Python dependency."""
    cleaned = dependency.strip()
    if not PYTHON_DEPENDENCY_RE.match(cleaned):
        raise FormulaInputError(
            "python dependency must look like a Homebrew formula, for example python@3.11"
        )
    return cleaned


def build_formula(
    *,
    version: str,
    url: str,
    sha256: str,
    homepage: str,
    python_dependency: str,
) -> str:
    """Build the Homebrew Ruby formula text from release metadata."""
    formula_version = normalize_version(version)
    formula_url = validate_url(url)
    formula_sha256 = validate_sha256(sha256)
    formula_homepage = homepage.strip()
    if not formula_homepage.startswith("https://"):
        raise FormulaInputError("homepage must be an https URL")
    formula_desc = validate_desc(FORMULA_DESC)
    formula_python_dependency = validate_python_dependency(python_dependency)

    return f'''# SPDX-License-Identifier: Apache-2.0
class Mainspring < Formula
  include Language::Python::Virtualenv

  desc "{formula_desc}"
  homepage "{formula_homepage}"
  url "{formula_url}"
  sha256 "{formula_sha256}"
  license "Apache-2.0"
  version "{formula_version}"

  depends_on "bash"
  depends_on "{formula_python_dependency}"
  depends_on "git"

  # Before publishing the tap, run `brew update-python-resources mainspring`
  # from the tap checkout so rich/litellm transitive resources are vendored.

  def install
    virtualenv_install_with_resources
  end

  test do
    system bin/"mainspring", "doctor"
  end
end
'''


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Generate the Homebrew Formula/mainspring.rb release file."
    )
    parser.add_argument("--version", required=True, help="Release tag or SemVer")
    parser.add_argument("--url", required=True, help="Release source tarball URL")
    parser.add_argument("--sha256", required=True, help="Release tarball sha256")
    parser.add_argument(
        "--homepage",
        default="https://github.com/dlogvinenko/mainspring",
        help="Project homepage URL for the formula",
    )
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=Path("pyproject.toml"),
        help="pyproject.toml path used to derive the python@X.Y dependency",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write Formula/mainspring.rb here instead of stdout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Write or print a Homebrew formula."""
    args = parse_args(argv)
    try:
        python_dependency = python_dependency_from_pyproject(args.pyproject)
        formula = build_formula(
            version=args.version,
            url=args.url,
            sha256=args.sha256,
            homepage=args.homepage,
            python_dependency=python_dependency,
        )
    except FormulaInputError as exc:
        raise SystemExit(f"homebrew_formula: {exc}") from exc

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(formula, encoding="utf-8")
    else:
        print(formula, end="")
    return 0


if __name__ == "__main__":
    run_cli(main)
