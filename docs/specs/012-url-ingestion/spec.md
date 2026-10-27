# URL Ingestion — Design

**Date:** 2026-10-26
**Status:** Draft for review
**Parent spec:** [001-guitarvis-design](../001-guitarvis-design/spec.md):
*Two deliberate boundaries*, *Failure handling*, *Risks*, open decisions 11–13
**Builds on:** [005-api-job-queue](../005-api-job-queue/spec.md),
[006-tab-view-sync](../006-tab-view-sync/spec.md) (reasons and their text),
[011-player-redesign](../011-player-redesign/spec.md) (which left the link field to this spec)
**Mockup:** the link field in *Web mockups · WebHome*, in the
[GuitarVis design system](https://claude.ai/artifact/3Zc4v6XxdR3viHReBX6weE)
**Research:** [research.md](research.md)

## Purpose

This is build phase 6. Today a song gets in only if the user has the file.
Most people who want to learn a song have a YouTube link instead. This phase
lets them paste it.

The parent spec already decided the shape. `UrlSource` is one more
`AudioSource`. It must be swappable, testable on its own, and possible to
turn off in config, because it is the part most likely to break and the
part most likely to need removing for legal reasons. Most of this spec covers
the second half of that requirement: how a link job fails, and how links get
turned off.

Success conditions:

1. With links on, pasting a YouTube link on the upload page reaches the song
   page within seconds, titled with the video's title. The job shows
   *Fetching the audio*, then the four stages. The song plays from our stored
   copy with the tab in sync.
2. The same video, pasted again in any form (`youtu.be/…`, `/shorts/…`,
   `&t=`, `&list=`), returns the same job without any request to YouTube.
3. The api refuses a video over ten minutes before downloading any of it.
4. Every row of the failure catalog produces its reason, status, message and
   log line. No response, job row or page ever contains yt-dlp's own text.
5. With links off, the link field is gone, and `POST /jobs/from-url` answers
   403 `links_disabled`. A link job already queued fails with
   `links_disabled` without fetching.
6. Nothing in `make check` touches the network, and `make check` gates all
   of it.
7. Upload jobs are unchanged. Their tests pass unmodified, apart from those
   that pin the list of failure reasons, the one that pins a whole `JobView`
   body (it gains `source_url`), and two that narrow the now-optional
   `upload_key` for the type checker.

## Scope

**In:** `packages/fetch` (link parsing, the yt-dlp child process, the failure
catalog); `POST /jobs/from-url` and `GET /features`; `source_url`, a nullable
`upload_key` and migration `r0002`; `UrlSource` and the worker's download
step with its own progress band; the kill switch `GUITARVIS_URL_INGESTION`,
honoured by api, worker and client; three new failure reasons and their
client text; the link field on the upload page; `make smoke-url`, a live
test outside `make check`; ADR 0010, written by the plan; a manual acceptance
record.

**Out:** sites other than YouTube (each is an addition to the site registry,
with its own spec); playlists, channels, clips and `t=` start times (a link
with `t=` gets the whole video); signing in of any kind — cookies, age-gated
or members-only video, PO tokens, proxies, geo-bypass: we refuse what needs
them rather than get round them; processing part of a long video; previewing
a video before sending; the rest of the WebHome mockup and the processing
view; a retention policy (open decision 13) and egress controls at hosting
(open decision 12); a switch that works without a restart; cancelling jobs.

`tabdoc.py` doesn't change. The api schema is regenerated.

## Decisions and where they came from

| # | Decision | Why |
|---|---|---|
| D1 | The api validates and looks up the link; the worker downloads | Given. The api stays thin, with no ML imports and no `guitarvis_worker` (invariant 3). |
| D2 | The api refuses a video over ten minutes from its metadata, before queueing | Given. A three-hour mix is refused in seconds, before any of it is fetched. The worker checks again (*Three length checks*). |
| D3 | yt-dlp, with ffprobe as today | Given. Run as a library inside a child process of our own (*Where yt-dlp runs*). |
| D4 | One setting turns links off at every step | Given. Off by default (*The kill switch*). |
| D5 | Every failure is catalogued: where it is caught, reason, status, message, log, retry, test | Given (*Failure catalog*). |
| D6 | Supported sites are code, not config. The user's string never reaches the network | Each site needs a parser that turns any form of its links into one canonical URL built from a validated id. Config could add a host, but not a parser. |
| D7 | A separate route, `POST /jobs/from-url`, with a JSON body | One body type per route, and the feature comes out in one line. |
| D8 | Dedupe by video identity; cache by downloaded bytes | A repeat link costs no request to YouTube, and the stem always comes from the exact bytes we play. |
| D9 | The reason says what to do, the message says why, the logged kind says what broke | Three new reasons rather than fifteen. |

## Approach

### Shape of the change

```
packages/fetch/src/guitarvis_fetch/   new workspace member
  links.py     parse, refuse, canonicalize. Pure, stdlib only
  catalog.py   FetchKind → reason, status, message, retry, log level
  fetcher.py   UrlFetcher protocol, VideoInfo, FetchError; ChildFetcher
  child.py     the only module that imports yt_dlp; runs as a child process
packages/core  FailureReason + link_unusable, links_disabled;
               PipelineError gains `retryable`
packages/jobs  Settings.url_ingestion; source_url; upload_key nullable;
               JobStore.attach_upload; migration r0002
apps/api       routes_links.py: POST /jobs/from-url, GET /features;
               audio/mix 409 until stored; HttpReason.UNSUPPORTED_LINK;
               JobView.source_url
apps/worker    ingest.py: UrlSource; runner.py: the download step
web/src        api/client.ts, api/messages.ts, pages/UploadPage.tsx,
               pages/progress.ts; vite.config.ts proxies /features
```

`guitarvis_fetch` is its own package for the reason 001 gives: the part most
likely to break or be removed is walled off. Only the api and the worker
depend on it. Removing links for good means deleting it, one router include,
and one branch in the worker.

### Where yt-dlp runs

yt-dlp is pure Python, and so are its default extras apart from two small C
helpers (brotli, pycryptodomex). None of them is torch, demucs, basic_pitch,
librosa or numpy, so **importing yt-dlp into the api would not break invariant
3**. It still isn't imported by the api, or by the worker's own process. It
runs only in a child process, `python -I -m guitarvis_fetch.child`. The child
imports it as a library and writes JSON lines to stdout: progress fractions,
then either one result or one classified error.

- **A hard deadline.** A library call running in a thread can't be stopped,
  and the api must get its request thread back. That is why
  `PROBE_TIMEOUT_SEC` exists for ffprobe. A child process can be killed: we
  kill its whole process group, which includes the JavaScript runtime yt-dlp
  starts.
- **Containment.** A hang, crash or memory blow-up in the part most likely to
  break takes down one child, not the api or a worker. The child runs with
  every `GUITARVIS_*` variable removed from its environment, so it can't read
  the database URL or the storage secret.
- **Typed failures.** Inside the child, yt-dlp's exception types are visible
  (`GeoRestrictedError`, `HTTPError.status`, the `ExtractorError` inside a
  `DownloadError`), and the child classifies them before anything crosses the
  process boundary. Running the yt-dlp command line instead would leave us
  parsing English text on stderr.
- **No stray config.** The yt-dlp command line reads `yt-dlp.conf` from the
  user's and system config directories, so a file on some host could quietly
  add cookies or a proxy. The library reads no config files, but it does load
  plugins, which are code, from the same directories when a `YoutubeDL` is
  made; the child sets `YTDLP_NO_PLUGINS` to stop that (both confirmed in
  2026.10.26: research.md).

The cost is starting an interpreter for each lookup: a few hundred
milliseconds, against the one to five seconds the lookup itself takes.

`guitarvis-fetch` depends on `yt-dlp[default]`, whose extras include
`yt-dlp-ejs`, which YouTube's player challenges now need. It is a plain
dependency, not an optional extra. The `ml` extra exists because torch is
gigabytes; yt-dlp is a few megabytes. An optional extra would also add a
second off-switch ("is it installed?") alongside the setting. The lock pins
the version. Since 2025.11.12, yt-dlp needs an external JavaScript runtime
for full YouTube support, and Deno is the only one enabled by default
(research.md). So Deno becomes a system dependency of every host that
fetches, like ffmpeg. The child names the runtime explicitly and sets
`remote_components=[]`, so no code is downloaded at run time.

### Links: parse, refuse, canonicalize

`links.parse(raw) -> Link(site, video_id, canonical_url)` is pure and does no
I/O. On refusal it raises `LinkRefused(kind)`. The rules:

- Trim the string. Refuse it if it is blank, over 2,048 characters, or has
  whitespace or control characters inside.
- A missing scheme means `https://`. Any scheme other than http or https is
  refused.
- Refuse a link with user info, a port, an IP address as host, or a
  non-ASCII host. Lowercase the host and drop any trailing dot.
- The host must exactly match one of the site's hosts. For YouTube:
  `youtube.com` bare or with `www.`, `m.` or `music.`;
  `youtube-nocookie.com` bare or with `www.`; and `youtu.be`.
  `youtube.com.example.net` doesn't match.
- The path must name one video: `/watch?v=ID`, `/shorts/ID`, `/live/ID`,
  `/embed/ID`, `/v/ID`, or `youtu.be/ID`, where ID matches
  `[A-Za-z0-9_-]{11}`. Anything else on a supported host (a playlist, a
  channel, search, a clip) is refused as `not_a_video`.

The canonical URL is built fresh, never edited from the input:
`https://www.youtube.com/watch?v=ID`. Every other parameter is dropped,
including `t=`, `list=`, and `si=`, the share id that links a URL to the
account that shared it. The canonical URL is what yt-dlp receives and what
the job stores. The user's original string is never passed on, logged or
stored.

### The api: `POST /jobs/from-url`

The body is JSON, `{"url": "…"}`. Checks run cheapest first, and nothing
touches the network until step 5:

1. **Switch.** If links are off, answer **403 `links_disabled`**.
2. **Parse.** A refused link, a body that isn't JSON, or a missing or
   too-long `url` all get **422 `unsupported_link`**. `UploadSizeLimit` caps
   the body at 16 KB (413).
3. **Dedupe.** The key is `sha256("youtube:" + id)`. If a live job has that
   key, reconcile it as uploads do and answer **200** with it, whatever form
   the link took. A repeated link costs YouTube nothing, which also keeps us
   further from its rate limits.
4. **Limit.** Count this address's active jobs *before* any outbound
   request, so a client at its limit can't make us fetch: **429
   `too_many_jobs`**.
5. **Lookup.** `fetcher.lookup(link)` runs in a child with a 30 s deadline.
   Each api process runs at most four lookups at once. A fifth gets **503
   `fetch_failed`** straight away instead of waiting for a thread.
6. **Check.** Refuse live, upcoming and just-ended streams, and videos with
   no duration in their metadata. `check_duration` refuses anything over ten
   minutes: **422 `too_long`**.
7. **Create** the row with `create(..., max_active=...)` and `ON CONFLICT`,
   as for uploads. It holds `source_url`, the metadata's title (control
   characters removed, at most 200 characters, "Untitled" if empty) and
   duration, and no `upload_key`. Answer **202** with `Location`, or **200**
   if the same video was submitted at the same moment.
