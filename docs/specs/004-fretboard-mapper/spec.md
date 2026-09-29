# Fretboard Mapper and Evaluation Harness — Design

**Date:** 2026-09-29
**Status:** Approved design, pre-implementation
**Parent spec:** [001-guitarvis-design](../001-guitarvis-design/spec.md)
**Builds on:** [003-pipeline-skeleton](../003-pipeline-skeleton/spec.md) — read
its [carried findings](../003-pipeline-skeleton/review-notes.md) first

## Purpose

Build phase 2: stage 4 turns pitched note events into string and fret
positions, and an evaluation harness measures how well it — and the stages
above it — do against GuitarSet ground truth.

After 003 the pipeline emits a document with an empty `notes` array. This phase
fills it, and makes the result measurable. The parent spec calls the harness
infrastructure rather than a nice-to-have: without it, tuning the mapper's
costs or swapping the transcription model is guesswork.

The success conditions:

1. `guitarvis-worker process song.mp3 -o song.json` produces a document whose
   `notes` are non-empty and every one passes `check_invariant`.
2. `make eval` reports the mapper's string accuracy on the held-out GuitarSet
   split, next to a naive baseline, and writes the result to `eval/results/`.
3. `make eval ARGS=--full` reports note F1, string accuracy and chord accuracy
   for the full transcription → structure → mapper chain.

## Scope

**In:** `ViterbiFretboardMapper`; a `FretboardResult` return type carrying
warnings; the orchestrator's stage-4 degradation; the GuitarSet download
target; a JAMS reader; the oracle and full evaluation modes; a lowest-position
baseline mapper used only by the harness; the results file format.

**Out:** technique detection (slides, bends, hammer-ons); capo detection;
letting a long rest discount hand movement; sub-stage progress during
separation; the shared worker `conftest.py` (still recorded in the 003
review notes); any CI use of evaluation numbers. No `tabdoc.py` change, so no
schema regeneration.

## Approach

### Contract change

`FretboardMapper.assign(notes, tuning)` returns a `FretboardResult(notes:
list[TabNote], warnings: list[str])` instead of a bare `list[TabNote]`. This
mirrors `SeparationResult` and `StructureResult`, and it is forced: the mapper
must be able to drop notes it cannot place (below, *Degrading*), and a silent
drop is exactly the kind of loss the client is supposed to show. `TabNote`
itself is unchanged.

### Stage 4 · the mapper

Pure Python in `apps/worker/src/guitarvis_worker/stages/fretboard.py`. It needs
nothing heavy, which also keeps it clear of the stage-module rule against
module-level numpy.

**Grouping.** Notes are sorted by onset. A note joins the current voicing if
its onset is within 50ms of that voicing's *first* note; otherwise it starts a
new one. Anchoring to the first note, rather than the most recent, stops a fast
run from chaining into one many-note "chord".

**Candidates.** For each note, every string `s` with
`0 ≤ midi − open_pitch(s) ≤ max_fret`. Open pitches come from
`guitarvis_core.fretboard.parse_pitch`, so any tuning with any string count
works without special cases.

**Playability.** A combination of candidates — one per note — is a playable
fingering when:

- no two notes share a string;
- the fretted notes (fret > 0) span at most `max_span` frets;
- it can be held with four fingers: all notes at the lowest fretted fret are
  covered by one finger (a barre), and the remaining distinct fretted notes
  need at most three more. Open strings need no finger.

**Fingering cost.** For one fingering:

```
span_weight · span + height_weight · position − open_bonus · open_strings
```

where `position` is the lowest fretted fret. The height term is the "mild
penalty for high frets when a lower position exists"; the open bonus is the
open-string preference. Only the `beam` cheapest fingerings per voicing are
kept, which bounds Viterbi's per-step work. A single note has two to four
candidates and a full six-note chord rarely has more than twenty playable
fingerings, so in practice the beam only bites on pathological input.

**Transition cost.** `move_weight · |position_a − position_b|`. The parent
spec calls this the dominant term: real players stay put. A voicing of only
open strings has no position; moving into or out of it costs nothing, since
open strings free the fretting hand.

