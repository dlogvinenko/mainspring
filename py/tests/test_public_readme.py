# SPDX-License-Identifier: Apache-2.0
"""Tests for the Mainspring public README release draft."""

from __future__ import annotations

import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
GUIDE = REPO_ROOT / "docs" / "guide.md"
PRD = REPO_ROOT / "docs" / "prd.md"
PLAYBOOK = REPO_ROOT / "docs" / "playbook.md"
HELP_SH = REPO_ROOT / "lib" / "help.sh"
STATUS_SH = REPO_ROOT / "lib" / "status.sh"
HUD_PY = REPO_ROOT / "py" / "hud.py"
HUD_DEMO = REPO_ROOT / "docs" / "assets" / "hud-demo.cast"
README_HERO = REPO_ROOT / "docs" / "assets" / "readme-hero.svg"
HUD_PREVIEW = REPO_ROOT / "docs" / "assets" / "hud-preview.svg"
PUBLIC_MARKDOWN_WITH_LINKS = (
    README,
    GUIDE,
    PRD,
    REPO_ROOT / "docs" / "architecture.md",
    REPO_ROOT / "docs" / "competitive-analysis.md",
    REPO_ROOT / "docs" / "method.md",
    REPO_ROOT / "docs" / "metrics.md",
    PLAYBOOK,
    CONTRIBUTING,
    REPO_ROOT / "SECURITY.md",
    REPO_ROOT / "CHANGELOG.md",
    REPO_ROOT / "method" / "README.md",
    REPO_ROOT / "method" / "skill" / "SKILL.md",
    REPO_ROOT / "method" / "templates" / "prd.md",
    REPO_ROOT / "method" / "templates" / "task.md",
    REPO_ROOT / "method" / "templates" / "adr.md",
    REPO_ROOT / "method" / "templates" / "audit-prompt.md",
    REPO_ROOT / "method" / "templates" / "reality-reset-prompt.md",
    REPO_ROOT / "method" / "skill" / "templates" / "prd.md",
    REPO_ROOT / "method" / "skill" / "templates" / "task.md",
    REPO_ROOT / "method" / "skill" / "templates" / "adr.md",
    REPO_ROOT / "method" / "skill" / "templates" / "audit-prompt.md",
    REPO_ROOT / "method" / "skill" / "templates" / "reality-reset-prompt.md",
    REPO_ROOT / "packaging" / "homebrew" / "README.md",
)


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def _contributing_text() -> str:
    return CONTRIBUTING.read_text(encoding="utf-8")


def _guide_text() -> str:
    return GUIDE.read_text(encoding="utf-8")


def _prd_text() -> str:
    return PRD.read_text(encoding="utf-8")


def _github_anchor_slug(heading: str) -> str:
    heading = re.sub(r"<[^>]+>", "", heading)
    heading = re.sub(r"[`*_~]", "", heading).strip().lower()
    heading = heading.replace("—", " ").replace("–", " ")
    heading = re.sub(r"['’]", "", heading)
    heading = re.sub(r"[^a-z0-9\s-]", "", heading)
    heading = re.sub(r"\s+", "-", heading)
    return re.sub(r"-+", "-", heading).strip("-")


def _svg_text_overflow_failures(svg: str, view_width: int) -> list[str]:
    class_sizes = {
        name: float(size)
        for name, size in re.findall(
            r"\.([a-zA-Z0-9_-]+)\s*\{[^}]*font-size:\s*([0-9.]+)px",
            svg,
        )
    }
    root = ET.fromstring(svg)
    failures: list[str] = []

    for element in root.iter("{http://www.w3.org/2000/svg}text"):
        raw_text = "".join(element.itertext()).strip()
        if not raw_text:
            continue
        x = float(element.attrib.get("x", "0"))
        css_class = element.attrib.get("class", "")
        font_size = class_sizes.get(css_class, 18.0)
        estimated_right = x + (len(raw_text) * font_size * 0.62)
        if estimated_right > view_width - 20:
            failures.append(
                f"{raw_text!r} estimated right edge {estimated_right:.1f} "
                f"exceeds {view_width - 20}"
            )

    return failures


# Scenario: The public README draft stays inside the v1.0 launch brief.
# Expected: It is concise enough to become the extracted repo root README.
def test_public_readme_line_budget() -> None:
    lines = _readme_text().splitlines()
    assert len(lines) <= 270


# Scenario: public release docs should stay readable in GitHub raw, diffs, and
# review panes.
# Expected: prose lines are wrapped; wide markdown tables and badge/image lines
# are allowed because wrapping them would hurt rendered output.
def test_public_markdown_prose_lines_are_reviewable() -> None:
    checked_paths = [
        README,
        GUIDE,
        REPO_ROOT / "docs" / "competitive-analysis.md",
        REPO_ROOT / "docs" / "method.md",
        REPO_ROOT / "CHANGELOG.md",
        REPO_ROOT / "SECURITY.md",
        REPO_ROOT / "method" / "README.md",
        REPO_ROOT / "method" / "skill" / "SKILL.md",
    ]
    failures: list[str] = []
    for path in checked_paths:
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            stripped = line.strip()
            if (
                len(line) <= 180
                or "|" in line
                or stripped.startswith(("<img ", "![", "description:"))
            ):
                continue
            failures.append(
                f"{path.relative_to(REPO_ROOT)}:{line_no}: {len(line)} chars"
            )

    assert not failures, "\n".join(failures)


