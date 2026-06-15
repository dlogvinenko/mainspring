# Security Policy

Mainspring is a local operator tool. It can read project files, launch AI coding
CLIs, call configured providers, and send Telegram notifications when you enable
them, so security reports should be handled carefully.

## Supported Versions

The public source release supports the current `main` branch and the latest
published `v1.x` tag once tags are available.

## Reporting A Vulnerability

Do not post live tokens, private logs, exploit details, or sensitive project
files in a public issue.

Use GitHub private vulnerability reporting or a GitHub Security Advisory when
available. If that channel is not enabled yet, open a minimal public issue that
says a private security report is needed, without including the vulnerability
details.

Useful report details:

- affected Mainspring version or commit
- operating system and shell
- command that triggered the issue, with secrets removed
- whether the issue involves provider credentials, Telegram notifications,
  runtime state, team worktrees, or generated logs

## Secret Handling

Mainspring should never require committing provider keys, Telegram tokens,
runtime logs, `.mainspring/`, `.codex/`, `.claude/`, legacy runtime dirs,
`.env`, or Taskmaster runtime state. The repository ships `.env.example` with
empty placeholders only.

Treat `.mainspring/logs/`, `waves.jsonl`, prompt snapshots, notifier logs, and
team worktrees as sensitive local runtime evidence. They can include project
paths, filenames, prompts, model output, failure details, and notification
context. Do not paste them into public issues without review and redaction.

If a real token or private log is committed by mistake, rotate the credential
first, remove the material from the public branch, and include the affected
commit hash only in the private security report.