8. **Enqueue** as for uploads. On failure, mark the row failed with
   `internal` and answer **503**.

The response is a `JobView`, exactly as for an upload. This is its own route,
not a second body type on `POST /jobs`, because the existing validation
handler assumes multipart. A separate route also means the feature can be
removed with one line.

`GET /features` answers `{"url_ingestion": true}` (or false), from the api's
own setting. Its response model and the request model join `JobView` and
`ErrorBody` in `api.schema.json`, so `make schema` regenerates
`web/src/types/api.ts`. Nobody edits that file by hand.

### The job record

Migration `r0002`:

| Column | Change | For a link job |
|---|---|---|
| `content_hash` | none | the dedupe key, `sha256("youtube:" + id)`; still the hash of the bytes for an upload |
| `source_url` | new, text, null | the canonical URL; null for an upload |
| `upload_key` | becomes nullable | null until the worker stores the download at `uploads/{sha256 of bytes}{ext}` |
| `title`, `duration_sec` | none | from the lookup; the worker later replaces the duration with ffprobe's |

A check constraint, `upload_key IS NOT NULL OR source_url IS NOT NULL`, means
every row has a way to get its audio. `JobStore.attach_upload(job_id,
upload_key, duration_sec)` is a new conditional write on running rows only,
added to the shared contract suite for both stores. `content_hash` keeps its
name: renaming it would touch every store method and the dedupe index for no
change in behaviour. Its docstring and 005's table will say what it holds for
each kind of job.