# Scenario: manual docs edits should not collapse separate Markdown list items
# into one unreadable line.
# Expected: numbered, bullet, and task-list items stay on separate lines.
def test_public_markdown_lists_are_not_collapsed() -> None:
    list_paths = [
        README,
        GUIDE,
        PRD,
        REPO_ROOT / "docs" / "method.md",
        REPO_ROOT / "method" / "README.md",
        REPO_ROOT / "method" / "skill" / "SKILL.md",
    ]
    collapsed_markers = (
        re.compile(r"\.\s+[2-9]\.\s+\*\*"),
        re.compile(r"\.\s+-\s+\*\*"),
        re.compile(r"\.\s+-\s+\["),
        re.compile(r"\]\s+[2-9]\.\s+\["),
    )
    failures: list[str] = []

    for path in list_paths:
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if any(pattern.search(line) for pattern in collapsed_markers):
                failures.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {line}")

    assert not failures, "\n".join(failures)


# Scenario: Public Markdown should render cleanly on GitHub and Pages.
# Expected: fenced code blocks are balanced and do not swallow later prose.
def test_public_markdown_code_fences_are_balanced() -> None:
    failures: list[str] = []

    for path in PUBLIC_MARKDOWN_WITH_LINKS:
        fence_count = sum(
            1
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("```")
        )
        if fence_count % 2 != 0:
            failures.append(f"{path.relative_to(REPO_ROOT)}: {fence_count} fences")

    assert not failures, "\n".join(failures)


# Scenario: The public playbook is packaged and published, so it must not read
# like a generic npm app runbook or user quickstart.
# Expected: It is explicitly scoped to Mainspring maintainers and uses the
# repository release gate.
def test_playbook_is_maintainer_scoped_and_uses_mainspring_gates() -> None:
    text = PLAYBOOK.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert text.startswith("# Mainspring Maintainer Playbook")
    assert "This is not the first-read user guide" in normalized
    assert "start with [`guide.md`](guide.md)" in text
    assert "make release-check" in text
    assert "npm test" not in text
    assert "npm run typecheck" not in text
    assert "npm run build" not in text


# Scenario: Placeholder endpoints should not look like broken real links in
# public docs.
# Expected: docs describe how to call provider APIs without shipping fake
# clickable URLs that fail external link checks.
def test_public_markdown_does_not_publish_fake_placeholder_urls() -> None:
    forbidden = (
        "https://api.telegram.org/bot<",
        "https://api.telegram.org/bot{",
        "https://api.telegram.org/bot$",
    )
    failures: list[str] = []

    for path in PUBLIC_MARKDOWN_WITH_LINKS:
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            if marker in text:
                failures.append(f"{path.relative_to(REPO_ROOT)}: {marker}")

    assert not failures, "\n".join(failures)


# Scenario: public docs and CLI help must not expose owner-only maintenance
# workflows as if they were normal operator commands.
# Expected: README, guide, PRD, package docs, and installed help stay focused on
# daily operator commands.
def test_public_surface_does_not_expose_internal_maintainer_workflows() -> None:
    forbidden = (
        "mainspring release-" + "blockers",
        "mainspring release-" + "notes",
        "--use-standard-" + "proof-" + "state",
        "--proof-" + "state",
        "--emit-live-provider-" + "proof",
        "--emit-pair-matrix-" + "proof",
        "public-source " + "blocker",
        "public visibility " + "blocker",
        "public-visibility " + "blockers",
        "retired release " + "helpers",
        "release-" + "fresh-box",
        "Re" + "lease:\n  mainspring",
        "../../.mainspring/logs",
        "Drop these into a one-liner harness",
        "mainspring stop --force --" + "all",
        "mainspring --help-" + "full",
        "| Goal | Base " + "command | Arguments / " + "options |",
        "| Feature | Base " + "command | Arguments / " + "options |",
    )
    checked_paths = (
        *PUBLIC_MARKDOWN_WITH_LINKS,
        HELP_SH,
        STATUS_SH,
        HUD_PY,
        HUD_PREVIEW,
    )
    failures: list[str] = []

    for path in checked_paths:
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            if marker in text:
                failures.append(f"{path.relative_to(REPO_ROOT)}: {marker}")

    assert not failures, "\n".join(failures)


# Scenario: The public README must answer the release checklist prompts.
# Expected: It includes buyer-facing why/start/features/HUD/Telegram/docs sections.
def test_public_readme_required_sections() -> None:
    text = _readme_text()
    headings = [
        "# Mainspring",
        "## Install Mainspring",
        "## Why It Exists",
        "## Start Here",
        "## What Happens",
        "## Key Features",
        "## HUD",
        "## Telegram Notifications",
        "## When To Use It",
        "## Core Concepts",
        "## Engine Support",
        "## Copy/Paste Commands",
        "## Docs",
    ]
    for heading in headings:
        assert heading in text

    assert "## Release Status" not in text
    assert text.count("## Key Features") == 1


