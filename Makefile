# The command surface. CI runs `make check` and nothing else, so anything that
# must not break belongs behind that target.
#
# `eval` is deliberately absent from `check`. Evaluation is measured, never
# gated: a suite that fails because a model got two percent worse on a Tuesday
# is a suite people learn to ignore.

.DEFAULT_GOAL := help
UV  := uv
NPM := npm --prefix web

# mypy is pointed at the source trees rather than the repo root: with a src
# layout it resolves package names from these directories, and tests stay out
# of the strict contract rules.
PY_SOURCES := packages/core/src apps/api/src apps/worker/src apps/eval/src

.PHONY: help install lint format typecheck test test-py test-web \
        schema schema-check check eval clean

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk -F':.*?## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies and wire up the git hooks
	$(UV) sync
	$(NPM) ci
	git config core.hooksPath .githooks
	@echo "✓ hooks active — commits on main will be refused"

lint: ## Lint Python and TypeScript
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(NPM) run lint

format: ## Apply Python formatting and import order
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

# typecheck MUST stay inside `check`. The cross-language contract test in
# web/src/types/tabDocument.test.ts is enforced in two halves: vitest verifies
# the fixture's runtime VALUES, while `tsc --noEmit` verifies its SHAPE
# against the generated TypeScript types. esbuild strips the `import type` at
# test time, so vitest alone would pass vacuously even if the shape drifted.
# If `check` ever runs tests without typecheck, half the contract enforcement
# disappears silently while everything still looks green.
typecheck: ## Type-check Python and TypeScript
	$(UV) run mypy $(PY_SOURCES)
	$(NPM) run typecheck

test: test-py test-web ## Run every test

test-py:
	$(UV) run pytest

test-web:
	$(NPM) run test

schema: ## Regenerate the tab document schema and the web types
	$(UV) run python -m guitarvis_core.schema_export schema/tab-document.schema.json
	$(NPM) run generate-types

schema-check: schema ## Fail if the committed contract artifacts are stale
	@git diff --exit-code -- schema web/src/types || { \
	  echo ""; \
	  echo "✗ Contract artifacts are stale."; \
	  echo "  tabdoc.py changed without regenerating. Commit the diff above."; \
	  exit 1; \
	}

check: lint typecheck test schema-check ## Everything CI runs

eval: ## GuitarSet evaluation. Measured, never gated — not part of `check`.
	$(UV) run python -m guitarvis_eval

clean: ## Remove caches and build output
	rm -rf .pytest_cache .mypy_cache .ruff_cache .venv web/node_modules web/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