**The tab document.** `source.title` is the video's title.
`source.duration_sec` is ffprobe's reading of our stored file.
`source.audio_url` is `/jobs/{id}/audio/mix`, which redirects to our stored
copy (the runner already passes this). It is never a YouTube URL: those
expire within hours, only work for the address that requested them, and the
tab is timed against the exact bytes we separated.

The original link is **not** put in the document. It describes the job, not
the tab. A new field would also be additive for in-repo clients but breaking
for any validator that bundles the committed schema (see the `tab-document`
skill). Instead, `JobView` gains `source_url`. `GET /jobs/{id}/audio/mix`
answers **409 `not_ready`** while `upload_key` is null, so it never presigns
a key that doesn't exist.

### Caching and dedupe

**Dedupe is by video**, checked before any lookup. The alternative, deduping
by the downloaded bytes, was rejected: it needs the download first, and it
would miss whenever YouTube serves a re-encode. **Stage caching stays by
content.** `CacheKeys` takes the hash of the downloaded bytes (the hash in the
upload key), never the video id. A stem cached from one download then can
never be paired with the mix from another, whose encoder delay could shift the
tab tens of milliseconds off the audio. A link and an upload of the same bytes
share files and cache entries, as two identical uploads do.

**`CACHE_VERSION` is not bumped:** no stage's output changes for the same
input. The download isn't a cached stage. It is stored once, like an upload,
and a retry reuses it. A dedupe hit can return a job whose video has since
been taken down, because we keep our copy. That belongs to open decision 13,
and `source_url` is what makes it answerable.

### The worker: fetching a link

`process_job` is unchanged until `_run` gets the audio:

1. **Already stored** (`upload_key` set): this is a retry after a download
   that was kept. Fetch the blob as for an upload. No request goes to
   YouTube, so the switch doesn't apply.
2. **Switch off:** fail with `links_disabled`, no retry.
3. **Fetch.** `UrlSource(link, work_dir, fetcher, max_bytes=…, progress=…)`
   implements `AudioSource`. Its `fetch()` runs the child's `download` in the
   job's temporary directory with a 300 s deadline. It then probes the result
   with `probe_duration` and `check_duration`, as `UploadSource` does, and
   returns `IngestedAudio`. The child fetches the metadata again and repeats
   step 6's checks before downloading anything. It can't reuse the api's
   format URLs: they are bound to the api's address and expire, and the
   worker may be on another host.
4. **Store.** Hash the file, put it at `uploads/{hash}{ext}` unless it is
   already there, then `attach_upload` the key and ffprobe's duration. If the
   row is no longer running, log and stop, as a late `succeed` does.
5. **Run the pipeline** with `CacheKeys(hash)`, exactly as for an upload.

`UrlFetcher` is a protocol with `lookup` and `download`. `ChildFetcher` is
the yt-dlp implementation; tests pass in a fake. `WorkerDeps` gains
`fetcher: UrlFetcher | None`, which is `None` when the switch is off.

**Progress.** The download is a stage of its own, `download`, and fills 0–5%
of a link job's progress from the child's byte fraction. The pipeline's
0–100 is then scaled onto 5–100. A ten-minute song downloads in seconds and
separates in minutes, so 5% is honest. Upload jobs' percentages don't change,
and rows are written only when the whole percent rises, as now.

**Retries.** `PipelineError` gains `retryable`, defaulting to today's rule
(only `internal` retries). The runner retries whatever is retryable. On the
final attempt it records the error's own reason and message, unless the
reason is `internal`. A fetch that keeps failing therefore ends as
`fetch_failed` with its own text, not "something went wrong on our side".
Network errors, timeouts and unclassified errors are retryable. Rate limiting
is not, because retrying at 10 and 60 s only extends the limit.

### Three length checks

1. **The api, from metadata**, enforces D2. It takes seconds and downloads
   nothing.
2. **The child, from fresh metadata, before downloading.** This costs
   nothing, since the download needs that metadata anyway, and a video can
   change while queued (a premiere goes live, a video is replaced). Our code
   makes this check rather than yt-dlp's `match_filter`, which skips a video
   silently instead of failing.
