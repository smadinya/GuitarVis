# Manual acceptance

**Spec:** [008 — Manual acceptance](spec.md#manual-acceptance)

Checks that cannot be automated honestly. A person runs each one in a
browser against real services, and records the result here.

Filled in before the PR is merged. 007's record was committed blank and merged
without the run.

## Setup

- Commit: …
- Machine, OS and browser: …
- Songs: title, length, and the frets they reach

Use a song this database has never seen. The api dedupes uploads by content
hash and returns any job that has not failed (`_LIVE` in
`packages/jobs/src/guitarvis_jobs/postgres.py`; `create_job` in
`apps/api/src/guitarvis_api/routes.py`), and the compose volumes keep old jobs
across restarts. So a song processed before this branch comes back as its old
document, with no `loudness`, and so does a song you re-upload after changing
the loudness constants. To reuse a song, delete its row from the `jobs` table
first (a job's `title` is the upload's file name without its extension):

```
docker compose exec postgres psql -U guitarvis -d guitarvis -c "DELETE FROM jobs WHERE title = '<song title>'"
```

That is enough. The stage cache is keyed by content hash, so the rerun skips
separation and transcription and measures loudness fresh. To check the default
amplitude on purpose, re-upload a song processed before this branch.

## End to end

- [ ] At 1×, dots and vibration match the audio and the tab strip
- [ ] At 0.5×, dots and vibration match the audio and the tab strip
- [ ] A repeated pluck on one fret shows each pluck
- [ ] Loud and quiet notes look different, and the default amplitude for an old document looks natural
- [ ] The vibration helps more than it distracts
- [ ] With only the present on the neck, the tab strip gives enough warning to move the hand

Notes: …

## The views

- [ ] 2D opens on the whole neck, zooms and pans, and never tilts
- [ ] 3D rotates, zooms and pans
- [ ] Double-click, reset, and switching views work
- [ ] Shift-, ctrl- and meta-drag each pan in 2D, as any drag does (fixed by [009](../009-review-fixes/spec.md), #20)
- [ ] The choice is remembered across a reload

Reset view sits over the upper tuner buttons in 2D? …

Notes: …

## Readability

- [ ] In 2D at full width, the note names on the dots can be read without zooming

Readable without zoom down to a panel width of: … px

Label/bushing overlap at the headstock for wide labels? …

Notes: …

## Frame rate

- [ ] Playback with the 3D view moving is smooth on the dev machine's browser

Frame rate: browser … , about … fps, playing with the 3D view moving

Notes: …

## Dark mode, reduced motion, resizing, WebGL off

- [ ] Dark mode: the background and dots follow the theme, and the guitar keeps its colours
- [ ] Reduced motion: no pulse and no vibration, and the camera jumps instead of animating
- [ ] Resizing the window during playback keeps the guitar and its dots right
- [ ] WebGL turned off: the panel shows its message, and the tab strip and controls carry on

Notes: …

## The string orders

The tab strip puts the highest string on top, and the guitar the lowest.

- [ ] Reading the two together was not confusing

Notes: …

## Constants changed

Constants changed in this run, from → to, and why: …

These are the amplitudes, the pulse, `WIDE`, the panel height and the pixel
ratio.
