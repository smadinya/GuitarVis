# Tab View and Sync — Design

**Date:** 2026-10-08
**Status:** Draft for review
**Parent spec:** [001-guitarvis-design](../001-guitarvis-design/spec.md)
**Builds on:** [005-api-job-queue](../005-api-job-queue/spec.md) — read its
[carried findings](../005-api-job-queue/review-notes.md) first

## Purpose

Build phase 4: the first real end-to-end experience. A user drops a song into
the browser, watches the job move through its stages, then plays the song with
a scrolling tab strip that stays in sync with the audio, and can slow it down,
loop a passage, and solo the guitar.

After 005 the pipeline is reachable over HTTP but has no client. `web/` is a
shell with generated types and nothing else. This phase builds the client the
parent spec describes, minus the two fretboard views, which are phase 5. It
also stands up the pieces every later view reuses: the `PlaybackEngine`, the
note cursor, and the shared confidence rule.

The success conditions:

1. With `make services`, `make migrate`, `make api`, `make worker` and
   `make web` running, a user uploads a song in the browser, watches the four
   stages progress, and plays it. The tab strip stays in sync by ear across a
   full song at 1× and at 0.5×.
2. Speed, the A/B loop and the mix ↔ guitar toggle all work, and the toggle
   keeps the playback position.
3. Every failure reason the api can return shows mapped, actionable text, and
   a document missing any optional track renders its fallback. Tests prove
   both.
4. The confidence thresholds that fade notes and hide passages come from a
   recorded measurement, not a guess.
5. `make check` gates all of it.

## Scope

**In:**
- an upload page and a song page, with progress polling;
- the `PlaybackEngine`, its clock, and the note cursor;
- the canvas tab strip;
- transport controls, speed (0.5 / 0.75 / 1×), the A/B loop, and the mix ↔
  guitar toggle;
- a warnings banner;
- the shared confidence module;
- one reason → text map, and API types generated from the api's response
  models;
- confidence calibration through `make eval ARGS=--full`;
- the 429 reconciliation fix from 005's carried findings;
- `make web`;
- ADR 0008, which resolves open decision 7 (pitch-preserved slow-down).

**Out:**
- the 2D fretboard and the 3D guitar (phase 5);
- URL ingestion (phase 6);
- a backing track with the guitar muted. The api stores only the mix and the
  guitar stem, so this needs pipeline and api work and its own spec;
- serving `web/` in production, and hosting generally (open decision 12);
- mobile layouts (open decision 10);
- a "my songs" list, and accounts (open decision 11);
- editing;
- a sync-offset control for output latency (see *Risks*);
- click-to-seek on the tab strip, and a zoom control;
- the other carried 005 findings. The 429 fix is taken because the web client
  is what makes it visible; the rest are unaffected by this phase.

No `tabdoc.py` change, so the tab document schema does not move.

## Approach

### Shape of the client

```
web/src/
  api/client.ts       createJob · getJob · getDocument → typed result or ApiError
  api/messages.ts     Record<Reason, {headline, action}> — the one reason → text map
  routing.ts          "/" and "/songs/{jobId}"; pushState and popstate
  pages/UploadPage    drop or pick → POST /jobs → navigate
  pages/SongPage      poll → fetch document → <Player>, or the failure view
  playback/clock.ts   Clock; MediaClock (real), FakeClock (tests)
  playback/engine.ts  PlaybackEngine: a plain TS class owning the one <audio>
  playback/cursor.ts  notes in a time window, via monotonic pointers
  confidence.ts       emphasis(c) and hiddenPassages(notes) — shared by every view
  song.ts             Song: the document, its notes sorted, its hidden passages
  tab/layout.ts       pure: (song, t, viewport, loop) → draw list
  tab/TabStrip.tsx    canvas; paints the draw list each frame
  player/             Player, Controls, Warnings
```

Two routes, no router library. Client routes live under `/songs/…`, never
`/jobs/…`, so the Vite proxy that forwards `/jobs` and `/health` to the api
never swallows a page load. Refreshing a song page keeps the song. Vite's
dev server already falls back to `index.html` for unknown paths.