3. **ffprobe, after the download**, is the check that counts. Metadata is
   rounded and can be wrong, the pipeline runs on the file, and the worker
   must not trust its caller (005).

Missing duration metadata is refused at checks 1 and 2 rather than left to
check 3. The size cap would stop a three-hour download, but only after
150 MB of it had arrived.

### Fetching safely

The api and the worker both make outbound requests on user input. The
defences, strongest first:

- **The user never names a host.** Only a canonical URL built from an
  11-character id reaches yt-dlp. No YouTube id can spell
  `http://169.254.169.254/` or `http://localhost:6379/`.
- **yt-dlp is held to the site.** `allowed_extractors` lists only YouTube's
  extractors, so the generic extractor, which fetches any URL, can't run.
  Also: `noplaylist`, no cookies, `geo_bypass` off, no post-processors,
  `socket_timeout` 15 s, low internal retry counts (RQ retries the job), and
  a fixed output template, `source.%(ext)s` in the job's temporary
  directory, so a title never becomes a path.
- **The media URL is checked before download.** Formats are audio-only over
  plain HTTPS (`bestaudio[ext=m4a][protocol=https]/bestaudio[protocol=https]`),
  so the download is one GET. Its host must end in `.googlevideo.com` and
  resolve only to public addresses (`is_global`). Anything else is refused
  before connecting.
- **Size.** The cap is `GUITARVIS_MAX_UPLOAD_MB` (150), the largest audio
  the system stores from anyone. It is enforced three times: yt-dlp's
  `max_filesize`, our progress hook counting bytes (for responses with no
  length), and the file's size on disk.
- **Time and concurrency.** 30 s per lookup and 300 s per download, after
  which the child's process group is killed. The job timeout remains the
  outer bound. At most four lookups per api process, and one download per
  job.

What remains: redirects that yt-dlp follows mid-download, and DNS answers
that change between our check and its connect, are not re-checked. Closing
that needs egress rules where the worker runs, a hosting question (open
decision 12).

### The kill switch

`GUITARVIS_URL_INGESTION` is a boolean. `Settings` learns to parse booleans:
`1`/`true`/`on` and `0`/`false`/`off`, with anything else failing at start,
as a bad integer does. It is **off by default**, so a deployment that hasn't
decided takes no ToS risk. `make api` and `make worker` turn it on for local
development.

| Where | Off means |
|---|---|
| api | `POST /jobs/from-url` answers 403 `links_disabled` before parsing; `GET /features` says false. Existing link jobs, documents and audio are still served: the switch stops fetching, not serving (retention is decision 13) |
| worker | A link job with no stored audio fails `links_disabled`, not retried. A job whose download is already stored runs, since it fetches nothing |
| client | Reads `/features` and hides the link field unless the answer is true, including when the call fails. A 403 `links_disabled` after the field was shown removes it and shows the message |

The setting is read at start, like every other, so flipping it means
restarting the api and the workers, which takes seconds. A job that was
mid-download when its worker restarted is retried by RQ, and the retry fails
with `links_disabled`. The api and the worker are configured separately, and
each enforces its own step.

### Failure vocabulary

| Reason | Used for | Headline (client) | Action (client) |
|---|---|---|---|
| `links_disabled` *(new)* | job, request | Links are turned off. | Upload the audio file instead. |
| `unsupported_link` *(new, `HttpReason`)* | request | We can't use that link. | Paste a link to a single YouTube video, or upload the audio file. |
| `link_unusable` *(new)* | job, request | We can't use that video. | Try a different link, or upload the audio file. |
| `fetch_failed` | job, request | We couldn't fetch that audio. | Try again later, or upload the audio file. *(action changed)* |
| `too_long` | job, request | That recording is too long. | Try a single song, up to ten minutes long. *(action changed)* |

The client shows the headline and action, plus the server's message as
detail. It already does this for failed jobs, and the upload page now does it
for refused links too. A reason per cause (private, region-locked,
age-restricted, live and so on) was rejected: every client would need text
for each, and most of that text would be the same. The cause goes in the
message, and the finer `FetchKind` goes in the log.

`FailureReason` isn't part of the tab document, so only `api.schema.json` and
`api.ts` change. `messages.ts`'s `Record<Reason, …>` refuses to compile until
the new reasons have text, which is the existing mechanism. An older client
reads an unknown reason as `internal` and keeps the server's message
(`knownReasons`). The vocabulary grows from nine values to twelve.

**The rule:** yt-dlp's text, tracebacks and exception names never reach a
response or a row. Messages come from the catalog, keyed by kind. yt-dlp's
own words go only to the log.

### Failure catalog

Status is HTTP for the api, *job* for a worker failure recorded on the row.
Log *+tail* adds the end of the child's stderr. Retry: *RQ* is automatic
(three attempts, then the reason shown); *later* means the same link may
work later; *no* means it won't. Tests are named as in *Testing*.
`MSG_INTERNAL` is "Something went wrong on our side. Try again later."

**R. The request, in the api, before any network**

