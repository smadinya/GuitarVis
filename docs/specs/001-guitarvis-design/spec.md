# GuitarVis — Design

**Date:** 2026-09-24
**Status:** Approved design, pre-implementation

## Purpose

GuitarVis takes a recording of a song, isolates the guitar, transcribes what it
plays, and renders the result as tablature that a learner can play along with —
in three views: scrolling tab notation, a 2D fretboard, and a 3D guitar.

The audience is musicians and beginners who want to play songs they already
love. The core experience is synced play-along: audio plays, the views follow,
and practice controls (looping, slow-down, stem isolation) let the user work a
passage until it sticks.

## Context and constraints

- Portfolio piece first, with a credible path to real users. Architecture
  should not foreclose scaling, but v1 need not implement it.
- Solo developer, strong in Python and TypeScript/React.
- Web app first. iOS and desktop clients are anticipated, so all clients
  consume the same HTTP API and the same tab document.
- Server-side ML. The browser never runs models.
- Primary input is user file upload; URL ingestion (e.g. YouTube) is an
  additional, isolated path.

## Approach

A **staged pipeline with guitar-specialized transcription**, starting from an
off-the-shelf configuration.

Four independent stages — separation, transcription, musical structure,
fretboard assignment — each behind a narrow interface and separately testable.
Stage 2 (transcription) begins with a general-purpose polyphonic model and is
designed to be swapped for a guitar-specific one once an evaluation harness can
prove the swap is an improvement.

Rejected alternatives:

- **End-to-end learned tab model** (audio → tab in one network). Highest
  ceiling — it learns idiomatic fingerings rather than inferring them — but it
  is a research project. Available ground-truth data (GuitarSet, ~3 hours of
  clean solo guitar) is thin for generalizing to full mixes, and the approach
  demands GPU budget and ML depth incompatible with a solo v1. High risk of
  nothing demoable for months.
- **Generic MIDI-first only.** The starting configuration, not the
  destination. Adopted as stage 2's initial implementation precisely so the end
  to end system works early; the staged architecture exists so it can be
  replaced.

The deliberate consequence: the step that makes output *tablature* rather than
MIDI — fretboard assignment — is deterministic code under full control, so it
can be correct even when the ML above it is not.

## Architecture

Three deployable components plus storage.

**`api`** (FastAPI) — thin. Accepts an upload or URL, validates, creates a
`Job`, enqueues it, returns a job id. Serves job status, finished tab
documents, and audio for playback. No ML code, no model weights; scales
independently of GPU work.

**`worker`** (Python, separate process/container) — owns the pipeline. Pulls
jobs, runs the stages, reports per-stage progress, persists the tab document
and stems. The only component needing torch, GPU, or weights. Stateless:
everything it needs comes from the job payload and object storage.

**`web`** (React + TypeScript, Vite) — upload, job progress, then the three
synced views. Talks only to the documented HTTP API.

**Storage** — Postgres (jobs, tab documents), S3-compatible object storage
(uploaded audio, isolated stems, intermediate artifacts; MinIO locally), Redis
(queue broker).

### Job flow

```
upload ──▶ api ──▶ [jobs] ──▶ worker
                                │ separation      (progress 0–40%)
                                │ transcription   (40–65%)
                                │ structure       (65–80%)
                                │ fretboard       (80–100%)
                                ▼
                        tab document ──▶ api ──▶ web
```

Full-song processing is an asynchronous job, not a request/response call —
separation alone takes tens of seconds to minutes.

The client polls `GET /jobs/{id}` for stage and percent. Polling rather than
WebSockets: jobs run for a minute or more, stage-level granularity is
sufficient, there is less to build and less to break, and it works unchanged
from a future native client.

### Two deliberate boundaries

**Ingestion is a source adapter.** `UploadSource` and `UrlSource` both produce
"a local audio file plus metadata." The URL path is one implementation of one
interface — swappable, independently testable, and disableable by config. It is
the component most likely to break (URL extraction tooling breaks often) or to
need removal for legal reasons, so it is walled off. See Risks.

**The worker is reachable only through the queue.** It exposes no HTTP surface.
This is what allows it to move to a GPU host, another cloud, or — in a future
desktop build — the user's own machine, with no API change.

**Future clients:** because every client consumes the same tab document over
the same API, a later iOS or desktop app reimplements rendering only.

## The tab document

The contract between pipeline and all clients, present and future.

