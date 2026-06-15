#!/usr/bin/env bats
# shellcheck shell=bash disable=SC1007,SC1090,SC2034
# SPDX-License-Identifier: Apache-2.0
# test_wizard.bats — exercise apply_pair_mode() and apply_default_models_for_current_pair()
#   from lib/wizard.sh.

setup() {
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT_DIR="$ROOT_DIR"
  MAINSPRING_SH="${MAINSPRING_SH:-$ROOT_DIR/mainspring.sh}"
  COMMON_LIB="$ROOT_DIR/lib/common.sh"
  WIZARD_LIB="$ROOT_DIR/lib/wizard.sh"
  DRY_RUN_LIB="$ROOT_DIR/lib/dry_run.sh"
  MAINSPRING_PY_DIR="$ROOT_DIR/py"
  unset MAINSPRING_RUNTIME_DIR
  unset MAINSPRING_STATE_DIR
  unset MAINSPRING_ENGINE_USAGE_FILE
  unset MAINSPRING_WAVE_USAGE_FILE
  # Defaults needed by apply_default_models_for_current_pair
  DEFAULT_CODEX_MODEL="gpt-5.5"
  DEFAULT_CLAUDE_MODEL="opus"
  DEFAULT_FAST_CODEX_MODEL="gpt-5.4-mini"
}

_load_wizard() {
  if [ ! -f "$WIZARD_LIB" ]; then
    skip "required helper missing: $WIZARD_LIB"
  fi
  source "$COMMON_LIB"
  source "$WIZARD_LIB"
  source "$DRY_RUN_LIB"
  if ! declare -f apply_pair_mode >/dev/null 2>&1; then
    skip "apply_pair_mode not exported by $WIZARD_LIB"
  fi
}

# Scenario: claude+claude -> both engines become claude.
# Expected: $ENGINE and $REVIEW_ENGINE both equal "claude".
@test "apply_pair_mode claude+claude sets both engines to claude" {
  _load_wizard
  ENGINE=""
  REVIEW_ENGINE=""
  apply_pair_mode "claude+claude"
  [ "$ENGINE" = "claude" ]
  [ "$REVIEW_ENGINE" = "claude" ]
}

# Scenario: claude+codex -> writer is claude, reviewer is codex.
# Expected: $ENGINE=claude, $REVIEW_ENGINE=codex.
@test "apply_pair_mode claude+codex sets writer=claude reviewer=codex" {
  _load_wizard
  ENGINE=""
  REVIEW_ENGINE=""
  apply_pair_mode "claude+codex"
  [ "$ENGINE" = "claude" ]
  [ "$REVIEW_ENGINE" = "codex" ]
}

# Scenario: codex+codex -> both engines become codex.
# Expected: $ENGINE and $REVIEW_ENGINE both equal "codex".
@test "apply_pair_mode codex+codex sets both engines to codex" {
  _load_wizard
  ENGINE=""
  REVIEW_ENGINE=""
  apply_pair_mode "codex+codex"
  [ "$ENGINE" = "codex" ]
  [ "$REVIEW_ENGINE" = "codex" ]
}

# Scenario: codex+claude -> writer is codex, reviewer is claude.
# Expected: $ENGINE=codex, $REVIEW_ENGINE=claude.
@test "apply_pair_mode codex+claude sets writer=codex reviewer=claude" {
  _load_wizard
  ENGINE=""
  REVIEW_ENGINE=""
  apply_pair_mode "codex+claude"
  [ "$ENGINE" = "codex" ]
  [ "$REVIEW_ENGINE" = "claude" ]
}

# Scenario: a registered non-default engine can be selected as a pair member.
# Expected: generic registry-backed pair parsing sets writer=gemini reviewer=claude.
@test "apply_pair_mode accepts registered engine pairs" {
  _load_wizard
  ENGINE=""
  REVIEW_ENGINE=""
  apply_pair_mode "gemini+claude"
  [ "$ENGINE" = "gemini" ]
  [ "$REVIEW_ENGINE" = "claude" ]
}

# Scenario: unknown pair mode.
# Expected: exits non-zero.
@test "apply_pair_mode unknown pair exits with error" {
  _load_wizard
  run bash -c "
    source '$COMMON_LIB'
    source '$WIZARD_LIB'
    apply_pair_mode 'grok+grok'
  "
  [ "$status" -ne 0 ]
}

# Scenario: apply_default_models_for_current_pair with codex writer + claude reviewer.
# Expected: MODEL_OVERRIDE and REVIEW_MODEL_OVERRIDE come from registry defaults,
# including existing operator env overrides for codex/claude.
@test "apply_default_models sets codex writer model and claude reviewer model" {
  _load_wizard
  export MAINSPRING_DEFAULT_CODEX_MODEL="gpt-fixture-frontier"
  export MAINSPRING_DEFAULT_CLAUDE_MODEL="claude-fixture-opus"
  ENGINE="codex"
  REVIEW_ENGINE="claude"
  MODEL_OVERRIDE=""
  REVIEW_MODEL_OVERRIDE=""
  apply_default_models_for_current_pair
  [ "$MODEL_OVERRIDE" = "gpt-fixture-frontier" ]
  [ "$REVIEW_MODEL_OVERRIDE" = "claude-fixture-opus" ]
}

# Scenario: registered non-default engines get their registry default model.
# Expected: gemini defaults to the LiteLLM provider model while claude still
# honors its env override through registry metadata.
@test "apply_default_models uses registry default for registered extra engines" {
  _load_wizard
  export MAINSPRING_DEFAULT_CLAUDE_MODEL="claude-fixture-opus"
  ENGINE="gemini"
  REVIEW_ENGINE="claude"
  MODEL_OVERRIDE=""
  REVIEW_MODEL_OVERRIDE=""
  apply_default_models_for_current_pair
  [ "$MODEL_OVERRIDE" = "gemini/gemini-2.5-pro" ]
  [ "$REVIEW_MODEL_OVERRIDE" = "claude-fixture-opus" ]
}

# Scenario: Mainspring-name environment variables are the public defaults.
# Expected: MAINSPRING_* values win and stale legacy aliases are ignored.
@test "dry-run ignores legacy env aliases when MAINSPRING values are set" {
  local legacy_prefix="OMX""_LOOP"
  run env \
    MAINSPRING_NOTIFY_ENABLED=0 \
    MAINSPRING_ENGINE="codex" \
    "${legacy_prefix}_ENGINE=claude" \
    MAINSPRING_REVIEW_ENGINE="claude" \
    "${legacy_prefix}_REVIEW_ENGINE=codex" \
    MAINSPRING_DEFAULT_CODEX_MODEL="gpt-main-frontier" \
    "${legacy_prefix}_DEFAULT_CODEX_MODEL=gpt-legacy-frontier" \
    MAINSPRING_DEFAULT_CLAUDE_MODEL="claude-main-opus" \
    "${legacy_prefix}_DEFAULT_CLAUDE_MODEL=claude-legacy-opus" \
    MAINSPRING_CODEX_REASONING_EFFORT="high" \
    "${legacy_prefix}_CODEX_REASONING_EFFORT=low" \
    MAINSPRING_SPEED_PROFILE="fast" \
    "${legacy_prefix}_SPEED_PROFILE=max" \
    MAINSPRING_MAX_AGENTS="3" \
    "${legacy_prefix}_MAX_AGENTS=6" \
    MAINSPRING_AUTO_RETRY_CI="2" \
    "${legacy_prefix}_AUTO_RETRY_CI=0" \
    MAINSPRING_TOPOLOGY="solo" \
    "${legacy_prefix}_TOPOLOGY=team" \
    MAINSPRING_AUTO_CHECKPOINT="false" \
    "${legacy_prefix}_AUTO_CHECKPOINT=true" \
    "$MAINSPRING_SH" --dry-run --once

  [ "$status" -eq 0 ]
  [[ "$output" == *"Writer engine:     codex"* ]]
  [[ "$output" == *"Writer model:      gpt-main-frontier"* ]]
  [[ "$output" == *"Reviewer engine:   claude"* ]]
  [[ "$output" == *"Reviewer model:    claude-main-opus"* ]]
  [[ "$output" == *"Speed profile:     fast"* ]]
  [[ "$output" == *"Max agents:        3"* ]]
  [[ "$output" == *"Auto-retry CI:     2"* ]]
  [[ "$output" == *"Topology:          solo"* ]]
  [[ "$output" == *"Auto-checkpoint:   false"* ]]
  [[ "$output" == *"Reasoning effort:  high"* ]]
  [[ "$output" != *"gpt-legacy-frontier"* ]]
  [[ "$output" != *"claude-legacy-opus"* ]]
}

# Scenario: A stale pre-v1 env alias is present in the shell.
# Expected: Dry-run ignores it and uses the public default without noise.
@test "dry-run ignores legacy env fallback" {
  local legacy_prefix="OMX""_LOOP"
  run env \
    MAINSPRING_NOTIFY_ENABLED=0 \
    "${legacy_prefix}_SPEED_PROFILE=fast" \
    "$MAINSPRING_SH" --dry-run --once --topology solo

  [ "$status" -eq 0 ]
  [[ "$output" == *"Speed profile:     max"* ]]
  [[ "$output" != *"${legacy_prefix}_SPEED_PROFILE"* ]]
}

# Scenario: public installs should not require the external team backend for the
# default dry-run/start path.
# Expected: topology defaults to solo unless a preset, config, or CLI flag
# explicitly selects team mode.
@test "dry-run defaults to solo topology for public first run" {
  MAINSPRING_NOTIFY_ENABLED=0 run "$MAINSPRING_SH" --dry-run --once

  [ "$status" -eq 0 ]
  [[ "$output" == *"Topology:          solo"* ]]
}