# Scenario: Release candidate instructions should be safe copy/paste commands,
# not hidden helper CLIs or live-provider gates.
# Expected: The PRD release appendix uses source/package/doc/diff checks first,
# and keeps live self-tests explicitly optional.
def test_prd_release_verification_commands_are_operator_safe() -> None:
    text = _prd_text()
    appendix = text.split("## Appendix B — Verification commands", 1)[1]
    appendix = appendix.split("## Appendix C", 1)[0]

    for command in (
        "make release-check",
        "./mainspring.sh doctor",
        "./mainspring.sh --dry-run --once",
    ):
        assert command in appendix

    for included_gate in (
        "it runs `make all`, package",
        "Python coverage",
        "Product Requirements Document (PRD) validation",
        "`git diff --check`",
    ):
        assert included_gate in text

    normalized_text = " ".join(text.split())
    required_phrase = "There is no public release subcommand for this on purpose"
    assert required_phrase in normalized_text
    assert "Optional live engine smoke" in appendix
    assert "Drop these into a one-liner harness" not in appendix
    assert "../../.mainspring/logs" not in appendix

    base_gate = appendix.split("Optional live engine smoke", 1)[0]
    assert "--self-test-all" not in base_gate


# Scenario: The public README must explain the product before internal mechanics.
# Expected: The first screen says what Mainspring does in plain language.
def test_public_readme_plain_english_first_screen() -> None:
    first_screen = "\n".join(_readme_text().splitlines()[:12])

    assert "Product Requirements Document (PRD)-first" in first_screen
    assert "AI coding agent orchestration" in first_screen
    assert "terminal HUD" in first_screen
    assert "Telegram" in first_screen
    assert "cheap project progress" not in _readme_text()
    assert "cheap project progress" not in _guide_text()
    assert "cheap/private" not in _readme_text()
    assert "local writer: cheaper" not in _guide_text()
    assert "lightweight and read-only" in _readme_text()
    assert "private, low-cost iteration" in _readme_text()
    assert "lower-cost and private" in _guide_text()


# Scenario: Public release docs should read like product documentation, not a
# personal workspace memo.
# Expected: release-owner duties are named without personal author wording, and
# private author/user language stays out of release-facing docs.
def test_public_docs_avoid_personal_author_language() -> None:
    docs = {
        "README.md": _readme_text(),
        "docs/guide.md": _guide_text(),
        "docs/prd.md": _prd_text(),
        "docs/method.md": (REPO_ROOT / "docs" / "method.md").read_text(
            encoding="utf-8"
        ),
    }
    forbidden = (
        "project author",
        "The author, every working day",
        "future-author",
        "solo author",
        "This author's stack",
        "The user is a Node/TypeScript developer",
        "the author has actually hit",
        "The author's own scar tissue",
        "original author",
        "maintainer-only",
        "maintainer/admin",
    )

    hits = [
        f"{label}: {phrase}"
        for label, text in docs.items()
        for phrase in forbidden
        if phrase in text
    ]

    assert hits == []


# Scenario: package metadata should use the same public positioning as README.
# Expected: PyPI/Homebrew previews inherit the release-facing SEO language.
def test_package_description_matches_public_positioning() -> None:
    metadata = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert metadata["project"]["description"] == (
        "Product Requirements Document (PRD)-first AI coding agent orchestration "
        "for production-grade software delivery."
    )


# Scenario: The public README must make the current install path explicit.
# Expected: GitHub clone plus make install-user is primary until package-manager
# publication gates close.
def test_public_readme_install_starts_with_mainspring() -> None:
    text = _readme_text()
    normalized = " ".join(text.split())
    install_section_index = text.index("## Install Mainspring")
    install_index = text.index("## Start Here")
    first_command_index = text.index("If Mainspring is already installed")
    clone_index = text.index("git clone https://github.com/dlogvinenko/mainspring.git")

    assert install_section_index < clone_index < install_index < first_command_index
    assert "brew install pipx" in text
    assert "pipx ensurepath" in text
    assert "command -v mainspring" in text
    assert "`~/.local/bin` is on your shell PATH" in text
    assert "make install-user" in text
    assert "stale optional provider dependencies do not survive an update" in normalized
    assert "MAINSPRING_PROVIDERS_PYTHON=python3.13 make install-user-providers" in text
    assert "Python 3.11-3.13" in normalized
    assert "./mainspring.sh --project /path/to/your-project" in text
    help_text = HELP_SH.read_text(encoding="utf-8")
    assert (
        "Source install stays the supported path until package-manager channels exist"
        in help_text
    )
    assert (
        "The v1 install path is source install until package-manager channels "
        "are actually published" in normalized
    )
    assert "will be added only after" not in normalized
    assert "will be documented after" not in help_text
    assert "the first command is just" in text
    assert "mainspring init checkout-redesign" in text
    assert "replacing `checkout-redesign` with" in text
    old_placeholder = "mainspring init <" + "project-name>"
    assert old_placeholder not in text
    assert old_placeholder not in _guide_text()
    assert "not the normal first-run path" in normalized
    assert "pipe wizard answers" in text
    assert "setup choices plus explicit next commands" not in text
    assert "such as `mainspring --wizard`" not in text


# Scenario: The README uses sober visual markers for the decision tables.
# Expected: Green/red badge language makes good and bad paths scan quickly.
def test_public_readme_uses_green_red_decision_badges() -> None:
    text = _readme_text()

    for phrase in (
        "img.shields.io/badge/risk-unclear%20target-dc2626",
        "img.shields.io/badge/fix-PRD%20before%20code-059669",
        "img.shields.io/badge/use-Mainspring-059669",
        "img.shields.io/badge/avoid-vibes%20only-dc2626",
    ):
        assert phrase in text