The client assumes it is served from the same origin as the api. In
development the Vite proxy makes that true. A later reverse proxy in front of
both keeps it true. So the api needs no CORS, and `<audio>` loads the api's
audio routes directly.

### The audio path: one media element

The `PlaybackEngine` owns a single `HTMLAudioElement`. That one choice decides
how speed, the toggle and the clock work, and it was chosen for speed.

Open decision 7 called pitch-preserved slow-down the largest client-side risk,
on the assumption that `playbackRate` shifts pitch. That is no longer true for
media elements. Current browsers time-stretch natively when `preservesPitch`
is set, and it is set by default. Native time-stretching exists only on media
elements. Web Audio buffer sources still shift pitch with rate, and would need
a phase vocoder. A media element therefore makes slow-down nearly free. It
costs a short gap when switching between the mix and the guitar stem. See
*Rejected alternatives* for the two designs that avoid that gap.

ADR 0008 records the resolution, conditional on the listening test under
*Manual acceptance*.

### The PlaybackEngine

**One clock, two kinds of subscription.** The parent spec has views subscribe
to `(tabDocument, currentTime)`. Here that becomes:

- **`engine.onFrame(cb)`.** The engine runs one `requestAnimationFrame` loop
  and hands every listener the same `t` for that frame. Views draw from it
  directly; React never re-renders at frame rate. Every view sees the same
  instant in the same frame, which is what keeps them consistent with each
  other without talking to each other. The loop runs while playing. When
  paused, the engine emits a single frame after each seek or state change, so
  the views redraw without spinning the CPU. A phase 5 fretboard view is one
  more `onFrame` listener.
- **`engine.subscribe(cb)` and `getState()`.** These feed the controls through
  `useSyncExternalStore`. The state holds playing, rate, source, loop,
  duration, buffering and error, plus a time readout updated at about 4 Hz.

**The clock.** `MediaClock` reads `audio.currentTime`:

- While playing, it extrapolates between media updates with
  `performance.now()` and the rate. Media time is coarse in some browsers,
  and a strip that steps visibly reads as out of sync even when it is not.
- It re-anchors on every event that breaks playback: `seeked`, `ratechange`,
  `play`, `pause`, `waiting`, `playing`.
- `timeupdate` is only a reading, as is a change in `currentTime` between
  events. A reading may be up to 250 ms old, the longest gap the HTML spec
  allows between `timeupdate`s, but is never ahead of where playback is. So a
  reading ahead of the extrapolation corrects it, and one behind it snaps the
  clock only when the two differ by more than 50 ms. Comparing against a
  reading that has not changed would snap a coarse clock every 50 ms and
  stall the strip until the next one.
- It runs at most 300 ms past the last reading: 250 ms plus the 50 ms
  allowance. Past that, the element has stalled without saying so, and the
  strip waits for it.
- While playing, it never returns a time earlier than the last one it
  returned, except after a seek.
- While paused or buffering it returns media time exactly, even if that is
  behind the last time it returned, so a stall freezes the strip at what is
  heard rather than where extrapolation had got to.

**Speed.** `setRate(r)` accepts 0.5, 0.75 and 1:

- It sets `playbackRate` and `defaultPlaybackRate` together. The media load
  algorithm resets `playbackRate` to the default whenever `src` changes, and
  that would silently undo a speed change on every toggle.
- It sets `preservesPitch = true` explicitly, and the `webkitPreservesPitch`
  alias where it exists, rather than trusting the default.

**The mix ↔ guitar toggle.** `setSource(s)`:

1. Records the time and whether it was playing.
2. Sets `src` to `/jobs/{id}/audio/{mix|guitar}`.
3. Seeks to the recorded time on `loadedmetadata`.
4. Resumes if it was playing.

`src` is always the api path, never the presigned URL it redirects to. The
next part depends on that.

**Expired audio URLs.** The api redirects to presigned URLs that live 15
minutes, and a practice session outlasts that:

- On a media network error, the engine sets `src` again. The api answers with
  a fresh redirect, and the engine seeks back and resumes.
