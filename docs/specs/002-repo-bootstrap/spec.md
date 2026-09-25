# Repository Bootstrap — Design

**Date:** 2026-09-24
**Status:** Approved design, pre-implementation
**Parent spec:** [001-guitarvis-design](../001-guitarvis-design/spec.md)

## Purpose

Turn a repository holding one design document into one that a solo developer —
or a Claude session starting cold — can work in without deciding anything twice.

This spec covers structure, conventions, tooling, and the agent-facing rules
that every later phase inherits. It produces no application code. Its success
condition is that `make check` passes on an essentially empty tree, and that
phase 1 begins by writing implementations into slots that already type-check.

## Scope

**In:** monorepo layout, uv workspace wiring, the tab document contract
mechanism, documentation set, four repo-local skills, `.gitignore`, MIT
license, Makefile, CI workflow, the spec-driven branch workflow and its git
hook.

**Out:** any pipeline, API, or client implementation; `docker-compose` and
local infrastructure (Postgres, Redis, MinIO); deployment. Those belong to
phases 1 and 3 of the parent spec.

## Approach

A **uv workspace monorepo with a shared `core` package**, where the tab
document is a single Pydantic source of truth and every other representation is
generated and drift-checked.

The parent spec's central argument is that the tab document is the stable
contract the architecture exists to protect. This layout expresses that
argument in the filesystem: `core` is a real package that `api` and `worker`
both depend on, so they cannot hold different ideas of the contract.

Rejected alternatives:

- **Flat services with a hand-written JSON Schema as source of truth.**
  Language-neutral and honest about the contract being data, but the Pydantic
  models and the schema are then maintained separately, and nothing
  structurally prevents the divergence the design is trying to rule out.
- **Flat services, no shared package.** Schema duplicated per language with a
  contract test over a shared fixture. Cheapest to start; defers the drift
  problem rather than solving it. With three views and two anticipated
  additional clients reading this document, drift is the failure that costs
  most.

## Repository layout

```
GuitarVis/
├── apps/
│   ├── api/                  guitarvis_api      FastAPI; no ML
│   ├── worker/               guitarvis_worker   pipeline stages; torch lives here
│   └── eval/                 guitarvis_eval     GuitarSet harness (filled in phase 2)
├── packages/
│   └── core/                 guitarvis_core     tab document, invariants, job types, errors
├── web/                      Vite + React + TypeScript
├── schema/                   tab-document.schema.json   (generated, committed)
├── eval/results/             tracked metric history     (NOT gitignored)
│                             results sit at the top level, apart from the
│                             harness code in apps/eval/, because they are a
│                             tracked record of the project rather than part
│                             of a package — and because a reader looking for
│                             "how good is it" should find them without
│                             reading source
├── docs/
│   ├── CONVENTIONS.md
│   ├── decisions/            ADRs + template + open-decision backlog
│   └── specs/                NNN-short-name/ folders
├── .claude/skills/           four repo-local skills
├── .githooks/pre-commit
├── .github/
│   ├── workflows/ci.yml
│   └── pull_request_template.md
├── pyproject.toml            uv workspace root
├── uv.lock  ruff.toml  mypy.ini  Makefile
├── README.md  CONTRIBUTING.md  CLAUDE.md  LICENSE  .gitignore
```

Four uv workspace members: `core`, `api`, `worker`, `eval`. Each uses a `src/`
layout with its own `pyproject.toml` and `tests/` directory.

`core` is a library and depends on nothing heavy — Pydantic and the standard
library. `api` and `worker` both depend on `core`. `worker` and `eval` are the
only members permitted torch, demucs, or model weights.

### The dependency boundary is a test

The parent spec requires that `api` carry no ML code and no model weights, so
it can scale independently of GPU work. That rule is enforced rather than
documented: `apps/api/tests/test_boundaries.py` imports `guitarvis_api` in a
clean interpreter and asserts that `torch` and `demucs` are absent from
`sys.modules`. It runs on CPU in about a second and fails on the day someone
reaches for a convenient import.

### Stage interfaces exist before implementations

`core` defines the four stage interfaces from the parent spec as `Protocol`
classes — `Separator`, `Transcriber`, `StructureAnalyzer`, `FretboardMapper` —
along with the plain data types they exchange (`NoteEvent`, `TabNote`,
`Timing`, `Chord`). `apps/worker/src/guitarvis_worker/stages/` holds one module
per stage whose methods raise `NotImplementedError`.

Phase 1 fills bodies into slots that already type-check, and the shape of the
pipeline is reviewable before any model is installed.

## The tab document contract

`packages/core/src/guitarvis_core/tabdoc.py` holds the tab document as Pydantic
v2 models — `TabDocument`, `Source`, `Instrument`, `Timing`, `Beat`, `Note`,
`Chord`, `Section` — plus `SCHEMA_VERSION = 1`. Field semantics are exactly
those fixed in the parent spec.

