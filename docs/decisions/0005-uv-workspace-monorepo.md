# 0005. A uv workspace monorepo with a shared core package

**Status:** Accepted
**Date:** 2026-09-24
**Spec:** [002-repo-bootstrap](../specs/002-repo-bootstrap/spec.md#approach)

## Context

The tab document is the contract between the pipeline and every client, present
and future. Where it physically lives determines whether it can drift. The
alternatives were a hand-written JSON Schema as source of truth, or fully
separate services each holding their own copy.

## Decision

A uv workspace with four members. `packages/core` owns the tab document as
Pydantic models — the single source of truth — and both `api` and `worker`
depend on it. The JSON Schema and the TypeScript types are generated from those
models, committed, and diff-checked in CI.

## Consequences

`api` and `worker` cannot hold different ideas of the contract, and a schema
change is visible as a diff in review. A future iOS client reads a
language-neutral JSON Schema from the repository rather than reverse-engineering
Python.

Generated artifacts in git will occasionally produce merge conflicts in
`schema/` and `web/src/types/`. That is a true signal — two branches changed the
contract — and is exactly when a human should look.
