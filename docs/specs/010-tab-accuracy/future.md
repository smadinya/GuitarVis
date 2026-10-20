# Tab accuracy — design changes for later iterations

**Spec:** [010 — Tab accuracy](spec.md)
**Date:** 2026-10-19

Ideas that came up while researching and designing 010 and were left out of
it on purpose. Each says why it was deferred and what would justify picking it
up. None of them is a commitment. Numbers are from [research.md](research.md)
unless a source is linked.

## Most likely next

### Hear which string was played

The ceiling that pitch alone can reach is where 010 leaves off. Once the
mapper stops leaning toward the nut, the remaining solo errors miss by one
string in either direction equally often. The mapper is choosing a valid
position the player did not, and only the audio can tell them apart. Each
string has its own timbre, and models trained on that report gains on
GuitarSet. One 2026 paper reports about 61 → 69 tablature F1 from adding
audio, given correct notes.

- **Model:** TabCNN, with weights on Zenodo under CC BY 4.0, about 834k
  parameters, CPU-friendly, CQT input at 22.05 kHz. Another option is the
  cascaded multi-task model (MIT, weights for six folds).
- **Shape that keeps ADR 0003:** the model gives a probability per (string,
  fret) per frame. The mapper turns it into one more cost term in the Viterbi
  it already runs. Stage 2 still owns the notes, stage 4 still owns the
  decision, and the invariant is untouched. Whether that counts as a
  learned fingering model needs an ADR either way.
- **Contract question:** stage 4 needs the stem or the model's activations,
  and `FretboardMapper.assign(notes, tuning)` sees neither. Options:
  - an optional evidence argument;
  - a new stage between 2 and 4 that annotates `NoteEvent`s with string
    likelihoods;
  - a guitar-specific `Transcriber` that returns them alongside pitches.

  The pipeline-stage rules (no stage imports another; stage 2 returns
  pitches, not fingerings) constrain all three.
- **Measuring it:** TabCNN was trained on GuitarSet, so GuitarSet can't
  measure it fairly. It needs EGSet12, GAPS, or a small hand-annotated set of
  real songs (below). It also drops to about 0.45 on electric guitar.
- **Pick it up when:** 010 has shipped, so its results are the before-number.

### A real-song test set with ground truth

Every number 010 reports comes from clean, solo, acoustic GuitarSet audio
that basic-pitch was partly trained on. 010's real-song review measures note
counts and confidence, plus a human look, but not correctness. A handful of
real songs with hand-checked tab would cover what GuitarSet can't:
- full mixes;
- separation bleed;
- distortion;
- electric guitar.

Published tab is a ready source of truth for string and fret, as long as it
is checked against the recording.

- It would also give the harness its first measure of separation quality.
- **Pick it up when:** before the string-hearing work, which needs it. Or as
  soon as GuitarSet and real-song behaviour visibly disagree.

## The mapper

### Scale movement by the time available

A four-fret jump over two seconds of rest is easy; the same jump between
sixteenth notes is hard. The literature includes "can the hand get there in
time" as a transition cost. 004 listed "letting a long rest discount hand
movement" as out of scope, and 010 kept it out.

- **Pick it up when:** the review shows the mapper refusing an easy shift
  after a rest, or making a hard one mid-run.

### Minimise the worst jump, not the sum