# Scenario: The release README should give the operator obvious commands.
# Expected: It lists complete runnable command lines and keeps noisy release
# maintainer commands out of the public copy/paste section.
def test_public_readme_copy_paste_section_names_operator_commands() -> None:
    text = _readme_text()
    for phrase in (
        "mainspring",
        "mainspring hud",
        "mainspring stop --force",
        "mainspring notify-test",
        "mainspring notify-health",
        "mainspring doctor",
        "mainspring status",
        "mainspring --preset fast-smoke --dry-run",
        "mainspring taskmaster --once",
        "mainspring night --prd docs/prd.md --once",
        "mainspring --metrics --days 7 --routing",
        "| Need | Run | Result |",
    ):
        assert phrase in text
    assert "./mainspring.sh --project /path/to/your-project" in text
    assert "Each row is a complete command you can paste" in text
    assert "flags are shown only as part of real runnable commands" in text
    assert "never separate columns" in text
    assert "Operator commands are grouped by the command family" not in text
    assert "The variants column gives exact copy/paste forms" not in text
    assert "Drop `--once`" not in text
    assert "add `--pair" not in text
    assert "Add `--pair" not in text
    copy_paste_section = text.split("## Copy/Paste Commands", 1)[1].split("## Docs", 1)[
        0
    ]
    assert "Script " + "output:" not in copy_paste_section
    command_rows = [
        line
        for line in copy_paste_section.splitlines()
        if line.startswith("| ") and "`" in line and not line.startswith("| Need ")
    ]
    assert command_rows
    for row in command_rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert len(cells) == 3
        commands = re.findall(r"`([^`]+)`", cells[1])
        assert commands, row
        for command in commands:
            assert command.startswith(("mainspring", "./mainspring.sh")), row
    assert ("| Check Telegram | `mainspring notify-health --format json` |") in text
    assert "Reads notifier health without calling Telegram" in text
    assert (
        "| Machine-readable snapshot | `mainspring hud --json --once` | Emits `run_count`, `live_count`, `needs_action_count`, `stale_count`, and `runs[]` for scripts and agents. |"
        in text
    )
    stale_notify_text = "Reads notifier health without " + "reading logs"
    assert stale_notify_text not in text
    retired_commands = (
        "release-" + "blockers",
        "release-" + "notes",
        "--use-standard-" + "proof-" + "state",
    )
    for retired in retired_commands:
        assert retired not in text
    old_goal_header = "| Goal | Base " + "command | Arguments / " + "options | Notes |"
    old_feature_header = (
        "| Feature | Base " + "command | Arguments / " + "options | Why you care |"
    )
    assert old_goal_header not in text
    assert old_feature_header not in text
    assert "| Need | Command family | Useful variants | Result |" not in text


# Scenario: the operator guide should cover the full supported CLI surface.
# Expected: agents and humans can understand advanced commands without reading
# lib/cli.sh or lib/dispatch.sh.
def test_guide_command_reference_covers_supported_public_commands() -> None:
    text = _guide_text()
    normalized = " ".join(text.split())

    assert "## Everyday Commands" in text
    assert "## Command Reference" in text
    assert "## Project Planning Commands" in text
    assert "## Advanced and Recovery Commands" in text
    assert "| Need | Run | Notes |" in text
    assert "| Need | Run | What it does |" in text
    assert "HUD JSON is intentionally small and stable for scripts and agents" in text
    for field in (
        "`scope`",
        "`generated_at`",
        "`run_count`",
        "`live_count`",
        "`needs_action_count`",
        "`stale_count`",
        "`runs`",
    ):
        assert field in text
    old_reference_header = (
        "| Need | Primary " + "command | More " + "commands | Notes |"
    )
    assert old_reference_header not in text
    assert "Other complete commands" not in text
    assert "Every row below is a complete runnable command" in text
    assert "Flags are shown only inside" in text
    assert "never as separate columns" in text
    assert "The table below groups the public surface by command family" not in text
    for phrase in (
        "mainspring engines",
        "`mainspring engines --json`",
        "mainspring limits",
        "mainspring --metrics --days 7 --routing",
        "mainspring limits --hours 72",
        "mainspring init",
        "mainspring validate-prd docs/prd.md",
        "mainspring decompose docs/prd.md --phase P1",
        "mainspring next",
        "mainspring scope-check",
        "mainspring replay",
        "mainspring --repair-state",
        "mainspring --self-test",
        "mainspring --self-test-all",
        "MAINSPRING_PROVIDERS_PYTHON=python3.13 make install-user-providers",
        "module=litellm: missing",
        "Useful verification ladder from the Mainspring source checkout",
        "cd /path/to/mainspring",
        "python3 py/litellm_runner.py",
        "source-checkout diagnostic",
        "normal operator path",
    ):
        assert phrase in text
    assert "python py/litellm_runner.py" not in text

    prd_text = _prd_text()
    help_text = (REPO_ROOT / "lib" / "help.sh").read_text(encoding="utf-8")
    assert "Requires a Taskmaster backlog" in text
    assert "Script " + "output:" not in text
    assert (
        "missing backlog prints\n`mainspring init checkout-redesign` guidance" in text
    )
    assert "requires configured engines and may consume provider quota" in text
    assert "Run a live writer/reviewer handshake" in help_text
    assert "consume provider quota" in help_text
    assert "Taskmaster backlog: print next ready item" in help_text
    assert "mainspring limits --hours 72" in help_text
    assert (
        "limits [engine ...] [--engine <name>] [--format text|json] [--hours N]"
        in help_text
    )
    assert "prints setup guidance instead of Python internals" in help_text
    assert "fails closed" in prd_text
    assert "no-op if already migrated" not in prd_text
    stale_migration_window = "migration " + "window"
    stale_explicit_migration = "explicit " + "migration"
    assert stale_migration_window not in prd_text
    assert stale_explicit_migration not in prd_text

    assert "do not need to read shell code" in text
    assert "never rewrites history and never pushes" not in normalized
    old_guide_header = (
        "| Goal | Base " + "command | Arguments / " + "options | Use it when |"
    )
    assert old_guide_header not in text
    assert "## Normal " + "Commands" not in text
    assert "Release" + ":\n  mainspring" not in text
    assert "The variants are" not in text
    assert "not separate concepts to memorize" not in text
    assert "| Need | Command family | Useful variants | What it does |" not in text
    assert "routing label" in text
    stale_team_marker = "internal subject " + "marker"
    assert stale_team_marker not in text
    assert "`Task Master `" not in text
    assert "`Task Master ...`" not in text
    removed_migration_flag = "--migrate" + "-from"
    assert removed_migration_flag not in text
    assert removed_migration_flag not in help_text
    assert "## Source Checkout Maintenance" not in text
    assert "not a release command" not in text
    hidden_history_cmd = "mainspring " + "final" + "ize"
    assert hidden_history_cmd not in text


