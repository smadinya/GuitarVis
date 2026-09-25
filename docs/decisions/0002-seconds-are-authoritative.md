# 0002. Seconds are authoritative; musical position is derived

**Status:** Accepted
**Date:** 2026-09-24
**Spec:** [001-guitarvis-design](../specs/001-guitarvis-design/spec.md#the-tab-document)

## Context

Every note needs a position. It could be musical (bar 4, beat 2) or wall-clock
(12.84 seconds). Beat tracking is the most error-prone stage in the pipeline.

## Decision

Every note carries a wall-clock onset in seconds. Bars and beats live in a
separate `timing.beats` array mapping time to musical position, and measures
are computed at render time.

## Consequences

A bad beat grid yields ugly bar lines over correctly synced notes — a degraded
experience rather than a useless one. Had positions been musical, a tempo error
would desynchronise playback from audio, which is the one thing a play-along
app must never do.

Rendering must do more work: bar lines require a lookup into the beat grid
rather than being implicit in the data. Accepted.
