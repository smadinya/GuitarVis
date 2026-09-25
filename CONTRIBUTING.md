# Contributing

## Setup

```bash
make install
make check
```

Requires Python 3.12+, Node 22+, and [uv](https://docs.astral.sh/uv/)
(`curl -LsSf https://astral.sh/uv/install.sh | sh`).

`make install` also runs `git config core.hooksPath .githooks`, which activates
the hook that refuses commits on `main`.

## Commands

| Command | What it does |
|---|---|
| `make install` | Dependencies and git hooks |
| `make lint` | ruff and ESLint |
| `make format` | Apply Python formatting and import order |
| `make typecheck` | mypy and `tsc --noEmit` |
| `make test` | pytest and vitest |
| `make schema` | Regenerate the JSON Schema and the web types |
| `make check` | Everything CI runs |
| `make eval` | GuitarSet evaluation — measured, never gated |

The worker's ML dependencies are an optional extra and are not installed by
default. When you need them: `uv sync --extra ml`.

## Every change starts with a spec

Work is organised as numbered spec folders under `docs/specs/`:

```
docs/specs/
├── 001-guitarvis-design/      spec.md
├── 002-repo-bootstrap/        spec.md  plan.md
└── 003-pipeline-skeleton/     spec.md  plan.md
```

Folder names are `NNN-short-name`: three digits, zero-padded, monotonic, never
reused, then one to three kebab-case words. `spec.md` is the design, `plan.md`
is the implementation plan, and companion notes stay in the same folder.

**The branch name is the folder name.** Work for `003-pipeline-skeleton`
happens on a branch called `003-pipeline-skeleton`. One lookup, and `git
branch` reads as a list of specs in flight.

`main` is never committed to directly. The pre-commit hook enforces it;
`--no-verify` exists for the genuine exception, which is rarer than it feels.

Open a pull request using the template, which requires a link to the spec.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/):
`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `build:`, with an
optional scope such as `feat(core):`.

Write the body to explain *why*, not *what* — the diff already says what.

## Where things go

| Change | Where |
|---|---|
| Tab document field | `packages/core/.../tabdoc.py`, then `make schema` |
| Pipeline stage | `apps/worker/src/guitarvis_worker/stages/` |
| Stage interface | `packages/core/.../contracts.py` |
| HTTP endpoint | `apps/api/` — no ML imports, the test will catch you |
| Client view | `web/src/` |
| Evaluation metric | `apps/eval/` |

## Before you open a PR

- `make check` passes
- If you touched `tabdoc.py`, you ran `make schema` and committed the result
- The plan's checkboxes reflect reality