```jsonc
{
  "schema_version": 1,
  "source": { "title": "...", "duration_sec": 214.3, "audio_url": "..." },
  "instrument": {
    "tuning": ["E2","A2","D3","G3","B3","E4"],   // low → high
    "capo": 0,
    "string_count": 6
  },
  "timing": {
    "beats": [ { "t": 0.52, "bar": 1, "beat": 1 } ],
    "tempo_bpm_avg": 128.4,
    "time_signature": "4/4"
  },
  "notes": [
    {
      "id": "n_0041",
      "t": 12.84,              // onset, seconds — authoritative
      "dur": 0.21,
      "midi": 52,              // E3
      "string": 2,             // 0 = low E, so string 2 = D3
      "fret": 2,               // D3 + 2 semitones = E3 ✓ invariant holds
      "confidence": 0.81,
      "technique": null        // "bend" | "slide" | "hammer" | "mute" | ...
    }
  ],
  "chords": [
    { "t": 12.80, "dur": 1.92, "symbol": "Am", "confidence": 0.93 }
  ],
  "sections": [
    { "t": 0.0, "dur": 18.2, "label": "intro" }
  ]
}
```

**Seconds are authoritative; musical position is derived.** Every note carries
a wall-clock onset; bars and beats live in a separate `timing.beats` array
mapping time to musical position. Beat tracking is the most error-prone stage.
Storing note positions as bar/beat would let a tempo error desynchronize
playback from audio — the one thing a play-along app must never do. As
designed, a bad beat grid yields ugly bar lines over correctly synced notes: a
degraded experience rather than a useless one.

**A flat note list, not notes nested in measures.** Measures are computed from
the beat grid at render time. The document stays stable when timing is
corrected; the fretboard views (which care about time and position, not bars)
parse no structure they do not need; and future editing mutates a flat array.

**Confidence is first-class**, per note and per chord. With no editing in v1,
the interface's honesty depends entirely on this field. Silent wrongness is the
failure mode to avoid: a beginner cannot distinguish a wrong tab from a hard
passage, and will conclude they are bad at guitar.

**Slots exist for what v1 will not fill.** `technique` and `capo` ship as
`null`/`0`. Reserving them costs nothing; adding fields later means versioning
the schema and updating every client. `schema_version` lets a future client
refuse a document it does not understand rather than render it wrong.

## Pipeline stages

Each stage is a class behind a narrow interface, taking and returning plain
data. The worker orchestrates; no stage knows what runs before or after it.

### Stage 1 · Separation
`Separator.isolate(audio_path) -> SeparationResult`

Demucs `htdemucs_6s`, which provides a dedicated guitar stem. Output is
whatever Demucs writes — 16-bit stereo at the model's own 44.1kHz, which it
resamples the input to. Nothing is resampled or downmixed at this stage: stage
2 resamples internally and stage 3 downmixes to mono, so normalizing here would
be redundant work on every job.
If the guitar stem is empty or near-silent — common when a heavily distorted
guitar is attributed elsewhere — fall back to the 4-stem `other` track and
mark the document with a quality warning. This stage dominates job time.

### Stage 2 · Transcription
`Transcriber.transcribe(stem_path) -> list[NoteEvent]`

Starting implementation: `basic-pitch` — polyphonic, CPU-runnable,
pip-installable, and it emits per-note activation strength that maps to
`confidence`.

`NoteEvent` is `(onset, duration, midi_pitch, confidence)` — deliberately **not**
string/fret, so that a guitar-specific model can later implement the same
interface. This is the single upgrade point the staged architecture exists to
protect.

### Stage 3 · Musical structure
`StructureAnalyzer.analyze(stem, mix) -> Timing + Chords`

Beat and downbeat tracking run on the **original mix**, not the guitar stem:
drums are the strongest beat cue and the stem has them removed. Chord detection
runs on the guitar stem via chroma template matching. Section labels are
optional; if unreliable, the field stays empty and the UI omits them.

### Stage 4 · Fretboard assignment
`FretboardMapper.assign(notes, tuning) -> list[TabNote]`

The deterministic core. Notes within a ~50ms window group into a simultaneous
*voicing*. Each pitch has 2–4 candidate string/fret positions; each voicing has
a set of playable combinations, filtered by physical constraints (max ~4-fret
stretch, one note per string, barre feasibility). A Viterbi pass over the
voicing sequence minimizes total cost:

- fret span within a voicing — tight shapes beat impossible stretches
- hand-position movement between consecutive voicings — the dominant term, as
  real players stay put
- open-string preference, and a mild penalty for high frets when a lower
  position exists

Testable without audio: feed note sequences, assert fingerings.

**Hard invariant:** the pitch implied by `(string, fret, tuning)` must equal the
input MIDI pitch, for every note, always.

### Cross-cutting