# Scenario: P7 runtime paths can be moved to the Mainspring runtime root without
# changing the rest of dry-run behavior.
# Expected: all resolved runtime files point under MAINSPRING_RUNTIME_DIR.
@test "dry-run resolves runtime paths under MAINSPRING_RUNTIME_DIR" {
  local runtime_dir="$BATS_TEST_TMPDIR/custom-runtime"

  MAINSPRING_NOTIFY_ENABLED=0 \
  MAINSPRING_RUNTIME_DIR="$runtime_dir" \
  run "$MAINSPRING_SH" --dry-run --once --topology solo

  [ "$status" -eq 0 ]
  [[ "$output" == *"Runtime dir:       $runtime_dir"* ]]
  [[ "$output" == *"State dir:         $runtime_dir/state"* ]]
  [[ "$output" == *"Log dir:           $runtime_dir/logs"* ]]
  [[ "$output" == *"Lock file:         $runtime_dir/state/mainspring.lock"* ]]
  [[ "$output" == *"Wave ledger:       $runtime_dir/logs/waves.jsonl"* ]]
  [[ "$output" == *"Last-run file:     $runtime_dir/state/last-run.env"* ]]
  [ -d "$runtime_dir/state" ]
}

# Scenario: last-run subcommand prints saved setup without launching work.
# Expected: output shows the settings file and repeat commands.
@test "mainspring last-run shows saved project settings" {
  local runtime_dir="$BATS_TEST_TMPDIR/runtime-last-run"
  mkdir -p "$runtime_dir/state"
  cat > "$runtime_dir/state/last-run.env" <<'ENV'
MODE=taskmaster
PAIR_MODE=codex+codex
ENGINE=codex
MODEL_OVERRIDE=gpt-5.5
REVIEW_ENGINE=codex
REVIEW_MODEL_OVERRIDE=gpt-5.5
TOPOLOGY=team
SPEED_PROFILE=max
MAX_AGENTS=6
AGENT_MODE=code
RUN_ONCE=false
AUTO_RETRY_CI=1
AUTO_CHECKPOINT=true
ENV

  MAINSPRING_NOTIFY_ENABLED=0 \
  MAINSPRING_RUNTIME_DIR="$runtime_dir" \
  run "$MAINSPRING_SH" last-run

  [ "$status" -eq 0 ]
  [[ "$output" == *"Mainspring Last Run"* ]]
  [[ "$output" == *"Settings file: $runtime_dir/state/last-run.env"* ]]
  [[ "$output" == *"Mode:          taskmaster"* ]]
  [[ "$output" == *"Pair:          codex+codex"* ]]
  [[ "$output" == *"mainspring --last-run"* ]]
  [[ "$output" == *"mainspring --last-run --dry-run"* ]]
}

# Scenario: last-run JSON is machine-readable.
# Expected: JSON contains summary and repeat commands.
@test "mainspring last-run supports json output" {
  local runtime_dir="$BATS_TEST_TMPDIR/runtime-last-run-json"
  mkdir -p "$runtime_dir/state"
  cat > "$runtime_dir/state/last-run.env" <<'ENV'
MODE=night
PRD_PATH=docs/prd.md
RUN_ONCE=true
ENV

  MAINSPRING_NOTIFY_ENABLED=0 \
  MAINSPRING_RUNTIME_DIR="$runtime_dir" \
  run "$MAINSPRING_SH" last-run --json

  [ "$status" -eq 0 ]
  [[ "$output" == *'"mode": "night"'* ]]
  [[ "$output" == *'"topology": "solo"'* ]]
  [[ "$output" == *'"run": "one-shot"'* ]]
  [[ "$output" == *'"preview_here": "mainspring --last-run --dry-run"'* ]]
}

# Scenario: humans and agents ask how last-run/resume works before a project
# has saved settings.
# Expected: help exits cleanly and does not require last-run.env.
@test "mainspring last-run help explains resume without saved settings" {
  local runtime_dir="$BATS_TEST_TMPDIR/runtime-last-run-help"
  mkdir -p "$runtime_dir/state"

  MAINSPRING_NOTIFY_ENABLED=0 \
  MAINSPRING_RUNTIME_DIR="$runtime_dir" \
  run "$MAINSPRING_SH" last-run --help

  [ "$status" -eq 0 ]
  [[ "$output" == *"Mainspring Last Run"* ]]
  [[ "$output" == *"mainspring last-run"* ]]
  [[ "$output" == *"mainspring --last-run --dry-run"* ]]
  [[ "$output" == *"Product Requirements Document (PRD)"* ]]
  [[ "$output" != *"Unknown show option"* ]]
  [[ "$output" != *"No last-run settings found"* ]]
}

# Scenario: plain first run has no interactive stdin.
# Expected: it exits with actionable guidance before printing the wizard
# heading or starting from incomplete setup.
@test "plain mainspring without stdin explains guided setup instead of taskmaster internals" {
  local project="$BATS_TEST_TMPDIR/fresh-first-run"
  mkdir -p "$project"

  MAINSPRING_NOTIFY_ENABLED=0 \
  MAINSPRING_CONSOLE_ENTRYPOINT=1 \
  MAINSPRING_PROJECT_ROOT="$project" \
  MAINSPRING_RUNTIME_DIR="$project/.mainspring" \
  run "$MAINSPRING_SH" < /dev/null

  [ "$status" -eq 2 ]
  [[ "$output" != *"=== Mainspring Wizard ==="* ]]
  [[ "$output" == *"Mainspring needs an interactive terminal or piped answers"* ]]
  [[ "$output" == *"Pipe wizard answers"* ]]
  [[ "$output" != *"  mainspring --wizard"* ]]
  [[ "$output" == *"mainspring last-run          inspect saved setup, if any"* ]]
  [[ "$output" == *"mainspring --last-run        resume saved setup, if any"* ]]
  [[ "$output" == *"mainspring --dry-run --once  preview default setup with zero API calls"* ]]
  [[ "$output" == *"mainspring init checkout-redesign  scaffold PRD-backed starter docs"* ]]
  [[ "$output" == *"replace checkout-redesign with your feature name"* ]]
  local old_init_placeholder="mainspring init <project""-name>"
  [[ "$output" != *"$old_init_placeholder"* ]]
  [[ "$output" != *"Usage snapshot"* ]]
  [[ "$output" != *"Choose execution source:"* ]]
  [[ "$output" != *".taskmaster directory not found"* ]]
}

# Scenario: explicit wizard has no interactive stdin.
# Expected: it fails closed with the same operator-facing guidance before
# printing the wizard heading or launching the default loop.
@test "explicit wizard without stdin fails closed with setup guidance" {
  local project="$BATS_TEST_TMPDIR/fresh-explicit-wizard"
  mkdir -p "$project"

  MAINSPRING_NOTIFY_ENABLED=0 \
  MAINSPRING_CONSOLE_ENTRYPOINT=1 \
  MAINSPRING_PROJECT_ROOT="$project" \
  MAINSPRING_RUNTIME_DIR="$project/.mainspring" \
  run "$MAINSPRING_SH" --wizard < /dev/null

  [ "$status" -eq 2 ]
  [[ "$output" != *"=== Mainspring Wizard ==="* ]]
  [[ "$output" == *"Mainspring needs an interactive terminal or piped answers"* ]]
  [[ "$output" == *"Pipe wizard answers"* ]]
  [[ "$output" != *"  mainspring --wizard"* ]]
  [[ "$output" == *"mainspring last-run          inspect saved setup, if any"* ]]
  [[ "$output" == *"mainspring --last-run        resume saved setup, if any"* ]]
  [[ "$output" == *"mainspring --dry-run --once  preview default setup with zero API calls"* ]]
  [[ "$output" == *"mainspring init checkout-redesign  scaffold PRD-backed starter docs"* ]]
  [[ "$output" == *"replace checkout-redesign with your feature name"* ]]
  local old_init_placeholder="mainspring init <project""-name>"
  [[ "$output" != *"$old_init_placeholder"* ]]
  [[ "$output" != *"Usage snapshot"* ]]
  [[ "$output" != *"Choose execution source:"* ]]
  [[ "$output" != *".taskmaster directory not found"* ]]
}

# Scenario: plain interactive wizard sees an existing last-run file.
# Expected: the first choice can continue with saved settings without asking
# through the full setup wizard again.
@test "run_wizard offers saved setup before manual questions" {
  local runtime_dir="$BATS_TEST_TMPDIR/runtime-wizard-resume"
  mkdir -p "$runtime_dir/state"
  cat > "$runtime_dir/state/last-run.env" <<'ENV'
MODE=taskmaster
PAIR_MODE=codex+codex
ENGINE=codex
MODEL_OVERRIDE=gpt-5.5
REVIEW_ENGINE=codex
REVIEW_MODEL_OVERRIDE=gpt-5.5
TOPOLOGY=solo
SPEED_PROFILE=max
MAX_AGENTS=6
AGENT_MODE=code
RUN_ONCE=false
AUTO_RETRY_CI=0
AUTO_CHECKPOINT=true
ENV

  run bash -c "
    ROOT_DIR='$ROOT_DIR'
    SCRIPT_DIR='$SCRIPT_DIR'
    MAINSPRING_PY_DIR='$MAINSPRING_PY_DIR'
    LAST_RUN_FILE='$runtime_dir/state/last-run.env'
    WIZARD_ALLOW_LAST_RUN_OFFER=true
    DEFAULT_CODEX_MODEL='gpt-5.5'
    DEFAULT_CLAUDE_MODEL='opus'
    DEFAULT_FAST_CODEX_MODEL='gpt-5.4-mini'
    source '$COMMON_LIB'
    source '$WIZARD_LIB'
    print_usage_snapshot() { echo 'USAGE-SNAPSHOT'; }
    run_wizard
    echo \"MODE=\$MODE\"
    echo \"PAIR=\$PAIR_MODE\"
    echo \"TOPOLOGY=\$TOPOLOGY\"
  " <<'EOF'
1
EOF

  [ "$status" -eq 0 ]
  [[ "$output" == *"Saved setup found for this project"* ]]
  [[ "$output" == *"Mainspring Last Run"* ]]
  [[ "$output" == *"Use saved setup?"* ]]
  [[ "$output" == *"Continuing with saved setup."* ]]
  [[ "$output" == *"MODE=taskmaster"* ]]
  [[ "$output" == *"PAIR=codex+codex"* ]]
  [[ "$output" == *"TOPOLOGY=solo"* ]]
  [[ "$output" != *"USAGE-SNAPSHOT"* ]]
  [[ "$output" != *"Choose execution source"* ]]
}