- After three consecutive failures it stops and reports that the audio
  connection was lost, with a reload action. It holds the position, including
  a seek made while retrying, for the source the user chooses next.
- A recovery counts, and the failures stop counting, once two seconds have
  been played since it. Seeks and loop jumps do not count as playback. So an
  error that comes back at the same place, as in a truncated file, ends in the
  error state, while a short A/B loop that never gets two seconds past the
  error still recovers each time.

**Disposal.** The engine sets `preload = "metadata"` before its first `src`,
and on dispose it removes `src` and calls `load()`. Pausing alone leaves an
element downloading, and leaving a song page would otherwise keep fetching
its mix.

**The A/B loop.**
- `[A]` and `[B]` set the loop points at the current time; `[×]` clears them.
  Points less than 0.5 s apart are refused.
- The engine seeks to A when playback crosses B going forward from inside the
  loop. Seeking past B therefore releases the loop, and seeking before A plays
  into it.
- The check runs on every frame and on every `timeupdate`. A background tab
  stops animation frames but not `timeupdate`, so the loop holds while the tab
  is hidden.

**Ending, duration and keys.**
- At `ended` the engine pauses at the end. Play starts again from zero.
- Until media metadata arrives, the duration comes from
  `source.duration_sec`.
- Space plays and pauses, and ← / → seek 5 s. The handler sits on the window
  and ignores keys aimed at text inputs.

**Testability.** The engine takes a narrow `MediaLike` interface rather than a
DOM element, and a `now()` function rather than `performance`. Tests drive a
fake media object that fires events, so the toggle, error recovery and loop
crossing are covered without real audio.

### The note cursor

`cursor.window(from, to)` returns the notes whose sounding interval
`[t, t + dur]` overlaps `[from, to]`. It answers from the note array sorted
once by onset:

- Two pointers advance monotonically during normal playback.
- A backward jump, or a forward jump past the window, re-seats them by binary
  search.
- Overlap with the window's start is found by searching back from the start by
  the longest note duration, computed once.

Per-frame work is proportional to the notes on screen, not to the song's
length. The parent spec's "notes sounding now" and "notes within the 2 s
look-ahead" are both calls to `window`. Chords and sections have cursors of
their own, and beats and hidden passages, which never overlap, are found by
binary search, so nothing in a frame grows with the song.

### The tab strip

**Geometry.**
- A note sits at `x(t) = playheadX + (t − now) × pxPerSec`.
- The playhead is fixed at 20% of the width. The strip scrolls under it, so
  everything to its right is look-ahead.
- `pxPerSec` is a constant of 150, in song seconds, so at 0.5× the strip
  scrolls half as fast. An 800 px strip shows about 4 s ahead, more than the
  2 s look-ahead the parent spec asks for.
- Position is linear in seconds, not beats. A bad beat grid therefore moves
  only the bar lines, never the notes. This is ADR 0002's rule carried into
  the renderer.

**Rows, top to bottom.**
- Section labels, then chord symbols. Each row collapses when its track is
  empty, and that is the first rung of the degradation ladder.
- The string lines, highest string on top as in standard tab. Labels come from
  `instrument.tuning`. The top one is lowercased when it shares a letter with
  the bottom one, which gives `e` … `E` in standard tuning and keeps drop-D
  correct.

**Marks.**
- **Bar lines** at beats where `beat === 1`. With no beats there are no bar
  lines, and the notes are still in the right place.
- **Notes.** The fret number sits on its string, with a knockout behind it so
  the line does not strike through it, and a faint tail to `t + dur`. Each note
  is in one of three states — past (dimmed), sounding (accent colour, bold) or
  upcoming (plain) — and its opacity is then scaled by `emphasis(confidence)`.
- **Chords** are drawn with the same `emphasis`, at the chord thresholds (see
  *Confidence*).
- **The A/B loop** is a shaded band with its two markers. It is drawn over the
  tab, as a selection is: under it, each fret number's knockout would cut an
  untinted box out of the band.
- **Hidden passages** are a tinted band with no fret numbers inside it. Chord
  symbols over the band are drawn larger, since they are all that passage
  shows, but their own confidence still sets their opacity. With no chord
  there, the band is labelled "unclear passage".