Jobs are keyed by content hash of the input audio, so reprocessing a file is a
cache hit. Each stage writes its intermediate to object storage, so a stage-3
failure does not force re-running separation on retry.

### Evaluation harness

Infrastructure, not a nice-to-have. GuitarSet provides audio with ground-truth
string/fret annotations. `make eval` reports note F1 (onset within 50ms plus
correct pitch), string-assignment accuracy, and chord accuracy on a held-out
set, written to a tracked file so changes are visible over time.

Without this, "swap in a better model later" is a wish. With it, it is a
measurement. Build it alongside stage 4, before any model swap.

## Client

**One clock, three renderers.** A `PlaybackEngine` owns the audio element and
is the sole source of truth for current time. Views subscribe to
`(tabDocument, currentTime)` and render: they hold no playback state, do not
communicate with each other, and can be added or removed independently. A
fourth view later is a new subscriber, not a refactor.

Per frame a cursor advances through the sorted `notes` array — monotonic during
normal playback, so O(1) per frame, with a binary search only on seek. It
yields notes sounding now and notes within a ~2s look-ahead window. Beginners
need to see what is coming; every view receives both sets.

### Views

- **Tab view** — scrolling notation strip, canvas-rendered (a 4-minute song has
  thousands of notes; SVG nodes at that count stutter). Bar lines from the beat
  grid; chord symbols above the staff.
- **2D fretboard** — SVG, top-down neck. Active notes light up, look-ahead
  notes appear ghosted. Teaches where the hand goes; cheapest to build.
- **3D guitar** — react-three-fiber, neck angled as the player sees it. The
  showcase piece, and the one that can be built last without blocking anything.

### Layout

```
┌────────────────────────────────────────────┐
│   [ 3D guitar  |  2D fretboard ]  ← toggle │
│                                            │
│            main visual panel               │
│                                            │
├────────────────────────────────────────────┤
│  tab strip (always visible, scrolling)     │
├────────────────────────────────────────────┤
│  ▶  ──────●───────────  0:42 / 3:34        │
│  speed [0.5×|0.75×|1×]  loop [A]—[B]  ♪mix │
└────────────────────────────────────────────┘
```

The tab strip stays pinned in every mode because it is what the user reads
*ahead* from; the fretboard views show the present moment. They answer
different questions and should not compete for the same space.

### Practice controls

A/B loop, speed reduction, and a mix/stem toggle. The isolated guitar stem
already exists, so letting a learner solo the guitar — or mute it and play over
the backing track — is nearly free and is the feature practicing musicians are
most likely to use.

### Confidence rendering

Low-confidence notes render de-emphasized (reduced opacity; lighter fret
numbers in the tab view). Below a threshold, the tab view stops printing fret
numbers for that passage and shows the chord symbol alone. The rule is uniform
across all three views and lives in one shared function.

## Failure handling

**Degrade, do not fail.** Every stage after separation is optional to the core
promise. A job fails outright only when there is no usable guitar audio.

| What broke | What the user gets |
|---|---|
| Beat tracking | Notes still sync to audio; no bar lines, no chord grid |
| Chord detection | Note tab only; chord track hidden |
| Transcription confidence collapses in a passage | That passage shows chord symbols instead of fret numbers |
| Guitar stem empty/near-silent | Retry with 4-stem `other`; if still empty, fail honestly: "No clear guitar part found" |

The tab document's independent, individually-omittable tracks were shaped
around this table.

**Honest failure messages.** Failures carry a typed reason —
`unsupported_format`, `no_guitar_detected`, `too_long`, `fetch_failed`,
`internal` — which the UI maps to actionable text. The user needs to know
whether to try a different file, a different song, or come back later.

**Ingestion guards.** Max duration (~10 min), max file size, format validation
before any expensive work begins, and per-IP concurrent-job limits.

**Retries.** Stages are idempotent and intermediates are cached by content
hash, so a retry resumes rather than re-running separation. Three attempts,
then dead-letter with the failing stage recorded.

## Testing

**Correctness is tested; quality is measured.** Confusing the two produces a CI
suite that fails because a model got 2% worse on a Tuesday.

**Tested in CI (deterministic, no GPU):**

- **Fretboard mapper** — the bulk of unit tests, as it is pure logic. Property
  test the hard invariant: `pitch(string, fret, tuning) == input_midi`. Fixture
  cases: a C-major scale stays in one hand position; a known chord voicing
  comes out as the standard shape.
- **Tab document schema** — validation, round-trip, version rejection.
- **Degradation ladder** — feed documents with each track missing; assert the
  client renders the right fallback.
