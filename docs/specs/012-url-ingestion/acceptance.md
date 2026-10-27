# Manual acceptance

**Spec:** [012 — Manual acceptance](spec.md#manual-acceptance)

Checks that cannot be automated honestly, because they ask YouTube. A person
runs each one against real services, from a developer's machine, and records
the result here. Each case names the catalog row it exercises; the expected
reason, status and message are the catalog's. Read the api's and the worker's
log line for each case by eye, and copy it under the case.

Filled in before the PR is merged.

## Setup

- Commit: …
- Machine and OS: …
- yt-dlp version (`uv run python -c "import yt_dlp.version as v; print(v.__version__)"`): …
- Deno version (`deno --version`): …
- Browsers and versions: Chrome …, Firefox …, Safari …
- `make smoke-url` passed on this commit: yes / no

Start the stack with links on: `make services migrate`, then `make api`,
`make worker` and `make web`, each in its own terminal. The api dedupes by
video and keeps old jobs across restarts; to reuse a video, delete its row:

```
docker compose exec postgres psql -U guitarvis -d guitarvis -c "DELETE FROM jobs WHERE source_url LIKE '%<video id>%'"
```

## Links in every form

Use one short video for all of these; each after the first must return the
first's job (200, the same id) without a lookup in the api's log.

- [ ] `https://www.youtube.com/watch?v=ID` reaches the song page, titled with the video's title
- [ ] The job shows *Fetching the audio*, then the four stages
- [ ] The song plays from our stored copy with the tab in sync
- [ ] `https://youtu.be/ID` returns the same job
- [ ] `https://www.youtube.com/shorts/ID` returns the same job (use a Short for its own first run)
- [ ] `https://m.youtube.com/watch?v=ID` returns the same job
- [ ] `…watch?v=ID&t=42s` returns the same job, and the song starts at 0:00
- [ ] `…watch?v=ID&list=PL…` returns the same job, and only that video is fetched
- [ ] `https://youtu.be/ID?si=…` returns the same job, and `si=` appears in no log line

Log lines (api lookup, worker download): …

## Refused links

| Case | Row | Expected | Result | Log line |
|---|---|---|---|---|
| Blank field | client | "Paste a link first.", nothing sent | | |
| `hello there` | client | "That doesn't look like a link.", nothing sent | | |
| A playlist link (`/playlist?list=…`) | R7 | 422 `unsupported_link`, "That link isn't to a single video…" | | |
| A channel link (`/@…`) | R7 | 422 `unsupported_link` | | |
| A Vimeo link | R6 | 422 `unsupported_link`, "We can only fetch songs from YouTube for now…" | | |
| A private video | L1 | 422 `link_unusable`, "That video is private…" | | |
| A removed video | L2 | 422 `link_unusable`, "That video isn't available…" | | |
| An age-restricted video | L4 | 422 `link_unusable`, "That video is age-restricted…" | | |
| A members-only video, if one can be found | L5 | 422 `link_unusable` | | |
| A live stream | L6 | 422 `link_unusable`, "That's a live stream…" | | |
| An upcoming premiere, if one can be found | L7 | 422 `link_unusable`, "That video hasn't premiered yet…" | | |
| A video over ten minutes | L10 | 422 `too_long`, "That video is m:ss long…", in seconds, nothing downloaded | | |

Notes: …

## The switch

- [ ] With `make api GUITARVIS_URL_INGESTION=0`, the link field is gone after a reload, and `curl -X POST localhost:8000/jobs/from-url` answers 403 `links_disabled` (R1)
- [ ] With the field showing, the api restarted with links off, and a link pasted: the field goes, and the page shows "Links are turned off." with the server's message
- [ ] A link job queued, then the worker restarted with `GUITARVIS_URL_INGESTION=0` before it ran: the job fails `links_disabled` with "Links were turned off before this song could be fetched…", not retried (W1)
- [ ] A link job whose download was stored, retried with links off, still runs (stop the worker after *Fetching the audio* ends, restart it with links off)
- [ ] Jobs made from links are still served with links off: the song page and its audio load

Notes: …

## Network and upstream

- [ ] The network cut during a lookup (disconnect, then paste a new link): `fetch_failed` with "We couldn't reach YouTube…" (L13), or "YouTube took too long to answer…" after 30 s (L14); the api stays responsive meanwhile
- [ ] Deno taken off the api's PATH and the api restarted: a new link answers 503 `fetch_failed`, and the log says `kind=misconfigured` at ERROR (L16)
- [ ] Deno taken off the worker's PATH: the worker warns at start, and a queued link job fails `fetch_failed` (D4)
- [ ] Five links pasted at once from five tabs: four are looked up, one answers 503 "We're checking a lot of links right now…" (Q3), if the timing allows

Notes: …

## Playback of what was stored

The stored file is the format the worker's log names (`format=140 ext=m4a`
for most videos; `ext=webm` when a video has no m4a).

- [ ] A stored m4a plays, seeks and loops in Chrome
- [ ] A stored m4a plays, seeks and loops in Firefox
- [ ] A stored m4a plays, seeks and loops in Safari
- [ ] If a video without m4a was found: the stored webm plays in Chrome and Firefox; note Safari's behaviour

Notes: …

## The logs

- [ ] Every case above left exactly one `link fetch failed` or `link fetched` line per lookup or download, at the catalog's level
- [ ] Every line carries `ytdlp=` and `js=`
- [ ] No line carries a whole pasted link, a `si=` value, a database URL or a storage secret
- [ ] No response body and no job row carries yt-dlp's text (`ERROR:`, `[youtube]`, `yt-dlp`, a traceback)

Notes: …
