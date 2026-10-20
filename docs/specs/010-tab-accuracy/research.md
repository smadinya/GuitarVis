# Tab accuracy — research notes

**Spec:** [010 — Tab accuracy](spec.md)
**Date:** 2026-10-19

What was measured and read before 010 was designed. The measurements come from
throwaway scripts run against the local GuitarSet copy, not from `make eval`.
None of them is committed to `eval/results/`; the spec's first task produces
the committed before-numbers.

## The complaints

Seen on real output:

1. A chord is placed on the wrong strings.
2. Two notes that ring together are put on the same string, one straight after
   the other.
3. A note, alone or in a chord, sits where no player would put it.
4. Lots of noise: notes nobody played.

## The mapper

### Where it stands

Oracle mode gives the mapper GuitarSet's exact pitches, so it measures stage 4
alone. These are the committed results
([`2026-10-07-a3dfec3-oracle-test.json`](../../../eval/results/2026-10-07-a3dfec3-oracle-test.json))
and a dev-split run from the same code:

| String accuracy, oracle | all | comp | solo |
|---|---|---|---|
| test (player 05) | 54.0% | 62.0% | 30.2% |
| test, lowest-fret baseline | 37.7% | 43.3% | 20.7% |
| dev (players 00–04) | 65.7% | 74.4% | 42.7% |

### How it goes wrong

Dev split, oracle mode, current mapper:

| | comp | solo |
|---|---|---|
| Wrong string is one string *higher* (five frets lower) | 87% of errors | 76% of errors |
| Wrong string is two strings higher | 5% | 18% |
| Placed open where the player fretted | 24% of errors | 21% of errors |
| Placed fretted where the player played open | 0% | 0% |

The errors run one way, toward the nut. The cost model explains it:

- **Every fret change is a hand move.** The hand's position is the lowest
  fretted fret of the current voicing, so moving from fret 5 to fret 7 on the
  same string costs as much as shifting the hand two frets, though a hand at
  fifth position covers frets 5–8 without moving.
- **Open strings are free and rewarded.** An open voicing costs no movement and
  earns `open_bonus`, so the search reaches for open strings wherever the
  pitch allows.
- **A height cost and the tie-break both pull toward the nut.** Paths that
  differ only by playing everything one position higher tie on movement, and
  `height_weight` plus the lower-fret tie-break settle every such tie low.

### Notes that ring together

GuitarSet annotates each string separately. The truth never places a note on
a string while the previous note on that string is still sounding (30 ms
tolerance). The mapper does:

| Notes placed on a string still sounding | comp | solo |
|---|---|---|
| Truth, dev | 0 | 0 |
| Mapper, dev, oracle | 542 | 446 |

Strums are not the cause. Chaining truth notes with onset gaps of 35 ms or
less into strums of three or more notes, the spread from first to last note
is a median of 20 ms, with 90% of strums under 40 ms. Only 3% exceed the
mapper's 50 ms voicing window, and transcription does not widen them (3% of
transcribed strums exceed 50 ms). The cause is that the mapper never looks at
a note's duration. An arpeggio or a let-ring passage puts one note in each
voicing, and nothing stops the next voicing from reusing a string that is
still ringing.

### Throwaway variants

The spike (`whatif.py`, not committed) changed four things:

- **Hand box.** The hand at index-finger fret *h* covers frets *h* to *h*+3. A
  fingering inside that box costs no movement. Otherwise the hand moves the
  shortest distance that makes the shape fit.
- **No pull toward the nut.** `height_weight` = 0 and `open_bonus` = 0.
- **Open strings up the neck cost something.** Each open string costs 0.2 per
  fret the hand sits above fret 4.
- **Ringing strings.** Using a string whose note in the previous voicing is
  still sounding more than 30 ms past the new onset costs 2.0.

A hand arriving from nowhere puts the index finger on the fingering's lowest
fretted fret.

| String accuracy, oracle | dev all | dev comp | dev solo | test all | test comp | test solo |
|---|---|---|---|---|---|---|
| current | 65.7% | 74.4% | 42.7% | 54.0% | 62.0% | 30.2% |
| no open bonus, no height cost | 67.2% | 77.0% | 41.1% | 60.4% | 67.5% | 39.0% |
| hand box alone | 64.6% | 73.6% | 40.6% | 56.3% | 64.8% | 30.9% |
| hand box, no height/bonus | 68.8% | 78.1% | 44.0% | 63.4% | 70.8% | 41.0% |
| … + open strings cost up the neck | 71.8% | 80.5% | 48.7% | 65.3% | 71.4% | 46.9% |
| … + ringing-string penalty | 72.4% | 80.8% | 49.8% | 65.5% | 72.1% | 45.8% |

No single change does it. The hand box alone *loses* accuracy, because the
height cost and open bonus still pull toward the nut. Together they gain 11.5
points on the held-out player.

With the best variant, solo errors no longer run one way: 52% are one string
lower, 27% one string higher. Per excerpt, the mapper's median fret lands on
the player's in 40 of 150 dev solos and misses by up to six frets either way.
That is the mapper choosing a different valid position from the player's. A
melody can be played in several places, and pitch alone does not say which
one the player used.