- **An empty `notes` array** draws the bare strings and a centred message.
  The warnings banner says why.

**Painting.** `layout.ts` is pure and returns a draw list in CSS pixels.
`TabStrip` scales for `devicePixelRatio`, follows `ResizeObserver`, and paints
the list. The painter is thin enough that all the logic worth testing is in
layout. When a 2D context is unavailable, as in jsdom, it paints nothing
rather than throwing.

### Confidence

The parent spec puts the confidence rule in one shared function so it cannot
drift between views. It lives in `confidence.ts`, and phase 5's views import
it unchanged.

- **`emphasis(c)`** returns an opacity: 0.35 at or below `HIDE`, 1.0 at or
  above `FULL`, and linear in between. If calibration makes the two equal,
  it is a step. Chords use `CHORD_HIDE` and `CHORD_FULL` instead. A chord's
  confidence is how closely the audio matches a triad template, not the
  transcriber's, and the same number means something different.
- **`hiddenPassages(notes)`** finds runs of at least three consecutive notes,
  all below `HIDE`, where no gap between neighbouring onsets exceeds 1 s.
  Consecutive means consecutive in onset order, across all strings. Notes that
  share an onset are one moment: if any of them reaches `HIDE`, the moment is
  clear and ends the run, whatever order the document lists them in. Each run
  hides from its first onset to its latest end, but never past the next onset
  after it. Otherwise one faint, long sustain could hide seconds of confident
  notes. So every onset inside a passage belongs to its run. A lone weak note
  fades but does not punch a hole in the tab. The function runs once per
  document.
- **`isHidden(passages, t)`** is the one test of whether a note is hidden, for
  the views and for the calibration report. A passage covers `[from, to)`:
  its end is the onset of the note that ended the run, and that note shows.

**Where the thresholds come from.** Real output is low-confidence. The first
real song through the api had a median note confidence of 0.45 and a maximum of
0.88. A threshold picked by eye could blank most of a tab, or hide nothing.
So the thresholds are measured.

- `score_full` in `apps/eval` already pairs transcribed notes with the truth
  through `match_notes`. It gains a tally of each transcribed note's
  confidence and whether it was paired.
- The results JSON gains `precision_by_confidence`: ten bands, 0.1 wide, each
  holding `{estimated, matched, precision}`. `make eval` prints them as a
  table. Like all evaluation, this is measured and never gated.
- **`HIDE`** is the lower edge of the lowest band such that every band at or
  above it, among bands with at least 50 notes, has precision ≥ 0.5. Below
  `HIDE`, a note is more often wrong than right.
- **`FULL`** is found by the same rule with precision ≥ 0.8.
- **`CHORD_HIDE`** and **`CHORD_FULL`** come from the same rule, applied to
  `chord_precision_by_confidence`. It counts each 0.1 s frame that shows a
  chord, on the frames `chord_tally` scores, by that chord's confidence, and
  whether the chord is the truth's. Frames of one held chord are not
  independent, so a band needs 300 frames (30 s of chords) to count.
- If the measurement cannot support thresholds by this rule — say no band
  reaches 0.5 — `calibration.md` says so, and the values are chosen with that
  evidence in hand and the reasoning written down.

`calibration.md`, in this folder, records:
- the results file the numbers came from;
- the chosen values;
- the fraction of notes each threshold fades or hides on the real songs to
  hand.

That last figure is the sanity check. GuitarSet is clean solo guitar with no
separation, so calibration on it is optimistic for stems separated from full
mixes. The constants in `confidence.ts` cite `calibration.md`.

### The job lifecycle

**Upload page.**
- A drop zone and a file picker with `accept="audio/*"`.
- `POST /jobs` goes through `XMLHttpRequest`, not `fetch`. Only XHR reports
  upload progress, and a WAV can be tens of megabytes.
- 202 (new) and 200 (existing) both navigate to `/songs/{id}`. A re-upload
  therefore lands on the existing song, which may already be playable.
