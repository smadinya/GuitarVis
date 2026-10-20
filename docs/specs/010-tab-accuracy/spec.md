# Tab Accuracy — Design

**Date:** 2026-10-19
**Status:** Implemented
**Parent spec:** [001-guitarvis-design](../001-guitarvis-design/spec.md)
**Builds on:** [004-fretboard-mapper](../004-fretboard-mapper/spec.md);
[006-tab-view-sync](../006-tab-view-sync/spec.md) for the confidence thresholds
**Research:** [research.md](research.md), which holds every number this spec
quotes. Deferred ideas: [future.md](future.md)

## Purpose

Real output has four faults:

1. Chords land on the wrong strings.
2. Notes that ring together are put on one string, one straight after the other.
3. Notes and chords sit where no player would put them.
4. There is a lot of noise: notes nobody played.

The research traced most of the wrong strings to stage 4's cost model, not to
the transcriber. Given GuitarSet's exact pitches, the mapper puts 54.0% of
the held-out player's notes on the right string, and 30.2% in solos. Its
errors run one way: one string higher and five frets lower than the player,
or onto an open string the player fretted.

Three causes push it there:
- it counts every fret change as a hand move;
- it treats open strings as free;
- it settles every tie toward the nut.

It also never looks at how long a note rings. That is fault 2.

Most of the noise is basic-pitch's own artifacts:
- harmonic ghosts above a real note;
- octave errors;
- one note split in two.

In solos the ghosts also cause wrong strings. A ghost starts with the note it
shadows, so the mapper has to fit both under one hand shape, and the real
note moves off its string.

This spec fixes what can be fixed from pitches alone and leaves the next
lever, hearing which string was played, to its own spec.

The change is judged by people reading `make eval` results and looking at
real tab, never by CI
([ADR 0004](../../decisions/0004-evaluation-is-measured-not-gated.md)).

### When it is done

It comes in two halves that ship independently: stage 4 first, then stage 2.
Each half is a separately revertible set of commits, measured on its own.
A half that misses its conditions does not ship, and the other half can ship
without it.

Before-numbers are committed at the start. In what follows:
- **rises** means strictly above the before-number;
- **holds** means no more than 0.5 points below it.

Small effects on one player's 60 excerpts can flip on noise, and the
tolerance is there so noise alone cannot block a half.

**Stage 4 (the mapper)**, on `test`:

1. Oracle string accuracy rises in comp and in solo. The throwaway spike
   reached 65.5% overall, from 54.0%. That is a reference, not a quota.
2. Full-mode string accuracy rises in comp and in solo.
3. Same-string overlaps (a new metric, below) fall in both modes.

**Stage 2 (transcription)**, on `test`, with whichever mapper is shipping:

4. Full-mode note precision rises in comp and in solo. That is fault 4,
   measured.
5. Full-mode note F1 holds in comp and in solo.
6. Full-mode string accuracy holds in comp and in solo.
7. The real-song review (below) is signed off.

**Both halves:**

8. Every placed note still passes `check_invariant`, and the same input still
   gives the same tab.

If a condition fails, the regression is written up in this folder and that
half waits for an explicit decision.

### The real-song review

GuitarSet is clean solo acoustic guitar, and the real material is full-band
songs separated by Demucs. On the two small separated clips available, the
new decoding settings kept most notes on the guitar stems but cut the
`other` stem's notes roughly in half (see research.md). GuitarSet cannot see
that risk.

So each half is also run on the user's own songs, which are kept locally in
the gitignored `tmp/` and never committed. Each song goes through the
pipeline before and after the half.

A short report in this folder, `real-songs.md`, records for each song:
- note count;
- the confidence spread, from `web/scripts/confidence-report.ts`;
- the share of notes faded and hidden;
- warnings.

The user then looks at the before and after tab in the client.

The stage 2 half ships only with the user's sign-off. For the stage 4 half,
the review is informational: its GuitarSet conditions decide it, and the
user's look is a sanity check.

## Scope

**In:**
- **Stage 4's cost model:** a hand that covers a box of frets, open strings
  that cost something up the neck, no pull toward the nut, a penalty for
  reusing a string that is still ringing, and a cost for skipped strings in a
  chord.