## The transcriber

### What the noise is

`BasicPitchTranscriber` with today's settings, on a 100-excerpt dev sample (every
sixth comp and every sixth solo excerpt), confidence ≥ 0.1:

| | comp | solo |
|---|---|---|
| Precision | 71.4% | 78.7% |
| Recall | 70.0% | 84.3% |
| Note F1 | 70.7% | 81.4% |

The false notes in comp, by kind:

| Share of false notes | Kind |
|---|---|
| 38% | 12, 19, 24, 28 or 31 semitones above a note that is sounding: a harmonic ghost |
| 26% | an octave below a note that is sounding |
| 22% | the same pitch as a note still sounding: one note split in two |
| 11% | other |
| 2% | right pitch, onset 50–150 ms off |
| 1% | a semitone off: bends, slides, vibrato |

31% of false notes have confidence below 0.4, against 4% of true ones.

### What the noise does to strings

| String accuracy over matched notes, dev sample | comp | solo |
|---|---|---|
| Current mapper, transcribed notes | 67.8% | 37.9% |
| Current mapper, false notes removed (ceiling) | 68.0% | 41.1% |
| Spike mapper (hand box, open cost), transcribed notes | — | 38.0% |
| Spike mapper, false notes removed | — | 50.3% |
| Spike mapper, harmonic ghosts removed | 74.9% | 53.0% |

In comp, the noise barely moves string accuracy. In solos it costs the spike
mapper twelve points, and harmonic ghosts are most of it. A ghost starts
within 50 ms of the note it shadows, so the two form one voicing. The mapper
must then find a single hand shape for a melody note and a note an octave or a
twelfth above it, which drags the real note onto the wrong string.

### Clean-up rules

Same sample, note-level scores:

| Rule | comp P | comp R | comp F1 | solo P | solo R | solo F1 |
|---|---|---|---|---|---|---|
| none (today) | 71.4% | 70.0% | 70.7% | 78.7% | 84.3% | 81.4% |
| drop ghost if confidence < 0.8 × its base's | 75.9% | 65.3% | 70.2% | 82.8% | 84.2% | 83.5% |
| … < 0.6 × its base's | 74.1% | 68.4% | 71.1% | 81.5% | 84.3% | 82.9% |
| … only when the ghost and its base are alone at that onset (0.8) | 72.8% | 69.7% | 71.2% | 82.0% | 84.3% | 83.1% |
| drop octave-below if confidence < 0.8 × the upper note's | 74.2% | 69.1% | 71.6% | 79.4% | 84.3% | 81.8% |
| merge a re-trigger with confidence < 0.4 | 72.2% | 69.5% | 70.8% | 79.0% | 84.3% | 81.6% |
| drop everything below 0.4 | 77.7% | 67.3% | 72.2% | 84.6% | 84.1% | 84.4% |

The plain ghost rule at 0.8 deletes real octaves from chords, costing 4.7
points of comp recall. Gentler versions (ratio 0.6, or "alone at that onset")
improve F1 in both styles. A confidence floor of 0.4 scores best here, but see
the spec's rejected alternatives: real separated songs sit far lower on the
confidence scale than GuitarSet does.

### Decoding settings