# Scenario: operator declines the saved setup.
# Expected: wizard falls through to the normal manual questions.
@test "run_wizard can ignore saved setup and choose manually" {
  local runtime_dir="$BATS_TEST_TMPDIR/runtime-wizard-manual"
  mkdir -p "$runtime_dir/state"
  cat > "$runtime_dir/state/last-run.env" <<'ENV'
MODE=taskmaster
PAIR_MODE=codex+codex
ENGINE=codex
REVIEW_ENGINE=codex
TOPOLOGY=solo
ENV

  run bash -c "
    ROOT_DIR='$ROOT_DIR'
    SCRIPT_DIR='$SCRIPT_DIR'
    MAINSPRING_PY_DIR='$MAINSPRING_PY_DIR'
    LAST_RUN_FILE='$runtime_dir/state/last-run.env'
    WIZARD_ALLOW_LAST_RUN_OFFER=true
    DEFAULT_CODEX_MODEL='gpt-5.5'
    DEFAULT_CLAUDE_MODEL='opus'
    DEFAULT_FAST_CODEX_MODEL='gpt-5.4-mini'
    LOG_DIR='$BATS_TEST_TMPDIR/logs'
    source '$COMMON_LIB'
    source '$WIZARD_LIB'
    print_usage_snapshot() { echo 'USAGE-SNAPSHOT'; }
    run_wizard
  " <<'EOF'
2
1
2
1
1
1
3
3
2
2
EOF

  [ "$status" -eq 0 ]
  [[ "$output" == *"Saved setup found for this project"* ]]
  [[ "$output" == *"USAGE-SNAPSHOT"* ]]
  [[ "$output" == *"Choose execution source"* ]]
  [[ "$output" == *"Pair:   codex+codex"* ]]
}

# Scenario: apply_default_models_for_current_pair does not override existing values.
# Expected: pre-set values are preserved.
@test "apply_default_models preserves existing model overrides" {
  _load_wizard
  ENGINE="codex"
  REVIEW_ENGINE="claude"
  MODEL_OVERRIDE="custom-model"
  REVIEW_MODEL_OVERRIDE="custom-review"
  apply_default_models_for_current_pair
  [ "$MODEL_OVERRIDE" = "custom-model" ]
  [ "$REVIEW_MODEL_OVERRIDE" = "custom-review" ]
}

# Scenario: metrics state has auto-disabled codex+codex.
# Expected: wizard hides it from default pair choices, so choice 2 selects claude+claude.
@test "run_wizard hides auto-disabled pairs from default list" {
  local state_dir="$BATS_TEST_TMPDIR/state"
  mkdir -p "$state_dir"
  cat > "$state_dir/disabled-pairs.json" <<'JSON'
{"disabled_pairs":["codex+codex"]}
JSON

  run bash -c "
    ROOT_DIR='$ROOT_DIR'
    SCRIPT_DIR='$SCRIPT_DIR'
    MAINSPRING_PY_DIR='$MAINSPRING_PY_DIR'
    MAINSPRING_STATE_DIR='$state_dir'
    DEFAULT_CODEX_MODEL='gpt-5.5'
    DEFAULT_CLAUDE_MODEL='opus'
    DEFAULT_FAST_CODEX_MODEL='gpt-5.4-mini'
    LOG_DIR='$BATS_TEST_TMPDIR/logs'
    source '$COMMON_LIB'
    source '$WIZARD_LIB'
    print_usage_snapshot() { :; }
    run_wizard
  " <<'EOF'
1
2
1
1
1
1
1
2
2
EOF
  [ "$status" -eq 0 ]
  [[ "$output" == *"Auto-disabled pairs hidden from defaults: codex+codex"* ]]
  [[ "$output" == *"Pair:   claude+claude"* ]]
  [[ "$output" == *"Writer mode: code"* ]]
}

# ---------------------------------------------------------------------------
# list_presets tests
# ---------------------------------------------------------------------------

# Scenario: list_presets with the standard presets directory.
# Expected: output contains all 3 shipped preset names.
@test "list_presets shows nightly-max, conservative-docs, fast-smoke" {
  _load_wizard
  run list_presets
  [ "$status" -eq 0 ]
  [[ "$output" == *"nightly-max"* ]]
  [[ "$output" == *"conservative-docs"* ]]
  [[ "$output" == *"fast-smoke"* ]]
}

# Scenario: list_presets shows descriptions from first comment line.
# Expected: output includes "Maximum quality" from nightly-max.env.
@test "list_presets shows preset descriptions" {
  _load_wizard
  run list_presets
  [ "$status" -eq 0 ]
  [[ "$output" == *"Maximum quality"* ]]
  [[ "$output" == *"Conservative docs"* ]]
  [[ "$output" == *"Quick smoke"* ]]
}

# ---------------------------------------------------------------------------
# load_preset tests
# ---------------------------------------------------------------------------

# Scenario: load_preset nightly-max sets expected globals.
# Expected: ENGINE=claude, REVIEW_ENGINE=codex, TOPOLOGY=team.
@test "load_preset nightly-max sets engine=claude review=codex topology=team" {
  _load_wizard
  ENGINE=""
  REVIEW_ENGINE=""
  TOPOLOGY=""
  SPEED_PROFILE=""
  load_preset "nightly-max"
  [ "$ENGINE" = "claude" ]
  [ "$REVIEW_ENGINE" = "codex" ]
  [ "$TOPOLOGY" = "team" ]
  [ "$SPEED_PROFILE" = "max" ]
}

# Scenario: load_preset fast-smoke sets expected globals.
# Expected: ENGINE=codex, REVIEW_ENGINE=codex, TOPOLOGY=solo, RUN_ONCE=true.
@test "load_preset fast-smoke sets engine=codex topology=solo run_once=true" {
  _load_wizard
  ENGINE=""
  REVIEW_ENGINE=""
  TOPOLOGY=""
  RUN_ONCE=""
  load_preset "fast-smoke"
  [ "$ENGINE" = "codex" ]
  [ "$REVIEW_ENGINE" = "codex" ]
  [ "$TOPOLOGY" = "solo" ]
  [ "$RUN_ONCE" = "true" ]
}

# Scenario: load_preset with nonexistent preset.
# Expected: exits non-zero with error message.
@test "load_preset nonexistent exits with error" {
  _load_wizard
  run bash -c "
    SCRIPT_DIR='$SCRIPT_DIR'
    MAINSPRING_PY_DIR='$MAINSPRING_PY_DIR'
    source '$COMMON_LIB'
    source '$WIZARD_LIB'
    load_preset 'nonexistent-preset'
  "
  [ "$status" -ne 0 ]
  [[ "$output" == *"Preset not found"* ]]
}

# Scenario: preset names are operator input and must not escape presets/.
# Expected: traversal/path-shaped names fail before any file lookup.
@test "load_preset rejects traversal-shaped preset names" {
  _load_wizard
  run bash -c "
    SCRIPT_DIR='$SCRIPT_DIR'
    MAINSPRING_PY_DIR='$MAINSPRING_PY_DIR'
    source '$COMMON_LIB'
    source '$WIZARD_LIB'
    load_preset '../private'
  "
  [ "$status" -ne 0 ]
  [[ "$output" == *"Invalid preset name"* ]]
  [[ "$output" != *"Preset not found"* ]]
}

# Scenario: project-local YAML config uses aliases and explicit CLI guards exist.
# Expected: load_mainspring_yaml applies YAML values but preserves USER_SET_* values.
@test "load_mainspring_yaml respects explicit CLI value guards" {
  _load_wizard
  local config_file="$BATS_TEST_TMPDIR/.mainspring.yaml"
  cat > "$config_file" <<'YAML'
speed-profile: max
max-agents: 4
topology: team
run-once: true
YAML

  SPEED_PROFILE="standard"
  USER_SET_SPEED_PROFILE=true
  MAX_AGENTS="1"
  USER_SET_MAX_AGENTS=false
  TOPOLOGY="solo"
  USER_SET_TOPOLOGY=true
  RUN_ONCE="false"
  USER_SET_RUN_ONCE=false

  load_mainspring_yaml "$config_file"

  [ "$SPEED_PROFILE" = "standard" ]
  [ "$MAX_AGENTS" = "4" ]
  [ "$TOPOLOGY" = "solo" ]
  [ "$RUN_ONCE" = "true" ]
}