That file is the single source of truth. Two artifacts derive from it and are
committed to the repository:

1. `schema/tab-document.schema.json`, via `TabDocument.model_json_schema()`
2. `web/src/types/tabDocument.ts`, generated from that JSON Schema with
   `json-schema-to-typescript`

`make schema` regenerates both. Committing the generated artifacts — rather
than building them at install time — means a schema change shows up as a diff
in review, and a future iOS or desktop client reads a language-neutral JSON
Schema from the repository instead of reverse-engineering Python.

### Drift is a build failure

CI runs `make schema` followed by `git diff --exit-code schema web/src/types`.
Changing the Pydantic models without regenerating fails the build with the
diff in the log.

Two tests guard the contract beyond that check:

- `packages/core/tests/fixtures/minimal.tabdoc.json` must validate against the
  Pydantic models in pytest.
- The same fixture must parse against the generated TypeScript types in
  vitest.

The diff check catches a forgotten regeneration. The shared fixture catches a
generator that is silently emitting wrong types — a failure the diff check
cannot see, because both sides would be consistently wrong.

### The fretboard invariant lives in `core`

`pitch_of(string, fret, tuning) == note.midi` is stated in the parent spec as a
hard invariant. It ships as a single validator function in `core`, called by
the mapper, by its property tests, and by any future editing feature. One
implementation means one place it can break.

## Documentation set

Five documents with distinct jobs and no overlapping content.

**`README.md`** — the only document written for someone who has never heard of
this project. What it does, the pipeline diagram, the three views, an honest
status line naming the current phase, a quickstart, and the parent spec's
Known Limitations stated plainly rather than buried: roughly 70–85% note
accuracy on clean recordings, worse on dense mixes. It links to the design
spec rather than restating it.

**`CONTRIBUTING.md`** — operational. Prerequisites, `make install`, the command
table, Conventional Commits, the branch-per-spec rule, and where each kind of
change belongs. It points at `docs/CONVENTIONS.md` rather than absorbing it.

**`docs/CONVENTIONS.md`** — the rules that outlive any one change.

- Python: `src/` layout; mypy strict on stage interfaces and the tab document,
  lenient elsewhere; the parent spec's failure reasons
  (`unsupported_format`, `no_guitar_detected`, `too_long`, `fetch_failed`,
  `internal`) as an enum in `core` rather than string literals; stages take and
  return plain data and never reference their neighbours.
- TypeScript: views subscribe to `(tabDocument, currentTime)`, hold no playback
  state, never communicate with sibling views, and route every
  confidence-rendering decision through one shared function.
- Testing: correctness is tested and gates CI; quality is measured and never
  gates it.

**`docs/decisions/`** — ADRs. Each records one decision with status, context,
and a link to the parent spec section that argued it; none restates the spec.
Seeded with five:

| ADR | Decision |
|---|---|
| 0001 | Staged pipeline over an end-to-end learned tab model |
| 0002 | Seconds are authoritative; musical position is derived |
| 0003 | Fretboard assignment is deterministic code, not learned |
| 0004 | Evaluation is measured, never gated |
| 0005 | uv workspace monorepo with a shared `core` package |

`docs/decisions/README.md` carries the index plus the parent spec's thirteen
**Open decisions** as an explicit backlog, so resolving one has an obvious
home. A template accompanies them.

**`CLAUDE.md`** — agent-facing and short. What the repo is in three lines, the
command table, the hard invariants, the phase order, a pointer to the parent
spec, and pointers to the four skills. The invariants it states:

- `pitch_of(string, fret, tuning) == note.midi`, always
- seconds are authoritative; never store note positions as bar/beat
- `api` must not import torch or demucs
- evaluation never gates CI
- regenerate the schema after any change to `tabdoc.py`
- never commit to `main`

**`LICENSE`** — MIT.

Note for a later phase, not a blocker now: open decision 2 in the parent spec
weighs `madmom` as a beat tracker, and `madmom` carries a non-commercial
clause. MIT on this project's own code remains fine; a bundled distribution
including `madmom` would not be. The licence question needs an answer before
any commercial launch.

**`.gitignore`** — Python, Node, env, and OS standards, plus what this project
specifically attracts: model weights (`*.pt`, `*.onnx`, `models/`), audio
(`*.wav`, `*.mp3`, `*.flac`) with an allowlist exception for
`tests/**/fixtures/**`, local object storage, and `.venv`.

It carries an explicit comment that `eval/results/` and `schema/` are tracked
on purpose. Both look generated and both would otherwise be swept up by
someone tidying the ignore file.

## Repo-local skills

Four skills in `.claude/skills/`, each a `SKILL.md` with frontmatter naming its
trigger conditions.

**`tab-document`** — when a change is additive and safe versus when it requires
bumping `schema_version`; the regeneration step and why the CI diff check
exists; the pitch invariant; why seconds are authoritative and why storing
bar/beat would be a regression; why the note list is flat. Triggers on any edit
to `tabdoc.py` or `schema/`.