- **Playback sync** — a fake clock drives the engine; assert active and
  look-ahead note sets at given timestamps. No real audio needed.
- **Pipeline integration** — 5-second fixture clips with separation stubbed,
  asserting shapes and contracts rather than musical accuracy.

**Measured, not gated:** the GuitarSet evaluation harness, run on demand,
reporting note F1, string accuracy, and chord accuracy to a tracked file.

## Known limitations

Polyphonic guitar transcription with string/fret assignment is not a solved
problem. Expect roughly 70–85% note accuracy on clean recordings and worse on
dense mixes. The design responds to this with first-class confidence, the
degradation ladder, and a deterministic fretboard stage — not by assuming the
models will be right.

v1 has no editing, so transcription errors cannot be corrected by the user.
This is an accepted v1 tradeoff; the flat note list is shaped to make editing a
straightforward later addition.

## Open decisions

Deliberately unresolved. Each records the default v1 takes and what would force
a different answer.

1. **Chord source** — independent detection from the stem (chosen for v1, more
   robust to transcription error) vs derivation from transcribed notes
   (guarantees the chord and note views agree). Revisit if the two views
   visibly contradict each other.
2. **Beat tracker** — `librosa` (chosen: easy install, mediocre on rubato and
   live material) vs `madmom` (notably better; heavier install and a
   non-commercial licensing clause). **The license question needs an answer
   before any commercial launch, not after.**
3. **Tuning detection** — v1 assumes standard tuning. Drop-D and half-step-down
   are common in exactly the rock and metal material beginners want, and a
   wrong assumption makes every fret number wrong while the pitches stay right.
   Detection from the pitch histogram and lowest sustained notes is feasible;
   deferred.
4. **Capo detection** — same class of problem, harder; deferred. Schema slot
   exists.
5. **Polyphony ceiling** — `basic-pitch` will merge or drop notes in a dense
   six-string strum. Unresolved whether v1 shows the sparse result or falls
   back to chord-only display above a density threshold. Needs real output to
   judge.
6. **Multiple guitar parts** — separation yields one guitar stem even when
   rhythm and lead play simultaneously. v1 treats it as a single part.
   Splitting parts is a hard research problem, explicitly out of scope.
7. **Pitch-preserved slow-down** — the largest client-side risk. Naive
   `playbackRate` shifts pitch, which is useless for playing along (0.75× drops
   the song a fourth). Real time-stretching needs a phase vocoder
   (`soundtouchjs` or a WASM build) through Web Audio: meaningfully more work
   and a known source of artifacts. Either ship 1× only in v1 or budget real
   effort. Decide with the audio path in hand.
8. **3D guitar asset** — procedural geometry (chosen default: full control,
   programmer-art risk) vs a sourced glTF model (better looking; licensing and
   file size). A good asset is a visible upgrade for a portfolio piece.
9. **Simultaneous views** — one fretboard view at a time for now. Whether 3D
   and 2D should render side-by-side is best answered by using it.
10. **Mobile/responsive scope** — the layout assumes a desktop viewport. Phone
    layout is a real design problem, deferred — but it bears directly on the
    planned iOS app and should not be deferred indefinitely.
11. **Accounts and persistence** — v1 is anonymous and session-scoped. Saved
    libraries and accounts are a scaling concern.
12. **Hosting and GPU** — CPU-only inference runs several minutes per song for
    separation but has no idle cost. Needs a decision before public users, not
    before a demo.
13. **Stored copyrighted audio** — caching uploads and derived stems creates a
    takedown surface. A retention policy (e.g. audio expires after N days, tab
    documents persist) should be decided before launch.

## Risks

- **URL ingestion.** Fetching audio from YouTube violates its terms of service
  and is an operational and legal risk for a public product. It is deliberately
  isolated behind the source-adapter interface so it can be disabled by config
  or removed entirely without touching the rest of the system. Accepted
  knowingly for v1.
- **Transcription quality** may fall short of useful on the dense, distorted
  material users most want. The evaluation harness exists to make this visible
  early rather than at launch.

## Build phases

This spec covers the whole system; the implementation plan should not.

1. **Pipeline skeleton** — ingest → separation → transcription → tab document,
   CLI-driven, no web UI. Proves the hard part first.
2. **Fretboard mapper + evaluation harness** — the deterministic core and the
   measurement infrastructure.
3. **API + job queue** — wrap the pipeline in the service.
4. **Web client: tab view + sync** — first real end-to-end experience.
5. **2D fretboard**, then **3D guitar**.
6. **URL ingestion.**

Phases 1–2 hold all the technical risk and should form the first
implementation plan. The remainder is comparatively conventional work.