- 413, 422, 429, 503 and the client-only `unreachable` show their mapped
  headline and action on the page.
- Leaving the page mid-upload aborts the request. An upload that finishes
  anyway never pulls the user back to its song.

**Song page.**

| Job | Shown |
|---|---|
| `queued` | "Waiting for a worker" |
| `running` | the stage in plain words, and the percent |
| `attempts > 1` | adds "Retrying — attempt 2 of 3" |
| `failed` | the mapped headline and action, the server's `message` as detail, "Upload another song" |
| `succeeded` | fetch the document, then the player |
| 404 | "We couldn't find that song", with a link to upload |

- The stages read "Isolating the guitar", "Transcribing notes", "Finding the
  beat and chords" and "Working out fingerings". `stage` stays a plain string
  in the api, so an unknown name reads "Working".
- Polling runs every 1.5 s until the job is terminal. A network error or 503
  keeps polling, doubling the interval up to 10 s and showing
  "Reconnecting…". The first good answer restores 1.5 s.
- **The client never decides a job has hung.** 005's notes record that a row
  can sit at a stale percent while RQ waits to retry it. That is normal. A job
  the system has really lost is turned into `failed` by the api's
  reconciliation on read, which this polling triggers, and the page then shows
  it.
- On success, a failed document fetch offers a retry. A document whose
  `schema_version` is not 1 is refused: "This song was processed by a newer
  version of GuitarVis. Reload the page." A missing `schema_version` is 1, as
  the schema's default says.

The client does not otherwise validate the document at runtime. The worker
validates it as `TabDocument` before storing it, and the generated types
describe it. The page builds a `Song` once — the document, its notes sorted by
onset, and its hidden passages — and mounts the `Player` with it. Every view
reads the `Song`, never the raw document. The mix and guitar URLs are built from the job id. For an
api-produced document, `source.audio_url` is that same mix path.

### Errors: one vocabulary, generated types

005 left "publishing OpenAPI-derived types to `web/`" for phase 4 to decide. The
decision is a narrower version of it: generate types for the response models
from a JSON Schema, through the pipeline that already generates
`tabDocument.ts`.

- `apps/api/src/guitarvis_api/schemas.py` types `FailureView.reason` as
  `FailureReason`. The four `HttpReason` values describe a request, never a
  job. Error bodies carry any of the nine (`Reason`). A new `ErrorBody`
  model, in `errors.py`, describes `{"error": {"reason", "message"}}`, the
  shape the handlers already emit, and `error_body` builds every one from it.
  The bytes on the wire do not change.
- A new `guitarvis_api.schema_export` writes `schema/api.schema.json`, holding
  `JobView` and `ErrorBody`.
- `make schema` turns it into `web/src/types/api.ts` with the same
  `json-schema-to-typescript` step, and `schema-check` widens from
  `web/src/types/tabDocument.ts` to all of `web/src/types/`.

The payoff is in `api/messages.ts`, typed
`Record<Reason | "unreachable", {headline, action}>`. CONVENTIONS says adding a
reason means updating the UI mapping, and until now nothing enforced that. With
this change, a new server reason regenerates `api.ts`, and `tsc` then fails
until the reason has text. `unreachable` is the client's own reason for a
request that got no HTTP answer. It is not part of the server's vocabulary.

### The 429 fix

From 005's carried findings: `count_active` counts `queued` rows whose RQ job is
lost, and only a read of that exact row repairs it. A user can be refused with
"you already have 2 songs processing" when nothing is processing. The upload
page makes this visible, so it is fixed here.

`JobStore` gains `active_jobs(client_ip) → list[Job]`, in both implementations
and the shared contract suite. When the count reaches the limit, `POST /jobs`
reconciles each of those rows and counts again before refusing. It is still a
repair on read, with no reaper, as ADR 0007 has it. The race in which two
uploads both pass the count stays as 005 accepted it.

### Development wiring

- `vite.config.ts` proxies `/jobs` and `/health` to `http://localhost:8000`.
- `make web` runs the Vite dev server.
- `make check` already runs web lint, typecheck and tests, and still does.

### Testing