- **Stage 2's decoding:** basic-pitch's decoding settings, made explicit and
  tuned, and removal of harmonic ghosts.
- **Evaluation:**
  - a same-string-overlap metric;
  - the transcriber's settings recorded in each result;
  - tuning on the dev split in full mode as well as oracle.
- **Downstream of the change:**
  - re-measuring the note confidence thresholds (`HIDE`, `FULL`);
  - bumping `CACHE_VERSION`.
- **The real-song review** and its report, `real-songs.md`.

**Out:**
- **Hearing which string was played** (TabCNN or similar). It is the next
  spec, and this one's results are its before-number.
- **Replacing basic-pitch.**
- **Raising the transcriber's confidence floor.**
- **Changing the 50 ms voicing window.**
- **Further mapper ideas from the literature:** scaling movement by the time
  available, a minimax search, learned chord-shape priors.
- **Technique and capo detection.**
- **Regenerating documents already stored.** Existing jobs keep their tab.

There is no change to `tabdoc.py`, `contracts.py`, or any stage's
signature. `NoteEvent`, `TabNote` and `FretboardResult` are untouched, so
there is no schema regeneration.

## Approach

### Stage 4 · the hand covers a box

Today the hand's position is the lowest fretted fret of the current fingering,
and every change in it costs `move_weight` per fret. A player at fifth
position reaches frets 5–8 without moving, so today's model charges for
movement that does not happen.

The search state stays *(fingering, hand position)*, but the hand position
becomes the index finger's fret *h*. The hand covers frets *h* to
*h* + `hand_window` − 1.

- **The shape fits inside the box** (the fingering's fretted notes run from
  *lo* to *hi*): the hand does not move and the transition costs nothing.
- **It does not fit:** the hand moves the shortest distance that makes it fit,
  clamping *h* into [*hi* − `hand_window` + 1, *lo*]. That costs
  `move_weight` × the distance. A shape wider than the box, which `max_span`
  allows by one fret, puts the index finger on *lo*.
- **All-open voicings** leave the hand where it was, as now.
- **Before the first fretted voicing** the hand is nowhere and arriving costs
  nothing, as now. The index finger lands on *lo*, not on any lower fret
  that would also fit. A hand placed lower would make later open strings
  cheaper for no physical reason.

One fingering can now be reached with the hand in different places, so it
can carry more than one state. That is the same mechanism all-open voicings
already use. The beam still bounds fingerings per voicing. Landing is a clamp
into a range at most `hand_window` frets wide, so each fingering carries at
most `hand_window` hand positions.

### Stage 4 · open strings and the pull toward the nut

**Open strings.** `open_bonus` goes. An open string becomes free while the
hand sits at or below `open_reach`. Above that, it costs `open_weight` per
fret per open string, charged on the hand position after the move. Players
do use open strings up the neck, so this is a cost, not a ban.

**Forced open notes are exempt.** A note whose only candidate is an open
string costs nothing wherever the hand is. The lowest string's open pitch is
the usual case: E2 in standard tuning, D2 in drop D. Every path must play
it open, so charging for it would only drag the surrounding phrase toward
the nut. A riff at frets 7–12 over an open-E pedal is the case this protects.

*Amended after the PR review (2026-10-20):* the exemption covers any note
that every playable fingering of its voicing puts on an open string, not
only a note with one candidate. Under an E2+A2 pedal, the A2's other place
is the low E string's 5th fret. The E2 always takes that string, so the A2
is open in every fingering. Charging it pulled the riff above it toward the
nut. The same reasoning applies: every path plays it open.

**The pull toward the nut.** `height_weight` stays as a field, but its value
comes from tuning; the spike found anything above zero hurt. The tie-break
rule (lower fret, then lower string, latest voicing first) stays. Determinism
needs a tie-break, and with the other pulls gone it only settles real ties.

### Stage 4 · strings that are still ringing

A transition into a fingering costs `ring_weight` for each string it uses
where the previous voicing's note on that string is still sounding.
"Still sounding" means the previous note's onset plus duration passes the
new voicing's first onset by more than `ring_tolerance`.