| # | Failure | Caught by | Reason · status | Message | Log | Retry | Test |
|---|---|---|---|---|---|---|---|
| R1 | Links switched off | route, first | `links_disabled` · 403 | Links are turned off on this server. Upload the audio file instead. | INFO | later | route |
| R2 | Body not JSON; `url` missing, not a string, or over 2,048 characters | request validation | `unsupported_link` · 422 | Send the link as JSON, in a field named `url`. | INFO | no | route |
| R3 | Body over 16 KB | `UploadSizeLimit` | `too_large` · 413 | That request is too large. Send only the link. | — | no | route |
| R4 | Not a link: blank, whitespace or control characters inside, no host | `links.parse` | `unsupported_link` · 422 | That doesn't look like a link. Copy the video's address from your browser and paste it here. | INFO | no | links |
| R5 | Scheme other than http or https | `links.parse` | `unsupported_link` · 422 | Only web links (https://…) can be used. Copy the video's address from your browser. | INFO | no | links |
| R6 | Host not a supported site: includes user info, a port, an IP address, a lookalike domain | `links.parse` | `unsupported_link` · 422 | We can only fetch songs from YouTube for now. For anything else, upload the audio file. | INFO | no | links |
| R7 | Supported site, but not one video: playlist, channel, search, clip | `links.parse` | `unsupported_link` · 422 | That link isn't to a single video. Open the video itself and copy its address. | INFO | no | links |

**Q. Dedupe and limits, in the api, before any network**

| # | Failure | Caught by | Reason · status | Message | Log | Retry | Test |
|---|---|---|---|---|---|---|---|
| Q1 | A live job exists for this video (not a failure) | dedupe | — · 200, that job | — | — | — | route |
| Q2 | This address is at its active-job limit | count | `too_many_jobs` · 429 | *(existing)* You already have N songs processing. Wait for one to finish, then try again. | — | later | route |
| Q3 | Four lookups already running in this process | semaphore | `fetch_failed` · 503 | We're checking a lot of links right now. Try again in a minute. | WARNING | later | route |

**L. The lookup, in the api: a child process, over the network**

| # | Failure | Caught by | Reason · status | Message | Log | Retry | Test |
|---|---|---|---|---|---|---|---|
| L1 | Private video | classify | `link_unusable` · 422 | That video is private. Try a different link, or upload the audio file. | INFO | no | classify, route |
| L2 | Removed, never existed, account terminated, blocked on copyright grounds | classify | `link_unusable` · 422 | That video isn't available. It may have been removed. Check the link, or upload the audio file. | INFO | no | classify, route |
| L3 | Region-locked | classify (`GeoRestrictedError`) | `link_unusable` · 422 | That video can't be watched from where our server is. Try a different link, or upload the audio file. | INFO | no | classify, route |
| L4 | Age-restricted, or sign-in required | classify | `link_unusable` · 422 | That video is age-restricted, and we don't sign in to YouTube. Upload the audio file instead. | INFO | no | classify, route |
| L5 | Members-only or paid | classify, `availability` | `link_unusable` · 422 | That video is only for channel members or paying viewers. Upload the audio file instead. | INFO | no | classify, route |
| L6 | Live now | `live_status` is `is_live` | `link_unusable` · 422 | That's a live stream. Once it has ended and been saved as a video, try the link again. | INFO | later | route |
| L7 | Upcoming, or premiere not yet started | classify (YouTube's reason; there are no formats, so no metadata comes back), or `is_upcoming` | `link_unusable` · 422 | That video hasn't premiered yet. Try the link again once it has. | INFO | later | classify, route |
| L8 | Stream just ended, still processing | `post_live` | `link_unusable` · 422 | That stream has only just ended, and YouTube is still processing it. Try the link again in a few hours. | INFO | later | route |
| L9 | No duration in the metadata | step 6 | `link_unusable` · 422 | We couldn't tell how long that video is, so we didn't fetch it. Upload the audio file instead. | WARNING | no | route |
| L10 | Over ten minutes | `check_duration` | `too_long` · 422 | That video is {length} long. The limit is 10 minutes: try a link to a single song. | INFO | no | route |
| L11 | No audio-only format, without challenge-solving warnings | classify | `link_unusable` · 422 | That video has no audio we can use. Try a different link, or upload the audio file. | WARNING | no | classify |
| L12 | Rate-limited: HTTP 429, or "Sign in to confirm you're not a bot" | classify | `fetch_failed` · 503 | YouTube is limiting how often we can fetch right now. Try again later, or upload the audio file. | WARNING | later | classify, route |
| L13 | Network: DNS failure, connection refused or reset, TLS error, YouTube 5xx | classify | `fetch_failed` · 502 | We couldn't reach YouTube. Try again in a few minutes, or upload the audio file. | WARNING | later | classify, route |
| L14 | Lookup past its 30 s deadline | `ChildFetcher` (kills the process group) | `fetch_failed` · 504 | YouTube took too long to answer. Try again in a few minutes, or upload the audio file. | WARNING | later | fetcher, route |
| L15 | Extractor broken: "Unable to extract", "Unsupported URL" for our own canonical link, challenge solving failed, a format error with challenge warnings | classify | `fetch_failed` · 502 | We can't fetch from YouTube at the moment. Upload the audio file instead, or try the link again tomorrow. | ERROR +tail | later | classify |
| L16 | Misconfigured: no JavaScript runtime, or yt-dlp won't import | the child's start-up check | `fetch_failed` · 503 | *(as L15)* | ERROR | later | fetcher |
| L17 | A yt-dlp error the classifier doesn't recognise | classify (fallback) | `fetch_failed` · 502 | We couldn't fetch that video. Try again in a few minutes, or upload the audio file. | ERROR +tail | later | classify |
| L18 | Child crashed, exited without a result, or wrote garbage | `ChildFetcher` | `internal` · 500 | `MSG_INTERNAL` | ERROR, exit code +tail | later | fetcher |

**E. Queueing, in the api**

| # | Failure | Caught by | Reason · status | Message | Log | Retry | Test |
|---|---|---|---|---|---|---|---|
| E1 | Same video submitted at the same moment (not a failure) | `create`, `ON CONFLICT` | — · 200, the winner | — | — | — | route, store |
| E2 | Address limit passed in a race | `create(max_active)` | `too_many_jobs` · 429 | *(as Q2)* | — | later | route |
| E3 | Enqueue raises | route | `internal` · 503; row failed | *(existing)* We could not queue that song. Try again in a minute. | ERROR | later | route |
| E4 | Postgres unreachable | unhandled-error handler | `internal` · 500 | `MSG_INTERNAL` | ERROR | later | *(existing)* |

**W. The worker, before fetching**

| # | Failure | Caught by | Reason · status | Message | Log | Retry | Test |
|---|---|---|---|---|---|---|---|
| W1 | Links switched off, audio not yet stored | runner | `links_disabled` · job | Links were turned off before this song could be fetched. Upload the audio file instead. | INFO | no | worker |
| W2 | The video changed in the queue: any of L1–L11 in fresh metadata | child | as L1–L11 · job | as L1–L11 | as L1–L11 | no | worker |

**D. The download, in the worker: a child process, over the network**

| # | Failure | Caught by | Reason · status | Message | Log | Retry | Test |
|---|---|---|---|---|---|---|---|
| D1 | Network | classify | `fetch_failed` · job | *(as L13)* | WARNING | RQ | worker |
| D2 | Past its 300 s deadline | `ChildFetcher` | `fetch_failed` · job | Fetching that video took too long. Try again in a few minutes, or upload the audio file. | WARNING | RQ | fetcher, worker |
| D3 | Rate-limited | classify | `fetch_failed` · job | *(as L12)* | WARNING | later | worker |
| D4 | Extractor broken or misconfigured | classify | `fetch_failed` · job | *(as L15)* | ERROR +tail | later | worker |
| D5 | Media URL refused: not HTTPS, host off the site's list, or resolves to a non-public address | child, before connecting | `fetch_failed` · job | *(as L17)* | ERROR (security) | no | classify, worker |
| D6 | Over the 150 MB size cap | `max_filesize`, progress hook, file size | `link_unusable` · job | That video's audio is larger than we accept. Try a shorter video, or upload the audio file. | WARNING | no | fetcher, worker |
| D7 | Download produced no file, or an empty one | child | `link_unusable` · job | *(as L11)* | WARNING | no | worker |
| D8 | Disk full, or another local I/O error | child | `internal` · job | `MSG_INTERNAL` | ERROR +tail | RQ, then `internal` | worker |
| D9 | Child crashed | `ChildFetcher` | `internal` · job | `MSG_INTERNAL` | ERROR +tail | RQ, then `internal` | fetcher, worker |
| D10 | A yt-dlp error the classifier doesn't recognise | classify | `fetch_failed` · job | *(as L17)* | ERROR +tail | RQ | worker |

**P. After the download, in the worker**

| # | Failure | Caught by | Reason · status | Message | Log | Retry | Test |
|---|---|---|---|---|---|---|---|
| P1 | ffprobe can't read the file, or reads zero or NaN length | `UrlSource`, re-raising from `probe_duration`/`check_duration` | `link_unusable` · job | The audio we fetched from that video couldn't be read. Try a different link, or upload the audio file. | WARNING, with format, extension and ffprobe's tail | no | worker |
| P2 | ffprobe's length is over ten minutes | `check_duration` | `too_long` · job | *(existing)* That recording is longer than 10 minutes. Try a single song rather than a full set. | INFO, with metadata length vs probed length | no | worker |
| P3 | ffprobe not installed | `probe_duration` | `internal` · job | `MSG_INTERNAL` | ERROR | RQ, then `internal` | *(existing)* |

**S. Storing the download, in the worker**

| # | Failure | Caught by | Reason · status | Message | Log | Retry | Test |
|---|---|---|---|---|---|---|---|
| S1 | Saving to object storage fails | `blobs.put_file` | `internal` · job | `MSG_INTERNAL` | ERROR | RQ (the retry downloads again), then `internal` | worker |
| S2 | Recording the key fails | `attach_upload` raises | `internal` · job | `MSG_INTERNAL` | ERROR | RQ, then `internal` | worker |
| S3 | Row no longer running when the key is recorded (reconciliation failed it) | `attach_upload` returns false | — (already failed) | — | WARNING "dropping" | — | worker, store |

**G. Reading, in the api**

| # | Failure | Caught by | Reason · status | Message | Log | Retry | Test |
|---|---|---|---|---|---|---|---|
| G1 | `GET /jobs/{id}/audio/mix` before the audio is stored | route | `not_ready` · 409 | The audio is not ready yet. Poll the job until it succeeds. | — | later | route |

From separation onwards, failures are handled exactly as today (001, 005).

### Logging

One line per outcome, at the catalog's level:

```
link fetch failed kind=private phase=lookup site=youtube video=dQw4w9WgXcQ
  job=- attempt=- elapsed=1.8s ytdlp=2026.10.01 js=deno/2.5.4 detail="…"
```

- `detail` is yt-dlp's message, cut to 500 characters. ERROR lines add the
  last 2 KB of the child's stderr.
- **INFO** means the link itself is the problem. **WARNING** means upstream
  trouble that should pass. **ERROR** means something for us to fix: a broken
  extractor, a missing runtime, a crash, or a refused media host.
- A refused link is logged as its kind, host and first path segment. The
  full string is never logged, because it can carry the sharer's `si=` id.
- Successes are logged too (`link fetched … format=140 ext=m4a bytes=…`). A
  broken extractor then shows up as a change in the ratio of ERROR lines to
  fetched lines. Format ids show how often we fall back from m4a.
- `ytdlp=` and `js=` are on every line, so "it broke on Tuesday" can be traced
  to a version.

### Web client

**Upload page.** The layout follows the WebHome mockup: under the drop zone,
an "or paste a link" divider, a URL field with the link icon and `https://…`,
and a *Get tab* button. It shows only when `/features` says links are on.

- **Before sending:** a blank field shows "Paste a link first." Text that
  isn't an `http(s)` URL (after adding a missing `https://`) shows "That
  doesn't look like a link." Both appear under the field (`aria-invalid`,
  `aria-describedby`), and nothing is sent. Which hosts are supported is the
  api's call, so the client keeps no list that could drift.
- **While sending:** "Checking the link…". The drop zone and the field are
  disabled, so only one thing is sent at a time. Leaving the page aborts the
  request.
- **After:** 200 or 202 goes to the song page. An error shows `Failure` with
  the reason and the server's message as detail. `links_disabled` also
  removes the field. (The mockup shows every link failure as
  `fetch_failed`.)

**Song page.** `stageText` gains `download: "Fetching the audio"`. The title
is the video's from the first poll, so the user sees at once whether it is
the right song. A failed link job uses the same `Failure` component.

**Client.** `createJobFromUrl(url, signal)` posts JSON with `fetch`, since
there is no upload progress to report. `getFeatures()` reads `/features`.
`vite.config.ts` proxies `/features`, and hosting must route it alongside
`/jobs` and `/health`.

### Testing

Nothing in `make check` makes a network request.

- **links:** a table of forms. Each accepted shape maps to an id and a
  canonical URL, and each refusal to its kind. Includes lookalike hosts, user
  info, ports, IP literals, `xn--` hosts, backslashes, 2,049 characters,
  `javascript:` and `file:`.
- **classify:** the child's classifier against yt-dlp's exception types
  (built offline) and messages recorded from real failures (a fixture file).
  An unknown message maps to `unknown`. A format error that comes with
  challenge warnings maps to `extractor_broken`, not `no_audio`. The yt-dlp
  options are a pure function, asserted in full: extractors, playlists off,
  no cookies, format, template, size cap, runtime, no remote components.
- **fetcher:** `ChildFetcher` against a fake child module. Covers progress,
  results, each error kind, garbage on stdout, a crash, a hang killed at its
  deadline along with its process group, and no `GUITARVIS_*` variables in
  its environment.
- **catalog:** every `FetchKind` has an entry, and no message contains
  "yt-dlp", "ERROR:", "Traceback" or "[youtube]".
- **route:** `TestClient` with in-memory stores and a fake fetcher, covering
  every R, Q, L, E and G row. Dedupe and the limit make no lookup (the fake
  records its calls). Also: the deadline, the fifth concurrent lookup,
  `/features` both ways, and a sentinel string in a fake failure's detail
  that reaches the log but never the body.
- **worker:** `process_job` with a fake fetcher. Covers success (a
  content-addressed key, the duration replaced, progress moving from
  `download` into 5–100), and every W, D, P and S row, retried or not as the
  catalog says. The final attempt keeps `fetch_failed`. Also: the switch off,
  with and without stored audio; a retry that finds the download stored and
  never calls the fetcher; and the sentinel never reaching the row.
- **store:** `attach_upload` and the nullable `upload_key` in the shared
  contract suite, plus `r0002` going up and down.
- **boundaries:** `test_boundaries.py` checks that the api never imports
  `yt_dlp`, and that importing the app doesn't load it. This is this spec's
  rule, not invariant 3's.
- **web:** `client.test.ts` covers both calls and their errors. `UploadPage`
  (jsdom) covers: the field hidden when `/features` is false or fails; the
  client-side hints sending nothing; each reason's text and detail; and
  `links_disabled` removing the field. `progress.test.ts` covers `download`.
- **integration** (`@requires_services`, so a skip locally and a failure in
  CI under `GUITARVIS_REQUIRE_SERVICES=1`): the end-to-end test gains a link
  job, with the fake fetcher on real Postgres, Redis and RustFS.

**Live, never in `make check`:** `make smoke-url` runs a test that skips
unless `GUITARVIS_LIVE_FETCH=1`. It looks up and downloads one short Creative
Commons video, runs ffprobe on it, and prints the messages yt-dlp gives for a
private and a removed video so the classifier's fixtures can be refreshed. Run
it after bumping yt-dlp and before a release. It can't gate CI: it depends on
YouTube's behaviour that day, and from a CI runner's datacenter address
YouTube usually demands sign-in.

### Manual acceptance

`acceptance.md` in this folder: links in each form, including `t=` and
`list=`; a private, a removed, a live and a too-long video, and a playlist
link; the switch turned off with a job queued; the network cut during a
lookup; a stored m4a playing in Chrome, Firefox and Safari; and the log line
for each case, read by eye.

## Rejected alternatives

- **yt-dlp inside the api's and worker's own processes.** One process fewer,
  but a thread can't be killed, so a hung lookup keeps an api thread as long
  as it likes. A crash or leak would be the api's, and yt-dlp would run
  beside the database secret.
- **The yt-dlp command line as the child.** The hard timeout comes free. But
  failures arrive as English on stderr, progress arrives as a drawn bar, and
  it reads config files from the host.
- **The api checking syntax only, with the worker doing everything.** A
  thinner api, but a three-hour video waits out the queue before it is
  refused. Ruled out by D2.
- **Handing the api's format URLs to the worker.** Saves a second
  extraction, but those URLs are bound to the api's address and expire, and
  the worker may be on another host.
- **A host allowlist in config.** Adding a site would need no deploy, but a
  host without a parser means handing a raw user URL to yt-dlp, which is the
  attack surface D6 removes.
- **A `url` field on `POST /jobs`.** One route, but two body types that
  can't share a schema or a validation handler, and removing links would mean
  editing the upload path.
- **One reason per cause.** Precise, but every client needs text for each,
  and most would say the same thing.
- **Caching stages by video.** Simpler keys, but a stem could meet a mix
  from a different download, with a different encoder delay.
- **Re-encoding every download to one format.** Uniform files, but it costs
  time and quality on every job to cover a rare fallback.
- **On by default.** Less friction locally, but an undecided deployment
  would be fetching from YouTube. The Makefile carries the local default
  instead.
- **A switch that needs no restart** (a database row or Redis key). Faster,
  but it needs an admin surface and auth, which don't exist (open decision
  11).
