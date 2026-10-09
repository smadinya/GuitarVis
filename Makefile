# The command surface. CI runs `make check` and nothing else, so anything that
# must not break belongs behind that target.
#
# `eval` is deliberately absent from `check`. Evaluation is measured, never
# gated: a suite that fails because a model got two percent worse on a Tuesday
# is a suite people learn to ignore.

.DEFAULT_GOAL := help
UV  := uv
NPM := npm --prefix web

# `schema-check` rewrites schema/ and the generated files in web/src/types/ as a side
# effect of the `schema` prerequisite it runs first. typecheck and test both
# read those same files. Run with `make -j` (or a parallel `check`), that
# write could race a read and either see a half-written file or trip the
# stale-artifact check on a file schema-check hasn't finished writing yet.
.NOTPARALLEL:

# Empty by default so a developer who just edited pyproject.toml can still
# `make install` and get a re-resolved lock. CI overrides this to --locked so
# a drifted lockfile fails loudly there, matching how `npm ci` already
# enforces the lockfile on the Node side.
UV_SYNC_FLAGS ?=

# Extra arguments for `make eval` / `make eval-data`, e.g.
# `make eval ARGS="--split dev"`.
ARGS ?=

# mypy is pointed at these directories rather than the repo root: with a src
# layout it resolves package names from them. Tests ARE included — a typed
# Protocol conformance assignment (e.g. apps/worker/tests/test_stages.py) is
# only checked by mypy if the file it lives in is on this list, and the
# stub's own `if TYPE_CHECKING` conformance check needs the same coverage.
# Tests are not exempt from the strict contract rules for the modules they
# import strictly; mypy config in mypy.ini still scopes strictness per module.
#
# Caveat: mypy maps same-named test modules in different packages to the same
# module name unless each package's tests are namespaced or have distinct
# file names, which can cause a "Source file found twice under different
# module names" error. There are no collisions today (test files across
# packages/core/tests, apps/api/tests, apps/worker/tests, apps/eval/tests all
# have distinct basenames), but a future contributor adding a same-named test
# file to two packages will hit this and should rename one of the files.
PY_SOURCES := packages/core/src packages/jobs/src apps/api/src apps/worker/src apps/eval/src \
              packages/core/tests packages/jobs/tests apps/api/tests apps/worker/tests apps/eval/tests

.PHONY: help install lint format typecheck test test-py test-web \
        schema schema-check check eval eval-data services migrate api worker clean

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk -F':.*?## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies and wire up the git hooks
	$(UV) sync $(UV_SYNC_FLAGS)
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
# against the generated TypeScript types — the fixture JSON is imported
# directly (resolveJsonModule) and assigned, with no cast, to a
# TabDocument-typed constant, so a shape mismatch is a compile error. esbuild
# erases that type-only checking machinery at test time, so vitest alone
# would pass vacuously even if the shape drifted. If `check` ever runs tests
# without typecheck, half the contract enforcement disappears silently while
# everything still looks green.
typecheck: ## Type-check Python and TypeScript
	$(UV) run mypy $(PY_SOURCES)
	$(NPM) run typecheck

test: test-py test-web ## Run every test

test-py:
	$(UV) run pytest

test-web:
	$(NPM) run test

schema: ## Regenerate the contract schemas and the web types
	$(UV) run python -m guitarvis_core.schema_export schema/tab-document.schema.json
	$(UV) run python -m guitarvis_api.schema_export schema/api.schema.json
	$(NPM) run generate-types

# Scoped to every generated file in web/src/types, which is all of it but
# the hand-written *.test.ts files beside them: editing a test must not look
# like a stale artifact.
#
# `git status --porcelain`, not `git diff --exit-code`: diff only sees
# changes to tracked files, so a generator that starts emitting a brand-new
# (untracked) file would pass `git diff` silently. status also reports
# untracked paths under the scoped directories.
schema-check: schema ## Fail if the committed contract artifacts are stale
	@changes="$$(git status --porcelain -- schema web/src/types ':(exclude)web/src/types/*.test.ts')"; \
	if [ -n "$$changes" ]; then \
	  echo "$$changes"; \
	  echo ""; \
	  echo "✗ Contract artifacts are stale."; \
	  echo "  tabdoc.py or the api's schemas.py changed without regenerating,"; \
	  echo "  or the regenerated output was never committed. Commit the"; \
	  echo "  changes listed above."; \
	  exit 1; \
	fi

check: lint typecheck test schema-check ## Everything CI runs

eval: ## GuitarSet evaluation. Measured, never gated — not part of `check`.
	$(UV) run python -m guitarvis_eval $(ARGS)

eval-data: ## Download GuitarSet into ~/.cache (ARGS=--audio for full mode's audio)
	$(UV) run python -m guitarvis_eval.download $(ARGS)

services: ## Start Postgres, Redis and object storage (docker compose)
	docker compose up -d --wait

migrate: ## Bring the schema up to date and create the bucket
	$(UV) run python -m guitarvis_jobs.migrate

api: ## Serve the api on localhost:8000, reloading on change
	$(UV) run uvicorn guitarvis_api.app:app --reload

worker: ## Run jobs from the queue (ARGS="--device cuda"; needs `uv sync --extra ml`)
	$(UV) run guitarvis-worker serve $(ARGS)

clean: ## Remove caches and build output
	rm -rf .pytest_cache .mypy_cache .ruff_cache .venv web/node_modules web/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