**`pipeline-stage`** — adding or changing a stage: the `Protocol` it must
satisfy, plain data in and out, no knowledge of neighbouring stages,
content-hash caching of intermediates, how to stub it in tests, and the
degradation contract — a failing stage omits its track and the job continues;
only "no usable guitar audio" fails a job outright. Carries the parent spec's
degradation table as a checklist.

**`eval-harness`** — running and reading the evaluation: the commands, what
note F1 / string accuracy / chord accuracy mean, where results are tracked and
how runs compare, and the rule stated as a prohibition — this must never be
wired into CI pass/fail, because a suite that fails when a model drifts two
percent is a suite people learn to ignore.

**`spec-workflow`** — the numbering convention, the branch rule, where
writing-plans must place `plan.md`, and the PR template requirement. This skill
exists because Superpowers' own default writes specs to
`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`. Without something that
fires during brainstorming, the next cold session writes to the old path and
the convention decays in a single sitting.

## Spec-driven branch workflow

```
docs/specs/
├── 001-guitarvis-design/      spec.md
├── 002-repo-bootstrap/        spec.md  plan.md
└── 003-pipeline-skeleton/     spec.md  plan.md
```

Every spec folder lives inside `docs/specs/`; none sits at the top level of
`docs/`. Folder names are `NNN-short-name` — three-digit zero-padded, monotonic,
never reused, followed by one to three kebab-case words. `spec.md` is the
design, `plan.md` is the implementation plan, and any companion documents
(`research.md`, `eval-notes.md`) stay in the same folder.

**The branch name is the folder name.** Work for `002-repo-bootstrap` happens
on branch `002-repo-bootstrap`. One lookup, no mapping table, and `git branch`
reads as a list of specs in flight.

`main` is never committed to directly. That is enforced by
`.githooks/pre-commit`, which refuses a commit when `HEAD` is `main` and is
wired up by `make install` running `git config core.hooksPath .githooks`. It is
bypassable with `--no-verify` for the genuine exception. A note in CONTRIBUTING
is something a tired developer or an agent talks itself past; a hook is not.

`.github/pull_request_template.md` carries a required **Spec:** line linking the
folder, so a pull request with no spec is visibly irregular at review time
rather than discovered afterwards.

**Migration:** the existing design document moves to the new convention —
`git mv docs/superpowers/specs/2026-09-24-guitarvis-design.md
docs/specs/001-guitarvis-design/spec.md`, content unchanged. The date lives in
git history, so the filename no longer carries it, and the now-empty
`docs/superpowers/` tree is removed.

## Commands

```
make install     uv sync + npm ci + git config core.hooksPath .githooks
make lint        ruff check + ruff format --check + eslint
make typecheck   mypy + tsc --noEmit
make test        pytest + vitest
make schema      regenerate JSON Schema and web types
make check       lint + typecheck + test + schema drift check    ← what CI runs
make eval        GuitarSet harness (phase 2; never part of check)
make clean       remove caches and build artifacts
```

`make eval` is deliberately outside `make check`. The separation is the
measured-not-gated rule expressed in the build system, so wiring evaluation
into CI would require an edit someone has to justify.

## CI

`.github/workflows/ci.yml` runs `make check` on push and on pull request:
Ubuntu, CPU only, no model downloads, no GPU.

At bootstrap it passes against a near-empty tree. That is the point — a
baseline that is green before there is any code is the only way to know which
commit broke it.

## Testing

What this bootstrap itself must demonstrate:

- `make check` exits zero on the delivered tree.
- The dependency-boundary test passes, and is shown to fail when `torch` is
  added to `api`'s imports.
- The schema drift check passes, and is shown to fail when `tabdoc.py` changes
  without regeneration.
- The shared tab document fixture validates in both pytest and vitest.
- The pre-commit hook refuses a commit on `main` and permits one on a spec
  branch.

Each of these is a mechanism whose value is entirely in its failure behaviour,
so the plan verifies the failure, not only the pass.

## Risks

- **Bootstrap outliving its usefulness.** Scaffolding written before any code
  tends to encode guesses. Mitigated by keeping every stub to an interface
  already fixed in the parent spec, and creating nothing that spec does not
  already name.
- **Generated artifacts committed to the repository** invite merge conflicts in
  `schema/` and `web/src/types/`. Accepted: conflicts there are a true signal
  that two branches changed the contract, which is exactly when a human should
  look.
- **The `uv` dependency.** It is not currently installed on the development
  machine, and the worker's torch and demucs pins are the hardest install in
  the project. The plan installs `uv` and resolves the workspace before writing
  documentation that claims `make install` works.

## Out of scope, deliberately

`docker-compose` and local infrastructure, any pipeline implementation, the API
surface, the web client beyond a booting shell with lint and test wired, and
deployment. Phase 1 of the parent spec — the CLI-driven pipeline skeleton — is
the next spec, `003-pipeline-skeleton`.