The previous voicing's fingering is already part of the search state, so
this fits Viterbi's first-order transitions with no new state. A note ringing
across two or more later voicings is only checked against the next one. The
research suggests that misses little, and the overlap metric will show
whether it matters.

**It is a cost, not a hard rule.** basic-pitch lets notes run past the point
where a player moved on to the next note on the same string. A strict rule
with a 30 ms tolerance cost eight points on transcribed solos. At 100 ms the
penalty helped in every column measured. The tolerance and the weight are
tuned in full mode as well as oracle, for that reason.

### Stage 4 · skipped strings in a chord

A fingering of three or more notes costs `gap_weight` per unused string
between its lowest and highest string. A strum hits adjacent strings, so a
chord with a hole in the middle is unlikely. Fingerstyle chords do skip
strings, so the weight stays small.

### Stage 4 · what does not change

- Grouping notes into voicings within 50 ms of the first note: 97% of
  GuitarSet strums fit inside it, before and after transcription.
- The playability rules: one note per string, `max_span`, four fingers.
- The beam, the dropping of unplaceable notes with aggregated warnings, the
  invariant, and the output order.

### `MapperCosts`

| Field | Status | Starting value |
|---|---|---|
| `move_weight` | kept | 1.0 |
| `span_weight` | kept | 0.5 |
| `height_weight` | kept | 0 |
| `open_bonus` | removed | — |
| `hand_window` | new, frets | 4 |
| `open_reach` | new, fret | 4 |
| `open_weight` | new | 0.2 |
| `ring_weight` | new | 2.0 |
| `ring_tolerance` | new, seconds | 0.1 |
| `gap_weight` | new | 0.3 |
| `max_fret`, `max_span`, `beam` | unchanged | — |

The starting values come from a spike that tuned each one alone, on a
sample. The shipped values come from tuning on the whole dev split in both
modes. `__post_init__` validates the new fields as it does the old ones.

### Stage 2 · decoding

`BasicPitchTranscriber` today calls `predict()` with basic-pitch's defaults.
The decoding settings become explicit: a frozen settings dataclass passed to
the constructor, defaulted like `MapperCosts`, and recorded in each full-mode
eval result.

The research sweep's starting point:

| Setting | Default | Starting point |
|---|---|---|
| `melodia_trick` | on | off |
| `frame_threshold` | 0.3 | 0.4 |
| `minimum_note_length` | 127.7 ms | about 58 ms |
| `onset_threshold` | 0.5 | 0.5 |

That raised note F1 on the test player from 0.777 to 0.800. It was tuned on
only one dev player, so the shipped values are tuned on all five.

**`frame_threshold` acts as a confidence floor.** basic-pitch's confidence is
a note's mean frame activation, and a note only continues while its frames
stay at or above `frame_threshold`. Raising the threshold to 0.4 is therefore
close to the 0.4 floor rejected below, applied before `MIN_CONFIDENCE` sees
a note. Turning `melodia_trick` off also drops notes without a detected
onset, which separated stems may have more of. Both settings stay in the
sweep. Whatever the sweep picks for them reaches production only through the
real-song review. If the review rejects a setting, it goes back to
basic-pitch's default, and the rest of the half can still ship.

### Stage 2 · harmonic ghosts

After decoding, `BasicPitchTranscriber` drops a note when all three hold:
- it sits 12, 19 or 24 semitones above another note, its base;
- the base is sounding at its onset: the ghost starts no earlier than 50 ms
  before the base's onset and no later than the base's end. A ghost often
  starts a frame or two before its base, so the 50 ms lead matters;
- its confidence is below `ghost_ratio` × the base's.

Two forms measured well on the dev sample, and tuning picks between them:
- the rule as stated with `ghost_ratio` around 0.6;
- the rule at 0.8, applied only when the ghost and its base are the only
  notes starting at that onset.

Both raised note F1 in comp and in solo. The plain rule at 0.8 cost comp 4.7
points of recall, because chords contain real octaves, so it is not a
candidate.

**Where it lives.** It lives in stage 2, inside `BasicPitchTranscriber`, as
pure Python over `NoteEvent`s that is testable without the model. Ghosts are
an artifact of this model. A future transcriber implementing `Transcriber`
should not inherit a fix for someone else's artifact, and stage 4 should not
learn one model's quirks.