[Hori & Sagayama 2016](https://archives.ismir.net/ismir2016/paper/000285.pdf)
minimise the largest transition rather than the total. That speaks directly
to "one absurd jump" complaints, which a sum can trade away against many small
savings.

- **Pick it up when:** absurd single jumps survive 010. A max-stretch or
  max-jump metric, below, would show it.

### Chord-shape priors

010's skipped-string cost is a crude stand-in for "this looks like a chord a
person plays". Cwitkowitz's DadaGP pairwise matrix gives, for every two
(string, fret) pairs, how often they occur together in real tab. It ships
with `acquire_dadagp_matrix.py` in
[guitar-transcription-with-inhibition](https://github.com/cwitkowitz/guitar-transcription-with-inhibition),
MIT. As a fingering cost it would favour real shapes: open chords, barre
shapes, power chords. Fingerstyle voicings that skip strings would be scored
on their merits, not penalised for the gap.

- **Caveat:** DadaGP is mostly rock and metal Guitar Pro files, so the prior
  could pull jazz voicings toward rock shapes.
- **Pick it up when:** comp string accuracy plateaus after 010.

### A cost for changing strings

The literature charges for string changes as well as hand moves. 010
doesn't, and planning showed what that costs. In the phrase F5–B4–C5–B4–C5–D5,
the hand box puts B4 at G16, inside the box at 13–16, instead of B12, which
is one fret below it. A player would more likely keep B4 and C5 on the B
string as a half-step hammer-on. A small string-change cost would break that
near-tie toward staying on the string. It needs care in chords, though,
where "string change" means nothing.

- **Pick it up when:** the real-song review or the dev split shows
  single-note lines hopping strings to stay inside the box.

### Look further back for ringing strings

010's ringing-string penalty checks only the previous voicing, which keeps
Viterbi first-order. A note held under a three-note arpeggio is not seen by
the third note. The search state could carry the set of strings still
ringing, at most 2⁶ combinations, though the state space would grow by that
factor.

- **Pick it up when:** the overlap metric still shows overlaps that the
  first-order rule cannot see.

### A preferred region of the neck

The literature includes "distance from a preferred region" as a cost. 010
removed the pull toward the nut and put nothing in its place, so position is
decided by movement and open strings alone. A prior could fill that gap:
- a per-song region, centred on where the song's confident notes sit;
- a key-aware one, such as the pentatonic box for the detected key.

- **Pick it up when:** solo position errors are still large after the
  string-hearing work. Audio evidence may make this unnecessary.

### Confidence-aware mapping

The spike tried letting weak notes not move the hand, and it gained nothing.
Ghosts hurt by joining a real note's voicing, not by moving the hand, and
010 removes them before the mapper. One idea remains:
- **Optional notes:** a voicing could drop its weakest note when that
  makes a far cheaper fingering. The weakest note would not be placed, just
  as an unplayable one is dropped now.

That is a new kind of drop, though. It needs its own warning, and the eval's
rule that "dropping is not a way to score better" must still hold.

### Fingering techniques

Slides, hammer-ons, pull-offs and bends are played on one string, and so they
pin the string choice. Detecting them, perhaps from FretNet-style continuous
pitch, would give the mapper hard evidence where today it has only costs.
004 and 010 both left technique detection out.

## Transcription

### A better transcriber

basic-pitch scores about 79 note F1 on GuitarSet. MT3 scores 89–90 and
YourMT3+ 91.4, but YourMT3 is GPL-3.0. GAPS and Riley et al. score 86–91,
with weights unreleased. TART suggests transcription errors cost about 13
points of tab F1, so a better transcriber lifts everything downstream.

- **Pick it up when:** a permissively licensed guitar transcriber with
  released weights appears, or MT3's JAX/T5X stack becomes worth carrying.
- **Before swapping:** commit a before-number, per the `eval-harness` skill.
- **When it lands:** 010's ghost rule belongs to basic-pitch and should be
  deleted, not carried over.

### Ghosts inside chords

010's ghost rule is deliberately cautious: ratio 0.6, or the "alone at that
onset" form. In chords, a ghost and a real octave look the same to a
confidence ratio. Two signals could tell them apart:
- **Onsets:** a real note has its own onset in basic-pitch's onset
  posteriorgram, while a ghost usually doesn't.
- **Hand shapes:** a candidate ghost could be checked against the chord's
  likely shape.

The alone-only form the shipped rule uses has a known gap: two ghosts of one
base can shield each other, because each is a neighbour of the other that is
not one of its bases. With E3 at 0.9, E4 at 0.3 and B4 at 0.2, the E4 and the
B4 both stay (the plain rule would drop both). A weak E4 over a weak E3 over a
strong E2 (E2 0.9, E3 0.5, E4 0.25) likewise keeps the E3 and drops only the
E4. The shipped rule accepts both. A future rule could judge a neighbour that
is itself a ghost as not counting against its fellow.

- **Pick it up when:** comp precision is still poor after 010.

### Split notes and octave-below errors

Together these are 48% of the false notes in comp, and 010 left them alone.
The simple rules either did nothing for F1 or cost real notes. Better
evidence for both is in the model output 010 doesn't read:
- **Split notes:** a re-trigger without an onset peak is a continuation, and
  real repeated strums do have one.
- **Octave-below errors:** the frame activations around the suspect note
  would show whether the lower pitch has its own energy.

Reading the posteriorgrams means calling basic-pitch below `predict()`.

### Limit decoding to the guitar's range

basic-pitch can be told `minimum_frequency` and `maximum_frequency`. Notes
outside the neck's range are already dropped by the mapper, with a warning
counting them. Dropping them at decoding would be quieter and earlier, but the
warning would no longer report those notes.

- **Decide:** whether a user benefits from seeing "N notes outside the
  guitar's range". On real songs that is mostly bleed from bass or vocals.

## Evaluation

### More playability metrics

010 adds same-string overlaps. The MIDI-to-Tab paper found that guitarists
sometimes preferred tabs that disagreed with the ground truth, so string
accuracy is not the whole picture. More playability metrics would help:
- the largest stretch within a voicing;
- the largest hand jump, and jumps per minute;
- the share of open strings above fifth position.

Each would be measured, never gated, like everything else in `make eval`.

### Report the playability cost of the ground truth

Scoring GuitarSet's own fingerings with the mapper's cost function shows how
far the cost model is from what players do. Where the truth scores worse than
the mapper's choice, the cost model is wrong, not the search. That is a
cheap diagnostic for tuning.

## Pipeline and product

### Regenerate stored documents

010 changes the tab for new jobs only. Old jobs could be re-run from cached
stems, since separation is cached by content hash, though the transcription
cache is invalidated by 010's `CACHE_VERSION` bump. That needs a user-facing
story: does a re-run replace the tab someone has already used, or sit beside
it?

### Separation quality

Demucs rates its `htdemucs_6s` guitar stem only "okay", and the noise on real
songs likely starts there. Options:
- a newer separation model;
- separating twice and combining the stems;
- feeding transcription a confidence that the separation went well.

The real-song test set above is the prerequisite for measuring any of it.