**Search.** Viterbi over the voicing sequence, minimising the sum of fingering
and transition costs. Ties break toward the lower fret, then the lower string,
so the same input always yields the same tab. Output is sorted by onset, then
string.

**Configuration.** A frozen `MapperCosts` dataclass holds the four weights plus
`max_fret` (default 20), `max_span` (default 4) and `beam` (default 50), and is
passed to the mapper's constructor with defaults. The weights are tuned on the
dev split (below) without code edits, and every evaluation result records the
values it ran with.

**Degrading.** The invariant forbids a wrong fret, so a note that cannot be
placed correctly is dropped, never approximated:

- a note with no candidate at all (outside the instrument's range, usually a
  transcription error) is dropped;
- a voicing with no playable fingering (more notes than strings, or an
  impossible stretch) drops its lowest-confidence note, repeatedly, until a
  fingering exists.

Each kind of drop produces one aggregated warning — "12 notes outside the
guitar's range were dropped" — not one per note. An empty input returns an
empty result.

### The orchestrator

In `pipeline.py`:

- The mapper's warnings are appended to the document's warnings.
- `except NotImplementedError` becomes `except Exception`, as 003's review
  notes require. A mapper that raises costs the notes track, not the job,
  matching stages 2 and 3. The "not implemented yet" warning and its comment
  go.
- `check_invariant` still runs on every returned note, and a violation still
  raises `PipelineError(INTERNAL)`. A wrong fret is a bug in the mapper, not a
  degraded result, and must not be dressed up as one.

The degradation tables in the parent spec and the `pipeline-stage` skill gain
two rows: *mapper raised* → notes track omitted with a warning; *notes
unplaceable* → those notes dropped, count shown as a warning.

### The evaluation harness

Lives in `apps/eval`, which gains a dependency on `guitarvis-worker` (its base
install, which is light) for the mapper, and an optional extra
`full = ["guitarvis-worker[ml]", "mir_eval"]`. numpy and scipy arriving through
`mir_eval` are fine here; only `apps/api` carries the import ban.

**Data.** `make eval-data` downloads GuitarSet's `annotation.zip` (about 40 MB)
from Zenodo record 3371780 — and, with `ARGS=--audio`, the 650 MB
`audio_mono-mic.zip` that only full mode needs — verifies their MD5s, and
unpacks them into `~/.cache/guitarvis/guitarset/`, outside the repo. The
harness reads `GUITARSET_DIR`, falling back to that cache; if the data is
absent it prints the command to run and exits non-zero.

**Reading.** A standard-library JAMS reader in `guitarvis_eval`. Each excerpt
carries six `note_midi` annotations, one per string, whose `data_source` is the
string index with 0 as low E — the same convention as `Note.string`, so ground
truth needs no remapping. JAMS pitches are floats and are rounded to the
nearest MIDI number. Chords come from the *performed* chord annotation, not
the instructed one.

**Split.** Excerpt names begin with the player, e.g. `05_BN1-129-Eb_comp`.
Player 05 — 60 of the 360 excerpts — is `test`, the default and the split that
gets committed. Players 00–04 are `dev`, used when tuning `MapperCosts`.
Splitting by player keeps one player's habits from leaking between tuning and
measurement.

**Oracle mode** (`make eval`, the default). Ground-truth notes, with rounded
pitch and confidence 1.0, go through both `ViterbiFretboardMapper` and the
baseline. Pitch is identical by construction, so matching is one-to-one and
**string accuracy** is simply the share of notes on the ground-truth string.
Reported overall and separately for comp and solo excerpts, for mapper and
baseline side by side. Pure Python, runs in seconds, needs no `ml` extra.

**The baseline** places every note at its lowest playable fret, with no
grouping and no search. It exists only in the harness, as the number the
mapper has to beat; without it, a string accuracy figure has no reference
point.

**Full mode** (`make eval ARGS=--full`, requires `uv sync --extra ml`).
Separation is skipped — GuitarSet is already solo guitar — and the mic audio
goes straight to `BasicPitchTranscriber`, then the mapper, and to
`LibrosaStructureAnalyzer`. Metrics:

- **Note F1** via `mir_eval.transcription`, offsets ignored: a hit is an onset
  within 50ms with the exact pitch, each note matched at most once. Using
  `mir_eval` keeps the number comparable with published results.
- **String accuracy:** of the matched pairs, the share on the ground-truth
  string.
- **Chord accuracy:** ground truth and prediction sampled on a 100ms grid;
  ground truth reduced to the analyzer's vocabulary (major, minor, or no
  chord); the share of samples that agree. Samples whose ground truth has no
  major or minor reading — sus, diminished, power chords — are left out
  rather than counted against an analyzer that cannot express them.

**Results.** One run writes
`eval/results/<date>-<short sha>-<mode>-<split>.json`, holding the commit and
whether the working tree was dirty, the mode, split and `MapperCosts` values,
the aggregates, and a per-excerpt breakdown. It also prints a summary table.
Committing the file is a deliberate human step. Nothing in CI reads it.

## Rejected alternatives

**States are hand positions, not fingerings.** Viterbi over fret positions
0–15, choosing the best fingering per position locally. A smaller, fixed state
space — but two fingerings at the same position look identical to the
transition cost, which throws away exactly the string choice (staying on one
string through a run) that string accuracy measures.

**Greedy lowest-position as the mapper.** No global view, so it hops to open
strings and back mid-phrase. Kept as the harness baseline instead, where its
weakness is the point.

**Oracle-only or full-only evaluation.** Oracle alone leaves the parent spec's
note F1 and chord accuracy unmeasured. Full alone mixes transcription errors
into the mapper's number, only partly filtered by scoring matched notes.
Running both is what lets string accuracy isolate stage 4, as the
`eval-harness` skill describes.

**`mirdata` for loading GuitarSet.** It would handle download and parsing, but
pulls a large dependency tree into a package whose data format is six JSON
arrays per file. A small reader and an MD5-checked download are less to trust.

**A random 20% split, or none.** Random splits mix players across tuning and
measurement; no split measures tuned weights on the data they were tuned
against.

## Consequences

The pipeline emits real tablature for the first time. Every note in it is
guaranteed to sound the transcribed pitch; whether it is where a guitarist
would play it is now a number, not an opinion.

Changing the `FretboardMapper` return type touches the protocol, the
implementation, the orchestrator, and every test double of the mapper. It is
done once, now, while there is exactly one implementation.

`apps/eval` depends on `apps/worker`. That direction is fine — evaluation
measures the worker — but the worker must never import the eval package.

The `eval/results/` history starts here. The first committed oracle result on
`test` is the before-number every later cost change and model swap is compared
against.

## Risks

**Unidiomatic fingerings.** The costs can produce tab that is mechanically
sound but not what a player would choose — the failure ADR 0003 accepts as
better than a wrong note. The dev split and the baseline comparison are how
this is found and tuned, not a guarantee it is absent.

**Weight tuning overfits to GuitarSet.** Clean solo excerpts in five
genres (rock, singer-songwriter, bossa nova, jazz, funk) from six players are
not dense, distorted, mixed material. The held-out
player guards against overfitting to a player, not to the dataset. Treat the
numbers as relative between runs, as the `eval-harness` skill says.

**Beam pruning discards the globally best path.** Pruning by fingering cost
alone can drop a fingering that is locally worse but saves a large move. With
a beam of 50 against typical candidate counts under 20, this should almost
never bite; if the dev split suggests otherwise, the beam widens.

**Grouping at the 50ms edge.** Strummed chords can spread past 50ms, splitting
one chord into two voicings. The transition cost keeps both halves in one
position, so the fingering usually survives the split; if the dev split shows
otherwise, the window becomes a `MapperCosts` field rather than a constant.

**Zenodo availability.** The download depends on an external host. The
checksums catch corruption; a missing host means `make eval-data` fails
clearly and the harness can still be pointed at a local copy via
`GUITARSET_DIR`.
