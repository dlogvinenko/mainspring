# SPDX-License-Identifier: Apache-2.0
"""Regression tests for Method documentation release truth."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PRD = REPO_ROOT / "docs" / "prd.md"
METHOD_DOC = REPO_ROOT / "docs" / "method.md"
PLAYBOOK_DOC = REPO_ROOT / "docs" / "playbook.md"
METHOD_README = REPO_ROOT / "method" / "README.md"
METHOD_INSTALL = REPO_ROOT / "method" / "install.sh"
METHOD_SKILL = REPO_ROOT / "method" / "skill" / "SKILL.md"
METHOD_TEMPLATE = REPO_ROOT / "method" / "templates" / "prd.md"
METHOD_SKILL_TEMPLATE = REPO_ROOT / "method" / "skill" / "templates" / "prd.md"


PUBLIC_METHOD_SURFACES = (
    METHOD_DOC,
    PLAYBOOK_DOC,
    METHOD_README,
    METHOD_SKILL,
    METHOD_TEMPLATE,
    METHOD_SKILL_TEMPLATE,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# Scenario: P4.5 Method tooling shipped locally.
# Expected: Public Method docs do not claim those CLI commands are missing.
def test_method_docs_do_not_describe_shipped_cli_as_future_work() -> None:
    stale_phrases = (
        "don't exist yet",
        "When Mainspring `decompose` CLI exists",
        "When Mainspring `scope-check` CLI exists",
        "until Mainspring's Phase P5 ships",
        "Until then, eyeball",
        "Until then: manual",
        "once they ship (P4.5)",
    )

    for path in PUBLIC_METHOD_SURFACES:
        text = _read(path)
        for phrase in stale_phrases:
            assert phrase not in text, (
                f"{path.relative_to(REPO_ROOT)} still says {phrase!r}"
            )


# Scenario: P7 extracted the repo to root-level docs and method/ paths.
# Expected: Public Method surfaces link the extracted repo paths, not pre-extraction paths.
def test_method_docs_use_extracted_repo_paths() -> None:
    stale_paths = ("tools/" + "mainspring-method/",)

    for path in PUBLIC_METHOD_SURFACES:
        text = _read(path)
        for stale_path in stale_paths:
            assert stale_path not in text, (
                f"{path.relative_to(REPO_ROOT)} still references {stale_path}"
            )


# Scenario: Public Method language should sound intentional, not like internal
# startup jargon.
# Expected: Method surfaces describe self-application directly.
def test_method_docs_use_professional_self_application_language() -> None:
    for path in (METHOD_DOC, METHOD_SKILL):
        text = _read(path)

        assert "dogfood" not in text.lower(), path.relative_to(REPO_ROOT)
        assert "Practice the Method on itself" in text


# Scenario: The Method definition of done tracks shipped local tooling accurately.
# Expected: Local Mainspring command and validator gates are checked off.
def test_method_definition_of_done_marks_local_tooling_complete() -> None:
    text = _read(METHOD_DOC)

    assert (
        "- [x] `mainspring init` and `mainspring decompose` CLI commands ship" in text
    )
    assert "- [x] PRD-shape validator exists" in text
    assert "mainspring validate-prd docs/prd.md" in text
    assert "mainspring scope-check" in text


# Scenario: The PRD publishes a single public release score in the current
# truth table and in the explanatory score rule.
# Expected: Both surfaces stay numerically consistent so release reports do not
# drift between competing scores.
def test_prd_readiness_score_is_consistent() -> None:
    text = _read(PRD)

    table_match = re.search(
        r"\| PRD readiness score\s+\|\s+(\d+)\s*/\s*1000\s+\|",
        text,
    )
    rule_match = re.search(r"current score\s+\*\*(\d+)/1000\*\*", text)

    assert table_match is not None
    assert rule_match is not None
    assert table_match.group(1) == rule_match.group(1)


# Scenario: The public PRD truth snapshot is release evidence, so its simple
# counts must not drift from the actual source tree.
# Expected: current LOC, test-file counts, Python-file count, and largest bash
# module line count match the files in the checkout.
def test_prd_truth_snapshot_counts_match_repo() -> None:
    text = _read(PRD)

    main_lines = len((REPO_ROOT / "mainspring.sh").read_text().splitlines())
    python_files = len(list((REPO_ROOT / "py").rglob("*.py")))
    pytest_files = len(list((REPO_ROOT / "py" / "tests").glob("test_*.py")))
    bats_files = len(list((REPO_ROOT / "tests" / "bats").glob("*.bats")))
    function_pattern = re.compile(r"^[_A-Za-z][_A-Za-z0-9-]*\(\)[ \t]*\{")
    function_count = 0
    for path in [
        REPO_ROOT / "mainspring.sh",
        *sorted((REPO_ROOT / "lib").glob("*.sh")),
    ]:
        function_count += sum(
            1
            for line in path.read_text(encoding="utf-8").splitlines()
            if function_pattern.match(line)
        )
    module_counts = {
        path.relative_to(REPO_ROOT).as_posix(): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in sorted((REPO_ROOT / "lib").glob("*.sh"))
    }
    largest_module, largest_count = max(module_counts.items(), key=lambda item: item[1])

    assert re.search(rf"\| `mainspring\.sh` LOC\s+\|\s+{main_lines}\s+\|", text)
    assert re.search(
        rf"\| Bash functions across entrypoint \+ lib\s+\|\s+{function_count}\s+\|",
        text,
    )
    assert (
        f"| Python format                           | passes, {python_files} files already formatted"
        in text
    )
    assert re.search(rf"\| Pytest suite files\s+\|\s+{pytest_files}\s+\|", text)
    assert re.search(rf"\| Bats suite files\s+\|\s+{bats_files}\s+\|", text)
    assert (
        f"All bash modules ≤ 600 LOC _(largest: `{largest_module}` "
        f"at {largest_count} LOC;"
    ) in text


# Scenario: The public v1 release checklist should look complete and polished,
# not like a half-edited internal tracker.
# Expected: every third-level release checklist section contains at least one
# checked or unchecked checklist item before the next section.
def test_prd_release_checklist_sections_are_not_empty() -> None:
    text = _read(PRD)
    release = text.split("## v1.0 GitHub release checklist", 1)[1]
    release = release.split("## Explicit non-goals", 1)[0]
    headings = list(re.finditer(r"^### .+$", release, flags=re.MULTILINE))

    assert headings
    for index, heading in enumerate(headings):
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(release)
        body = release[start:end]
        assert re.search(r"^- \[[ x]\]", body, flags=re.MULTILINE), heading.group(0)


# Scenario: Release docs should not reintroduce the old giant publication-gate list.
# Expected: local gates and ordinary GitHub owner actions are explicit; external
# evidence remains follow-up credibility work.
def test_prd_release_language_is_publication_scoped() -> None:
    text = _read(PRD)
    normalized = " ".join(text.split())

    assert "GitHub credential that has `workflow` scope" in text
    assert "prepared for the `mainspring v1.0.0` GitHub source release" in normalized
    assert "not a hidden CLI workflow and not a Mainspring subcommand" in normalized
    assert "not from checkpoint-heavy working history" in normalized
    assert "published history is short, readable" in normalized
    assert "The source-install path is public on `main`" in normalized
    assert "sanitized release ref" not in normalized
    stale_helper_archaeology = "release-" + "helper archaeology"
    assert stale_helper_archaeology not in normalized
    assert "private development history" not in normalized
    hidden_helper_updates = "hidden release-" + "helper state updates"
    assert hidden_helper_updates not in normalized
    assert "release-only Mainspring commands" in normalized
    assert (
        "The source tree can be made public before Pages/Homebrew/benchmarks"
        not in text
    )
    assert "published on GitHub as `mainspring v1.0.0`" not in text
    assert "tag/release/Pages/Homebrew" not in text
    assert "public-source " + "blocker" not in text
    assert "public visibility " + "blocker" not in text
    assert "proof-" + "state" not in text
    assert "release-" + "blockers" not in text


# Scenario: The canonical PRD is public-facing release evidence, not only old
# project memory.
# Expected: current architecture and release sections use the extracted
# root-level repository contract instead of stale pre-extraction paths.
def test_prd_current_sections_use_public_repo_contract() -> None:
    text = _read(PRD)

    forbidden_current_phrases = (
        "Phase P2 / P3 extract them into real files",
        "scripts/" + "mainspring/lib/engines.sh",
        "scripts/" + "mainspring/lib/lock.sh",
        "scripts/" + "mainspring/lib/write_scope.sh",
        "Eight implementation phases plus the active release-audit remediation overlay",
        "No-commit phase",
        "P-Audit — Release audit remediation (ACTIVE",
        "cd scripts/" + "mainspring && make all",
    )

    for phrase in forbidden_current_phrases:
        assert phrase not in text
    assert "root-level `mainspring.sh`, `lib/`, and `py/`" in text
    assert "Run `make all` from the repository root" in text
    assert (
        "bench/                           # source-only SWE-bench helpers; not installed runtime"
        in text
    )
    assert (
        "packaging/homebrew/                # source-only Homebrew tap publishing runbook"
        in text
    )
    stale_homebrew_layout = "".join(
        [
            "packaging/homebrew/                # gen",
            "erated ",
            "formula release ",
            "notes",
        ]
    )
    assert stale_homebrew_layout not in text


# Scenario: The public PRD source-tree sketch is copied into release reviews.
# Expected: root files are visually root-level, not ambiguous children of docs/.
def test_prd_source_tree_sketch_uses_unambiguous_root_layout() -> None:
    text = _read(PRD)
    source_tree = text.split("- [x] **P7-2 Source tree.**", 1)[1]
    source_tree = source_tree.split("```", 1)[1].split("```", 1)[0]

    for root_entry in (
        "|-- Makefile",
        "|-- README.md",
        "|-- LICENSE",
        "|-- NOTICE",
        "|-- SECURITY.md",
        "|-- CONTRIBUTING.md",
        "|-- CHANGELOG.md",
        "|-- .github/workflows/ci.yml",
    ):
        assert root_entry in source_tree

    assert "|-- docs/" in source_tree
    assert "|   |-- guide.md" in source_tree
    assert "|   `-- assets/" in source_tree
    assert "      Makefile" not in source_tree
    assert "    Makefile" not in source_tree


# Scenario: Appendix A is public source-of-truth material, not historical
# scratchpad archaeology.
# Expected: it points future agents at current files and commands without
# embedding old prototype recipes.
def test_prd_appendix_a_is_current_source_of_knowledge() -> None:
    text = _read(PRD)
    appendix = text.split("## Appendix A — Source-of-knowledge recipes", 1)[1]
    appendix = appendix.split("## Appendix B — Verification commands", 1)[0]

    for phrase in (
        "CLI truth",
        "`lib/help.sh`",
        "`lib/cli.sh`",
        "Runtime and logs",
        "`py/hud.py`",
        "`py/notify_telegram.py`",
        "Package payload",
        "`pyproject.toml`",
    ):
        assert phrase in appendix

    for stale in ("module not yet " + "available", "source last-run.env", "test stubs"):
        assert stale not in appendix


# Scenario: runtime source comments and docstrings should describe shipped v1
# behavior, not leave "future work" placeholders in public source.
# Expected: the LiteLLM adapter names its current v1 limitation directly.
def test_litellm_adapter_docstrings_do_not_advertise_future_work() -> None:
    adapter = _read(REPO_ROOT / "py" / "engines" / "litellm_adapter.py")

    assert "future work" not in adapter.lower()
    assert "not available through the generic v1 adapter" in adapter


# Scenario: The PRD truth snapshot is public release evidence.
# Expected: It uses the current verified gate signals and does not retain stale
# pre-polish counts from earlier snapshots.
def test_prd_verification_snapshot_uses_current_gate_counts() -> None:
    text = _read(PRD)

    assert "442" in text
    assert "172" in text
    assert "1149 Python tests passed, 1 skipped" in text
    assert "223 Bats" in text
    assert "90.6% (coverage gate pass)" in text
    assert "90.6%, above the 80% gate" in text
    assert "`command -v mainspring` resolves `~/.local/bin/mainspring`" in text

    stale_counts = (
        "414" + " LOC",
        "415" + " LOC",
        "383" + " LOC",
        "384" + " LOC",
        "| 170",
        "| 171",
        "599" + " LOC",
        "fish finds",
        "fish global smoke",
        "218" + " Bats",
        "217" + " Bats",
        "407" + " LOC",
        "1093" + " pytest",
        "1093" + " pytest passed",
        "1107" + " pytest",
        "1107" + " pytest passed",
        "1113" + " pytest",
        "1113" + " pytest passed",
        "1118" + " pytest passed",
        "1118" + " pytest, 1 skipped",
        "1119" + " pytest",
        "1119" + " pytest passed",
        "1120" + " pytest",
        "1120" + " pytest passed",
        "1121" + " pytest",
        "1121" + " pytest passed",
        "1122" + " pytest",
        "1122" + " pytest passed",
        "1089" + " pytest",
        "1089" + " pytest passed",
        "1090" + " pytest",
        "1090" + " pytest passed",
        "1092" + " pytest",
        "1092" + " pytest passed",
        "1103" + " pytest",
        "1103" + " pytest passed",
        "1104" + " pytest",
        "1104" + " pytest passed",
        "1105" + " pytest",
        "1105" + " pytest passed",
        "1106" + " pytest",
        "1106" + " pytest passed",
        "1081" + " pytest",
        "1081" + " pytest passed",
        "210" + " Bats",
        "208" + " Bats",
        "209" + " Bats",
        "211" + " Bats",
        "214" + " Bats",
        "212" + " Bats",
        "219" + " Bats",
        "91.0" + "%",
        "91.1" + "%",
        "90.9" + "%",
        "90.8" + "%",
        "10897" + "/11998",
        "10934" + "/12028",
        "10944" + "/12062",
        "10945" + "/12062",
        "10922" + "/12028",
        "10879" + "/11983",
        "10905" + "/11984",
        "10907" + "/11984",
        "11043" + "/12134",
        "11019" + "/12107",
        "11015" + "/12103",
        "10848" + "/11926",
        "10805" + "/11878",
        "10847" + "/11925",
        "11025" + "/12109",
        "11215" + "/12321",
        "11216" + "/12321",
        "11227" + "/12321",
        "11228" + "/12321",
        "11239" + "/12333",
        "11240" + "/12334",
    )
    for stale in stale_counts:
        assert stale not in text


# Scenario: The public Method truth table should not preserve stale hand-counted
# numbers after docs or templates change.
# Expected: LOC values in docs/method.md match the current source tree.
def test_method_truth_snapshot_counts_current_files() -> None:
    text = _read(METHOD_DOC)
    method_files = [
        path for path in (REPO_ROOT / "method").rglob("*") if path.is_file()
    ]
    method_package_loc = sum(len(_read(path).splitlines()) for path in method_files)

    assert "refreshed 2026-06-15" in text
    assert (
        f"| Skill source LOC         | {len(_read(METHOD_SKILL).splitlines())} (`SKILL.md`)"
        in text
    )
    assert f"| Method package LOC       | {method_package_loc} " in text
    assert f"| Public Method doc LOC    | {len(text.splitlines())} " in text
    assert (
        f"| Canonical example        | `docs/prd.md` ({len(_read(PRD).splitlines())} LOC)"
        in text
    )
    assert "_Last edited: 2026-06-15." in text

    for stale in ("174 (`SKILL.md`)", "1678 ", "389 ", "1425 LOC"):
        assert stale not in text


# Scenario: Public installer force mode removes an existing install directory.
# Expected: The destructive operation is guarded by an exact destination check.
def test_method_installer_guards_force_delete_destination() -> None:
    text = _read(METHOD_INSTALL)

    assert "assert_safe_dest" in text
    assert 'expected="${HOME}/.claude/skills/mainspring-method"' in text
    assert 'rm -rf "$DEST"' in text
    assert text.index("assert_safe_dest") < text.index('rm -rf "$DEST"')


def _installer_sandbox(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    method = tmp_path / "source" / "method"
    skill = method / "skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("Synthetic current skill\n")
    # Redirect only variable references in a private copy; never override host HOME.
    source = (
        _read(METHOD_INSTALL)
        .replace("${HOME}", "${MAINSPRING_INSTALL_TEST_HOME}")
        .replace("$HOME", "$MAINSPRING_INSTALL_TEST_HOME")
    )
    assert "${HOME}" not in source and "$HOME" not in source
    script = method / "install.sh"
    script.write_text(source)
    sandbox = tmp_path / "sandbox"
    dest = sandbox / ".claude" / "skills" / "mainspring-method"
    dest.parent.mkdir(parents=True)
    (dest.parent / "unrelated.txt").write_text("Preserve unrelated skill\n")
    env = {
        "PATH": "/usr/bin:/bin",
        "LC_ALL": "C",
        "MAINSPRING_INSTALL_TEST_HOME": str(sandbox),
    }
    return script, skill, dest, env


@pytest.mark.parametrize("link", [False, True])
def test_method_installer_force_replaces_dangling_link(
    tmp_path: Path, link: bool
) -> None:
    script, skill, dest, env = _installer_sandbox(tmp_path)
    previous = tmp_path / "removed-worktree" / "skill"
    dest.symlink_to(previous, target_is_directory=True)

    result = subprocess.run(
        ["/bin/bash", str(script), "--force", *(["--link"] if link else [])],
        cwd=script.parent,
        env=env,
        stdin=subprocess.DEVNULL,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert dest.is_symlink() is link
    if link:
        assert dest.readlink() == skill
    assert (dest / "SKILL.md").read_text() == "Synthetic current skill\n"
    assert (skill / "SKILL.md").read_text() == "Synthetic current skill\n"
    assert not previous.exists()
    assert (dest.parent / "unrelated.txt").read_text() == "Preserve unrelated skill\n"


@pytest.mark.parametrize("link", [False, True])
def test_method_installer_dangling_link_requires_force(
    tmp_path: Path, link: bool
) -> None:
    script, _skill, dest, env = _installer_sandbox(tmp_path)
    previous = tmp_path / "removed-worktree" / "skill"
    dest.symlink_to(previous, target_is_directory=True)

    result = subprocess.run(
        ["/bin/bash", str(script), *(["--link"] if link else [])],
        cwd=script.parent,
        env=env,
        stdin=subprocess.DEVNULL,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert "Already installed" in result.stdout
    assert "Removing existing install" not in result.stdout
    assert dest.is_symlink() and dest.readlink() == previous
    assert not previous.exists()
    assert (dest.parent / "unrelated.txt").read_text() == "Preserve unrelated skill\n"


def test_method_installer_force_copy_preserves_linked_source(tmp_path: Path) -> None:
    script, skill, dest, env = _installer_sandbox(tmp_path)
    dest.symlink_to(skill, target_is_directory=True)

    result = subprocess.run(
        ["/bin/bash", str(script), "--force"],
        cwd=script.parent,
        env=env,
        stdin=subprocess.DEVNULL,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert not dest.is_symlink()
    assert (dest / "SKILL.md").read_text() == "Synthetic current skill\n"
    assert (skill / "SKILL.md").read_text() == "Synthetic current skill\n"
    assert (dest.parent / "unrelated.txt").read_text() == "Preserve unrelated skill\n"
