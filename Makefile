# SPDX-License-Identifier: Apache-2.0
# Mainspring local CI — lint + test harness
# Usage: make all
#
# Targets:
#   shell-lint   bash -n + shellcheck on all *.sh
#   ruff         ruff check + format on py/
#   pytest       pytest on py/tests/
#   coverage     release gate: pytest under stdlib trace with >=80% py/ line coverage
#   install-user update the user-level pipx mainspring command from this checkout
#   install-user-providers update pipx command with LiteLLM provider extras
#   dev-install  alias for install-user
#   package-smoke  wheel/console-script and release metadata smoke
#   audit        pip-audit dependency vulnerability gate
#   pipx-smoke   opt-in isolated pipx install smoke
#   homebrew-formula-smoke  generated Formula/mainspring.rb validation
#   docs-site-smoke  generated GitHub Pages / Jekyll docs source validation
#   fresh-clone-smoke  clone clean HEAD and run make all from the clone
#   release-check  public release local gate: all + package + coverage + PRD + diff hygiene
#   bats         bats on tests/bats/ (skipped if no tests exist yet)
#   bootstrap-dev  create/update the repo-local Python dev environment
#   hud-rich-smoke  bounded Rich HUD smoke test
#   lint         shell-lint + ruff
#   test         pytest + bats + hud-rich-smoke
#   all          lint + test + audit
#   clean        remove generated local build/test artifacts

.PHONY: help lint test bats pytest coverage ruff shell-lint bootstrap-dev install-user install-user-providers dev-install package-smoke pipx-smoke homebrew-formula-smoke fresh-clone-smoke docs-site-smoke hud-rich-smoke audit release-check all clean

HERE := $(shell pwd)
ROOT := $(HERE)
PY_DIR := $(HERE)/py
LIB_DIR := $(HERE)/lib
BATS_DIR := $(HERE)/tests/bats
VENV_DIR := $(HERE)/.venv
VENV_PYTHON := $(VENV_DIR)/bin/python
BOOTSTRAP_PYTHON ?= python3
MAINSPRING_PROVIDERS_PYTHON ?= python3.13
ifeq ($(origin PYTHON), undefined)
PYTHON := $(VENV_PYTHON)
PYTHON_BOOTSTRAP_TARGET := $(VENV_DIR)/.mainspring-dev
else
PYTHON_BOOTSTRAP_TARGET :=
endif
SH_FILES := $(shell find $(HERE) \
	\( -path '$(HERE)/.git' -o \
	   -path '$(HERE)/.claude' -o \
	   -path '$(HERE)/.mainspring' -o \
	   -path '$(HERE)/.omx' -o \
	   -path '$(HERE)/.venv' -o \
	   -path '$(HERE)/build' -o \
	   -path '$(HERE)/node_modules' \) -prune -o \
	-name '*.sh' -type f -print | sort)

help:
	@echo "mainspring targets: lint test bats pytest coverage ruff shell-lint bootstrap-dev install-user install-user-providers dev-install package-smoke pipx-smoke homebrew-formula-smoke fresh-clone-smoke docs-site-smoke hud-rich-smoke audit release-check all clean"

$(VENV_DIR)/.mainspring-dev: pyproject.toml requirements.txt
	@echo "--- python dev env ---"
	@$(BOOTSTRAP_PYTHON) -m venv $(VENV_DIR)
	@$(VENV_PYTHON) -m pip install --upgrade pip setuptools wheel
	@$(VENV_PYTHON) -m pip install -e ".[dev]"
	@touch $@

bootstrap-dev: $(VENV_DIR)/.mainspring-dev

shell-lint:
	@echo "--- bash -n ---"
	@for f in $(SH_FILES); do bash -n "$$f"; done
	@echo "bash -n: OK"
	@echo "--- shellcheck ---"
	@shellcheck -S warning $(SH_FILES)
	@echo "shellcheck: OK"

ruff: $(PYTHON_BOOTSTRAP_TARGET)
	@echo "--- ruff check ---"
	@$(PYTHON) -m ruff check $(PY_DIR)
	@echo "ruff check: OK"
	@echo "--- ruff format ---"
	@$(PYTHON) -m ruff format --check $(PY_DIR)
	@echo "ruff format: OK"

pytest: $(PYTHON_BOOTSTRAP_TARGET)
	@echo "--- pytest ---"
	@cd $(PY_DIR) && $(PYTHON) -m pytest tests/ -v --tb=short
	@echo "pytest: OK"

coverage: $(PYTHON_BOOTSTRAP_TARGET)
	@echo "--- python coverage ---"
	@$(PYTHON) $(PY_DIR)/coverage_gate.py --py-dir $(PY_DIR) --threshold 80
	@echo "python coverage: OK"

install-user:
	@echo "--- pipx editable install ---"
	@if ! command -v pipx >/dev/null 2>&1; then \
		echo "pipx not found; install pipx first, then rerun make install-user" >&2; \
		exit 127; \
	fi
	@pipx ensurepath >/dev/null
	@pipx uninstall mainspring >/dev/null 2>&1 || true
	@PATH="$$HOME/.local/bin:$$PATH" pipx install --force -e .
	@echo "install-user: OK; run mainspring from your project directory"

