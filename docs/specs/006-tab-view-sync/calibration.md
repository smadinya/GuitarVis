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
will show more faded and hidden notes than GuitarSet predicts. The next
section measures that gap on real output.

## On real songs

What the chosen values do to real pipeline output, from
`node web/scripts/confidence-report.ts` (`web/scripts/confidence-report.ts`
uses the same `hiddenPassages` the views use). The first row is the committed
fixture, the first song through the api. `song2` is an earlier CLI run from
before fretboard assignment existed, so it has no notes:

```text
HIDE 0.5, FULL 0.6
notes  at/below HIDE  partly faded  hidden  passages  document
   32            66%            3%     50%         1  web/src/test/fixtures/first-song.tabdoc.json
    0              —             —       —         0  tmp/song2.json
   12            33%           17%     33%         1  tmp/song3.json
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
