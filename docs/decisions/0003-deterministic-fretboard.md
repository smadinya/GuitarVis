# 0003. Fretboard assignment is deterministic code, not a learned model

**Status:** Accepted
**Date:** 2026-09-24
**Spec:** [001-guitarvis-design](../specs/001-guitarvis-design/spec.md#stage-4--fretboard-assignment)

## Context

A pitch can be played in several places on a guitar neck. Choosing among them
could be learned along with transcription, or computed from physical
constraints.

## Decision

Stage 4 is deterministic code: candidate positions per pitch, filtered by
playability, with a Viterbi pass minimising hand movement between voicings. It
enforces a hard invariant — the pitch implied by `(string, fret, tuning)` must
equal the input MIDI pitch, always.

## Consequences

The step that makes the output *tablature* rather than MIDI is under full
control and can be correct even when the model above it is not. It is testable
without audio: feed note sequences, assert fingerings.

Fingerings will sometimes be mechanically sensible but unidiomatic — correct
notes in a position no guitarist would choose. That is a better failure than a
wrong note, and it is improvable by tuning costs rather than retraining.