# Scenario: top-level launcher loads preset, then project YAML, then keeps CLI flags.
# Expected: YAML wins over preset values, while --topology remains explicit.
@test "mainspring project YAML overrides preset but not CLI flags" {
  local config_file="$BATS_TEST_TMPDIR/.mainspring.yaml"
  cat > "$config_file" <<'YAML'
pair-mode: codex+codex
model-override: gpt-5.5
review-model-override: gpt-5.5
speed-profile: standard
max-agents: 3
topology: solo
run-once: true
YAML

  MAINSPRING_CONFIG_FILE="$config_file" run "$MAINSPRING_SH" --preset nightly-max --dry-run --topology team
  [ "$status" -eq 0 ]
  [[ "$output" == *"Loading preset: nightly-max"* ]]
  [[ "$output" == *"Pair:              codex+codex"* ]]
  [[ "$output" == *"Writer engine:     codex"* ]]
  [[ "$output" == *"Reviewer engine:   codex"* ]]
  [[ "$output" == *"Speed profile:     standard"* ]]
  [[ "$output" == *"Max agents:        3"* ]]
  [[ "$output" == *"Topology:          team"* ]]
  [[ "$output" == *"Run once:          true"* ]]
  [[ "$output" == *"Config file:       $config_file"* ]]
}

# Scenario: project YAML violates schema.
# Expected: launcher fails closed before dry-run output.
@test "mainspring project YAML schema violation fails closed" {
  local config_file="$BATS_TEST_TMPDIR/.mainspring.yaml"
  cat > "$config_file" <<'YAML'
speed-profile: turbo
max-agents: 9
YAML

  MAINSPRING_CONFIG_FILE="$config_file" run "$MAINSPRING_SH" --dry-run
  [ "$status" -ne 0 ]
  [[ "$output" == *"Configuration validation failed"* ]]
  [[ "$output" == *"SPEED_PROFILE must be one of: standard, fast, max"* ]]
  [[ "$output" == *"MAX_AGENTS must be <= 6"* ]]
}

# Scenario: top-level replay subcommand is dispatched before loop prerequisites.
# Expected: replay build reads a ledger and prints the reconstructed command.
@test "mainspring replay build dispatches to replay helper" {
  local ledger="$BATS_TEST_TMPDIR/waves.jsonl"
  cat > "$ledger" <<'JSON'
{"wave_id":"w1","mode":"night","topology":"solo","engines":{"writer":"claude","reviewer":"codex"},"models":{"writer":"opus","reviewer":"gpt-5.5"},"verdict":"PASS","exit_code":0,"changed_files":[]}
JSON

  run "$MAINSPRING_SH" replay build w1 "$ledger"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Replay command"* ]]
  [[ "$output" == *"claude+codex"* ]]
}

# Scenario: top-level validate-prd subcommand is dispatched before loop prerequisites.
# Expected: the canonical PRD validates without requiring engine binaries.
@test "mainspring validate-prd dispatches to PRD validator" {
  run "$MAINSPRING_SH" validate-prd "$ROOT_DIR/docs/prd.md"
  [ "$status" -eq 0 ]
  [[ "$output" == *"PRD validation passed"* ]]
}

# Scenario: top-level init subcommand is dispatched before loop prerequisites.
# Expected: help exits without requiring engine binaries or creating files.
@test "mainspring init help dispatches to Method init helper" {
  run "$MAINSPRING_SH" init --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage: mainspring init"* ]]
}

