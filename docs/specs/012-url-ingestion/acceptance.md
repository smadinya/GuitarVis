# Manual acceptance

**Spec:** [012 — Manual acceptance](spec.md#manual-acceptance)

Checks that cannot be automated honestly, because they ask YouTube. A person
runs each one against real services, from a developer's machine, and records
the result here. Each case names the catalog row it exercises; the expected
reason, status and message are the catalog's. Read the api's and the worker's
log line for each case by eye, and copy it under the case.

Filled in before the PR is merged.

**This run:** by an agent (Claude Code), with no person present, on
2026-10-27, against real YouTube. A box is ticked only where the run
showed the whole check pass on the code as shipped. An item with a half
that needs a person or a browser is unticked, and says what passed as "API
half PASS: …". A logs item shown only with the workaround log config (bug 1)
is unticked, and says so. Checks not attempted are unticked and say why.
Its evidence (requests, responses, logs) stayed on the machine it ran on.

## Setup

- Commit: b90e462 (`012-url-ingestion`)
- Machine and OS: WSL2, Linux 6.18.54.1-microsoft-standard-WSL2 x86_64
- yt-dlp version (`uv run python -c "import yt_dlp.version as v; print(v.__version__)"`): 2026.10.26 (yt-dlp-ejs 0.8.0)
- Deno version (`deno --version`): 2.9.8
- Browsers and versions: none (no person present)
- `make smoke-url` passed on this commit: yes (3 passed)

How this run differed from the steps below:

- The developer's own `make api`, `make worker` and `make web` were already
  running on :8000 and :5173, so the run used a stack of its own, each part
  still started with `make`: `UVICORN_PORT=8001
  GUITARVIS_REDIS_URL=redis://localhost:6379/1 make api`, and `make worker`
  on the same Redis database. Postgres and object storage were shared.
- Bug 1 (see *The logs*): `make api` printed none of the api's INFO lines.
  From its second start, the api was given a log config from outside the
  repo (`UVICORN_LOG_CONFIG`), with the worker's format and our loggers at
  INFO. Every api log line below comes from that.
- The machine's clock was unsynchronised and jumped during the run, so
  timings come from monotonic sources (`elapsed=`, curl), not timestamps.

Start the stack with links on: `make services migrate`, then `make api`,
`make worker` and `make web`, each in its own terminal. The api dedupes by
video and keeps old jobs across restarts; to reuse a video, delete its row:

```
docker compose exec postgres psql -U guitarvis -d guitarvis -c "DELETE FROM jobs WHERE source_url LIKE '%<video id>%'"
```

## Links in every form

Use one short video for all of these; each after the first must return the
first's job (200, the same id) without a lookup in the api's log.

Three songs instead of one, each first submitted in a different form:
A1 Oasis, "Wonderwall" (`bx1Bh8ZvH84`, job 6b4e3a2b-c077-414e-94f5-4c045944e2c0),
A2 Guns N' Roses, "Sweet Child O' Mine" (`1w7OgIMMRc4`, job 286aa67c-c6a4-4f9f-b2f4-2a3356841879)
and A3 Nirvana, "Smells Like Teen Spirit" (`hTWKbfoikeg`, job 7e6e2a70-85c8-4b09-a7f3-664871dc1428).
Each succeeded in 48 to 84 s, and each stored file was `format=140 ext=m4a`.

- [ ] `https://www.youtube.com/watch?v=ID` reaches the song page, titled with the video's title. API half PASS: 202 with `Location: /jobs/{id}`, `title` the video's, `source_url` canonical. The page itself: NOT RUN (no browser)
- [ ] The job shows *Fetching the audio*, then the four stages. API half PASS: A2 polled `download` 0 → `separation` 5…33 → `transcription` 43 → `structure` 66 → `fretboard` 81 → `succeeded` 100. The client's wording: NOT RUN (no browser)
- [ ] The song plays from our stored copy with the tab in sync: NOT RUN (needs a person and a browser). `audio_url` was `/jobs/{id}/audio/mix` for all three, and the bytes it served were the download's (see *Playback*)
- [x] `https://youtu.be/ID` returns the same job: A1's first run; `youtu.be/bx1Bh8ZvH84?si=…` then gave 200 with its id
- [x] `https://www.youtube.com/shorts/ID` returns the same job: A1 and A2, 200 with the same id. A Short for its own first run: NOT RUN
- [x] `https://m.youtube.com/watch?v=ID` returns the same job: A3's first run (`…&list=PL…&si=…`, 202), then `www…`, `youtu.be` and `youtube-nocookie.com/embed` forms gave 200 with its id
- [ ] `…watch?v=ID&t=42s` returns the same job, and the song starts at 0:00. API half PASS: A2's first run; the canonical URL drops `t=`, and the stored file is the whole video (302.997 s against 303 s). Whether the client starts at 0:00: NOT RUN (no browser)
- [x] `…watch?v=ID&list=PL…` returns the same job, and only that video is fetched: A3, one `link fetched phase=download` line and one song's file (4.5 MB, 278 s)
- [x] `https://youtu.be/ID?si=…` returns the same job, and `si=` appears in no log line: four submissions carried `si=`; a search of every api and worker log found it 0 times

Log lines (api lookup, worker download), A1:

```
2026-10-27 17:41:38,838 INFO guitarvis_api.routes_links: link fetched phase=lookup site=youtube video=bx1Bh8ZvH84 job=- attempt=- elapsed=4.1s ytdlp=2026.10.26 js=deno/2.9.8
2026-10-27 17:41:47,391 INFO guitarvis_worker.ingest: link fetched phase=download site=youtube video=bx1Bh8ZvH84 job=6b4e3a2b-c077-414e-94f5-4c045944e2c0 attempt=1 elapsed=8.3s ytdlp=2026.10.26 js=deno/2.9.8 format=140 ext=m4a bytes=4493245
```

Every repeat (Q1) answered 200 with the first job's id in 11 to 20 ms, with
no `link fetched` line. All three tab documents validated, with 0
violations of `pitch_of(string, fret, tuning) == midi` over 5,085 notes.

## Refused links

| Case | Row | Expected | Result | Log line |
|---|---|---|---|---|
| Blank field | client | "Paste a link first.", nothing sent | NOT RUN (no browser). The api, sent `{"url":"   "}`: 422 `unsupported_link`, R4's message | none: logged before the log config (bug 1) |
| `hello there` | client | "That doesn't look like a link.", nothing sent | NOT RUN (no browser). The api: 422 `unsupported_link`, R4's message | `link refused kind=not_a_link host=- path=-` |
| A playlist link (`/playlist?list=…`) | R7 | 422 `unsupported_link`, "That link isn't to a single video…" | PASS | `link refused kind=not_a_video host=www.youtube.com path=playlist` |
| A channel link (`/@…`) | R7 | 422 `unsupported_link` | PASS (`/@Metallica`) | none: logged before the log config (bug 1) |
| A Vimeo link | R6 | 422 `unsupported_link`, "We can only fetch songs from YouTube for now…" | PASS | `link refused kind=unsupported_site host=vimeo.com path=-` |
| A private video | L1 | 422 `link_unusable`, "That video is private…" | PASS (`yZIXLfi8CZQ`, 0.95 s) | `INFO … link fetch failed kind=private phase=lookup site=youtube video=yZIXLfi8CZQ job=- attempt=- elapsed=0.9s ytdlp=2026.10.26 js=deno/2.9.8 detail="ERROR: [youtube] yZIXLfi8CZQ: Private video. …"` |
| A removed video | L2 | 422 `link_unusable`, "That video isn't available…" | PASS (`Q39EVAstoRM`, 0.96 s) | `INFO … link fetch failed kind=unavailable … video=Q39EVAstoRM … elapsed=1.0s … detail="ERROR: [youtube] Q39EVAstoRM: This video is unavailable"` |
| An age-restricted video | L4 | 422 `link_unusable`, "That video is age-restricted…" | PASS (`HtVdAasjOgU`, 4.1 s) | `INFO … link fetch failed kind=age_restricted … video=HtVdAasjOgU … elapsed=4.1s … detail="availability=needs_auth"` |
| A members-only video, if one can be found | L5 | 422 `link_unusable` | NOT RUN (none found) | |
| A live stream | L6 | 422 `link_unusable`, "That's a live stream…" | PASS (`0sfDth4lMLc`, sent as `/live/ID?si=…`, 2.0 s) | `INFO … link fetch failed kind=live … video=0sfDth4lMLc … elapsed=2.0s … detail="live_status=is_live"` |
| An upcoming premiere, if one can be found | L7 | 422 `link_unusable`, "That video hasn't premiered yet…" | NOT RUN (none found) | |
| A video over ten minutes | L10 | 422 `too_long`, "That video is m:ss long…" (h:mm:ss past an hour), nothing downloaded | PASS (`sOnqjkJTMaA`, 13:42): "That video is 13:42 long. The limit is 10 minutes: try a link to a single song." No job row, no download | `INFO … link fetch failed kind=too_long … video=sOnqjkJTMaA … elapsed=3.2s … detail="duration=822.0"` |

Notes: each lookup line above also carries `ytdlp=2026.10.26 js=deno/2.9.8`.
Also checked: `javascript:alert(1)` (R5), `/embed/videoseries?list=…` (R7,
`path=embed`) and the lookalike `youtube.com.evil.example` (R6), each 422
with the catalog's message; a body that is not JSON (R2), 422 and `link
refused kind=bad_request`; a third new link with two jobs active (Q2), 429
`too_many_jobs` with no lookup; and `/audio/mix` on a queued link job (G1),
409 `not_ready`. A host refusal logged `path=-`, short of the spec's "first
path segment"; fixed after this run (a6b57b5). An ended stream whose
recording was not kept (`jfKfPfyJRdk`) is refused as L2, which is right.

## The switch

- [ ] With `make api GUITARVIS_URL_INGESTION=0`, the link field is gone after a reload, and `curl -X POST localhost:8000/jobs/from-url` answers 403 `links_disabled` (R1). API half PASS (on :8001): `/features` gave `{"url_ingestion":false}`, and a link gave 403 `links_disabled` with the catalog's message, before parsing, the size check and dedupe alike, each logged `link refused kind=links_disabled` (with the workaround log config). The field: NOT RUN (no browser)
- [ ] With the field showing, the api restarted with links off, and a link pasted: the field goes, and the page shows "Links are turned off." with the server's message: NOT RUN (no browser)
- [x] A link job queued, then the worker restarted with `GUITARVIS_URL_INGESTION=0` before it ran: the job fails `links_disabled` with "Links were turned off before this song could be fetched…", not retried (W1). Job 88b3b62a-0207-4241-9876-98c18a438909 failed within 1 s, attempts 1, no download; RQ's registries empty afterwards
- [ ] A link job whose download was stored, retried with links off, still runs: NOT RUN (not attempted: it needs a worker killed mid-pipeline after a second download)
- [ ] Jobs made from links are still served with links off: the song page and its audio load. API half PASS: A1's job and document 200, `/audio/mix` followed to 200 with all 4,493,245 bytes, `/audio/guitar` 307. The song page: NOT RUN (no browser)

Notes: the W1 worker line:
`2026-10-27 17:48:18,180 INFO guitarvis_worker.runner: job 88b3b62a-0207-4241-9876-98c18a438909 is a link job and links are off, and its audio was never stored`

## Network and upstream

- [ ] The network cut during a lookup (disconnect, then paste a new link): `fetch_failed` with "We couldn't reach YouTube…" (L13), or "YouTube took too long to answer…" after 30 s (L14); the api stays responsive meanwhile: NOT RUN (not attempted)
- [ ] Deno taken off the api's PATH and the api restarted: a new link answers 503 `fetch_failed`, and the log says `kind=misconfigured` at ERROR (L16). API half PASS: 503 in 0.21 s, with no request to YouTube. The log half: with the workaround log config; as shipped at b90e462: FAIL (bug 1: the line printed bare, with no time, level or logger), fixed in 01f27e7. With it:
  `2026-10-27 17:50:28,976 ERROR guitarvis_api.routes_links: link fetch failed kind=misconfigured phase=lookup site=youtube video=sOnqjkJTMaA job=- attempt=- elapsed=0.2s ytdlp=2026.10.26 js=- detail="no JavaScript runtime: Deno 2.3.0 or later is not installed"`
- [x] Deno taken off the worker's PATH: the worker warns at start, and a queued link job fails `fetch_failed` (D4). It warned `links are on, but Deno 2.3 or later was not found: every link job will fail as fetch_failed until it is installed`, and job ee988964-c635-4e31-a5a2-cc66bd7da061 failed `fetch_failed` at `download` in 0.4 s, not retried:
  `2026-10-27 17:51:55,178 ERROR guitarvis_worker.ingest: link fetch failed kind=misconfigured phase=download site=youtube video=tAGnKpE4NCI job=ee988964-c635-4e31-a5a2-cc66bd7da061 attempt=1 elapsed=0.2s ytdlp=2026.10.26 js=- detail="no JavaScript runtime: Deno 2.3.0 or later is not installed"`
- [ ] Five links pasted at once from five tabs: four are looked up, one answers 503 "We're checking a lot of links right now…" (Q3), if the timing allows: NOT RUN (not attempted: four or more lookups)

Notes: YouTube never bot-checked, rate-limited or refused this machine over
15 requests. The api gives no warning at start when Deno is missing; only
the worker does.

## Playback of what was stored

The stored file is the format the worker's log names (`format=140 ext=m4a`
for most videos; `ext=webm` when a video has no m4a).

- [ ] A stored m4a plays, seeks and loops in Chrome: NOT RUN (needs a person and a browser)
- [ ] A stored m4a plays, seeks and loops in Firefox: NOT RUN (as above)
- [ ] A stored m4a plays, seeks and loops in Safari: NOT RUN (as above)
- [ ] If a video without m4a was found: the stored webm plays in Chrome and Firefox; note Safari's behaviour: NOT RUN (none found)

Notes: all three stored files were `format=140 ext=m4a` (AAC-LC, 44.1 kHz,
stereo). `/audio/mix` answered 307 to a presigned URL. The bytes fetched
from it hashed to their storage key, and their count was the worker's
`bytes=`.

## The logs

**Bug 1, found by this run: `make api` printed none of the api's INFO
lines.** uvicorn configures only its own loggers, so the api's had no
handler and stayed at WARNING: every `link fetched` lookup line and every
L1 to L8, L10 and R1 to R7 line was lost, and ERROR lines printed bare,
with no time, level or logger. The tests read the lines through caplog,
which hid it. The api's lines below were printed only through the log
config described in *Setup*, so the items that rest on them are unticked.
Fixed after this run (01f27e7): the api sets its logging up as it starts,
as the worker does. At a6b57b5, `UVICORN_PORT=8011 make api` and a Vimeo
link printed
`2026-10-27 18:07:23,289 INFO guitarvis_api.routes_links: link refused kind=unsupported_site host=vimeo.com path=1`.

- [ ] Every lookup or download left exactly one `link fetch failed` or `link fetched` line, at the catalog's level: with the workaround log config; as shipped at b90e462: FAIL (bug 1), fixed in 01f27e7. With it: 16 outcomes, 16 lines (12 lookups, 4 downloads); INFO for fetched, L1, L2, L4, L6 and L10, ERROR for the two misconfigured
- [ ] Every one of those lines carries `ytdlp=` and `js=`: the worker's 4 as shipped; the api's 12 with the workaround log config; as shipped at b90e462: FAIL (bug 1), fixed in 01f27e7. With it: `ytdlp=2026.10.26` on all 16; `js=deno/2.9.8` on the 14 with Deno, `js=-` on the two without
- [ ] Each refused link (R rows, and the switch at the api) left one `link refused kind=…` line, with `host=` and `path=` for a link the parser refused, and no `ytdlp=` or `js=`: with the workaround log config; as shipped at b90e462: FAIL (bug 1), fixed in 01f27e7. With it: 0 of 11 carried either. Host refusals said `path=-` (see *Refused links*)
- [x] The queued link job that met the switch (W1) left one worker line, "job … is a link job and links are off, and its audio was never stored"
- [ ] Each outcome is one line, with `detail` and `tail` JSON-quoted: the worker's lines as shipped; the api's with the workaround log config; as shipped at b90e462: FAIL (bug 1), fixed in 01f27e7. With it: 16 of 16 had `detail="…"`. No `tail=` came up: neither ERROR came with the child's stderr
- [x] No line carries a whole pasted link, a `si=` value, a database URL or a storage secret: 0 hits, over every log of the run, the first api's as shipped among them (the workaround only adds lines), for `si=`, pasted forms, `password`, a credentialed `postgresql://` or `X-Amz-Signature`
- [x] No response body and no job row carries yt-dlp's text (`ERROR:`, `[youtube]`, `yt-dlp`, a traceback): 0 hits in every captured response and in the five link rows' `failure_message` and `title`

A retried download failure (D1, D2, D8, D9, D10) also leaves RQ's own ERROR
line, with a traceback, beside our `link fetch failed` line. That is expected,
as it is for every retried job, and is not a second line for one outcome. Its
traceback carries the catalog's message, never yt-dlp's words.

Notes: no download failed in a way RQ retries, so no RQ traceback came up.
The structure stage reads an m4a through librosa's deprecated audioread
fallback (`apps/worker/src/guitarvis_worker/stages/structure.py:145`). It
works today; librosa 1.0 would drop beats and chords for link jobs, not
fail them.
