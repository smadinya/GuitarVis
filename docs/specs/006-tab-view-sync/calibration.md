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

## After 010

**Spec:** [010 — Tab accuracy](../010-tab-accuracy/spec.md#recalibrating-the-confidence-thresholds)
**Results:** [`eval/results/2026-10-19-fa69e14-full-test.json`](../../../eval/results/2026-10-19-fa69e14-full-test.json), from
`make eval ARGS=--full` on the test split (player 05), commit `fa69e14`, clean
tree.

Spec 010 changed the transcriber's decoding settings and added a ghost rule,
and confidence is a note's mean frame activation, which the frame threshold
changes. So the measurement above describes the old distribution, and this
section repeats it on the new one. Everything above stands as history; the
values in `web/src/confidence.ts` now cite this section.

The settings are the ones that ship: onset threshold 0.5, frame threshold 0.4,
minimum note length 93 ms, `melodia_trick` off, and the alone-only ghost rule
at 0.8. Commit `fa69e14` has the same stage-2 code as the shipped branch
([tuning.md](../010-tab-accuracy/tuning.md#fa69e14-the-alone-only-rule-at-08-current)).

### Precision by confidence

The same table as *Precision by confidence* above, from the `all` group:

| Confidence | Notes | Matched | Precision |
|---|---|---|---|
| 0.0–0.1 | 0 | 0 | — |
| 0.1–0.2 | 0 | 0 | — |
| 0.2–0.3 | 7 | 1 | 14.3% |
| 0.3–0.4 | 136 | 28 | 20.6% |
| 0.4–0.5 | 738 | 332 | 45.0% |
| 0.5–0.6 | 1868 | 1346 | 72.1% |
| 0.6–0.7 | 2959 | 2457 | 83.0% |
| 0.7–0.8 | 2791 | 2576 | 92.3% |
| 0.8–0.9 | 410 | 374 | 91.2% |
| 0.9–1.0 | 1 | 1 | 100.0% |

The transcriber now reports 8910 notes on the split, down from 9778, at 79.9%
precision, up from 73.4%. The weak bands emptied the most. Notes at or below
0.5 went from 2218 (22.7%) to 881 (9.9%), and the 0.3–0.4 band from 877 notes
to 136. The 0.4–0.5 band is right 45.0% of the time, down from 49.5%, and the
0.5–0.6 band 72.1%, down from 74.4%. Above 0.6 the bands barely moved.

### Chosen values

| | Rule (spec 006) | Printed | Chosen | Before 010 |
|---|---|---|---|---|
| `HIDE` | the lowest band edge such that every band at or above it, among bands of 50 or more notes, has precision ≥ 0.5 | 0.5 | 0.5 | 0.5 |
| `FULL` | the same, with precision ≥ 0.8 | 0.6 | 0.6 | 0.6 |

Derived two ways: from this file's bands with `guitarvis_eval.calibration`'s
`threshold`, the function `make eval` prints them with, and from the run
itself, which printed `HIDE` 0.5 and `FULL` 0.6. Neither is 0 or "not
supported", and neither moved, so spec 010's stop rule did not fire. The values
are unchanged. `web/src/confidence.ts` still holds them, and now cites this
section.

- `HIDE`: the 0.3–0.4 band (136 notes, 20.6%) and the 0.4–0.5 band (738 notes,
  45.0%) fall short of 0.5. The 0.2–0.3 band has 7 notes and does not count.
  The 0.5–0.6 band, at 72.1% on 1868 notes, is the lowest that holds.
- `FULL`: the 0.5–0.6 band is under 0.8 at 72.1%. The 0.6–0.7 band, at 83.0%
  on 2959 notes, is the lowest that clears it, and every band above it does
  too. The 0.9–1.0 band has one note and does not count.

`HIDE` = 0.5 is less of a coin flip than it was: the band just below it is
right 45.0% of the time, where it was 49.5%. `FULL` = 0.6 clears its line by
3 points (83.0% against 80%), and the band under it misses by 8.

The chord thresholds are untouched, because the analyzer is untouched.

### On real songs

**Round:** `R=stage2b` in [real-songs.md](../010-tab-accuracy/real-songs.md#stage-2-as-shipped),
at commit `679ce9e`, which has the shipped settings above. Nine songs, all
separated by Demucs and run through the real pipeline. The output of
`node web/scripts/confidence-report.ts tmp/010/stage2b/*.json`, under `HIDE`
0.5 and `FULL` 0.6:

```text
HIDE 0.5, FULL 0.6
notes  at/below HIDE  partly faded  hidden  passages  document
   26            58%            4%     50%         1  tmp/010/stage2b/Test.json
   13            62%           15%     31%         1  tmp/010/stage2b/Test2.json
   19            16%           16%      0%         0  tmp/010/stage2b/Test4.json
   39            10%           33%      0%         0  tmp/010/stage2b/Test5.json
  226            21%           36%      2%         1  tmp/010/stage2b/momsong.json
  426            25%           36%      5%         5  tmp/010/stage2b/mysong.json
  121            24%           40%      2%         1  tmp/010/stage2b/nutshell.json
  577            13%           33%      0%         0  tmp/010/stage2b/nutshellandsolo.json
    7            14%           14%      0%         0  tmp/010/stage2b/test3.json

CHORD_HIDE 0.7, CHORD_FULL 0.8
chords  at/below CHORD_HIDE  partly faded  document
   17                 100%            0%  tmp/010/stage2b/Test.json
   19                  58%           26%  tmp/010/stage2b/Test2.json
   44                  73%           23%  tmp/010/stage2b/Test4.json
   13                  85%            8%  tmp/010/stage2b/Test5.json
   34                  18%           65%  tmp/010/stage2b/momsong.json
   36                  19%           47%  tmp/010/stage2b/mysong.json
   30                  60%           23%  tmp/010/stage2b/nutshell.json
  109                  71%           21%  tmp/010/stage2b/nutshellandsolo.json
    6                  33%           50%  tmp/010/stage2b/test3.json
```

The documents are the user's own and live in the gitignored `tmp/`. The
per-song medians, in the order above, are 0.48, 0.49, 0.65, 0.67, 0.58, 0.57,
0.57, 0.61 and 0.74.

The GuitarSet table above predicts that 9.9% of notes sit at or below 0.5 (881
of 8910) and 21.0% fall between 0.5 and 0.6 (1868). Pooled over the nine songs,
19.9% are at or below `HIDE` (290 of 1454), 34.0% are partly faded (494), and
3.1% are hidden (45 notes, in 9 passages). The pooled median is 0.59. Real
songs still fade about twice what GuitarSet predicts, as the earlier section
found: the stage 4 round, on the old settings, faded 39.9% of its notes
against the old table's 22.7% (1.8 times). The values stay as measured.

The pooled figures hide two groups. Test and Test2, with 26 and 13 notes, still
fade 58% and 62% and hide 50% and 31% of their notes. Test is the first song
through the api, the fixture in *On real songs* above; that earlier run faded
66% and hid 50%, and it now fades 58% and hides 50%, at a median of 0.48. The four songs with over 100
notes (1350 in all) fade 19.2% at or below `HIDE`, about twice the prediction,
and hide 2.1%, where the stage 4 round hid 12.1% of all notes. The other three
songs have 7 to 39 notes each, so a note or two moves their shares by several
points.

The partly faded share, 34.0% pooled and 33% to 40% in the four big songs, is
well over GuitarSet's 21.0%. These are the notes the ramp between `HIDE` and
`FULL` draws at partial strength, and the new table has 72.1% of them right.

The chord report comes from the same documents and is shown for completeness.
The chord thresholds were not re-derived.