**No warning.** A dropped ghost raises no warning, just as notes below
`MIN_CONFIDENCE` raise none. It is noise removed, not music lost.

### The confidence floor stays

`MIN_CONFIDENCE` stays at 0.1. A floor of 0.4 scored best on GuitarSet, but
GuitarSet is the wrong guide here. The first real song through the pipeline
had a median note confidence of 0.45
([calibration.md](../006-tab-view-sync/calibration.md#on-real-songs)), so a
0.4 floor would delete much of a real song. Faint notes keep rendering
faintly; that is 006's design, and the client's thresholds already do the
job. `frame_threshold` can raise the floor by the back door, which is why it
answers to the real-song review.

### Recalibrating the confidence thresholds

New decoding settings move the confidence distribution, and `HIDE` and `FULL`
in `web/src/confidence.ts` were measured on the old one. After the shipped
settings are chosen:
- rerun `make eval ARGS=--full` on `test`;
- re-derive both values with 006's rule;
- record the new table in a new section of
  [calibration.md](../006-tab-view-sync/calibration.md) that cites the new
  results file;
- update `confidence.ts`, even if the values come out unchanged, so it cites
  the new run.

**Some results need a decision before they are applied.** If the rule gives
`HIDE` or `FULL` as 0 or "not supported", or moves either by more than 0.1,
the work stops and the user decides. `threshold()` returns 0 when no band
with enough notes falls short of the target precision, and None ("not
supported") when the measurement cannot support a threshold. A 0 can happen
once ghosts are gone and the low bands empty out. On GuitarSet it would mean
nothing ever fades, while real songs, whose notes sit near 0.45, would still
need fading. A mechanical rule should not make that call.

The chord thresholds are untouched, because the analyzer is untouched.

### Evaluation

- **Same-string overlaps.** These are placed notes that start on a string
  while the previous placed note on that string sounds on by more than 30 ms,
  reported per 1000 placed notes. It uses each note's own duration: the
  truth's in oracle mode, the transcriber's in full mode. Oracle reports it
  for the mapper and the baseline, and full mode for the mapper. The ground
  truth scores zero, so any overlap is the mapper's. This is fault 2 as a
  number.
- **Settings recorded.** Full-mode results record the transcriber's decoding
  settings and ghost rule next to `mapper_costs`, so a change to either shows
  up in the history beside the number it moved.
- **Tuning** happens on `dev` in both modes. A full-mode dev run takes
  minutes, not hours, on a CPU. A sweep may cache basic-pitch's raw model
  output, which no decoding setting changes, outside the repo so that each
  setting only re-decodes. `dev` results are not committed, as today.
- **Choosing the values.** Each half has its own objective, always the mean
  of the comp rate and the solo rate on `dev`. Comp has about three times as
  many notes, so a pooled rate would let comp outvote solo.
  - **Stage 4's objective** is full-mode string accuracy.
  - **Stage 2's objective** is full-mode note F1, with precision required to
    rise.
  - **Constraint, both halves:** no other `dev` column may fall below its
    before-number. The columns are oracle string accuracy (comp, solo),
    full-mode string accuracy (comp, solo), and full-mode note F1 (comp,
    solo).
  - **Overlaps:** a direction check, not something to minimise. They must
    fall with stage 4, and must not rise with stage 2.
  - **Between the two ghost forms:** take the one with the higher full-mode
    solo string accuracy. Within 0.5 points, take the plain rule; it is
    simpler.
- **Measuring on `test`.** There are three committed `test` measurements:
  before anything changes, after stage 4, and after stage 2. Each is in both
  modes, so each half's effect is measured on its own.
- **Before-numbers first.** The newest committed results are from
  `a3dfec3` (oracle) and `6005ffe`/`bb623bb` (full). Fresh oracle and full
  results on `test` are committed from this branch before any stage changes,
  after the overlap metric lands. That way every comparison uses the same
  harness.

None of this touches CI. `test_eval_never_gates_ci.py` still holds.

### Caching

Stage 2's output changes for the same audio, so `CACHE_VERSION` in
`caching.py` goes up by one. Stage 4's output is not cached.

## Rejected alternatives

**Raise the confidence floor to 0.4.** It is the best single F1 number on
GuitarSet. On separated real songs, whose confidences sit around 0.45, it
would delete a large share of the notes. It also breaks 006's promise that
faint notes render faintly.

**A hard rule against reusing a ringing string.** It is cleaner, but
basic-pitch's durations overrun, and a hard rule cost eight points on
transcribed solos.

**Widen the voicing window.** Strums are not the cause of fault 2: 97% fit
in 50 ms. A wider window would merge fast single-note runs into false chords.

**Let weak notes not move the hand.** This was tried in the spike, and it
gained nothing on transcribed solos. Ghosts hurt by joining the real note's
voicing, not by moving the hand.

**Remove ghosts inside the mapper.** That would teach stage 4 one
transcriber's artifact. See *Where it lives*.

**Rules for octave-below notes and split notes.** These were measured.
Their effect on F1 was neutral or within noise, and they drop real notes in
chords.

**A learned fingering model** (Fretting-Transformer, MIDI-to-Tab). ADR 0003
keeps stage 4 deterministic. On GuitarSet, published learned symbolic models
report about 60, which is no better than the spike, and none releases code.

**Swap the transcriber now.** The strong guitar transcribers are either
unreleased (GAPS, Riley et al.) or GPL (YourMT3+). That is a decision for
its own spec and ADR, not a side effect of this one.

**Hear the string now** (TabCNN weights, CC BY 4.0). It is the most
promising next step and the only evidence that gets past what pitch alone
can decide. It needs:
- a test set outside GuitarSet, because the model was trained on it;
- a decision on how audio evidence enters a deterministic mapper.

That is enough for its own spec. Fixing the cost model first also means that
spec measures against a sound mapper, not one that is biased toward the nut.

## Consequences

The tab moves up the neck. Players will see fewer open strings in solos and
more fifth- and seventh-position fingerings, closer to what GuitarSet's
players chose. Jobs already in Postgres keep their old tab until they are
reprocessed.

`MapperCosts` loses a field and gains six. Result files written after this
change carry different `mapper_costs` keys. Their metrics stay comparable;
their cost columns do not line up.

The note confidence thresholds are re-measured, so the views may fade more
or fewer notes than they did. That is the intended effect of a
better-calibrated transcriber, not a regression in the views.

Stage 2 gains post-processing that is specific to basic-pitch. Replacing the
model means deleting that post-processing, not carrying it over.

ADR 0003 stands. Stage 4 is still deterministic code minimising a cost, and
the invariant is untouched.

## Risks

**GuitarSet is not the material.** It is clean acoustic solo guitar, and
basic-pitch was partly trained on it. Real songs pass through Demucs first and
are noisier. The tuned values could be right for GuitarSet and only
somewhat right for real songs. The ghost rule and decoding settings are the
most exposed. The cost-model changes encode physical facts (a hand covers a
box; a ringing string is busy) and should travel better.

**The spike's numbers came from a sample.** The 100-excerpt transcription
sample and per-term sweeps are a starting point. Tuning the terms together on
the whole dev split may find a different balance, and the success conditions
are measured on `test`, not taken from the spike.

The spike's scripts lived in a session scratchpad and are not committed:
`ruff check .` lints the whole repo, and they were throwaway. Where they
made choices this spec depends on, the spec now states them:
- the hand's landing from nowhere;
- the ghost's 50 ms lead;
- the 30 ms ring tolerance behind the 65.5% reference, which differs from the
  100 ms starting value.

The plan cannot reproduce the spike's numbers exactly and should not try.

**State growth.** A fingering can now carry up to `hand_window` hand
positions. The spike ran the whole dev split in a few seconds per variant,
but a five-minute song with dense chords should be timed before and after.

**The ring penalty is first-order.** A note that rings across several later
voicings is checked against the next one only. The overlap metric shows how
much this leaves behind.

**Thresholds move under the views.** If recalibration shifts `HIDE` or
`FULL` sharply, passages that showed fret numbers may hide behind chord
symbols. The calibration section records what changed and why.