Everything below runs in `make check`. No test needs audio, a browser, or
the services, except the Python ones that already need them.

**TypeScript** (vitest). Pure modules stay on the `node` environment. Page
tests opt into jsdom per file, with `@testing-library/react`. Both are new dev
dependencies.

- **Cursor:** forward stepping, backward and forward jumps, overlapping
  durations, a note longer than the window, no notes.
- **Clock,** with a fake `MediaLike` and a fake `now()`:
  - extrapolation, and the snap on drift;
  - steady movement on readings 250 ms apart, and the 300 ms limit on a
    silent stall;
  - media time exactly once paused or waiting;
  - the freeze while `waiting`;
  - no backward time except after a seek;
  - a rate change mid-play.
- **Engine:**
  - the toggle keeps time, play state and rate across a source change;
  - `preservesPitch` and `defaultPlaybackRate` are set;
  - error recovery re-sets `src` and resumes, and gives up after three
    failures;
  - the loop-crossing rules, including enforcement from `timeupdate` alone.
- **Confidence:**
  - `emphasis` endpoints, and that it is monotonic;
  - `hiddenPassages` for a run of three, a run of two, the gap rule, a lone
    weak note, and adjacent runs.
- **Layout:**
  - the degradation ladder: no beats means no bar-line ops; no chords means
    no chord row; no sections means no section row; no notes means the
    message op;
  - no fret text inside a hidden band;
  - the three note states at chosen times;
  - `x(t)` geometry;
  - string order and labels, in standard tuning and drop-D.
- **API client:** with a fake `fetch` and XHR:
  - each status code and error body becomes the right `ApiError`;
  - a request with no answer becomes `unreachable`;
  - upload progress events surface.
- **Pages** (jsdom):
  - upload success navigates, and an upload error shows its mapped text;
  - the song page moves through queued → running → retrying → succeeded and
    mounts the player;
  - it also shows failed, 404, reconnecting after a poll error, and an
    unknown `schema_version`.
- **Fixtures:** the existing `minimal.tabdoc.json`, plus a real pipeline
  output, the first song run through the api, committed under
  `web/src/test/fixtures/`. It is 7 KB of derived data with no audio. It is
  imported and assigned uncast to a `TabDocument`, so `tsc` checks its shape
  as the existing contract test does.

**Python** (pytest):

- The api schema export writes what `schema-check` expects.
- Real error responses from the routes validate as `ErrorBody`.
- `POST /jobs` at the limit, with one of the counted rows lost, reconciles
  that row and accepts the upload.
- `active_jobs` in the store contract suite, against both stores.
- The eval band tally, fed hand-built pairs.

### Manual acceptance

Some checks cannot be automated honestly. They are recorded in
`acceptance.md` in this folder before the PR is opened:

- **An end-to-end run.** In a browser against real services: upload,
  progress, play, and the toggle, loop and speed controls.
- **The speed listening test,** at 0.5× and 0.75× in Chrome, Firefox and
  Safari. ADR 0008's resolution depends on it. A browser where native
  stretching is unusable gets no speed control rather than bad audio. If no
  Mac is to hand, Safari is recorded as untested, not assumed to pass.
- **The toggle offset.** Listen for any time offset between the mix and the
  guitar stem after switching. See *Risks*.

## Rejected alternatives

**Web Audio with both tracks decoded into buffers.**
- What it would give: a sample-accurate clock, and an instant crossfade
  between mix and guitar, or even a blend of the two.
- Why not:
  - Speed would shift pitch, which reopens open decision 7 at full cost: a
    phase vocoder.
  - It needs CORS on the storage bucket.
  - Both tracks must download and decode before play starts, about 170 MB of
    memory for a four-minute song.
- It stays available. If the toggle gap proves bad, it can replace the media
  element behind the same `PlaybackEngine` without touching a view.

**Two media elements, toggled by volume.** An instant toggle, but two
elements drift. Keeping them aligned means continuous correction, which is
fragile around rate changes and seeks, and it doubles the bandwidth.