- **An optional `links` extra, like `ml`.** Adds an "installed?" state beside
  the setting, to save a few megabytes.
- **Playing YouTube's stream directly.** Nothing to store, but its URLs
  expire and are bound to an address, the browser can't fetch them
  cross-origin, and the tab is timed against our bytes.

## Consequences

- **yt-dlp needs bumping.** YouTube changes break it often, and fixes follow
  within days. The procedure: `uv lock --upgrade-package yt-dlp`, then
  `make smoke-url`, commit, deploy. The switch is the stopgap until then.
  CLAUDE.md's *Things that will bite you* gains this, and Deno.
- **Deno on every host that fetches** (api and worker), like ffmpeg. CI
  doesn't need it.
- **The api makes outbound requests for the first time**, so its host needs
  egress to YouTube. `/health` doesn't check YouTube: YouTube being down
  doesn't mean the api is down.
- Housekeeping: a new workspace member (and `PY_SOURCES` entry); readers of
  `upload_key` (`get_mix`, the runner) handle null; the `pipeline-stage`
  skill's failure section and 001's reason list are amended for
  `retryable`; nine reasons become twelve in `CONVENTIONS.md`,
  `test_contracts.py` and `messages.ts`; `/features` is a third path hosting
  must route; the Makefile's `api` and `worker` set the switch, and
  `smoke-url` is new.