# Scenario: top-level decompose subcommand is dispatched before loop prerequisites.
# Expected: the PRD is converted into dry-run Taskmaster add-task prompt plans.
@test "mainspring decompose dispatches to dry-run planner" {
  local prd_file="$BATS_TEST_TMPDIR/prd.md"
  cat > "$prd_file" <<'MD'
# Example - Product Requirements Document (PRD)

## Contents

1. [Mission](#mission)

## Mission

Do the work.

## Durability principles

1. **Truth first.** Verify before claiming completion.

## Current truth snapshot (verified)

| Metric | Value | Source |
| --- | --- | --- |
| Main LOC | 10 | `wc -l scripts/main.sh` |

## Naming and brand boundary

Names are explicit.

## Target architecture

Architecture goes here.

## Phase map

### P1 - Current phase

- [ ] **P1-1 Add decompose dispatch.** Touch `mainspring.sh`.

## Architecture decisions (ADRs)

### ADR-01: Pick a license

**Context:** A decision is needed.

**Options considered:** MIT; Apache-2.0.

**Decision:** Apache-2.0.

**Rationale:** Patent grant.

**Consequences:** SPDX headers.

**Reversal cost:** high.

## Operational doctrine

Use the tool carefully.

## Health rituals

Run checks weekly.

## Disaster recovery

Recover with documented commands.

## Versioning and migration

SemVer.

## Definition of Done (release checklist)

- [ ] Tests pass.

## Explicit non-goals

- Not a SaaS.

## Backlog (Must / Should / Could / Won't)

### Must (blocks this release or scope)

1. Build it.

### Should (v1.x post-release)

1. Polish it.

### Could (v2 candidates, only if data justifies)

1. Maybe later.

### Won't (explicit non-goals - do not propose)

- SaaS hosting.

## Appendix A - Source-of-knowledge recipes

Recipes.

## Appendix B - Verification commands

Commands.

## Acknowledgments / Lineage

Lineage.
MD

  run "$MAINSPRING_SH" decompose "$prd_file" --phase P1
  [ "$status" -eq 0 ]
  [[ "$output" == *"mode: dry-run"* ]]
  [[ "$output" == *"task-master add-task --prompt"* ]]
  [[ "$output" == *"GeneratedBy: decompose"* ]]

  local tasks_file="$BATS_TEST_TMPDIR/tasks.json"
  echo '{"master":{"tasks":[]}}' > "$tasks_file"
  run "$MAINSPRING_SH" decompose "$prd_file" --phase P1 --apply --tasks-file "$tasks_file" --backup-dir "$BATS_TEST_TMPDIR/backups"
  [ "$status" -eq 0 ]
  [[ "$output" == *"created: 1 [1]"* ]]
}

# Scenario: top-level HUD subcommand keeps explicit ledger/state snapshots local.
# Expected: a read-only JSON snapshot is printed without requiring engine binaries.
@test "mainspring hud dispatches to snapshot helper" {
  local ledger="$BATS_TEST_TMPDIR/waves.jsonl"
  local state_dir="$BATS_TEST_TMPDIR/state"
  mkdir -p "$state_dir"
  cat > "$ledger" <<'JSONL'
{"timestamp":"2026-04-29T04:50:00+02:00","wave_id":"w1","task_id":"7","verdict":"PASS","exit_code":0,"duration_seconds":12,"engine":"claude","review_engine":"codex","codex_short_delta_pct":91}
JSONL

  run "$MAINSPRING_SH" hud --once --json --ledger "$ledger" --state-dir "$state_dir"
  [ "$status" -eq 0 ]
  [[ "$output" == *'"current_wave"'* ]]
  [[ "$output" == *'"wave_id": "w1"'* ]]
  [[ "$output" == *'"codex"'* ]]
}

# Scenario: plain HUD is the global operator view, not just the cwd project.
# Expected: the wrapper asks the HUD helper for a machine-level snapshot.
@test "mainspring hud defaults to global operator view" {
  local project="$BATS_TEST_TMPDIR/global-hud-project"
  mkdir -p "$project/.mainspring/state"
  printf '%s\n' "$$" > "$project/.mainspring/state/mainspring.lock"

  run "$MAINSPRING_SH" --project "$project" hud --once --search-root "$project"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Mainspring"* ]]
  [[ "$output" != *"Global "*"HUD"* ]]
  [[ "$output" == *"Runs:"* ]]
  [[ "$output" == *"global-hud-project"* ]]
}

# Scenario: humans and agents ask how to use the HUD.
# Expected: help describes the top-level Mainspring command, not the internal
# Python helper path.
@test "mainspring hud help explains global live default" {
  run "$MAINSPRING_SH" hud --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Mainspring HUD"* ]]
  [[ "$output" == *"mainspring hud"* ]]
  [[ "$output" == *"Global dashboard"* ]]
  [[ "$output" == *"interactive terminal"* ]]
  [[ "$output" == *"Copy/paste commands:"* ]]
  [[ "$output" == *"Each row below is a complete runnable command."* ]]
  [[ "$output" == *"mainspring stop --force"* ]]
  local global_stop="mainspring stop --force --""all"
  [[ "$output" != *"HUD command map:"* ]]
  [[ "$output" != *"$global_stop"* ]]
  [[ "$output" != *"Usage: hud.py"* ]]
  [[ "$output" != *"Internal/testing options"* ]]
  [[ "$output" != *"--ledger <waves.jsonl>"* ]]
  [[ "$output" != *"--state-dir <path>"* ]]
  [[ "$output" != *"--search-root <path>"* ]]
}

# Scenario: top-level stop subcommand is dispatched before loop prerequisites.
# Expected: an explicit forced stop can be run for an empty project without
# touching unrelated runtime processes.
@test "mainspring stop dispatches to process stopper" {
  local project="$BATS_TEST_TMPDIR/stop-project"
  mkdir -p "$project"

  run "$MAINSPRING_SH" --project "$project" stop --force
  [ "$status" -eq 0 ]
  [[ "$output" == *"No recorded live Mainspring process found"* ]]
}

# Scenario: stop is destructive and should never report success without the
# explicit safety flag.
# Expected: missing --force fails with a clear public CLI error.
@test "mainspring stop requires force before dispatching" {
  local project="$BATS_TEST_TMPDIR/stop-missing-force"
  mkdir -p "$project"

  run "$MAINSPRING_SH" --project "$project" stop
  [ "$status" -eq 2 ]
  [[ "$output" == *"stop: --force is required"* ]]
  [[ "$output" == *"Usage: mainspring stop --force [--all]"* ]]
  [[ "$output" != *"STOP_ARGS"* ]]
  [[ "$output" != *"unbound variable"* ]]
}

# Scenario: humans and agents ask how to force-stop all runtimes.
# Expected: stop help is read-only and does not require --force.
@test "mainspring stop help explains force and all flags" {
  run "$MAINSPRING_SH" stop --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage: mainspring stop --force [--all]"* ]]
  [[ "$output" == *"Emergency only"* ]]
  [[ "$output" != *"Refusing to stop processes without --force"* ]]
}

# Scenario: destructive stop commands must not ignore extra operator flags.
# Expected: an unsupported flag fails before any process termination runs.
@test "mainspring stop rejects unknown flags before stopping" {
  local project="$BATS_TEST_TMPDIR/stop-unknown-flag"
  mkdir -p "$project"

  run "$MAINSPRING_SH" --project "$project" stop --force --all --dry-run
  [ "$status" -eq 2 ]
  [[ "$output" == *"stop: unknown flag: --dry-run"* ]]
  [[ "$output" == *"Usage: mainspring stop --force [--all]"* ]]
  [[ "$output" != *"Stopped mainspring pid"* ]]
  [[ "$output" != *"Stopped "* ]]
}

# Scenario: top-level engines subcommand is dispatched before loop prerequisites.
# Expected: registered engine inventory is printed without requiring engine binaries.
@test "mainspring engines dispatches to registry helper" {
  run "$MAINSPRING_SH" engines --json
  [ "$status" -eq 0 ]
  [[ "$output" == *'"engines"'* ]]
  [[ "$output" == *'"name": "codex"'* ]]
  [[ "$output" == *'"name": "claude"'* ]]
  [[ "$output" == *'"name": "gemini"'* ]]
  [[ "$output" == *'"name": "openrouter"'* ]]
  [[ "$output" == *'"execution_status": "shell-dispatch"'* ]]
  [[ "$output" == *'"required_python_module": "litellm"'* ]]
  [[ "$output" == *'"required_env_vars": ['* ]]
  [[ "$output" == *'"GOOGLE_API_KEY"'* ]]
}

# Scenario: top-level engines receives no helper flags.
# Expected: Bash 3.2 nounset handling still dispatches an empty argv safely.
@test "mainspring engines with no args prints text inventory" {
  run "$MAINSPRING_SH" engines
  [ "$status" -eq 0 ]
  [[ "$output" == *"Mainspring engine inventory"* ]]
  [[ "$output" == *"module=litellm:"* ]]
}

# Scenario: top-level limits subcommand is dispatched before loop prerequisites.
# Expected: a combined readiness, quota, and spend snapshot prints without task loop setup.
@test "mainspring limits dispatches to limits helper" {
  local ledger="$BATS_TEST_TMPDIR/waves.jsonl"
  cat > "$ledger" <<'JSON'
{"ts":"2026-04-29T19:00:00Z","wave_id":"w1","task_id":"42","pair":"claude+codex","cost_usd":1.25}
JSON

  run "$MAINSPRING_SH" limits codex --ledger "$ledger" --format json
  [ "$status" -eq 0 ]
  [[ "$output" == *'"engines"'* ]]
  [[ "$output" == *'"engine": "codex"'* ]]
  [[ "$output" == *'"spend_24h"'* ]]
}

# Scenario: top-level --help is the quick operator surface.
# Expected: help is short and points to the full CLI contract.
@test "mainspring --help is concise and points to full help" {
  run "$MAINSPRING_SH" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Mainspring"* ]]
  [[ "$output" == *"mainspring hud"* ]]
  [[ "$output" == *"mainspring status"* ]]
  [[ "$output" == *"mainspring doctor"* ]]
  [[ "$output" == *"mainspring notify-test"* ]]
  [[ "$output" == *"mainspring help --full"* ]]
  [[ "$output" == *"MAINSPRING_TELEGRAM_BOT_TOKEN"* ]]
  [[ "$output" == *"Daily use:"* ]]
  [[ "$output" == *"start or continue"* ]]
  [[ "$output" == *"Product Requirements Document (PRD)-first"* ]]
  [[ "$output" == *"AI coding agent orchestration"* ]]
  [[ "$output" == *"production-grade software delivery"* ]]
  [[ "$output" == *"one PRD-driven slice"* ]]
  [[ "$output" == *"https://github.com/dlogvinenko/mainspring/blob/main/docs/guide.md"* ]]
  local old_positioning="autonomous ""coding loop"
  [[ "$output" != *"$old_positioning"* ]]
  [[ "$output" != *$'\n  docs/guide.md'* ]]

  line_count="$(printf '%s\n' "$output" | wc -l | tr -d ' ')"
  [ "$line_count" -le 50 ]
}

# Scenario: public top-level flags that require values are invoked without a
# value or with another flag in the value position.
# Expected: Mainspring prints a clear usage error instead of a silent shell
# shift failure.
@test "top-level value flags fail with clear usage errors" {
  local flag
  for flag in \
    --engine \
    --pair \
    --mode \
    --prd \
    --model \
    --review-engine \
    --review-model \
    --speed-profile \
    --max-agents \
    --auto-retry-ci \
    --auto-retry-ci-log \
    --retry-task \
    --topology \
    --days \
    --since \
    --format \
    --preset \
    --project
  do
    run "$MAINSPRING_SH" "$flag"
    [ "$status" -eq 2 ]
    [[ "$output" == *"$flag requires a value"* ]]
    [[ "$output" == *"Run: mainspring --help"* ]]
  done

  run "$MAINSPRING_SH" --engine --once
  [ "$status" -eq 2 ]
  [[ "$output" == *"--engine requires a value"* ]]
  [[ "$output" != *"Writer engine:"* ]]

  run "$MAINSPRING_SH" --project=
  [ "$status" -eq 2 ]
  [[ "$output" == *"--project requires a value"* ]]

  run "$MAINSPRING_SH" --project "$BATS_TEST_TMPDIR/missing-project" status
  [ "$status" -eq 2 ]
  [[ "$output" == *"--project path not found or not a directory:"* ]]

  run "$MAINSPRING_SH" "--project=$BATS_TEST_TMPDIR/missing-project" status
  [ "$status" -eq 2 ]
  [[ "$output" == *"--project path not found or not a directory:"* ]]
}

# Scenario: metrics modifier flags are typed without the command that consumes
# them.
# Expected: Mainspring fails before dry-run or loop startup instead of silently
# ignoring the flag.
@test "orphan command modifier flags fail before launch" {
  run "$MAINSPRING_SH" --days 7 --dry-run --once
  [ "$status" -eq 2 ]
  [[ "$output" == *"--days requires --metrics"* ]]
  [[ "$output" != *"Writer engine:"* ]]

  run "$MAINSPRING_SH" --routing --dry-run --once
  [ "$status" -eq 2 ]
  [[ "$output" == *"--routing requires --metrics"* ]]

  run "$MAINSPRING_SH" --format json --dry-run --once
  [ "$status" -eq 2 ]
  [[ "$output" == *"--format requires a command that accepts --format"* ]]

  run "$MAINSPRING_SH" --since HEAD --dry-run --once
  [ "$status" -eq 2 ]
  [[ "$output" == *"--since requires --metrics"* ]]
  local removed_history_cmd="mainspring ""final""ize"
  [[ "$output" != *"$removed_history_cmd"* ]]

  run "$MAINSPRING_SH" --metrics --days 7 --format json
  [ "$status" -eq 0 ]
  [[ "$output" == *'"total_waves"'* ]]
}

# Scenario: --metrics --routing is documented as an observation command.
# Expected: the public wrapper does not mutate wizard disabled-pair state unless
# the lower-level metrics helper is called with its explicit update flag.
@test "mainspring routing metrics is read-only by default" {
  local project="$BATS_TEST_TMPDIR/metrics-routing-project"
  mkdir -p "$project/.mainspring/logs" "$project/.mainspring/state"
  cat > "$project/.mainspring/logs/waves.jsonl" <<'JSONL'
{"timestamp":"2026-06-13T10:00:00+00:00","wave_id":"w1","verdict":"FAIL","duration_seconds":10,"engines":{"writer":"codex","reviewer":"codex"}}
JSONL

  run "$MAINSPRING_SH" --project "$project" --metrics --routing

  [ "$status" -eq 0 ]
  [[ "$output" == *"Routing metrics"* ]]
  [ ! -e "$project/.mainspring/state/disabled-pairs.json" ]
}

# Scenario: humans and agents naturally type noun command aliases.
# Expected: public aliases dispatch before loop prerequisites and legacy flags
# remain available for compatibility.
@test "mainspring status and doctor aliases dispatch read-only reports" {
  run "$MAINSPRING_SH" status
  [ "$status" -eq 0 ]
  [[ "$output" == *"=== Mainspring Status ==="* ]]

  run "$MAINSPRING_SH" doctor
  [ "$status" -eq 0 ]
  [[ "$output" == *"=== Mainspring Doctor ==="* ]]
  [[ "$output" == *"DOCTOR_RESULT:"* ]]
}

# Scenario: humans and agents pipe status into pagers or head while triaging.
# Expected: the report exits cleanly without shell Broken pipe noise.
@test "mainspring status is safe to pipe into head" {
  run bash -c 'set -o pipefail; "$1" status | head -1' bash "$MAINSPRING_SH"
  [ "$status" -eq 0 ]
  [ "$output" = "=== Mainspring Status ===" ]
}

# Scenario: humans and agents ask public read-only aliases for their own help.
# Expected: each alias owns --help instead of falling through to global help.
@test "mainspring status and doctor help are command-specific" {
  run "$MAINSPRING_SH" status --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage: mainspring status"* ]]
  [[ "$output" == *"without starting or stopping any work"* ]]
  [[ "$output" != *"Daily use:"* ]]

  run "$MAINSPRING_SH" doctor --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage: mainspring doctor"* ]]
  [[ "$output" == *"starting work"* ]]
  [[ "$output" == *"local dependencies"* ]]
  [[ "$output" == *"package tooling"* ]]
  [[ "$output" != *"Daily use:"* ]]
}

# Scenario: work modes are public commands, not hidden flag bundles.
# Expected: their --help explains the mode directly instead of showing generic
# top-level help or starting runtime prerequisites.
@test "mainspring taskmaster and night help are command-specific" {
  run "$MAINSPRING_SH" taskmaster --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage: mainspring taskmaster"* ]]
  [[ "$output" == *"Taskmaster backlog"* ]]
  [[ "$output" == *"mainspring taskmaster --once"* ]]
  [[ "$output" != *"Daily use:"* ]]

  run "$MAINSPRING_SH" night --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage: mainspring night --prd <path>"* ]]
  [[ "$output" == *"Product Requirements Document (PRD)"* ]]
  [[ "$output" == *"mainspring night --prd docs/prd.md --once"* ]]
  [[ "$output" != *"Daily use:"* ]]
}

# Scenario: Telegram test has a noun command alias.
# Expected: alias reaches the existing test path and fails closed without
# credentials instead of falling through to unknown-arg help.
@test "mainspring notify-test alias dispatches safely" {
  MAINSPRING_TELEGRAM_BOT_TOKEN='' \
  MAINSPRING_TELEGRAM_CHAT_ID='' \
  run "$MAINSPRING_SH" notify-test

  [ "$status" -eq 1 ]
  [[ "$output" == *"MAINSPRING_TELEGRAM_BOT_TOKEN and MAINSPRING_TELEGRAM_CHAT_ID required"* ]]
  [[ "$output" != *"Unknown argument"* ]]
}

# Scenario: Telegram test help should explain the subcommand without sending
# a message or falling through to generic top-level help.
# Expected: notify-test owns --help and exits successfully.
@test "mainspring notify-test help is command-specific" {
  run "$MAINSPRING_SH" notify-test --help

  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage: mainspring notify-test"* ]]
  [[ "$output" == *"Send one Telegram test message"* ]]
  [[ "$output" == *"MAINSPRING_TELEGRAM_BOT_TOKEN"* ]]
  [[ "$output" != *"Daily use:"* ]]
}

# Scenario: full help is a readable operator command list.
# Expected: it shows grouped daily commands instead of a giant flag dump.
@test "full help is grouped by operator action" {
  run "$MAINSPRING_SH" help --full
  [ "$status" -eq 0 ]
  [[ "$output" == *"Copy/paste commands:"* ]]
  [[ "$output" == *"Start / resume:"* ]]
  [[ "$output" == *"Run work:"* ]]
  [[ "$output" == *"Project planning:"* ]]
  [[ "$output" == *"Advanced inspection:"* ]]
  [[ "$output" == *"Options used by commands:"* ]]
  local old_details_header="Command details ""and flags:"
  [[ "$output" != *"$old_details_header"* ]]
  local removed_task_planning="Task planning ""commands:"
  [[ "$output" != *"$removed_task_planning"* ]]
  [[ "$output" == *"Copy the command exactly as shown after each dash"* ]]
  [[ "$output" == *"Every command line below is a complete runnable invocation"* ]]
  [[ "$output" == *"Flags are never shown as standalone workflows or separate columns"* ]]
  local command_map="${output#*Copy/paste commands:}"
  command_map="${command_map%%Options used by commands:*}"
  [[ "$command_map" != *"<"* ]]
  [[ "$command_map" != *"..."* ]]
  [[ "$output" == *"mainspring --metrics --days 7 --routing"* ]]
  [[ "$output" == *"- mainspring hud => live dashboard for every Mainspring run"* ]]
  [[ "$output" == *"mainspring hud --json --once"* ]]
  [[ "$output" == *"mainspring taskmaster --once"* ]]
  [[ "$output" == *"mainspring taskmaster --once --pair codex+claude"* ]]
  [[ "$output" == *"mainspring night --prd docs/prd.md --once"* ]]
  [[ "$output" == *"- mainspring stop --force => stop this project"* ]]
  [[ "$output" == *"mainspring init checkout-redesign"* ]]
  [[ "$output" == *"mainspring validate-prd docs/prd.md"* ]]
  [[ "$output" == *"mainspring decompose docs/prd.md --phase P1"* ]]
  [[ "$output" == *"mainspring decompose docs/prd.md --phase P1 --apply"* ]]
  [[ "$output" == *"mainspring replay show last .mainspring/logs/waves.jsonl"* ]]
  [[ "$output" == *"mainspring replay run last .mainspring/logs/waves.jsonl --dry-run"* ]]
  [[ "$output" == *"mainspring limits codex claude --format json"* ]]
  [[ "$command_map" != *"mainspring init <name>"* ]]
  [[ "$command_map" != *"mainspring replay <show|diff|build|run>"* ]]
  [[ "$output" != *"mainspring hud                             live dashboard"* ]]
  [[ "$output" != *"mainspring stop --force                    stop this project"* ]]
  [[ "$output" != *"add --apply to write"* ]]
  [[ "$output" != *"standard CLI patterns"* ]]
  [[ "$output" != *"mainspring --metrics [--days N] [--routing]"* ]]
  [[ "$output" != *"mainspring --metrics --days 7              pass rate"* ]]
  [[ "$output" != *"mainspring --metrics --routing             pair/topology"* ]]
  [[ "$output" != *"JSON: mainspring"* ]]
  [[ "$output" != *"Snapshot: mainspring"* ]]
  [[ "$output" != *"History: mainspring"* ]]
  [[ "$output" != *"Current project: mainspring"* ]]
  [[ "$output" != *"Routing: mainspring"* ]]
  [[ "$output" != *"Pair override: mainspring"* ]]
  [[ "$output" != *"Apply: mainspring"* ]]
  [[ "$output" != *"Selected engines: mainspring"* ]]
  [[ "$output" != *"Spend window: mainspring"* ]]
  [[ "$output" != *"execution_status=shell-dispatch"* ]]
  local removed_task_maintenance="Task and maintenance"" commands:"
  [[ "$output" != *"$removed_task_maintenance"* ]]
  [[ "$output" != *"Utilities:"* ]]
  [[ "$output" == *"mainspring --list-presets"* ]]
  [[ "$output" != *"Each row has one copy/paste command"* ]]
  [[ "$output" != *"Low-level compatibility command for old local projects"* ]]
  local removed_migration_flag="--migrate""-from"
  [[ "$output" != *"$removed_migration_flag"* ]]
  [[ "$output" != *"Low-level source-checkout maintenance helper"* ]]
  [[ "$output" != *"It is not a release command"* ]]
  local retired_command_map="Command ""map:"
  [[ "$output" != *"$retired_command_map"* ]]
  local removed_history_usage="final""ize [list|squash|draft]"
  [[ "$output" != *"$removed_history_usage"* ]]
  [[ "$output" == *"mainspring --repair-state --dry-run"* ]]
  [[ "$output" == *"Default: solo"* ]]
  [[ "$output" == *"external team backend plus tmux"* ]]
  [[ "$output" == *'Engines must be registered adapters; run `mainspring engines`'* ]]
  [[ "$output" != *"py/engines/"* ]]
}

# Scenario: unsupported commands should fail cleanly without dumping full help.
# Expected: typo handling stays terse and does not expose implementation details.
@test "unknown commands are rejected without noisy help dumps" {
  run "$MAINSPRING_SH" unsupported-command --help
  [ "$status" -eq 1 ]
  [[ "$output" == *"Unknown command: unsupported-command"* ]]
  [[ "$output" == *"Run: mainspring --help"* ]]
  [[ "$output" != *"Daily use:"* ]]

  run "$MAINSPRING_SH" --unsupported-flag value
  [ "$status" -eq 1 ]
  [[ "$output" == *"Unknown argument: --unsupported-flag"* ]]
  [[ "$output" == *"Run: mainspring --help"* ]]
  [[ "$output" != *"Daily use:"* ]]
}

# Scenario: unsupported maintainer helper names should not behave like hidden
# workflows.
# Expected: they fail exactly like any unknown command and do not dump advanced
# help text.
@test "unsupported helper-style commands stay unknown" {
  local command
  local old_gate_helper="release-"
  old_gate_helper="${old_gate_helper}blockers"
  local old_notes_helper="release-"
  old_notes_helper="${old_notes_helper}notes"
  for command in publish-audit maintainer-proof-check "$old_gate_helper" "$old_notes_helper"; do
    run "$MAINSPRING_SH" "$command" --help
    [ "$status" -eq 1 ]
    [[ "$output" == *"Unknown command: $command"* ]]
    [[ "$output" == *"Run: mainspring --help"* ]]
    [[ "$output" != *"Daily use:"* ]]
    local old_flag_combo="--version v1.0.0 ""--check"
    [[ "$output" != *"$old_flag_combo"* ]]
  done
}

# Scenario: public subcommand help should not expose implementation filenames.
# Expected: humans and agents see `mainspring ...` usage, not Python helper names.
@test "public subcommand help uses mainspring command names" {
  local commands=(
    "hud --help"
    "status --help"
    "doctor --help"
    "stop --help"
    "last-run --help"
    "notify-test --help"
    "notify-health --help"
    "notify-restart --help"
    "taskmaster --help"
    "night --help"
    "engines --help"
    "limits --help"
    "replay --help"
    "validate-prd --help"
    "init --help"
    "decompose --help"
    "scope-check --help"
    "next --help"
  )

  local cmd
  for cmd in "${commands[@]}"; do
    # shellcheck disable=SC2086
    run "$MAINSPRING_SH" $cmd
    [ "$status" -eq 0 ]
    [[ "$output" != *"Usage: engine_registry.py"* ]]
    [[ "$output" != *"Usage: limits.py"* ]]
    [[ "$output" != *"Usage: replay.py"* ]]
    [[ "$output" != *"Usage: prd_validate.py"* ]]
    [[ "$output" != *"Usage: method_init.py"* ]]
    [[ "$output" != *"Usage: decompose.py"* ]]
    [[ "$output" != *"Usage: taskmaster.py"* ]]
  done
}

# Scenario: local-model setup should be discoverable from CLI help.
# Expected: full help names both the Ollama shortcut and the MTPLX
# OpenAI-compatible LiteLLM route with explicit writer/reviewer flags.
@test "help text includes local model writer examples" {
  run "$MAINSPRING_SH" help --full
  [ "$status" -eq 0 ]
  [[ "$output" == *"--engine ollama --model 'ollama/qwen3:8b'"* ]]
  [[ "$output" == *"OPENAI_API_BASE=http://127.0.0.1:18080/v1 OPENAI_API_KEY=local"* ]]
  [[ "$output" == *"--engine litellm --model 'openai/qwen3.6-mtplx'"* ]]
  [[ "$output" == *"--review-engine codex --review-model gpt-5.5"* ]]
  [[ "$output" == *"MAINSPRING_PROVIDERS_PYTHON=python3.13 make install-user-providers"* ]]
  [[ "$output" == *"Refreshes the user-level pipx command after local Mainspring changes"* ]]
  [[ "$output" == *"Installs LiteLLM provider/local-model dependencies"* ]]
  [[ "$output" != *"Runs \`pipx ensurepath\` and then \`pipx install --force -e .\`"* ]]
}

# Scenario: top-level --version is a normal public CLI flag.
# Expected: it prints the package version without falling through to unknown-arg help.
@test "mainspring --version prints package version" {
  run "$MAINSPRING_SH" --version
  [ "$status" -eq 0 ]
  [ "$output" = "mainspring 1.0.0" ]
}

# Scenario: top-level notify-health command is dispatched before loop prerequisites.
# Expected: disabled notifier status is printed without launching work.
@test "mainspring notify-health dispatches to notifier health helper" {
  MAINSPRING_NOTIFY_ENABLED=0 run "$MAINSPRING_SH" notify-health --format json
  [ "$status" -eq 0 ]
  [[ "$output" == *'"status": "disabled"'* ]]
  [[ "$output" == *'"next_step": "enable-notifications"'* ]]
}

# Scenario: notify-health help should explain health states and recovery.
# Expected: it is self-contained enough for humans and agents.
@test "mainspring notify-health help is command-specific" {
  run "$MAINSPRING_SH" notify-health --help

  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage: mainspring notify-health"* ]]
  [[ "$output" != *"[--json]"* ]]
  [[ "$output" == *"Statuses:"* ]]
  [[ "$output" == *"healthy"* ]]
  [[ "$output" == *"stale"* ]]
  [[ "$output" == *"next_step"* ]]
  [[ "$output" == *"mainspring notify-restart"* ]]
  [[ "$output" != *"Daily use:"* ]]
}

# Scenario: public full help should prefer one canonical JSON spelling.
# Expected: compatibility aliases can exist, but operator docs use --format json.
@test "full help avoids duplicate json aliases for health and last-run" {
  local stale_last_usage="last-run [--format text|json] ""[--json]"
  local stale_health_usage="notify-health [--format text|json] ""[--json]"

  run "$MAINSPRING_SH" help --full
  [ "$status" -eq 0 ]
  [[ "$output" == *"last-run [--format text|json]"* ]]
  [[ "$output" == *"notify-health [--format text|json]"* ]]
  [[ "$output" != *"$stale_last_usage"* ]]
  [[ "$output" != *"$stale_health_usage"* ]]
  [[ "$output" != *"OMX""_LOOP_"* ]]
}

# Scenario: the retired full-help flag spelling should not remain as hidden CLI
# surface.
# Expected: users get the normal unknown-argument guidance and the canonical
# command remains `mainspring help --full`.
@test "retired full-help flag stays removed" {
  local retired_help_flag="--help-""full"

  run "$MAINSPRING_SH" "$retired_help_flag"

  [ "$status" -eq 1 ]
  [[ "$output" == *"Unknown argument: $retired_help_flag"* ]]
  [[ "$output" == *"Run: mainspring --help"* ]]
  local retired_command_map="Command ""map:"
  [[ "$output" != *"$retired_command_map"* ]]
}

# Scenario: notify-restart help should describe the safe restart boundary.
# Expected: it names notifier.pid validation and the post-restart test command.
@test "mainspring notify-restart help is command-specific" {
  run "$MAINSPRING_SH" notify-restart --help

  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage: mainspring notify-restart"* ]]
  [[ "$output" == *"notifier.pid"* ]]
  [[ "$output" == *"ignores unrelated PIDs"* ]]
  [[ "$output" == *"mainspring notify-test"* ]]
  [[ "$output" != *"Daily use:"* ]]
}

# Scenario: top-level notify-restart command receives no trailing args.
# Expected: dispatch reaches the notifier helper instead of failing under nounset.
@test "mainspring notify-restart dispatches without nounset empty-array failure" {
  MAINSPRING_NOTIFY_ENABLED=1 \
    MAINSPRING_TELEGRAM_BOT_TOKEN= \
    MAINSPRING_TELEGRAM_CHAT_ID= \
    run "$MAINSPRING_SH" notify-restart
  [ "$status" -eq 1 ]
  [[ "$output" == *"MAINSPRING_TELEGRAM_BOT_TOKEN and MAINSPRING_TELEGRAM_CHAT_ID required"* ]]
  [[ "$output" != *"unbound variable"* ]]
}

# Scenario: top-level scope-check subcommand is dispatched before loop prerequisites.
# Expected: a vague task is reported without requiring engine binaries.
@test "mainspring scope-check dispatches to Taskmaster checker" {
  local tasks_file="$BATS_TEST_TMPDIR/tasks.json"
  cat > "$tasks_file" <<'JSON'
{"master":{"tasks":[{"id":1,"status":"pending","title":"improve dashboard","details":"Acceptance criteria: dashboard names the next action.","testStrategy":"Run npx vitest run tests/components/tabs/dashboard.test.tsx.","subtasks":[]}]}}
JSON

  run "$MAINSPRING_SH" scope-check "$tasks_file"
  [ "$status" -eq 1 ]
  [[ "$output" == *"vague-title"* ]]
}

# Scenario: a clean Method-shaped task is accepted.
# Expected: scope-check reports zero violations.
@test "mainspring scope-check reports zero violations for clean task" {
  local tasks_file="$BATS_TEST_TMPDIR/tasks-clean.json"
  cat > "$tasks_file" <<'JSON'
{"master":{"tasks":[{"id":1,"status":"pending","title":"Render dashboard empty state","details":"Acceptance criteria: empty state shows one concrete CTA. Estimated effort: 30 min - 2 hrs.","testStrategy":"Run npx vitest run tests/components/tabs/dashboard.test.tsx.","subtasks":[]}]}}
JSON

  run "$MAINSPRING_SH" scope-check "$tasks_file"
  [ "$status" -eq 0 ]
  [[ "$output" == *"scope-check: 0 violations"* ]]
}

# Scenario: no Taskmaster backlog exists in the selected project.
# Expected: public CLI explains the missing setup without Python internals.
@test "mainspring scope-check missing backlog is operator-friendly" {
  local project="$BATS_TEST_TMPDIR/empty-project"
  mkdir -p "$project"

  run "$MAINSPRING_SH" --project "$project" scope-check
  [ "$status" -eq 2 ]
  [[ "$output" == *"scope-check: Taskmaster backlog not found at .taskmaster/tasks/tasks.json"* ]]
  [[ "$output" == *"mainspring init checkout-redesign"* ]]
  [[ "$output" == *"replace checkout-redesign with your feature name"* ]]
  [[ "$output" != *"mainspring init <name>"* ]]
  [[ "$output" != *"$project"* ]]
  [[ "$output" != *"Errno"* ]]
}

# Scenario: top-level next subcommand is dispatched before loop prerequisites.
# Expected: blocked work is skipped and the ready task id is printed.
@test "mainspring next dispatches blocker-aware selector" {
  local tasks_file="$BATS_TEST_TMPDIR/tasks-next.json"
  cat > "$tasks_file" <<'JSON'
{"master":{"tasks":[{"id":1,"status":"blocked","dependencies":[],"title":"Blocked","subtasks":[]},{"id":2,"status":"pending","dependencies":[],"title":"Ready","subtasks":[]}]}}
JSON

  run "$MAINSPRING_SH" next "$tasks_file"
  [ "$status" -eq 0 ]
  [ "$output" = "2" ]
}

# Scenario: active PRD phase state is honored.
# Expected: a current-phase task is preferred over an earlier later-phase id.
@test "mainspring next prefers active PRD phase" {
  local tasks_file="$BATS_TEST_TMPDIR/tasks-next-phase.json"
  local active_prd="$BATS_TEST_TMPDIR/active-prd.json"
  cat > "$tasks_file" <<'JSON'
{"master":{"tasks":[{"id":1,"status":"pending","dependencies":[],"title":"P2 Later phase task","subtasks":[]},{"id":2,"status":"pending","dependencies":[],"title":"P1 Current phase task","subtasks":[]}]}}
JSON
  cat > "$active_prd" <<'JSON'
{"active_phase":"P1","phase_order":["P1","P2"]}
JSON

  run "$MAINSPRING_SH" next "$tasks_file" --active-prd "$active_prd"
  [ "$status" -eq 0 ]
  [ "$output" = "2" ]
}

# Scenario: runtime dirs can be configured per project.
# Expected: top-level next uses the resolved STATE_DIR active PRD by default
# instead of hard-coding .mainspring/state.
@test "mainspring next uses configured state dir for active PRD" {
  local project="$BATS_TEST_TMPDIR/next-runtime-project"
  local runtime="$BATS_TEST_TMPDIR/custom-runtime"
  local tasks_file="$BATS_TEST_TMPDIR/tasks-next-runtime-phase.json"
  mkdir -p "$project" "$runtime/state"
  cat > "$tasks_file" <<'JSON'
{"master":{"tasks":[{"id":1,"status":"pending","dependencies":[],"title":"P2 Later phase task","subtasks":[]},{"id":2,"status":"pending","dependencies":[],"title":"P1 Current phase task","subtasks":[]}]}}
JSON
  cat > "$runtime/state/active-prd.json" <<'JSON'
{"active_phase":"P1","phase_order":["P1","P2"]}
JSON

  MAINSPRING_RUNTIME_DIR="$runtime" run "$MAINSPRING_SH" --project "$project" next "$tasks_file"

  [ "$status" -eq 0 ]
  [ "$output" = "2" ]
}

# Scenario: no Taskmaster backlog exists when asking for the next task.
# Expected: public CLI gives the next action instead of a Python file error.
@test "mainspring next missing backlog is operator-friendly" {
  local project="$BATS_TEST_TMPDIR/empty-next-project"
  mkdir -p "$project"

  run "$MAINSPRING_SH" --project "$project" next
  [ "$status" -eq 2 ]
  [[ "$output" == *"next: Taskmaster backlog not found at .taskmaster/tasks/tasks.json"* ]]
  [[ "$output" == *"mainspring init checkout-redesign"* ]]
  [[ "$output" == *"replace checkout-redesign with your feature name"* ]]
  [[ "$output" != *"mainspring init <name>"* ]]
  [[ "$output" != *"$project"* ]]
  [[ "$output" != *"Errno"* ]]
}

# ---------------------------------------------------------------------------
# run_dry_run tests
# ---------------------------------------------------------------------------

# Scenario: run_dry_run prints resolved settings.
# Expected: output contains key labels and engine names.
@test "run_dry_run prints resolved settings without API calls" {
  _load_wizard
  MODE="taskmaster"
  ENGINE="claude"
  REVIEW_ENGINE="codex"
  MODEL_OVERRIDE="opus"
  REVIEW_MODEL_OVERRIDE="gpt-5.5"
  SPEED_PROFILE="max"
  MAX_AGENTS="6"
  AGENT_MODE="debug"
  TOPOLOGY="team"
  RUN_ONCE="false"
  AUTO_CHECKPOINT="true"
  CODEX_REASONING_EFFORT="xhigh"
  LOG_DIR="/tmp/test-logs"
  LOCK_FILE="/tmp/test-lock"
  WAVE_LEDGER_FILE="/tmp/test-waves.jsonl"
  LAST_RUN_FILE="/tmp/test-last-run.env"
  run run_dry_run
  [ "$status" -eq 0 ]
  [[ "$output" == *"Mainspring Dry Run"* ]]
  [[ "$output" == *"Writer engine:     claude"* ]]
  [[ "$output" == *"Reviewer engine:   codex"* ]]
  [[ "$output" == *"Writer model:      opus"* ]]
  [[ "$output" == *"Reviewer model:    gpt-5.5"* ]]
  [[ "$output" == *"Writer mode:       debug"* ]]
  [[ "$output" == *"Topology:          team"* ]]
  [[ "$output" == *"Registered engines:"* ]]
  [[ "$output" == *"gemini"* ]]
  [[ "$output" == *"Zero API calls made"* ]]
}

# Scenario: run_dry_run shows writer command shape for claude engine.
# Expected: output contains the claude CLI invocation.
@test "run_dry_run shows claude writer command" {
  _load_wizard
  MODE="taskmaster"
  ENGINE="claude"
  REVIEW_ENGINE="codex"
  MODEL_OVERRIDE="opus"
  REVIEW_MODEL_OVERRIDE="gpt-5.5"
  SPEED_PROFILE="max"
  MAX_AGENTS="6"
  TOPOLOGY="solo"
  RUN_ONCE="false"
  AUTO_CHECKPOINT="true"
  CODEX_REASONING_EFFORT="xhigh"
  LOG_DIR="/tmp/test-logs"
  LOCK_FILE="/tmp/test-lock"
  WAVE_LEDGER_FILE="/tmp/test-waves.jsonl"
  LAST_RUN_FILE="/tmp/test-last-run.env"
  run run_dry_run
  [ "$status" -eq 0 ]
  [[ "$output" == *"claude -p --dangerously-skip-permissions"* ]]
  [[ "$output" == *"--model opus"* ]]
}

# Scenario: run_dry_run shows codex writer command shape for codex engine.
# Expected: output contains the codex CLI invocation.
@test "run_dry_run shows codex writer command" {
  _load_wizard
  MODE="taskmaster"
  ENGINE="codex"
  REVIEW_ENGINE="codex"
  MODEL_OVERRIDE="gpt-5.5"
  REVIEW_MODEL_OVERRIDE="gpt-5.5"
  SPEED_PROFILE="fast"
  MAX_AGENTS="2"
  TOPOLOGY="solo"
  RUN_ONCE="true"
  AUTO_CHECKPOINT="true"
  CODEX_REASONING_EFFORT="xhigh"
  LOG_DIR="/tmp/test-logs"
  LOCK_FILE="/tmp/test-lock"
  WAVE_LEDGER_FILE="/tmp/test-waves.jsonl"
  LAST_RUN_FILE="/tmp/test-last-run.env"
  run run_dry_run
  [ "$status" -eq 0 ]
  [[ "$output" == *"codex exec --ignore-user-config --yolo"* ]]
  [[ "$output" == *"gpt-5.5"* ]]
}

# Scenario: a registered provider engine dispatches through LiteLLM.
# Expected: dry-run previews the provider runner command instead of a preflight-only fallback.
@test "run_dry_run previews gemini LiteLLM dispatch" {
  _load_wizard
  MODE="taskmaster"
  ENGINE="gemini"
  REVIEW_ENGINE="claude"
  MODEL_OVERRIDE="gemini/gemini-2.5-pro"
  REVIEW_MODEL_OVERRIDE="opus"
  SPEED_PROFILE="fast"
  MAX_AGENTS="2"
  TOPOLOGY="solo"
  RUN_ONCE="true"
  AUTO_CHECKPOINT="true"
  CODEX_REASONING_EFFORT="xhigh"
  LOG_DIR="/tmp/test-logs"
  LOCK_FILE="/tmp/test-lock"
  WAVE_LEDGER_FILE="/tmp/test-waves.jsonl"
  LAST_RUN_FILE="/tmp/test-last-run.env"
  run run_dry_run
  [ "$status" -eq 0 ]
  [[ "$output" == *"litellm_runner.py"* ]]
  [[ "$output" == *"gemini/gemini-2.5-pro"* ]]
  [[ "$output" == *"env=GOOGLE_API_KEY:"* ]]
  [[ "$output" != *"execution_status=preflight-only"* ]]
}

# Scenario: a provider dry-run is blocked by missing runtime setup.
# Expected: dependency checks print exact commands instead of raw registry JSON.
@test "run_dry_run explains provider setup remediation" {
  _load_wizard
  unset GOOGLE_API_KEY
  MODE="night"
  ENGINE="gemini"
  REVIEW_ENGINE="claude"
  MODEL_OVERRIDE="gemini/gemini-2.5-pro"
  REVIEW_MODEL_OVERRIDE="opus"
  SPEED_PROFILE="fast"
  MAX_AGENTS="2"
  TOPOLOGY="solo"
  RUN_ONCE="true"
  AUTO_CHECKPOINT="true"
  CODEX_REASONING_EFFORT="xhigh"
  LOG_DIR="/tmp/test-logs"
  LOCK_FILE="/tmp/test-lock"
  WAVE_LEDGER_FILE="/tmp/test-waves.jsonl"
  LAST_RUN_FILE="/tmp/test-last-run.env"
  PRD_PATH="$ROOT_DIR/docs/prd.md"

  run run_dry_run

  [ "$status" -eq 0 ]
  [[ "$output" == *"gemini readiness: NOT READY"* ]]
  [[ "$output" == *"run: export GOOGLE_API_KEY=<provider API key>"* ]]
  [[ "$output" == *"Status: NOT READY"* ]]
}

# Scenario: source-checkout dependencies are installed in .venv, not PATH python3.
# Expected: provider readiness uses Mainspring's Python resolver instead of
# reporting a false missing-module blocker from the wrong interpreter.
@test "require_engine_ready uses repo venv python for provider checks" {
  _load_wizard
  local tmpdir project fake_py registry_script calls_file
  tmpdir="${BATS_TEST_TMPDIR:-$(mktemp -d)}"
  project="$tmpdir/project"
  MAINSPRING_PY_DIR="$tmpdir/py"
  fake_py="$project/.venv/bin/python3"
  registry_script="$MAINSPRING_PY_DIR/engine_registry.py"
  calls_file="$tmpdir/python-calls.log"
  mkdir -p "$project/.venv/bin" "$MAINSPRING_PY_DIR"
  printf '#!/bin/sh\nprintf "venv %%s\\n" "$*" >> "%s"\nexit 0\n' "$calls_file" > "$fake_py"
  chmod +x "$fake_py"
  touch "$registry_script"
  ROOT_DIR="$project"
  SCRIPT_DIR="$project"
  unset VIRTUAL_ENV
  unset MAINSPRING_PY
  unset MAINSPRING_RUNTIME_PYTHON

  run require_engine_ready "gemini" "writer" "gemini/gemini-2.5-pro"

  [ "$status" -eq 0 ]
  [[ "$(cat "$calls_file")" == *"$registry_script validate --engine gemini --role writer --model gemini/gemini-2.5-pro --require-execution --require-executable"* ]]
}