**Paged tab rows.** Familiar from printed tab, but the layout depends on the
beat grid, which is the least reliable stage. A fixed playhead over a
time-linear strip keeps notes correct whatever the beat tracker did.

**Beat-proportional spacing.** Prettier on a good beat grid, wrong on a bad
one. See ADR 0002.

**Confidence thresholds by eye, or relative to each document.** By eye is a
guess. Thresholds relative to each document hide the same fraction of every
song, which makes a uniformly bad transcription look as trustworthy as a good
one. That is the silent wrongness the parent spec warns against.

**Validating the document at runtime against the committed JSON Schema.**
Every model has `extra="forbid"`, so the schema is closed. An external
validator would reject a whole document over one later additive field (see the
`tab-document` skill). The api serves only documents the worker has already
validated, so the client checks `schema_version` and trusts the generated
types.

**Hand-written API types.** About 25 lines less tooling, but the reason
vocabulary could drift silently. That is the drift the generated `Record` is
there to catch.

**A router library.** Two routes do not need one.

**Client-side hang detection.** A timeout in the browser would call a job dead
while RQ is still waiting to retry it. The api already decides when a job is
lost, and polling surfaces its decision.

## Consequences

- **Open decision 7 closes,** provided the listening test passes. ADR 0008
  records it, and the open-decisions table in `docs/decisions/README.md`
  loses its row.
- **There is a second generated contract.** `schema/api.schema.json` and
  `web/src/types/api.ts` join the tab document's two artifacts. `make schema`
  writes all four, and `schema-check` guards all four. CONVENTIONS' mechanism
  table gains "every failure reason has UI text →
  `Record<Reason, …>` + generated `api.ts`".
- **`FailureView.reason` changes in the OpenAPI schema,** from a string to the
  `FailureReason` enum. The JSON it describes is identical.
- **`JobStore` grows a method.** Both implementations and the contract suite
  change, as the protocol requires.
- **Same origin is now an assumption.** Hosting must put the api and `web/`
  behind one origin, or add CORS deliberately.
- **The web package gains jsdom and Testing Library** as dev dependencies.
- **Phase 5 starts from a working base.** It inherits the engine, the cursor
  and the confidence rule, and builds only its renderers.

## Risks

- **Native time-stretching quality.** Browsers stretch with general-purpose
  algorithms. At 0.5×, guitar may sound smeared or watery. The listening test
  decides. The fallback is no speed control in the affected browser, not a
  phase vocoder in this phase.
- **Output latency.** Audio is heard later than `currentTime` reports, by the
  output path's latency. That is negligible on wired output and roughly
  150–250 ms on Bluetooth headphones, which learners commonly use. There is no
  offset control in this phase. If the end-to-end run shows a visible lead
  over the audio, a per-browser offset setting is the follow-up.
- **An offset between the mix and the stem.** The mix is the original upload.
  The stem is Demucs's re-encoding of what ffmpeg decoded. MP3 encoder delay
  is handled differently by different decoders, so the two could disagree by
  about 25–50 ms. The beat grid comes from the mix and the notes from the
  stem, so the tab is aligned to one or the other. The acceptance check
  listens for it. A fix would belong in the pipeline, not the client.
- **Optimistic calibration.** GuitarSet thresholds come from clean solo
  recordings. Separated stems are worse, so real songs will show more faded
  and hidden notes than GuitarSet predicts. `calibration.md`'s
  real-song figures make the gap visible. Closing it needs labelled real
  mixes, which do not exist here.
- **Media element behaviour after a redirect.** Whether a browser re-requests
  the api path or the presigned URL for later `Range` requests is not
  specified. Error recovery covers both cases. If a browser stalls instead of
  erroring when a URL expires, recovery will not fire, and the end-to-end run
  needs to watch past the 15-minute mark.
- **Clock precision.** Firefox can coarsen media time for privacy, and some
  browsers update it only at `timeupdate`. Extrapolation carries the strip
  between readings up to 250 ms apart. A browser that reports time coarser
  than that would hold the strip briefly at each gap. The other side of the
  same allowance: an element that stalls without firing `waiting` runs the
  strip up to 300 ms ahead of the audio before it holds.
