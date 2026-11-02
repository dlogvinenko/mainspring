# SPDX-License-Identifier: Apache-2.0
"""Release-hygiene tests for machine-specific path leakage."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = [
    REPO_ROOT / ".github",
    REPO_ROOT / ".env.example",
    REPO_ROOT / ".gitignore",
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "docs",
    REPO_ROOT / "lib",
    REPO_ROOT / "method",
    REPO_ROOT / "packaging",
    REPO_ROOT / "presets",
    REPO_ROOT / "py",
    REPO_ROOT / "schema",
    REPO_ROOT / "tests",
    REPO_ROOT / "CHANGELOG.md",
    REPO_ROOT / "CONTRIBUTING.md",
    REPO_ROOT / "LICENSE",
    REPO_ROOT / "Makefile",
    REPO_ROOT / "NOTICE",
    REPO_ROOT / "SECURITY.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "mainspring.sh",
    REPO_ROOT / "pyproject.toml",
    REPO_ROOT / "requirements.txt",
]
PUBLIC_COPY_ROOTS = [
    REPO_ROOT / ".github",
    REPO_ROOT / ".env.example",
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "CHANGELOG.md",
    REPO_ROOT / "CONTRIBUTING.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "SECURITY.md",
    REPO_ROOT / "docs",
    REPO_ROOT / "lib",
    REPO_ROOT / "method",
    REPO_ROOT / "packaging",
    REPO_ROOT / "presets",
    REPO_ROOT / "schema",
    REPO_ROOT / "mainspring.sh",
    REPO_ROOT / "pyproject.toml",
]
EXCLUDED_PARTS = {
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "mainspring.egg-info",
}
TEXT_SUFFIXES = {
    ".bats",
    ".cast",
    ".env",
    ".example",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".svg",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {"LICENSE", "Makefile", "NOTICE"}
MACHINE_PATH_PATTERNS = {
    "macos_user_home": re.compile(r"/Users/[A-Za-z0-9._-]+(?:/|$)"),
    "linux_user_home": re.compile(r"/home/[A-Za-z0-9._-]+(?:/|$)"),
    "windows_user_home": re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+"),
    "macos_temp_dir": re.compile(r"/var/" r"folders/[A-Za-z0-9._/-]+"),
}

FORBIDDEN_PUBLIC_STRINGS = [
    "Release" + ":",
    "Common " + "commands",
    "Normal " + "Commands",
    "Base " + "command",
    "Arguments / " + "options",
    "Script " + "output:",
    "product" + "-doc",
    "Global " + "HUD",
    "AI coding for " + "serious" + " projects",
    "serious " + "local" + " projects",
    "safe writer/" + "reviewer handshake",
    "release-status box",
    "old monolith " + "audit",
    "mainspring " + "final" + "ize",
    "final" + "ize [list|squash|draft]",
    "py/" + "final" + "ize.py",
    "history-" + "hygiene",
    "history_" + "hygiene.py",
    "release" + "-candidate",
    "current " + "RC",
    "release-" + "RC",
    "autonomous " + "coding loop",
    "Autonomous AI execution loop",
    "gh repo create " + "mainspring",
    "git tag -a " + "v1.0.0",
    "scripts/" + "mainspring",
    "tools/" + "mainspring-method",
    "docs/" + "mainspring/prd.md",
    "docs/" + "mainspring/guide.md",
    "/tmp/" + "mainspring-loop",
    "699" + " pytest",
    "708" + " pytest",
    "739" + " pytest",
    "794" + " pytest",
    "1098" + " pytest",
    "1100" + " pytest",
    "1101" + " pytest",
    "1102" + " pytest",
    "1103" + " pytest",
    "1103" + " passed",
    "1108" + " pytest",
    "1108" + " passed",
    "1110" + " pytest",
    "1110" + " passed",
    "1112" + " pytest",
    "1112" + " passed",
    "1113" + " pytest",
    "1113" + " passed",
    "1118" + " passed",
    "1119" + " pytest",
    "1119" + " passed",
    "1120" + " pytest",
    "1120" + " passed",
    "1121" + " pytest",
    "1121" + " passed",
    "1122" + " pytest",
    "1122" + " passed",
    "1081" + " pytest",
    "1081" + " passed",
    "210" + " Bats",
    "210" + " bats",
    "202" + " bats",
    "202" + " Bats",
    "203" + " Bats",
    "205" + " bats",
    "205" + " Bats",
    "206" + " bats",
    "206" + " Bats",
    "208" + " bats",
    "208" + " Bats",
    "209" + " bats",
    "209" + " Bats",
    "211" + " bats",
    "211" + " Bats",
    "1147" + " pytest",
    "91.2" + "%",
    "91.1" + "%",
    "coverage-91.2",
    "coverage-91.1",
    "11130" + "/12210",
    "11160" + "/12257",
    "11161" + "/12257",
    "10805" + "/11878",
    "11190" + "/12290",
    "11200" + "/12303",
    "11204" + "/12307",
    "11215" + "/12321",
    "11216" + "/12321",
    "11227" + "/12321",
    "11228" + "/12321",
    "11239" + "/12333",
    "11240" + "/12334",
    "docs/prd.md` (1425" + " LOC)",
    "Method package LOC       | 1678",
    "Public Method doc LOC    | 389",
    "Skill source LOC         | 174",
    "705" + "/1000",
    "source release at " + "705",
    "201" + " Bats",
    "199" + " Bats",
    "PERPLEXITY" + "_API_KEY",
    "GROQ" + "_API_KEY",
    "GITHUB" + "_API_KEY",
    "AZURE_OPENAI" + "_API_KEY",
    "OLLAMA" + "_API_KEY",
    "YOUR" + "_TOKEN",
    "gh" + "p_",
    "github" + "_pat_",
    "sk" + "-proj-",
    "sk-ant" + "-api",
    "pp" + "lx-",
    "claude-mem-" + "context",
    "Memory " + "Context",
    "OMX" + "_",
    "OMX " + "ultrawork",
    "oh-my-" + "codex",
    "omx-" + "loop",
    "completed " + "OMX wave",
    "hook_run_" + "id",
    "feedback_mainspring_method.md",
    "Rune" + "Lite",
    "OS" + "RS",
    "run" + "elite-",
    "os" + "rs-",
    "Dmitri" + "HQ",
    "pkill -f " + "mainspring",
    "rm " + ".mainspring/state/mainspring.lock",
    "tmux " + "kill-server",
    "omx " + "team shutdown",
    "bash " + "eval",
    'eval "$(fnm env',
    "shell" + "=True",
    "os" + ".system(",
    "User has formalized",
    "the " + "user has been " + "burned",
    "author burned " + "cycles",
    "the user expects you",
    "future sessions that you use the Method",
    "real " + "cigarettes",
]
SECRET_PATTERNS = {
    "openai_token": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    "github_pat": re.compile("github" + r"_pat_[A-Za-z0-9_]{20,}"),
    "github_legacy_token": re.compile("gh" + r"p_[A-Za-z0-9_]{20,}"),
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    "private_key": re.compile(r"BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY"),
}


def _text_files_under(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            paths = [root]
        elif root.is_dir():
            paths = [path for path in root.rglob("*") if path.is_file()]
        else:
            continue
        for path in paths:
            if EXCLUDED_PARTS.intersection(path.parts):
                continue
            if path.suffix in TEXT_SUFFIXES or path.name in TEXT_FILENAMES:
                files.append(path)
    return sorted(files)


def _candidate_files() -> list[Path]:
    return [path for path in _text_files_under(SCAN_ROOTS) if path != Path(__file__)]


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return [REPO_ROOT / line for line in result.stdout.splitlines() if line.strip()]


# Scenario: The hardcoded-path guard should fail closed if future repo moves make
# its scan roots stale.
# Expected: the current standalone release tree is represented in candidates.
def test_hardcoded_path_scan_covers_current_release_tree() -> None:
    candidates = {path.relative_to(REPO_ROOT) for path in _candidate_files()}

    assert Path("mainspring.sh") in candidates
    assert Path(".env.example") in candidates
    assert Path("docs/assets/readme-hero.svg") in candidates
    assert Path("docs/assets/hud-preview.svg") in candidates
    assert Path("docs/assets/hud-demo.cast") in candidates
    assert Path("method/README.md") in candidates
    assert Path("AGENTS.md") in candidates
    assert Path("LICENSE") in candidates
    assert Path("NOTICE") in candidates
    assert Path("SECURITY.md") in candidates


# Scenario: future public text files should not silently bypass release-hygiene
# scanning.
# Expected: every tracked text-like source, doc, config, and test file is in the
# machine-path/secret/retired-command candidate set.
def test_hardcoded_path_scan_covers_all_tracked_text_files() -> None:
    candidates = {path.relative_to(REPO_ROOT) for path in _candidate_files()}
    fixture_file = Path(__file__).resolve().relative_to(REPO_ROOT)
    expected = {
        path.relative_to(REPO_ROOT)
        for path in _tracked_files()
        if (path.suffix in TEXT_SUFFIXES or path.name in TEXT_FILENAMES)
        and path.relative_to(REPO_ROOT) != fixture_file
    }

    assert expected - candidates == set()


# Scenario: P7 release safety requires the extracted Mainspring tree to be
# portable and free of local operator machine paths.
# Expected: source, release docs, and method-package files contain no
# hardcoded user-specific absolute paths.
def test_mainspring_release_tree_has_no_hardcoded_user_paths() -> None:
    hits = []
    for path in _candidate_files():
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in MACHINE_PATH_PATTERNS.items():
                if pattern.search(line):
                    location = f"{path.relative_to(REPO_ROOT)}:{line_number}"
                    hits.append(f"{location}: {label}: {line.strip()}")

    assert hits == []


# Scenario: the public repository must not re-introduce removed release-owner
# command surfaces, stale release counters, or real token-shaped secrets.
# Expected: public text files stay free of removed release-owner command
# surfaces, machine-private paths, and credential material.
def test_public_tree_has_no_removed_cli_or_secret_junk() -> None:
    hits = []
    for path in _candidate_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT)
        for forbidden in FORBIDDEN_PUBLIC_STRINGS:
            if forbidden in text:
                hits.append(f"{rel}: forbidden string: {forbidden}")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(line):
                    hits.append(f"{rel}:{line_number}: {label}")

    assert hits == []


# Scenario: public release copy should not read like a private migration log.
# Expected: user-facing docs, CLI help, templates, and packaging metadata avoid
# internal helper names and scratchpad vocabulary.
def test_public_copy_omits_internal_release_jargon() -> None:
    forbidden = (
        "release-" + "helper archaeology",
        "hidden release-" + "helper state updates",
        "internal audit scaffolding",
        "publication-only helper commands",
        "private development history",
        "private extraction helper",
        "specialized release-" + "proof commands",
        "proof-" + "state",
        "use-standard-" + "proof-" + "state",
        "release-" + "blockers",
        "release-" + "notes",
        "Command " + "map",
        "command " + "map",
        "old temporary loop paths",
        "temporary checkpoint scaffolding",
    )
    hits = []
    for path in _text_files_under(PUBLIC_COPY_ROOTS):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT)
        for phrase in forbidden:
            if phrase in text:
                hits.append(f"{rel}: {phrase}")

    assert hits == []


# Scenario: maintainer-only history scripts create confusing public
# surface area when they are not supported commands.
# Expected: the public source tree no longer tracks those removed helper files.
def test_maintainer_only_history_helpers_are_not_tracked() -> None:
    forbidden_paths = [
        "py/history_" + "hygiene.py",
        "py/tests/test_history_" + "hygiene.py",
    ]
    tracked = subprocess.run(
        ["git", "ls-files", *forbidden_paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    deleted = subprocess.run(
        ["git", "ls-files", "--deleted", *forbidden_paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    tracked_paths = set(tracked.stdout.splitlines())
    pending_deleted_paths = set(deleted.stdout.splitlines())

    assert tracked.returncode == 0
    assert deleted.returncode == 0
    assert tracked_paths - pending_deleted_paths == set()


# Scenario: Runtime backlog state is useful locally but noisy and potentially
# machine-specific in a public source release.
# Expected: the repository ignores .taskmaster/ and does not track live backlog
# state, task ledgers, or Taskmaster provider config.
def test_taskmaster_runtime_state_is_not_tracked() -> None:
    result = subprocess.run(
        ["git", "ls-files", ".taskmaster"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


# Scenario: local runtime directories are useful while developing, but they are
# machine-specific and must not be tracked or accidentally suggested for public
# release commits.
# Expected: every runtime directory is gitignored and absent from the index.
def test_runtime_state_directories_are_ignored_and_not_tracked() -> None:
    runtime_dirs = [
        ".mainspring",
        ".omx",
        ".taskmaster",
        ".claude",
        ".codex",
        "node_modules",
    ]
    gitignore_lines = (
        (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    )
    tracked = subprocess.run(
        ["git", "ls-files", *runtime_dirs],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    ignored = subprocess.run(
        ["git", "check-ignore", *[f"{runtime_dir}/" for runtime_dir in runtime_dirs]],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    for runtime_dir in runtime_dirs:
        assert f"{runtime_dir}/" in gitignore_lines
    assert tracked.returncode == 0
    assert tracked.stdout.strip() == ""
    assert ignored.returncode == 0
    assert ignored.stdout.splitlines() == [f"{path}/" for path in runtime_dirs]


# Scenario: Real environment files should never be accidentally staged in a
# public source release, while the empty example file remains tracked.
# Expected: .env variants are ignored and .env.example is the only tracked env
# file.
def test_env_secret_files_are_ignored_except_example() -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", ".env", ".env.local", ".env.production"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    tracked = subprocess.run(
        ["git", "ls-files", ".env.example", ".env", ".env.local", ".env.production"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert ignored.returncode == 0
    assert ignored.stdout.splitlines() == [".env", ".env.local", ".env.production"]
    assert tracked.returncode == 0
    assert tracked.stdout.splitlines() == [".env.example"]


# Scenario: Public releases must not ship private per-user memory snippets.
# Expected: the Method ships reusable skill/templates only.
def test_method_private_memory_entries_are_not_tracked() -> None:
    memory_dir = REPO_ROOT / "method" / "memory"

    assert not memory_dir.exists()


# Scenario: shell launch paths must not regress to inline Python snippets.
# Expected: Bash dispatches and Python scripts compute in named .py files.
def test_shell_sources_do_not_embed_python_snippets() -> None:
    shell_files = [
        *REPO_ROOT.glob("*.sh"),
        *REPO_ROOT.glob("lib/*.sh"),
    ]
    forbidden_patterns = ("python3 -c", "python -c", "python3 - <<", "<<'PY'", "<<PY")
    hits = []
    for path in sorted(shell_files):
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(pattern in line for pattern in forbidden_patterns):
                hits.append(
                    f"{path.relative_to(REPO_ROOT)}:{line_number}: {line.strip()}"
                )

    assert hits == []


# Scenario: packaged Mainspring should run helper scripts with its resolved
# runtime Python instead of whichever python3 happens to be on PATH.
# Expected: sourced shell modules call mainspring_python for Mainspring helpers;
# the only launcher-level bare python3 helper is the optional early fnm bootstrap
# that runs before common.sh is available.
def test_shell_helpers_use_resolved_mainspring_python() -> None:
    hits = []
    for path in sorted((REPO_ROOT / "lib").glob("*.sh")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if 'python3 "$MAINSPRING_PY_DIR/' in line:
                hits.append(
                    f"{path.relative_to(REPO_ROOT)}:{line_number}: {line.strip()}"
                )
            if 'python3 "${' in line:
                hits.append(
                    f"{path.relative_to(REPO_ROOT)}:{line_number}: {line.strip()}"
                )

    for line_number, line in enumerate(
        (REPO_ROOT / "mainspring.sh").read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if 'python3 "$MAINSPRING_PY_DIR/' in line and "fnm_env.py" not in line:
            hits.append(f"mainspring.sh:{line_number}: {line.strip()}")

    assert hits == []
