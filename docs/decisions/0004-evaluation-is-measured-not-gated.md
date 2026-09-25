# 0004. Evaluation is measured, never gated

**Status:** Accepted
**Date:** 2026-09-24
**Spec:** [001-guitarvis-design](../specs/001-guitarvis-design/spec.md#testing)

## Context

The GuitarSet harness reports note F1, string accuracy, and chord accuracy.
The obvious move is to put it in CI with a threshold.

## Decision

Evaluation runs on demand via `make eval` and writes to `eval/results/`. It is
unreachable from `make check`, which is the only thing CI runs. No CI job reads
those results.

## Consequences

CI stays fast, deterministic, CPU-only, and trustworthy: a red build always
means something is broken rather than that a model drifted two percent on a
Tuesday. A suite that cries wolf is a suite people learn to ignore, and then a
real failure goes unnoticed.

Nothing automatically stops a quality regression from merging. The tracked
results file makes it visible instead, which requires someone to look.
