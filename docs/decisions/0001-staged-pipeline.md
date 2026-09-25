# 0001. Staged pipeline rather than an end-to-end learned tab model

**Status:** Accepted
**Date:** 2026-09-24
**Spec:** [001-guitarvis-design](../specs/001-guitarvis-design/spec.md#approach)

## Context

Audio to tablature can be one learned model or a sequence of narrow stages. The
end-to-end model has the higher ceiling: it would learn idiomatic fingerings
instead of inferring them. But the available ground truth — GuitarSet, roughly
three hours of clean solo guitar — is thin for generalising to full mixes, and
the approach needs GPU budget and ML depth a solo v1 does not have.

## Decision

Four independent stages — separation, transcription, structure, fretboard
assignment — each behind a narrow interface, each separately testable.
Transcription starts with a general-purpose polyphonic model and is designed to
be swapped once an evaluation harness can prove the swap is an improvement.

## Consequences

Something demoable exists in weeks rather than months, and each stage can be
tested without the others. The transcription interface returns pitches and not
fingerings, which is the seam a guitar-specific model slots into later.

The ceiling is lower: inferred fingerings will sometimes be unidiomatic where a
learned model would be natural. Revisit if transcription quality plateaus below
usefulness and training data has grown.
