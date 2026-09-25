# Pipeline Skeleton — Design

**Date:** 2026-09-25
**Status:** Approved design, pre-implementation
**Parent spec:** [001-guitarvis-design](../001-guitarvis-design/spec.md)

## Purpose

Build phase 1: audio goes in, stages 1–3 run, a valid tab document comes out,
driven from a command line. This is where the parent spec's central claim —
that a staged pipeline can be assembled from off-the-shelf parts — either holds
or does not.

The success condition is a real song processed end to end: `guitarvis-worker
process song.mp3 -o song.json` produces a document that validates against the
committed schema, with a beat grid, a chord track, and a reported count of
transcribed note events.

## Scope

**In:** ingestion of a local file with its guards; stage 1 separation; stage 2
transcription; stage 3 beats and chords; the orchestrator implementing the
degradation ladder with per-stage progress; the CLI; the ML dependency wiring
that makes all of it installable.

**Out:** stage 4 fretboard assignment and the evaluation harness — both belong
to [004-fretboard-mapper](../004-fretboard-mapper/), per the stage stubs. Also
out: the API, the job queue, object storage, content-hash caching, retries, and
URL ingestion, which all presuppose a job record that does not exist yet.

### The consequence of that split, stated plainly

Stage 4 turns pitches into string and fret positions, so until 004 lands, this
phase cannot emit `notes`. The CLI produces a document whose `notes` array is
empty, carrying an explicit warning and a printed count of the note events
transcription found. That is a real gap, deliberately taken: it keeps 003
reviewable as three independent stages rather than five, and 004 fills it by
implementing an already-wired interface. The alternative — a throwaway
lowest-fret-first mapper to make the output look complete — was rejected
because a plausible-looking wrong tab is exactly the failure mode the parent
spec's confidence handling exists to prevent, and a placeholder would be the
first thing to survive longer than intended.

## Approach

Implement the four stage classes that
[002-repo-bootstrap](../002-repo-bootstrap/spec.md) left as typed stubs, in the
slots they already occupy, against the protocols already declared in
`guitarvis_core.contracts`. No interface in core changes except one addition:
the ingestion boundary.

Three additions to core, each forced by something in scope:

**`AudioSource` and `IngestedAudio` in `guitarvis_core.contracts`.** The parent
spec argues ingestion is a source adapter so that URL fetching is one swappable
implementation; declaring the protocol in core — where the api can see it
without importing the worker — is the same argument the stage protocols already
make.

**`SeparationResult` in `guitarvis_core.contracts`, replacing `Separator`'s
bare `Path` return.** The degradation ladder requires stage 1 to report that it
fell back to the 4-stem `other` track. A `Path` cannot carry that, and stashing
it on the separator instance would make a stateless stage stateful.

**`TabDocument.warnings: list[str]`.** The parent spec requires marking a
document whose quality is degraded, and the schema committed in 002 has nowhere
to put it. The client is what must show "this came from the fallback track" or
"some notes could not be placed", so the signal belongs in the document rather
than in worker logs the client never sees. This regenerates
`schema/tab-document.schema.json` and `web/src/types/tabDocument.ts`. It is an
additive optional field, but note that `extra="forbid"` makes even additive
changes breaking for an external validator holding a bundled copy of the schema
— the open-decision table already tracks that, and no external client exists
yet.

### Stage 2's backend

`basic-pitch` through **ONNX Runtime, with TensorFlow overridden out of the
dependency graph**. Recorded as [ADR 0006](../../decisions/0006-onnx-transcription-backend.md).

This was an open question because basic-pitch 0.4.0 unconditionally requires
`tensorflow<2.15.1` on Linux at Python ≥3.11, and no cp312 wheel of that
TensorFlow exists. A spike settled it: the published wheel already ships
`saved_models/icassp_2022/nmp.onnx`, `basic_pitch.inference` selects its
backend at import time from what is installed rather than importing TensorFlow
unconditionally, and with only `onnxruntime` present it resolves
`ICASSP_2022_MODEL_PATH` to the ONNX model and transcribes correctly — a
two-pitch polyphonic test signal came back as MIDI 69 and 73 in 0.34s for 2s of
audio on CPU.

Rejected alternatives:

- **Pin the workspace to Python 3.11.** Works with no tricks, but all four
  manifests, CONTRIBUTING, and CI move to an older Python together, and the
  constraint would outlive the problem.
- **A different polyphonic transcriber.** The realistic candidates are
  monophonic (crepe), instrument-specific (piano transcription), unmaintained,
  or heavier than this phase justifies. None is clearly better than the model
  the parent spec already chose.
- **Vendor `nmp.onnx` and write our own post-processing.** Avoids the
  dependency override entirely, but note creation — thresholding, onset
  matching, note segmentation — is the non-trivial part of basic-pitch, and
  reimplementing it to import a file we could import anyway trades a packaging
  problem for a correctness problem. Kept as the fallback if the override
  mechanism fails.

The override also has to force `resampy>=0.4.3`. basic-pitch pins
`resampy<0.4.3`, and those versions import `pkg_resources`, which setuptools
≥81 no longer ships — a second, independent Python 3.12 break found by the same
spike.

## Consequences

Stage 2 runs on CPU with no GPU requirement and no TensorFlow anywhere in the
tree, which keeps the worker image smaller than the parent spec assumed. The
cost is two dependency overrides that a future `uv lock` refresh could
invalidate silently: if basic-pitch ever relaxes its TensorFlow pin, or a
transitive dependency starts requiring the real thing, the override is where to
look first.

Pinning transcription to a specific released artifact — the ONNX file inside a
wheel — makes the phase's output reproducible. It also means an upstream
release that reorganises `saved_models/` breaks stage 2 loudly at import, which
is the right failure mode.

## Risks

- **The dependency override is the load-bearing trick.** If uv's
  `override-dependencies` cannot express "drop this requirement", the fallback
  is vendoring the model file. The first task verifies the override before any
  stage code is written.
- **Separation dominates runtime and is unverified at full length.** The spike
  measured transcription only. Demucs on a 4-minute song may need
  `--segment` on a 6GB GPU, and is minutes-long on CPU.
- **Chroma template matching is a weak chord detector** on distorted or dense
  material. The degradation ladder covers it: a poor chord track is omitted, not
  wrong.
