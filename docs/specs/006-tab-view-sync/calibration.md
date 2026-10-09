# Confidence calibration

**Spec:** [006 — Confidence](spec.md#confidence)
**Results:** [`eval/results/2026-10-08-6005ffe-full-test.json`](../../../eval/results/2026-10-08-6005ffe-full-test.json), from
`make eval ARGS=--full` on the test split (player 05), commit `6005ffe`, clean tree.

## Precision by confidence

Every note the transcriber produced on the test split, by its confidence
band, and the share that matched the truth: an onset within 50 ms at the
exact pitch. These are the `all` group's numbers.

| Confidence | Notes | Matched | Precision |
|---|---|---|---|
| 0.0–0.1 | 0 | 0 | — |
| 0.1–0.2 | 0 | 0 | — |
| 0.2–0.3 | 80 | 6 | 7.5% |
| 0.3–0.4 | 877 | 173 | 19.7% |
| 0.4–0.5 | 1261 | 624 | 49.5% |
| 0.5–0.6 | 2050 | 1525 | 74.4% |
| 0.6–0.7 | 2851 | 2412 | 84.6% |
| 0.7–0.8 | 2326 | 2142 | 92.1% |
| 0.8–0.9 | 332 | 297 | 89.5% |
| 0.9–1.0 | 1 | 1 | 100.0% |

## Chosen values

| | Rule (spec 006) | Printed | Chosen |
|---|---|---|---|
| `HIDE` | the lowest band edge such that every band at or above it, among bands of 50 or more notes, has precision ≥ 0.5 | 0.5 | 0.5 |
| `FULL` | the same, with precision ≥ 0.8 | 0.6 | 0.6 |

`web/src/confidence.ts` holds the chosen values and cites this file.

`HIDE` = 0.5 is close to a coin-flip boundary: the 0.4–0.5 band missed the
0.5 precision rule at 49.5% on 1261 notes, so notes just below `HIDE` are
almost as often right as wrong.

## How far to trust this

GuitarSet is clean solo guitar, and full mode skips separation, so these
thresholds are optimistic for stems separated from full mixes. Real songs
will show more faded and hidden notes than GuitarSet predicts. *On real
songs*, below, measures that gap on real output.

## Chords

**Results:** [`eval/results/2026-10-08-bb623bb-full-test.json`](../../../eval/results/2026-10-08-bb623bb-full-test.json), from
`make eval ARGS=--full` on the test split, commit `bb623bb`, clean tree. Its
note numbers are identical to the run above.

A chord's confidence is not the transcriber's. It is the cosine between the
audio's chroma and the nearest triad template, and the analyzer drops
anything under 0.5. Until this measurement, the tab strip faded chords with
the note thresholds.

Each 0.1 s frame that shows a chord is counted in that chord's band, over the
frames `chord_tally` scores, and is right when the chord is the truth's.
These are the `all` group's numbers:

| Confidence | Frames | Correct | Precision |
|---|---|---|---|
| 0.0–0.5 | 0 | 0 | — |
| 0.5–0.6 | 3264 | 221 | 6.8% |
| 0.6–0.7 | 6651 | 1572 | 23.6% |
| 0.7–0.8 | 3835 | 2034 | 53.0% |
| 0.8–0.9 | 1846 | 1522 | 82.4% |
| 0.9–1.0 | 93 | 91 | 97.8% |

| | Rule (spec 006) | Printed | Chosen |
|---|---|---|---|
| `CHORD_HIDE` | `HIDE`'s rule, among bands of 300 or more frames | 0.7 | 0.7 |
| `CHORD_FULL` | `FULL`'s rule, among bands of 300 or more frames | 0.8 | 0.8 |

A band needs 300 frames, 30 seconds of chords, because the frames of one held
chord are not independent.

The note thresholds drew every chord at 0.6 or above at full strength. That
was 79% of the frames that show a chord, and 42% of those were right. Under
the chord thresholds, 12% are drawn at full strength, and 83% of those are
right. Everything below 0.7 fades: 63% of the frames, right 18% of the time.

`CHORD_HIDE` = 0.7 is, like `HIDE`, close to a coin flip: the 0.7–0.8 band is
right 53.0% of the time.

The thresholds come from the `all` group, as for notes. Solo excerpts score
badly at every band, 25.7% at best: one melodic line gives a triad template
little to match. Comp excerpts reach 65.9% at 0.7–0.8 and 85.2% at 0.8–0.9.

## On real songs

What the chosen values do to real pipeline output, from
`node web/scripts/confidence-report.ts` (`web/scripts/confidence-report.ts`
uses the same `hiddenPassages`, `isHidden` and thresholds the views use). The
first row is the committed fixture, the first song through the api. `song2` is
an earlier CLI run from before fretboard assignment existed, so it has no
notes:

```text
HIDE 0.5, FULL 0.6
notes  at/below HIDE  partly faded  hidden  passages  document
   32            66%            3%     50%         1  web/src/test/fixtures/first-song.tabdoc.json
    0              —             —       —         0  tmp/song2.json
   12            33%           17%     33%         1  tmp/song3.json

CHORD_HIDE 0.7, CHORD_FULL 0.8
chords  at/below CHORD_HIDE  partly faded  document
    17                 100%            0%  web/src/test/fixtures/first-song.tabdoc.json
    17                 100%            0%  tmp/song2.json
    19                  68%           26%  tmp/song3.json
```

The GuitarSet table predicts that 23% of notes sit at or below 0.5 (2218 of
9778) and 21% fall between 0.5 and 0.6. The first song fades 66% of its notes,
nearly three times that, and hides half of them in one passage: its
confidences cluster between 0.3 and 0.5 (median 0.45), with almost none in the
partly-faded band. `song3` is nearer the prediction, but 12 notes and 44 in
all make this an indication rather than a measurement. It points the way the
section above warned: separated full mixes score lower than GuitarSet, so real
songs show more faded and hidden notes than the table predicts. The values
stay as measured.

The chords tell the same story. Every chord in the first song scores below
0.7, the highest at 0.68, so all of them fade. Under the note thresholds, the
ones at 0.6 or above were drawn at full strength. `song3` fades two thirds of
its chords. On GuitarSet, chords below 0.7 are right about one time in five.
