---
name: spec-workflow
description: Use when starting any change to GuitarVis, writing a spec or an implementation plan, creating a branch, or opening a PR. This repo's spec layout differs from the Superpowers default, and this skill states the difference.
---

# Spec workflow

## Where specs live

```
docs/specs/NNN-short-name/
├── spec.md      the design
├── plan.md      the implementation plan
└── *.md         research notes, eval notes — same folder
```

`NNN` is three digits, zero-padded, monotonic, never reused. The name is one to
three kebab-case words. Every spec folder sits inside `docs/specs/`; none sits
at the top level of `docs/`.

**This overrides the Superpowers default**, which writes to
`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and plans to
`docs/superpowers/plans/`. Do not use those paths. The date lives in git.

## The branch is the folder

Work for `003-pipeline-skeleton` happens on a branch called
`003-pipeline-skeleton`. Create it before writing the spec:

```bash
git checkout -b 003-pipeline-skeleton
mkdir -p docs/specs/003-pipeline-skeleton
```

`main` is never committed to directly. `.githooks/pre-commit` refuses it. If
you find yourself reaching for `--no-verify`, you are almost certainly on the
wrong branch rather than facing the genuine exception.

## Finding the next number

```bash
ls docs/specs | sort | tail -1
```

## Opening the PR

Use `.github/pull_request_template.md`. The **Spec:** line is required — a PR
with no spec is the signal that design was skipped.

## What belongs where

`spec.md` argues: purpose, approach, rejected alternatives, consequences,
risks, what is deliberately out of scope. It does not contain step-by-step
instructions.

`plan.md` instructs: tasks with exact file paths, real code, and a test cycle
per task. It does not re-argue the design; it links the spec.

## Build phase order

Recorded in the design spec, and worth respecting — phases 1–2 hold all the
technical risk:

1. Pipeline skeleton · 2. Fretboard mapper and eval harness · 3. API and queue ·
4. Tab view and sync · 5. 2D then 3D fretboard · 6. URL ingestion