- ADR 0010 records D3 and D4: yt-dlp as a library in a child process, behind
  a switch that is off by default.
- **Retention is more urgent.** An upload is a file the user already had.
  With a link, the server fetches the audio itself. Open decision 13 (audio
  kept indefinitely) now covers that too. `source_url` makes a takedown
  answerable: one query finds every job made from a video, and its blobs can
  be deleted. Whether `source_url` itself should expire belongs to decision 13.
- There is no `CACHE_VERSION` bump and no tab-document change.

## Risks

- **Terms of service, and the law.** Fetching from YouTube breaks its terms
  of service. The parent spec accepted that knowingly for v1, and it still
  holds. The exposure isn't only contractual. In 2020 the RIAA argued that
  youtube-dl's handling of YouTube's player signatures circumvented a
  technical protection measure. GitHub reinstated the project, and the
  argument was never tested in court. yt-dlp now runs YouTube's challenge
  code to do the same thing. What contains it: links are off unless a
  deployment turns them on; one setting stops all fetching, at api and
  worker, within a restart; nothing signs in, sends cookies or bypasses
  geography, so protected video is refused, not circumvented; the whole path
  is one package, one route and one branch, removable without touching
  uploads; and `source_url` makes takedowns answerable. What isn't contained:
  audio already fetched stays until decision 13 says otherwise.