install-user-providers:
	@echo "--- pipx editable install with provider extras ---"
	@if ! command -v pipx >/dev/null 2>&1; then \
		echo "pipx not found; install pipx first, then rerun make install-user-providers" >&2; \
		exit 127; \
	fi
	@if ! command -v "$(MAINSPRING_PROVIDERS_PYTHON)" >/dev/null 2>&1; then \
		echo "$(MAINSPRING_PROVIDERS_PYTHON) not found; set MAINSPRING_PROVIDERS_PYTHON=python3.12 or python3.11" >&2; \
		exit 127; \
	fi
	@pipx ensurepath >/dev/null
	@pipx uninstall mainspring >/dev/null 2>&1 || true
	@PATH="$$HOME/.local/bin:$$PATH" pipx install --force --python "$(MAINSPRING_PROVIDERS_PYTHON)" -e ".[providers]"
	@echo "install-user-providers: OK; run mainspring engines from any project"

dev-install: install-user

package-smoke: $(PYTHON_BOOTSTRAP_TARGET)
	@echo "--- package smoke ---"
	@find "$(PY_DIR)" -maxdepth 1 -name '*.egg-info' -type d -exec rm -rf -- {} + 2>/dev/null || true
	@tmp="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmp"' EXIT; \
	$(PYTHON) -m build --sdist --wheel --outdir "$$tmp/dist" >/dev/null; \
	test -f "$$tmp/dist/mainspring-1.0.0.tar.gz"; \
	test -f "$$tmp/dist/mainspring-1.0.0-py3-none-any.whl"
	@$(PYTHON) -m pytest py/tests/test_mainspring_bootstrap.py -q
	@$(PYTHON) -m pytest py/tests/test_homebrew_formula.py -q
	@echo "package smoke: OK"

pipx-smoke: $(PYTHON_BOOTSTRAP_TARGET)
	@echo "--- pipx smoke ---"
	@MAINSPRING_RUN_PIPX_SMOKE=1 $(PYTHON) -m pytest py/tests/test_mainspring_bootstrap.py::test_isolated_pipx_install_uses_caller_project_root -q
	@echo "pipx smoke: OK"

homebrew-formula-smoke: $(PYTHON_BOOTSTRAP_TARGET)
	@echo "--- homebrew formula smoke ---"
	@$(PYTHON) -m pytest py/tests/test_homebrew_formula.py -q
	@echo "homebrew formula smoke: OK"

fresh-clone-smoke: $(PYTHON_BOOTSTRAP_TARGET)
	@echo "--- fresh clone smoke ---"
	@$(PYTHON) py/fresh_clone_smoke.py --repo . --target all --evidence-json .mainspring/state/fresh-clone-smoke-evidence.json
	@echo "fresh clone smoke: OK"

docs-site-smoke: $(PYTHON_BOOTSTRAP_TARGET)
	@echo "--- docs site smoke ---"
	@tmp="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmp"' EXIT; \
	$(PYTHON) py/docs_site.py --output "$$tmp/site" --clean; \
	test -f "$$tmp/site/_config.yml"; \
	test -f "$$tmp/site/_layouts/default.html"; \
	test -f "$$tmp/site/prd.md"; \
	test -f "$$tmp/site/guide.md"
	@echo "docs site smoke: OK"

bats:
	@if [ -f "$(BATS_DIR)/run.sh" ]; then \
		echo "--- bats ---"; \
		bash $(BATS_DIR)/run.sh || exit $$?; \
		echo "bats: OK"; \
	else \
		echo "--- bats: skipped (no tests/bats/run.sh yet) ---"; \
	fi

hud-rich-smoke: $(PYTHON_BOOTSTRAP_TARGET)
	@echo "--- hud rich smoke ---"
	@$(PYTHON) $(PY_DIR)/hud.py --rich --once --ledger $(ROOT)/.mainspring/logs/waves.jsonl --state-dir $(ROOT)/.mainspring/state --width 80 >/dev/null
	@echo "hud rich smoke: OK"

audit: $(PYTHON_BOOTSTRAP_TARGET)
	@echo "--- dependency audit ---"
	@$(PYTHON) -m pip_audit -r $(ROOT)/requirements.txt
	@echo "dependency audit: OK"

release-check: all package-smoke coverage
	@echo "--- release check: PRD + diff hygiene ---"
	@$(PYTHON) $(PY_DIR)/prd_validate.py $(ROOT)/docs/prd.md
	@git diff --check
	@echo "release check: OK"

lint: shell-lint ruff
test: pytest bats hud-rich-smoke docs-site-smoke
all: lint test audit

clean:
	@find "$(PY_DIR)" -name __pycache__ -type d -exec rm -rf -- {} + 2>/dev/null || true
	@rm -rf -- "$(HERE)/build" "$(HERE)/dist"
	@rm -rf -- "$(HERE)/.pytest_cache" "$(HERE)/.ruff_cache" "$(HERE)/.mypy_cache"
	@find "$(PY_DIR)" -name '*.egg-info' -type d -exec rm -rf -- {} + 2>/dev/null || true
	@find "$(HERE)" -maxdepth 1 -name '*.egg-info' -type d -exec rm -rf -- {} + 2>/dev/null || true
	@find "$(PY_DIR)" -maxdepth 1 \( -name '.mainspring' -o -name '.omx' \) -exec rm -rf -- {} + 2>/dev/null || true
	@echo "clean: OK"