def test_guide_command_tables_keep_flags_attached_to_full_commands() -> None:
    text = _guide_text()
    failures: list[str] = []

    for header in (
        "| Need | Run | Notes |",
        "| Need | Run | What it does |",
        "| Need | Command | What it does |",
    ):
        start = 0
        while True:
            try:
                table_start = text.index(header, start)
            except ValueError:
                break
            lines = text[table_start:].splitlines()
            for line in lines[2:]:
                if not line.startswith("| "):
                    break
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                command_cells = [cells[1]]
                for cell in command_cells:
                    if cell == "-":
                        continue
                    commands = re.findall(r"`([^`]+)`", cell)
                    if not commands:
                        failures.append(line)
                        continue
                    for command in commands:
                        if not command.startswith(("mainspring", "./mainspring.sh")):
                            failures.append(f"{line} :: {command}")
                        if command.startswith("-"):
                            failures.append(f"{line} :: standalone flag {command}")
            start = table_start + len(header)

    assert not failures, "\n".join(failures)


# Scenario: Public guide prose should look hand-edited, not duplicated by a
# generation pass.
# Expected: important safety notes appear once and only once.
def test_guide_team_safety_text_has_no_duplicated_sentences() -> None:
    text = " ".join(_guide_text().split())

    assert (
        text.count(
            "`.claude/` helper worktrees are excluded by default; configured "
            "prefixes are additive."
        )
        == 1
    )


# Scenario: recovery docs are copied under stress.
# Expected: the first recovery surface starts with read-only commands and keeps
# work-launching resume commands out of the recovery command table.
def test_guide_recovery_commands_are_read_only_first() -> None:
    text = _guide_text()
    section = text.split("## Recovery Commands", maxsplit=1)[1]
    section = section.split("## No-Side-Effect Smoke Checklist", maxsplit=1)[0]

    assert "Start with read-only inspection" in section
    for command in (
        "`mainspring hud`",
        "`mainspring status`",
        "`mainspring doctor`",
        "`mainspring last-run`",
        "`mainspring --repair-state --dry-run`",
    ):
        assert command in section

    table = section.split("| Need | Run | Effect |", maxsplit=1)[1]
    table = table.split("Use `mainspring stop --help`", maxsplit=1)[0]
    assert "`mainspring --last-run`" not in table
    assert "mainspring taskmaster" not in table
    assert "git worktree prune" not in table
    assert "launch work" in section


# Scenario: The PRD's frozen CLI contract should not lag behind the guide.
# Expected: the canonical plan names the current public command families.
def test_prd_cli_contract_covers_supported_public_commands() -> None:
    text = _prd_text()
    contract = text.split("### CLI contract (frozen at v1.0)", maxsplit=1)[1]
    contract = contract.split("### JSONL wave schema", maxsplit=1)[0]

    for phrase in (
        "hud [--once|--json|--local]",
        "status                         runtime + git + scheduler + waves snapshot",
        "last-run [--format json]",
        "--metrics [--days N]",
        "engines [--json]",
        "limits [engine ...] [--hours N]",
        "init <name>",
        "validate-prd <path>",
        "decompose <prd-path>",
        "next [tasks.json]",
        "scope-check [tasks.json]",
        "--repair-state --dry-run",
        "--repair-state --force",
        "stop --force [--all]",
        "notify-health [--format json]",
        "notify-restart",
        "replay <show|diff|build|run>",
    ):
        assert phrase in contract

    for hidden in (
        "final" + "ize [list|squash|draft]",
        "Release" + ":",
    ):
        assert hidden not in contract

    for stale in (
        "scripts/" + "mainspring/mainspring.sh",
        "today: still .omx",
        "after extraction",
    ):
        assert stale not in contract