- **The extractor breaks.** This is the most likely failure. It shows up as
  ERROR `extractor_broken` lines, and users see an honest `fetch_failed`. The
  response is to bump yt-dlp or switch links off.
- **Hosted servers may not be able to fetch at all.** YouTube treats
  datacenter addresses with suspicion, demanding sign-in or proof-of-origin
  tokens. v1 provides neither, so on a hosted deployment most lookups may end
  `rate_limited`. Fetching works from a developer's machine. We can't know
  until there is a host (decision 12), but the catalog makes it visible from
  day one.
- **A missing JavaScript runtime looks like the video's fault.** Without
  Deno, YouTube offers few formats, and "no audio" would blame every video.
  The classifier treats a format error that comes with challenge warnings as
  `extractor_broken`. The child reports a missing runtime as `misconfigured`
  before trying. The worker logs a warning at start when links are on and no
  runtime is found.
- **Classifier drift.** When yt-dlp rewords a message, a known cause falls
  back to `unknown`: still `fetch_failed`, and retried. That is honest but
  less helpful. The fixtures and the smoke test catch it.
- **SSRF residue.** Redirects mid-download and DNS rebinding are not
  re-checked. Only egress rules at hosting close that gap.
- **Lookup starvation.** The four-lookup cap is global, not per address, so
  one client can hold others up. Accepted for v1, which has no public
  deployment.
- **The m4a fallback.** When a video has no m4a, we store Opus in WebM,
  which older Safari doesn't play. The logs show how often this happens, and
  acceptance checks Safari. If it bites, the fix is to remux or re-encode that
  case only. New bytes get new cache keys, so no version bump is needed.

## Open questions

1. **Off by default (D4).** Chosen, but confirm it: it means a fresh checkout
   shows the link field only under `make api`, not bare `uvicorn`.
2. **Retention of fetched audio and of `source_url`.** This is decision 13.
   This spec makes it more pressing but doesn't answer it.
3. **Whether a hosted deployment can fetch from YouTube at all.** This is
   decision 12, and it can only be answered from the host.
4. **The Deno minimum for the pinned yt-dlp, and whether hosting can install
   it.** The plan confirms this, along with research.md's *confirm* items.
5. **The smoke-test video.** It should be short and Creative Commons
   licensed, and the plan picks it. Its staying online is itself a
   dependency.
