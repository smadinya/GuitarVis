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

Round `R=stage4`, to be filled in by plan Task 9.

## Stage 2

Round `R=stage2`, to be filled in by plan Task 12.