# Scenario: Engine support is one of the competitive launch claims.
# Expected: The matrix names every registered engine family and fail-closed behavior.
def test_public_readme_engine_matrix_names_registered_engines() -> None:
    text = _readme_text()
    for engine in (
        "Claude",
        "Codex",
        "Anthropic",
        "OpenAI",
        "Azure OpenAI",
        "Google Gemini",
        "xAI Grok",
        "Mistral",
        "Ollama",
        "OpenRouter",
        "LiteLLM",
    ):
        assert engine in text
    for key in (
        "claude",
        "codex",
        "anthropic",
        "openai",
        "azure",
        "gemini",
        "grok",
        "mistral",
        "ollama",
        "openrouter",
        "litellm",
    ):
        assert f"`{key}`" in text
    assert "fail closed" in text
    assert "silently fall back" in text


# Scenario: Local model routing is a core operator setup path.
# Expected: README gives concrete Ollama and MTPLX commands with explicit
# writer/reviewer flags instead of requiring users to infer LiteLLM syntax.
def test_public_readme_documents_local_model_writer_setup() -> None:
    text = _readme_text()
    for phrase in (
        "Local Model Writer",
        "mainspring engines",
        "--engine ollama",
        "--model 'ollama/qwen3:8b'",
        "mtplx quickstart",
        "--model Youssofal/Qwen3.6-27B-MTPLX-Optimized-Speed",
        "--model-id qwen3.6-mtplx",
        "OPENAI_API_BASE=http://127.0.0.1:18080/v1",
        "OPENAI_API_KEY=local",
        "--engine litellm",
        "--model 'openai/qwen3.6-mtplx'",
        "--review-engine codex",
        "Status: READY",
    ):
        assert phrase in text
    assert "- Ollama: `mainspring night" not in text
    assert "- MTPLX: start `mtplx quickstart" not in text
    assert "Preview an Ollama writer:" in text
    assert "Preview an MTPLX writer:" in text


# Scenario: The README should route readers to the durable docs instead of duplicating them.
# Expected: Existing public docs are linked from the launch artifact.
def test_public_readme_links_canonical_docs() -> None:
    text = _readme_text()
    for link in (
        "docs/guide.md",
        "docs/method.md",
        "docs/competitive-analysis.md",
        "docs/metrics.md",
        "docs/architecture.md",
        "SECURITY.md",
    ):
        assert link in text
    assert "CONTRIBUTING.md" in text


