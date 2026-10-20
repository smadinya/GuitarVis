# Real-song review

**Spec:** [010 — Tab accuracy](spec.md#the-real-song-review)
**Date:** 2026-10-19

GuitarSet is clean solo acoustic guitar. The songs here are full-band
recordings, separated by Demucs, and no benchmark covers them. They are the
user's own and live in the gitignored `tmp/`; nothing from them is committed
except the numbers in this file.

Each of the spec's two halves goes through the pipeline on every song, once
before it and once after. This file holds the numbers; the user looks at the
tabs in the client.

## The round

One round is every song in `tmp/*.mp3` run through the real pipeline, with
`make api`, `make worker` and `make web` up:

1. Copy the song with `ffmpeg -c copy -metadata comment="010 $R"`, where `R`
   names the round. Jobs dedupe on the file's content hash, so uploading the
   original again would return the old job. The copy changes the hash and
   leaves the audio alone.
2. Upload the copy to `localhost:8000/jobs` and poll until it succeeds or
   fails.
3. Download the job's tab document into `tmp/010/$R/`.
4. Run `node web/scripts/confidence-report.ts tmp/010/$R/*.json`.

The script is Task 2, step 2 of [plan.md](plan.md). Later rounds, `R=stage4`
and `R=stage2`, rerun it unchanged. Each table row also takes the median
confidence, from
`jq '[.notes[].confidence] | sort | .[length/2|floor]'` on the document, and
the document's `warnings`.

Columns, as the report defines them: at or below `HIDE` is the share of notes
whose confidence is `HIDE` or lower; partly faded is the share between `HIDE`
and `FULL`; hidden is the share inside a hidden passage; passages counts the
hidden passages.

## Before

Round `R=before`, run on 2026-10-19 at commit `21f4f89`: the mapper and the
transcriber as they stood when 010 began. `HIDE` is 0.5 and `FULL` is 0.6.
All nine jobs succeeded.

| Song | Job | Notes | At or below `HIDE` | Partly faded | Hidden | Passages | Median confidence | Warnings |
|---|---|---|---|---|---|---|---|---|
| Test | [86a54243](http://localhost:5173/songs/86a54243-c5dd-4c09-bddf-db194052af72) | 32 | 66% | 3% | 50% | 1 | 0.47 | none |
| Test2 | [380d903f](http://localhost:5173/songs/380d903f-efa6-41a6-83b6-6554f20c7a4c) | 30 | 80% | 10% | 60% | 2 | 0.41 | 1 note outside the guitar's range was dropped. |
| Test4 | [161510fc](http://localhost:5173/songs/161510fc-2016-4526-85d4-62a01bb07e41) | 25 | 44% | 8% | 0% | 0 | 0.57 | none |
| Test5 | [84a4cc5f](http://localhost:5173/songs/84a4cc5f-589d-40bc-9b11-a17d4c907891) | 48 | 29% | 29% | 0% | 0 | 0.58 | 2 notes outside the guitar's range were dropped. 1 note in chords no hand could play was dropped. |
| momsong | [d65ba56e](http://localhost:5173/songs/d65ba56e-1903-4c1d-833c-89b2cbb41a07) | 281 | 43% | 23% | 11% | 8 | 0.53 | 1 note in chords no hand could play was dropped. |
| mysong | [7b4313de](http://localhost:5173/songs/7b4313de-7a49-498f-b9ba-418898562a34) | 517 | 45% | 26% | 18% | 24 | 0.52 | 3 notes outside the guitar's range were dropped. 18 notes in chords no hand could play were dropped. |
| nutshell | [9896637e](http://localhost:5173/songs/9896637e-6c15-42cf-bf33-64b698c34a00) | 141 | 47% | 27% | 10% | 4 | 0.51 | 1 note outside the guitar's range was dropped. 10 notes in chords no hand could play were dropped. |
| nutshellandsolo | [10cb6ffb](http://localhost:5173/songs/10cb6ffb-d90c-496a-a155-a2b7b0586b80) | 678 | 31% | 29% | 5% | 11 | 0.57 | 4 notes outside the guitar's range were dropped. 13 notes in chords no hand could play were dropped. |
| test3 | [8960e818](http://localhost:5173/songs/8960e818-7b86-4566-a7ef-7672f9d86c47) | 12 | 33% | 17% | 33% | 1 | 0.69 | 1 note outside the guitar's range was dropped. |

## Stage 4

Round `R=stage4`, run on 2026-10-19 at commit `7c02b6e`, on a worker started
after the tuned mapper commit `354c2c8`. All nine jobs succeeded. `HIDE` is 0.5
and `FULL` is 0.6, as before. *Before* links the same song's job in the round
above.

| Song | Job | Before | Notes | At or below `HIDE` | Partly faded | Hidden | Passages | Median confidence | Warnings |
|---|---|---|---|---|---|---|---|---|---|
| Test | [c7a6aed1](http://localhost:5173/songs/c7a6aed1-f73d-4803-92b2-5d0a4483a1e4) | [86a54243](http://localhost:5173/songs/86a54243-c5dd-4c09-bddf-db194052af72) | 30 | 63% | 7% | 47% | 1 | 0.46 | none |
| Test2 | [f942f153](http://localhost:5173/songs/f942f153-cd6e-411a-9d85-d4dbb76ecc37) | [380d903f](http://localhost:5173/songs/380d903f-efa6-41a6-83b6-6554f20c7a4c) | 24 | 88% | 8% | 75% | 2 | 0.41 | 1 note outside the guitar's range was dropped. |
| Test4 | [76dbc7eb](http://localhost:5173/songs/76dbc7eb-744a-44bf-bb4f-9bb15ad377ae) | [161510fc](http://localhost:5173/songs/161510fc-2016-4526-85d4-62a01bb07e41) | 24 | 38% | 13% | 13% | 1 | 0.62 | none |
| Test5 | [0923c576](http://localhost:5173/songs/0923c576-cd42-4e56-8124-3bf7fc75e691) | [84a4cc5f](http://localhost:5173/songs/84a4cc5f-589d-40bc-9b11-a17d4c907891) | 46 | 26% | 33% | 0% | 0 | 0.57 | 1 note outside the guitar's range was dropped. 1 note in chords no hand could play was dropped. |
| momsong | [60dfde77](http://localhost:5173/songs/60dfde77-5f78-42b8-8ab4-4c37226c5847) | [d65ba56e](http://localhost:5173/songs/d65ba56e-1903-4c1d-833c-89b2cbb41a07) | 280 | 43% | 23% | 11% | 8 | 0.53 | 1 note in chords no hand could play was dropped. |
| mysong | [36bd1c25](http://localhost:5173/songs/36bd1c25-fae9-4cf5-8dc2-44ed50671d66) | [7b4313de](http://localhost:5173/songs/7b4313de-7a49-498f-b9ba-418898562a34) | 523 | 45% | 26% | 16% | 21 | 0.52 | 3 notes outside the guitar's range were dropped. 16 notes in chords no hand could play were dropped. |
| nutshell | [be2d156b](http://localhost:5173/songs/be2d156b-dd33-4f1f-81ca-f6e1a243aef0) | [9896637e](http://localhost:5173/songs/9896637e-6c15-42cf-bf33-64b698c34a00) | 148 | 50% | 26% | 16% | 6 | 0.50 | 1 note outside the guitar's range was dropped. 10 notes in chords no hand could play were dropped. |
| nutshellandsolo | [552bb023](http://localhost:5173/songs/552bb023-ff11-4413-a95e-41586d1d3b30) | [10cb6ffb](http://localhost:5173/songs/10cb6ffb-d90c-496a-a155-a2b7b0586b80) | 683 | 31% | 29% | 6% | 11 | 0.57 | 4 notes outside the guitar's range were dropped. 13 notes in chords no hand could play were dropped. |
| test3 | [d94ebcc8](http://localhost:5173/songs/d94ebcc8-a92d-4152-a1ae-2d0e60f9de4d) | [8960e818](http://localhost:5173/songs/8960e818-7b86-4566-a7ef-7672f9d86c47) | 11 | 36% | 9% | 36% | 1 | 0.68 | 2 notes outside the guitar's range were dropped. |

Note counts differ between the rounds, although stage 4 cannot change which
notes are transcribed. Separation is not deterministic: the worker runs the
Demucs CLI (`_demucs` in `apps/worker/src/guitarvis_worker/stages/separation.py`)
without `--shifts`, and Demucs' default of one random shift (`--shifts` defaults
to 1, and `apply_model` draws the shift with `random.randint`) makes each run's
stems differ slightly. Each round uploads a new copy of the song, so each round
separates afresh.

Evidence that the difference is upstream of stage 4:

- Test2 goes from 30 to 24 notes with identical `warnings` in both documents
  (one note outside the guitar's range, none dropped from chords). Its 24
  notes' pitches are a subset of the 30's; the mapper drops notes only with a
  warning.
- The out-of-range warning depends on a note's pitch alone. It changes between
  the rounds on Test5 (2 notes, then 1) and test3 (1 note, then 2).
- Every song's pitch multiset differs between the rounds.

So note counts and confidence shares between the rounds carry separation noise.
Before to Stage 4, the note count changes by -6 to +7 notes per song, or -20% to
+5%. The share of notes hidden moves by up to 15 points (Test2, 60% to 75%;
Test4, 0% to 13%). The stage 4 effect on real songs is in the tab itself, the
string and fret chosen for each note, which the *Before* and *Job* links let the
user compare in the client.

The user's look at this round is informational. The spec decides the stage 4
half by its GuitarSet conditions, not by this table.

## Stage 2

Round `R=stage2`, run on 2026-10-19 at commit `dc315bd`, on a worker started
after it. `CACHE_VERSION` is 2, which forces a fresh transcription. The mapper
is the tuned one from the round above. Stage 2 runs with onset threshold 0.5,
frame threshold 0.4, minimum note length 93 ms, `melodia_trick` off and the
plain ghost rule at 0.7. basic-pitch's defaults are 0.5, 0.3, 127.7 ms, on, and
no ghost rule. All nine jobs succeeded. `HIDE` is 0.5 and `FULL` is 0.6, as
before. *Before* and *Stage 4* link the same song's jobs in the two rounds
above.

| Song | Job | Before | Stage 4 | Notes | At or below `HIDE` | Partly faded | Hidden | Passages | Median confidence | Warnings |
|---|---|---|---|---|---|---|---|---|---|---|
| Test | [4ed6e011](http://localhost:5173/songs/4ed6e011-5236-47dd-8109-17771343eb41) | [86a54243](http://localhost:5173/songs/86a54243-c5dd-4c09-bddf-db194052af72) | [c7a6aed1](http://localhost:5173/songs/c7a6aed1-f73d-4803-92b2-5d0a4483a1e4) | 28 | 57% | 11% | 46% | 1 | 0.50 | none |
| Test2 | [e5fcfabd](http://localhost:5173/songs/e5fcfabd-ce09-4bd3-821a-c49900090498) | [380d903f](http://localhost:5173/songs/380d903f-efa6-41a6-83b6-6554f20c7a4c) | [f942f153](http://localhost:5173/songs/f942f153-cd6e-411a-9d85-d4dbb76ecc37) | 14 | 50% | 21% | 29% | 1 | 0.52 | 2 notes outside the guitar's range were dropped. |
| Test4 | [7bd40a00](http://localhost:5173/songs/7bd40a00-b5ed-4fcf-8b42-b27361686085) | [161510fc](http://localhost:5173/songs/161510fc-2016-4526-85d4-62a01bb07e41) | [76dbc7eb](http://localhost:5173/songs/76dbc7eb-744a-44bf-bb4f-9bb15ad377ae) | 18 | 17% | 17% | 0% | 0 | 0.66 | none |
| Test5 | [aad902b8](http://localhost:5173/songs/aad902b8-e520-48d2-9c4f-147094b12428) | [84a4cc5f](http://localhost:5173/songs/84a4cc5f-589d-40bc-9b11-a17d4c907891) | [0923c576](http://localhost:5173/songs/0923c576-cd42-4e56-8124-3bf7fc75e691) | 39 | 10% | 26% | 0% | 0 | 0.68 | 1 note outside the guitar's range was dropped. |
| momsong | [8127355c](http://localhost:5173/songs/8127355c-62a5-410b-94de-2107b87eacfe) | [d65ba56e](http://localhost:5173/songs/d65ba56e-1903-4c1d-833c-89b2cbb41a07) | [60dfde77](http://localhost:5173/songs/60dfde77-5f78-42b8-8ab4-4c37226c5847) | 227 | 21% | 35% | 6% | 4 | 0.58 | 1 note in chords no hand could play was dropped. |
| mysong | [bee31c12](http://localhost:5173/songs/bee31c12-6964-4f84-a55d-31298bb4622d) | [7b4313de](http://localhost:5173/songs/7b4313de-7a49-498f-b9ba-418898562a34) | [36bd1c25](http://localhost:5173/songs/36bd1c25-fae9-4cf5-8dc2-44ed50671d66) | 420 | 23% | 38% | 5% | 6 | 0.58 | 7 notes in chords no hand could play were dropped. |
| nutshell | [f0732097](http://localhost:5173/songs/f0732097-f422-4926-bdeb-5502f65ceb41) | [9896637e](http://localhost:5173/songs/9896637e-6c15-42cf-bf33-64b698c34a00) | [be2d156b](http://localhost:5173/songs/be2d156b-dd33-4f1f-81ca-f6e1a243aef0) | 115 | 23% | 37% | 3% | 1 | 0.58 | 3 notes in chords no hand could play were dropped. |
| nutshellandsolo | [4dca5f38](http://localhost:5173/songs/4dca5f38-1dc1-483b-a269-ef55eead8ff8) | [10cb6ffb](http://localhost:5173/songs/10cb6ffb-d90c-496a-a155-a2b7b0586b80) | [552bb023](http://localhost:5173/songs/552bb023-ff11-4413-a95e-41586d1d3b30) | 575 | 13% | 35% | 0% | 0 | 0.61 | 1 note in chords no hand could play was dropped. |
| test3 | [d336ae68](http://localhost:5173/songs/d336ae68-4203-4a3e-afce-54c6f8cccf1a) | [8960e818](http://localhost:5173/songs/8960e818-7b86-4566-a7ef-7672f9d86c47) | [d94ebcc8](http://localhost:5173/songs/d94ebcc8-a92d-4152-a1ae-2d0e60f9de4d) | 8 | 13% | 25% | 0% | 0 | 0.73 | none |

### Flags

The plan flags a song when its note count fell by more than a third from the
Stage 4 round, or its share of hidden notes rose by more than 10 points. These
are the frame-threshold risk the spec names: `frame_threshold` acts as a
confidence floor, and `melodia_trick` off drops notes with no detected onset,
which separated stems may have more of. Each song, Stage 4 to Stage 2:

| Song | Notes, Stage 4 | Notes, Stage 2 | Change | Hidden, Stage 4 | Hidden, Stage 2 | Change | Flag |
|---|---|---|---|---|---|---|---|
| Test | 30 | 28 | -2 (-7%) | 47% | 46% | -1 point | none |
| Test2 | 24 | 14 | -10 (-42%) | 75% | 29% | -46 points | **count** |
| Test4 | 24 | 18 | -6 (-25%) | 13% | 0% | -13 points | none |
| Test5 | 46 | 39 | -7 (-15%) | 0% | 0% | 0 points | none |
| momsong | 280 | 227 | -53 (-19%) | 11% | 6% | -5 points | none |
| mysong | 523 | 420 | -103 (-20%) | 16% | 5% | -11 points | none |
| nutshell | 148 | 115 | -33 (-22%) | 16% | 3% | -13 points | none |
| nutshellandsolo | 683 | 575 | -108 (-16%) | 6% | 0% | -6 points | none |
| test3 | 11 | 8 | -3 (-27%) | 36% | 0% | -36 points | none |

The hidden-share change is the difference of the rounded shares shown. One song
flags: Test2, on note count (24 to 14, a drop of 42%; a third is 33%). No song
flags on hidden share, which fell or held in all nine.

Separation noise is in these numbers too. Between Before and Stage 4, where
stage 4 cannot change the notes, a song's note count moved by -20% to +5%, and
its hidden share by up to 15 points. That is one pair of rounds, so -20% is the
largest drop seen there, not a bound. What can be told apart from it:

- **The direction.** Between Before and Stage 4 the counts moved both ways and
  the total hardly moved (1,764 notes, then 1,769). Here all nine fell and the
  total fell 18.4%. That is not the pattern the noise showed.
- **Test2's size.** Its drop of 42% is more than twice the largest the noise
  gave. That drop was Test2's too (30 to 24, -20%).
- **The share at or below `HIDE`.** It moved by at most 8 points per song
  between Before and Stage 4 (Test2, 80% to 88%). Here it fell in every song,
  by 6 to 38 points; only Test, at 6, is inside the noise.

What cannot:

- **One song's drop, for most songs.** Test, Test5, momsong, mysong and
  nutshellandsolo fell by 7% to 20%, inside the range the noise gave. For them
  the common direction is the evidence, not the song. nutshell, Test4 and test3
  fell by 22% to 27%, just past it, on one measurement of the noise.
- **Small songs.** Test, Test2, Test4, Test5 and test3 have 8 to 39 notes. Two
  or three notes move the percentage: test3's -27% is 3 notes.
- **Which setting removed a note.** The onset and frame thresholds, the note
  length, `melodia_trick` and the ghost rule all changed together. This round's
  separation also differs from Stage 4's, so a Stage 2 note cannot be paired
  with a Stage 4 one.
- **Whether the lost notes were real.** The table counts notes. Only the tab in
  the client shows whether a dropped note was played.

### What changed overall

Across the nine songs the notes went from 1,764 (Before) and 1,769 (Stage 4) to
1,444, a drop of 18.4% from Stage 4. Pooled over all notes, the share at or
below `HIDE` went from 39.9% to 19.0% (706 notes to 274), the partly faded
share from 26.1% to 34.8% (462 to 503), and the hidden share from 12.1% to 3.9%
(214 notes to 56); the hidden passages went from 51 to 13. The notes above
`HIDE` went from 1,063 to 1,170, and none of the nine songs has fewer of them.
The median confidence rose in all nine songs, by 0.03 to 0.11. `HIDE` and
`FULL` are still the values measured on the old settings, and confidence is a
note's mean frame activation, which the frame threshold changes. So these
shares are not the same notes cut at the same line.

### Sign-off

Awaits the user, after they open the three links per song.