basic-pitch's defaults
([`inference.py`](https://raw.githubusercontent.com/spotify/basic-pitch/main/basic_pitch/inference.py))
are onset threshold 0.5, frame threshold 0.3, minimum note length 127.7 ms,
and `melodia_trick=True`. The melodia trick turns leftover frame energy into
notes that have no onset of their own.

A sweep by the research subagent tuned the settings on player 00 and tested
them on player 05, scoring onset-only F1 at 50 ms. The defaults reproduce the
committed eval's 0.777.

| Settings | dev (player 00) | test (player 05) |
|---|---|---|
| defaults | 0.722 | 0.777 |
| `melodia_trick` off, frame threshold 0.4, minimum note 5 frames (~58 ms) | 0.755 | 0.800 |

All six of the best dev settings had `melodia_trick` off. Tuning on one dev
player is thin; the spec tunes on all five.

### Decoding settings on real separated stems

A builder review of the spec pointed out that `frame_threshold` acts as a
confidence floor. A note only continues while its frames stay at or above
the threshold, and its confidence is their mean. GuitarSet cannot show what
that does to separated full-band stems, whose confidences sit lower. Two
clips from 2026-09-25 are in the gitignored `tmp/stems/` (`Test`, `test3`).
Run on their Demucs stems, they gave:

| Stem | Settings | Notes ≥ 0.1 | Median confidence |
|---|---|---|---|
| `test3` other | defaults | 11 | 0.42 |
| `test3` other | `melodia_trick` off, frame 0.4, min 58 ms | 5 | 0.56 |
| `test3` guitar | defaults | 11 | 0.68 |
| `test3` guitar | `melodia_trick` off, frame 0.4, min 58 ms | 8 | 0.73 |
| `Test` other | defaults | 7 | 0.47 |
| `Test` other | `melodia_trick` off, frame 0.4, min 58 ms | 3 | 0.60 |
| `Test` guitar | defaults | 32 | 0.46 |
| `Test` guitar | `melodia_trick` off, frame 0.4, min 58 ms | 30 | 0.47 |

The clips are seconds long, so this is a warning, not a measurement. On the
weaker `other` stems the new settings cut the note count roughly in half.
That is why the spec puts these settings behind a review on real songs.

### The ringing-string penalty with transcribed durations

The penalty counts a string as ringing when the previous note's end passes
the next onset by more than a tolerance. Dev sample, harmonic ghosts removed,
hand box and open cost on. Each cell is string accuracy, then same-string
overlaps per 1000 placed notes.

| Variant | oracle comp | oracle solo | full comp | full solo |
|---|---|---|---|---|
| no penalty | 81.2% / 8.0 | 48.6% / 27.3 | 74.9% / 16.1 | 53.0% / 33.7 |
| 2.0, tolerance 30 ms | 80.9% / 2.0 | 50.8% / 2.5 | 75.4% / 5.8 | 45.4% / 8.6 |
| 2.0, tolerance 100 ms | 81.9% / 3.1 | 51.9% / 18.4 | 75.1% / 9.2 | 54.5% / 23.6 |
| 2.0, tolerance 200 ms | 81.7% / 4.7 | 48.5% / 21.3 | 74.7% / 13.0 | 54.2% / 29.1 |
| no penalty, skipped-string cost 0.3 | 83.3% / 7.4 | 48.6% / 27.3 | 75.6% / 17.2 | 53.0% / 34.2 |
| 2.0 at 100 ms, skipped-string cost 0.3 | 83.9% / 2.8 | 51.9% / 18.4 | 76.3% / 9.1 | 54.5% / 23.8 |

The tight tolerance costs eight points on transcribed solos. basic-pitch
lets a note run on past the point where the player moved to the next note on
that string, so a tight rule pushes legato lines off their string. At 100 ms
the penalty helps everywhere and still removes about half the overlaps.

A skipped-string cost charges for each unused string between a 3+ note
voicing's lowest and highest strings, because a strum hits adjacent strings.
It helps comp by about two points in oracle mode.

## The literature

Gathered by a research subagent. Every number below is as the cited source
reports it. Not every source was opened and checked by hand. The papers use
tablature F1 and TDR, which are frame-level metrics, not this harness's
note-level string accuracy, so compare their trends, not their digits.

**Assigning strings from pitches** is the classic shortest-path or Viterbi
problem ([Sayegh 1989, via Bontempi et al.](https://ar5iv.labs.arxiv.org/html/2407.09052);
[Burlet & Fujinaga 2013](https://archives.ismir.net/ismir2013/paper/000217.pdf);
[Hori & Sagayama 2016](https://archives.ismir.net/ismir2016/paper/000285.pdf)).
The cost terms that recur:

- hand position change;
- string change;
- finger span;
- distance from a preferred region of the neck;
- open strings;
- whether a transition can be made in the time available.

Published systems treat a string as unavailable while its note sounds:
- [TART](https://arxiv.org/html/2609.11904v1) resolves a same-string collision
  by keeping the longer note.
- [MIDI-to-Tab](https://arxiv.org/abs/2408.05024) moves a note only to
  "strings with no notes intersecting".

Learned symbolic models beat rule-based ones on DadaGP:
- [Fretting-Transformer](https://arxiv.org/html/2506.14223v1) reaches 81.6%,
  against 78.9% for A*.

On GuitarSet, given correct notes, TART reports 60.4 (Fretting-Transformer),
61.3 (its own symbolic model) and 69.2 when the model also hears the audio.

**The ceiling from pitch alone** is roughly where the spike already is. The
ground truth is one player's choice among valid positions. The only evidence
that pushes past it is audio: each string sounds slightly different.

**Models that read the string from audio:**
- [TabCNN](https://github.com/andywiggins/tab-cnn) reports tablature F1
  0.74–0.75 on GuitarSet in reproductions
  ([Cwitkowitz et al.](https://arxiv.org/abs/2204.08094)), and 0.45 on
  electric guitar. Trained weights are on
  [Zenodo, CC BY 4.0](https://zenodo.org/records/11406378). It has about
  834k parameters and runs easily on a CPU.
- [Cascaded multi-task](https://github.com/ErenReyhanlioglu/Guitar-Transcription)
  (MIT, weights for six folds) reports 0.776.
- FretNet, Inhibition-TabCNN and Trimplexx release code but no weights.
- Noise2Fret's claimed 0.845 could not be verified.

These models were trained on GuitarSet, so GuitarSet cannot measure them
fairly. GuitarSet's six players all play the same 30 lead sheets, so even
leave-one-player-out training has seen the test pieces.

**Better transcribers** exist, but none is usable here today. Reported note
F1 on GuitarSet:
- basic-pitch: 79.0
- MT3: 89–90
- [YourMT3+](https://arxiv.org/html/2407.04822): 91.4, but its code is GPL-3.0
- [GAPS](https://arxiv.org/html/2408.08653) and Riley et al.: 86–91, with no
  weights released

basic-pitch was itself partly trained on GuitarSet, so its numbers here are
optimistic.