# Scenario: Public launch docs should teach the Mainspring namespace only.
# Expected: legacy migration aliases stay out of user-facing README/guide/help.
def test_public_docs_do_not_advertise_legacy_env_aliases() -> None:
    texts = {
        "README.md": _readme_text(),
        "docs/guide.md": _guide_text(),
        "lib/help.sh": (REPO_ROOT / "lib" / "help.sh").read_text(encoding="utf-8"),
        "CHANGELOG.md": (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
        "CONTRIBUTING.md": _contributing_text(),
        "SECURITY.md": (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8"),
    }

    for label, text in texts.items():
        assert "OMX" + "_LOOP_" not in text, label


# Scenario: Public security docs must protect local runtime evidence.
# Expected: They warn operators not to publish Mainspring logs or ledgers raw.
def test_security_policy_warns_about_runtime_evidence() -> None:
    text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for phrase in (
        ".mainspring/logs/",
        ".codex/",
        ".claude/",
        "waves.jsonl",
        "prompt snapshots",
        "notifier logs",
        "project paths",
        "prompts",
        "model output",
        "public issues",
        "rotate the credential",
        "commit hash",
    ):
        assert phrase in normalized


# Scenario: Public launch docs are often read directly on GitHub.
# Expected: local Markdown links and same-repo anchors resolve.
def test_public_markdown_links_resolve() -> None:
    link_pattern = re.compile(r"!??\[[^\]]*]\(([^)]+)\)")
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    anchors_by_file: dict[Path, set[str]] = {}

    for path in REPO_ROOT.rglob("*.md"):
        if any(
            part in {".git", ".venv", "build", "dist", ".mainspring", ".omx"}
            for part in path.parts
        ):
            continue
        counts: dict[str, int] = {}
        anchors: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            match = heading_pattern.match(line)
            if not match:
                continue
            base = _github_anchor_slug(match.group(2))
            seen = counts.get(base, 0)
            counts[base] = seen + 1
            anchors.add(base if seen == 0 else f"{base}-{seen}")
        anchors_by_file[path] = anchors

    problems: list[str] = []
    for path in PUBLIC_MARKDOWN_WITH_LINKS:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for raw_target in link_pattern.findall(line):
                if raw_target.startswith(("http://", "https://", "mailto:")):
                    continue
                target, _, fragment = raw_target.partition("#")
                target = target.strip()
                if target.startswith("<") and target.endswith(">"):
                    target = target[1:-1]
                target_parts = target.split()
                target = target_parts[0] if target_parts else ""
                if not target or target.startswith("data:"):
                    destination = path.resolve()
                else:
                    destination = (path.parent / target).resolve()
                try:
                    destination.relative_to(REPO_ROOT.resolve())
                except ValueError:
                    problems.append(
                        f"{path}:{line_number}: link escapes repo: {raw_target}"
                    )
                    continue
                if not destination.exists():
                    problems.append(
                        f"{path}:{line_number}: missing link target: {raw_target}"
                    )
                    continue
                if (
                    fragment
                    and destination.suffix == ".md"
                    and fragment not in anchors_by_file.get(destination, set())
                ):
                    problems.append(
                        f"{path}:{line_number}: missing anchor #{fragment} in {destination}"
                    )

    assert problems == []


# Scenario: P7-4 asks for an animated GIF/asciinema of the HUD.
# Expected: README links a committed asciinema cast generated from hud output.
def test_public_readme_links_hud_asciinema() -> None:
    text = _readme_text()
    demo = HUD_DEMO.read_text(encoding="utf-8")

    assert "docs/assets/hud-demo.cast" in text
    assert "docs/assets/hud-preview.svg" in text
    assert "mainspring hud" in text
    assert "$ mainspring hud --all-runtimes --once" in demo
    assert "1 past" in demo
    assert "View: all projects on this machine" in demo
    assert "Runs:" in demo
    assert "Folder: /workspace/checkout" in demo
    assert "Project:" not in demo
    assert "project=" not in demo
    stale_scope = "Scope: global " + "machine view"
    stale_runtimes = "Run" + "times:"
    assert stale_scope not in demo
    assert stale_runtimes not in demo
    assert "Next: Inspect .mainspring/logs/latest-taskmaster.log" in demo
    assert "1 stale" not in demo
    assert "Mainspring " + "runtimes" not in demo
    assert "$ ./mainspring.sh hud" not in demo

    preview = HUD_PREVIEW.read_text(encoding="utf-8")
    assert "1 needs action" in preview
    assert "attention" not in preview
    assert ">Stopped<" in preview


# Scenario: The README hero carries durable public evidence language.
# Expected: It avoids brittle test-count strings that become stale as soon as
# the suite changes; exact numbers live in the PRD.
def test_readme_hero_uses_durable_release_gate_language() -> None:
    hero = README_HERO.read_text(encoding="utf-8")

    assert "Confidence: tested, reviewed, auditable" in hero
    assert "package smoke" in hero
    assert "HUD smoke" in hero
    assert "Every run leaves an audit trail." in hero
    assert "Everything else is evidence." not in hero
    assert "Source release gate: make all green" not in hero
    assert "pytest passed" not in hero
    assert ("203" + " Bats") not in hero
    assert HUD_DEMO.is_file()
    first_line = HUD_DEMO.read_text(encoding="utf-8").splitlines()[0]
    assert '"version":2' in first_line


# Scenario: The GitHub README should have an immediate visual product signal.
# Expected: It links a committed hero graphic plus honest release-quality badges.
def test_public_readme_has_visual_github_landing_surface() -> None:
    text = _readme_text()

    assert "docs/assets/readme-hero.svg" in text
    assert "img.shields.io/badge/source%20install-ready" in text
    assert "img.shields.io/badge/coverage%20gate-pass" in text
    assert "img.shields.io/badge/coverage-" + "91." + "0%25" not in text
    normalized = " ".join(text.split())
    assert "v1 source install is the entrypoint" in normalized
    assert (
        "Everything starts from the same operator CLI people use day to day"
        in normalized
    )
    assert "source install is ready" not in text
    assert "special release-management commands" not in text
    assert "release commands" not in text
    stale_compound_command = "`mainspring notify-test`, " + "then"
    assert stale_compound_command not in text
    assert "operator-side release commands" not in text
    assert "remaining maintainer step is external to the" not in text
    assert "growth work after the" not in text
    assert "post-" + "v1" not in text.lower()
    assert "post-" + "source" not in text.lower()
    assert ("repository is still " + "private") not in text
    assert "production-grade software delivery" in text
    assert README_HERO.is_file()
    hero = README_HERO.read_text(encoding="utf-8")
    assert "Mainspring" in hero
    assert "Mainspring Product Requirements Document to evidence flow" in hero
    assert "Product requirements first" in hero
    assert "Requirements-driven agent work</text>" in hero
    stale_hero_subtitle = "Product Requirements Document " + "driven agents"
    assert stale_hero_subtitle not in hero
    assert "Operator evidence" in hero
    assert "Product Requirements Document to " + "proof flow" not in hero
    assert "Operator " + "proof" not in hero
    assert "Product intent" in hero
    assert "Requirements + gates" in hero
    assert "Requirements define success" in hero
    assert "Operator commands stay simple" in hero
    assert "No release commands required" not in hero
    assert "JSONL " + "proof" not in text
    assert "→" not in hero
    assert "PRD, backlog, gates" not in hero
    assert ("Mainspring turns " + "product intent") not in hero
    assert ("PRD " + "+ Method") not in hero
    assert "PRD defines success" not in hero
    assert "PRD-first agent orchestration" not in hero
    assert re.search(r"\d+ pytest", hero) is None
    assert re.search(r"\d+ Bats", hero) is None
    text_nodes = re.findall(r"<text[^>]*>([^<]+)</text>", hero)
    assert text_nodes
    assert all("PRD" not in node for node in text_nodes)
    assert max(len(node) for node in text_nodes) <= 60


# Scenario: The HUD section should show an actual dashboard preview on GitHub.
# Expected: The committed SVG names the operator fields users need when several
# projects run in parallel.
def test_public_readme_hud_preview_is_product_specific() -> None:
    text = _readme_text()
    preview = HUD_PREVIEW.read_text(encoding="utf-8")

    assert "![Mainspring HUD terminal preview](docs/assets/hud-preview.svg)" in text
    for phrase in (
        "Mainspring HUD preview",
        "All projects on this machine",
        "State",
        "Project",
        "Folder",
        "Tag",
        "Task",
        "Pair",
        "Progress",
        "Next",
        "Past runs",
        "Telegram/log rows include Project, Folder, Tag, Task, Pair, Result,",
        "Reason, Next, and Duration, so parallel runs stay readable.",
    ):
        assert phrase in preview

    for stale in (
        "Dmitri" + "HQ",
        "rune" + "lite",
        "os" + "rs",
        "Global " + "HUD",
        "Mainspring " + "runtimes",
        "Global machine " + "view",
    ):
        assert stale not in preview


# Scenario: The HUD preview is a fixed-format image for GitHub rendering.
# Expected: Panels and text stay inside the SVG viewBox.
def test_hud_preview_elements_fit_declared_viewbox() -> None:
    preview = HUD_PREVIEW.read_text(encoding="utf-8")
    match = re.search(r'viewBox="0 0 (\d+) (\d+)"', preview)

    assert match is not None
    view_width = int(match.group(1))
    view_height = int(match.group(2))
    assert (view_width, view_height) == (1200, 1200)

    rect_pattern = re.compile(
        r'<rect class="panel" x="([0-9.]+)" y="([0-9.]+)" '
        r'width="([0-9.]+)" height="([0-9.]+)"'
    )
    rects = [
        tuple(float(value) for value in groups)
        for groups in rect_pattern.findall(preview)
    ]
    assert rects
    for x, y, width, height in rects:
        assert x >= 0
        assert y >= 0
        assert x + width <= view_width
        assert y + height <= view_height

    text_x_values = [
        float(value)
        for value in re.findall(r'<text class="[^"]+" x="([0-9.]+)"', preview)
    ]
    text_y_values = [
        float(value)
        for value in re.findall(
            r'<text class="[^"]+" x="[0-9.]+" y="([0-9.]+)"', preview
        )
    ]
    assert text_x_values
    assert text_y_values
    assert max(text_x_values) <= view_width - 50
    assert max(text_y_values) <= view_height - 30
    assert not _svg_text_overflow_failures(preview, view_width)
    rx_values = [float(value) for value in re.findall(r' rx="([0-9.]+)"', preview)]
    assert rx_values
    assert max(rx_values) <= 8


# Scenario: The SVG hero should render as a complete GitHub social-card-style
# image instead of relying on clipped or overflowing elements.
# Expected: Fixed-format elements stay inside the declared viewBox.
def test_readme_hero_elements_fit_declared_viewbox() -> None:
    hero = README_HERO.read_text(encoding="utf-8")
    match = re.search(r'viewBox="0 0 (\d+) (\d+)"', hero)

    assert match is not None
    view_width = int(match.group(1))
    view_height = int(match.group(2))
    assert (view_width, view_height) == (1200, 1200)

    node_pattern = re.compile(
        r'<rect class="node" x="([0-9.]+)" y="([0-9.]+)" '
        r'width="([0-9.]+)" height="([0-9.]+)"'
    )
    panel_pattern = re.compile(
        r'<rect class="panel" x="([0-9.]+)" y="([0-9.]+)" '
        r'width="([0-9.]+)" height="([0-9.]+)"'
    )
    node_rects = [
        tuple(float(value) for value in groups) for groups in node_pattern.findall(hero)
    ]
    rects = node_rects + [
        tuple(float(value) for value in groups)
        for groups in panel_pattern.findall(hero)
    ]
    assert len(node_rects) == 6
    assert min(width for _, _, width, _ in node_rects) >= 280
    for x, y, width, height in rects:
        assert x >= 0
        assert y >= 0
        assert x + width <= view_width
        assert y + height <= view_height

    text_x_values = [float(value) for value in re.findall(r'<text x="([0-9.]+)"', hero)]
    text_y_values = [
        float(value) for value in re.findall(r'<text [^>]*y="([0-9.]+)"', hero)
    ]
    assert max(text_x_values) <= view_width - 80
    assert max(text_y_values) <= view_height - 60
    assert not _svg_text_overflow_failures(hero, view_width)
    assert "letter-spacing: 0" in hero
    assert "letter-spacing: 0." not in hero
    rx_values = [float(value) for value in re.findall(r' rx="([0-9.]+)"', hero)]
    assert rx_values
    assert max(rx_values) <= 8


# Scenario: The v1.0 release checklist requires contributor engine guidance.
# Expected: CONTRIBUTING includes the canonical adapter workflow and safeguards.
def test_contributing_engine_adapter_walkthrough() -> None:
    text = _contributing_text()
    for phrase in (
        "## Add An Engine Adapter",
        "py/engines/",
        "LiteLLMProviderAdapter",
        "EngineAdapter",
        "EngineInfo",
        "build_command()",
        "detect_failure()",
        "mainspring engines --json",
        "mainspring --engine <name> --review-engine codex --dry-run --once",
        "Do not edit `mainspring.sh`",
        "Keep provider credentials out of fixtures",
    ):
        assert phrase in text
