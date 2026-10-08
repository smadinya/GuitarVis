---
name: pipeline-stage
description: Use when adding or modifying a pipeline stage in apps/worker, changing a stage interface in guitarvis_core.contracts, or handling pipeline failures. Stages have a narrow contract and a degradation rule that is easy to break by accident.
---

# Pipeline stages

Four stages, each behind a narrow interface, each separately testable.

| Stage | Interface | Progress |
|---|---|---|
| 1 Separation | `Separator.isolate(audio_path, *, progress=None) -> SeparationResult` | 0–40%, live: `progress(fraction)` while it runs |
| 2 Transcription | `Transcriber.transcribe(stem_path) -> list[NoteEvent]` | starts at 40% |
| 3 Structure | `StructureAnalyzer.analyze(stem, mix) -> StructureResult` | starts at 65% |
| 4 Fretboard | `FretboardMapper.assign(notes, tuning) -> FretboardResult` | starts at 80%; 100% when the document is built |

Progress names the stage **running**. The pipeline reports each stage's start
and keeps the percent monotonic whatever a separator reports, so a separator
may report nothing, or nonsense, without breaking a client.

Protocols live in `packages/core/src/guitarvis_core/contracts.py`.
Implementations live in `apps/worker/src/guitarvis_worker/stages/`.

## The rules

**A stage never imports another stage.** They exchange plain data; the worker
orchestrates. If a stage needs to know what ran before it, the interface is
wrong — fix the interface, do not reach sideways.

**Stage 2 returns pitches, not fingerings.** `NoteEvent` is `(onset, duration,
midi, confidence)` and carries no string or fret. This is the single upgrade
point the staged architecture exists to protect: a guitar-specific model must
be able to implement `Transcriber` without anything downstream changing.

**Heavy imports go inside methods, never at module level.** `uv sync` installs
the worker without its `ml` extra, so a module-level `import torch` breaks test
collection. Use `uv sync --extra ml` when you need the real dependencies.

**Beat tracking runs on the original mix, not the stem.** Drums are the
strongest beat cue and the stem has them removed.

**Stages are idempotent and intermediates are cached by content hash.** A
stage-3 failure must not force re-running separation on retry. The cache lives
in `apps/worker/src/guitarvis_worker/caching.py`: one decorator per cached
stage, each implementing that stage's Protocol. **Bump `CACHE_VERSION`
whenever a stage's output for the same input would change** (a new model, a
changed threshold, a fixed bug). Nothing enforces it, and forgetting serves
old results for audio processed before the change. A cache read or write error
is a miss, never a stage failure; only the separation stem must be stored,
because the api serves it. Output a stage degraded inside itself is not stored
either: `CachedAnalyzer` skips a structure result with warnings, so the next
attempt runs the stage again rather than replaying a failure that may pass.

## Degrade, do not fail

Every stage after separation is optional to the core promise. A job fails
outright only when there is no usable guitar audio.

| What broke | What the user gets |
|---|---|
| Beat tracking | Notes still sync to audio; no bar lines, no chord grid |
| Chord detection | Note tab only; chord track hidden |
| Confidence collapses in a passage | That passage shows chord symbols, not fret numbers |
| Guitar stem empty or near-silent | Retry with the 4-stem `other` track; if still empty, fail honestly |
| Fretboard mapper raises | No notes; timing and chords unaffected by it; a warning says why |
| Notes no hand could play, or outside the neck's range | Those notes dropped, never approximated; a warning gives the count |

When a stage fails, omit its track from the tab document and continue. Raise
`PipelineError` with a typed `FailureReason` only when the job genuinely cannot
produce anything: `unsupported_format`, `no_guitar_detected`, `too_long`,
`fetch_failed`, `internal`. Those strings are a contract — the UI maps each to
actionable text so the user knows whether to try a different file, a different
song, or come back later.

## Testing a stage

Test contracts and shapes, not musical accuracy. Accuracy is the evaluation
harness's job — see the `eval-harness` skill.

- Stub the expensive stage. A 5-second fixture clip with separation stubbed
  asserts the pipeline's shape without a GPU.
- Stage 4 needs no audio at all: feed note sequences, assert fingerings.
- Every note leaving stage 4 must pass
  `guitarvis_core.fretboard.check_invariant`.

## Adding a stage

1. Define the Protocol and its data types in `contracts.py`.
2. Add a module under `stages/` implementing it.
3. Assert `isinstance(YourStage(), YourProtocol)` in
   `apps/worker/tests/test_stages.py`. `isinstance` against a
   `@runtime_checkable` Protocol only compares method *names* — it cannot see
   whether the signatures match. Also add a statically typed assignment, e.g.
   `_your_stage: YourProtocol = YourStage()`, so mypy checks the actual
   signature. The assignment is what makes conformance able to fail; the
   `isinstance` assertion alone cannot.
4. Decide what the tab document loses when it fails, and add the row to the
   degradation table above and in the design spec.
