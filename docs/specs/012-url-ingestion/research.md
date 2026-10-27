# URL Ingestion — research notes

Facts the [spec](spec.md) leans on, with where each came from. Checked on
2026-10-26. The items the spec marked *confirm* were checked against the
version the [plan](plan.md) pins, by reading its source in a throwaway
virtualenv and by a handful of live lookups from a developer's machine.
Where a fact could not be reproduced, it says so.

## The version pinned

- **yt-dlp 2026.10.26**, `pip install "yt-dlp[default]"`. It was the latest
  release on PyPI when checked (uploaded 2026-10-26 22:25 UTC; the stable
  release before it was 2026.10.21). Requires Python 3.11 or later.
- Its `default` extra pins **yt-dlp-ejs 0.8.0** exactly, and brings brotli,
  certifi, mutagen, pycryptodomex, requests, urllib3 and websockets. All pure
  Python apart from brotli and pycryptodomex; none is torch, demucs,
  basic_pitch, librosa or numpy.
- The lock pins both. Bumping is `uv lock --upgrade-package yt-dlp`, then
  `make smoke-url`.

## yt-dlp needs a JavaScript runtime for YouTube

- Since **yt-dlp 2025.11.12**, full YouTube support needs an external
  JavaScript runtime to solve the player's challenges. Without one, YouTube
  support is deprecated. Downloads still work, but fewer formats are offered,
  and sometimes far fewer. In 2026.10.26 the warning reads "No supported
  JavaScript runtime could be found. Only deno is enabled by default; …
  YouTube extraction without a JS runtime has been deprecated, and some
  formats may be missing." (`extractor/youtube/_video.py`).
- **Deno** is the only runtime enabled by default: `YoutubeDL.__init__` sets
  `js_runtimes` to `{'deno': {}}` when it is not given. Node, Bun and QuickJS
  have to be named.
- **Confirmed minimums** (`yt_dlp/utils/_jsruntime.py`, 2026.10.26): Deno
  2.3.0, Node 22.0.0, Bun 1.2.11, QuickJS 2023-12-09 (any QuickJS-ng). An
  older runtime is found but marked unsupported.
- yt-dlp looks for `deno` beside the running Python first
  (`sysconfig.get_path("scripts")`), then lets the OS search `PATH`. The
  child does the same check itself, so it can report a missing runtime as
  `misconfigured` before trying, and passes the path it found explicitly.
- The challenge solver scripts come from **yt-dlp-ejs**. With it installed,
  its scripts are the first source tried (`ejs.py`, `_iter_script_sources`:
  python package, then cache, then built in, then GitHub), so
  `remote_components=[]` downloads nothing. Deno runs them with
  `--no-remote`, `--no-npm` (unless npm packages are already cached) and
  `--no-config`.
- **Open question 4, answered.** Hosting can always install Deno: from
  deno.com, or from PyPI, where the `deno` package ships the binary as a
  wheel (2.9.8, about 42 MB per platform), and `yt-dlp[deno]` is an extra for
  exactly that. Not adopted: it would add 42 MB to every `make install` and
  every CI run, which needs no Deno. The plan's own check of the real child
  ran against Deno 2.9.8 installed that way, outside the project.

Sources: [yt-dlp issue #15012](https://github.com/yt-dlp/yt-dlp/issues/15012);
[Gigazine, 2025-11-13](https://gigazine.net/gsc_news/en/20251113-yt-dlp-required-deno-javascript-runtime);
the source of yt-dlp 2026.10.26 and yt-dlp-ejs 0.8.0.

## Library options the spec uses

From the option list in the `YoutubeDL` class docstring, and the code that
reads each option, in 2026.10.26:

| Option | What 2026.10.26 does with it | Spec use |
|---|---|---|
| `allowed_extractors` | A list of regexes, each **full-matched, case-insensitive**, against every extractor's `IE_NAME` (`orderedSet_from_options`). YouTube's video extractor is `youtube`; the list `["youtube"]` loads that one and nothing else, not even the "Unsupported URL" fallback | Only YouTube's video extractor, so the generic one is unreachable |
| `match_filter` | A function called for every video. If it returns a message, the video is **skipped**; `None` lets it through | Not used. Skipping doesn't raise an error, so the child checks length and liveness itself |
| `js_runtimes` | A dict of runtime name to config, `{'deno': {'path': …}}`. An unknown name raises `ValueError` | Deno, with the path the child found |
| `remote_components` | A list; unknown names are dropped with a warning; empty by default. Known: `ejs:npm`, `ejs:github` | `[]` |
| `socket_timeout` | Seconds, passed to every request | 15 |
| `noplaylist` | Boolean. A `watch?v=…&list=…` URL gets the video only | On |
| `geo_bypass` | Boolean: fake `X-Forwarded-For` | Off |
| `cookiefile`, `cookiesfrombrowser` | Where cookies come from | Never set |
| `extractor_retries` | YouTube's own retries for known errors (default 3) | 1 |
| `retries`, `fragment_retries`, `file_access_retries` | Downloader options, not in the docstring's list but named beside it | 1 each |
| `max_filesize` | Downloader option. The HTTP downloader compares it with `Content-Length` and, when larger, prints "File is larger than max-filesize (N bytes > M bytes). Aborting." and **returns without an error and without a file** | The size cap; the child also checks the format's `filesize` first, and reads that line to tell too large from empty |
| `progress_hooks` | Called with a dict: `status` (`downloading`, `finished`, `error`), `downloaded_bytes`, `total_bytes`, `total_bytes_estimate`, `filename`, `tmpfilename`, `elapsed`, `eta`, `speed`. An exception raised in a hook propagates out of `process_info` | Byte fraction for progress, and the size cap |
| `outtmpl`, `paths` | `{'default': 'source.%(ext)s'}` and `{'home': dir, 'temp': dir}` | A fixed name in the job's directory |
| `logger` | An object with `debug`, `warning` and `error`; screen and info messages go to `debug`. With a logger set, warnings always reach `logger.warning`, whatever `no_warnings` says | The child's, to keep warnings and send everything to stderr |
| `color` | `'never'` keeps ANSI codes out of messages | Set |
| `fixup` | Default `detect_or_warn`: for a DASH m4a (`container: m4a_dash`, as format 140 is) yt-dlp remuxes it with ffmpeg (`FixupM4a`, a stream copy) | Left as is (see below) |

**Format selection and the download, observed.** `extract_info(url,
download=False, process=False)` returns the video's metadata — `live_status`,
`duration`, `availability`, `title`, the formats — **without choosing a
format**. `process_ie_result(raw, download=False)` chooses one and merges its
fields (`url`, `format_id`, `ext`, `protocol`, `filesize`) into the result;
`process_info(selected)` downloads it. The order matters: a live stream has
no format the spec's filter accepts, and choosing first would raise
"Requested format is not available" before `live_status` could be read.
`process_ie_result` is not wrapped in yt-dlp's error handling, so a format
error from it arrives as a bare `ExtractorError`, not a `DownloadError`.

A live run on the smoke video below, without a JavaScript runtime, chose
format 140 (m4a, `https`, about 600 KB) from a `*.googlevideo.com` host that
resolved only to global IPv4 and IPv6 addresses; with Deno 2.9.8 the same.
yt-dlp's FixupM4a remuxed it (600,547 bytes downloaded, 600,184 stored), and
ffprobe read 37.06 s. "No post-processors" in the spec is read as none
configured: the automatic container fixup is kept, because without it the
stored file is a DASH m4a that, in yt-dlp's words, "only some players
support".

**Config files: confirmed, with a finding.** The `YoutubeDL` class reads no
`yt-dlp.conf`: only `yt_dlp.options.parseOpts`, the command line's option
parser, loads config files. But the class **does load plugins** from the
same configuration directories (`~/.config/yt-dlp/plugins/`,
`~/yt-dlp-plugins/`, the system ones, and `yt_dlp_plugins` packages on
`sys.path`) the first time a `YoutubeDL` is made (`load_all_plugins`,
`YoutubeDL.py`). Checked: a module placed in
`$XDG_CONFIG_HOME/yt-dlp/plugins/x/yt_dlp_plugins/extractor/` ran on
`YoutubeDL({})`. Setting `YTDLP_NO_PLUGINS` to any non-empty value stops it
(`plugins.load_plugins`), and the child sets it. This is the same stray-code
risk the spec raised for config files, and worse, since a plugin is code.

## Info-dict fields the checks read

Confirmed against 2026.10.26 (`extractor/common.py`'s field list, and
`extractor/youtube/_video.py`):

- `live_status`: `None` (unknown), `is_live`, `is_upcoming`, `was_live`,
  `not_live`, or `post_live` ("was live, but VOD is not yet processed").
  YouTube's extractor sets it from `isPostLiveDvr`, `isLive`, `isUpcoming` and
  `isLiveContent`. The spec refuses `is_live`, `is_upcoming` and
  `post_live`.
- `availability`: `private`, `premium_only`, `subscriber_only`, `needs_auth`,
  `unlisted` or `public` (`InfoExtractor._availability`). On YouTube,
  `needs_auth` means `age_limit >= 18`. The child treats `needs_auth` as
  age-restricted, `premium_only` and `subscriber_only` as members-only.
  Usually yt-dlp raises before returning a private or members-only video,
  so this field is a second signal.
- `duration` is `lengthSeconds` from the player response, as an integer, and
  `None` when it is missing or zero, as it is for live and upcoming streams.
- A paid video can come back as `_type: url`, pointing at its trailer
  (`playerLegacyDesktopYpcTrailerRenderer`). The child refuses anything that
  is not one video as members-only.

## Exception types the classifier keys on

Confirmed in `yt_dlp/utils/_utils.py` and `yt_dlp/networking/exceptions.py`:

- `DownloadError(msg, exc_info)`: what `extract_info` raises for any
  extraction error. `YoutubeDL.trouble` builds it with `exc_info` set to the
  `ExtractorError`'s own `exc_info` when it has one, else to the current
  exception.
- `ExtractorError(msg, tb=None, expected=False, cause=None, video_id=None,
  ie=None)`: its `str()` is `[ie] video_id: msg`, plus `(caused by …)` and,
  when not `expected`, a request to report a bug. It records `sys.exc_info()`
  when it is made, so an extractor that wraps a network error inside an
  `except` block hands **the network error itself** to `DownloadError.exc_info`,
  not the `ExtractorError`. The classifier therefore walks `exc_info`,
  `cause`, `__cause__` and `__context__`.
- `GeoRestrictedError(ExtractorError)`, with `countries`; always `expected`.
- `UnavailableVideoError(YoutubeDLError)`: "Unable to download video: …",
  raised by `process_info` when writing the file fails with an `OSError` (a
  full disk, say).
- `ContentTooShortError(YoutubeDLError)`: the connection dropped mid-file.
- `HTTPError(RequestError)`, with `.status` and `.reason`; `str()` is
  `HTTP Error 429: Too Many Requests`. Not a `TransportError`.
- `TransportError(RequestError)` and its subclasses `SSLError`,
  `CertificateVerifyError`, `ProxyError`, `IncompleteRead`: DNS failures,
  refused and reset connections, TLS errors, timeouts.
  `network_exceptions = (HTTPError, TransportError)`.

## Messages, as yt-dlp gives them

YouTube's reasons for refusing a video come from YouTube's server
(`playabilityStatus.reason` and `subreason`), not from yt-dlp's source.
yt-dlp passes them on through `raise_no_formats(reason, expected=True)`,
adds its cookie hint when the reason mentions signing in, and prefixes
`[youtube] <id>: `. `DownloadError` adds `ERROR: `. So the classifier's
fixtures (`packages/fetch/tests/fixtures/youtube-messages.json`) are of three
kinds, each marked:

**Recorded live** on 2026-10-26 with yt-dlp 2026.10.26, from a developer's
machine, no JavaScript runtime (the private video and `Q39EVAstoRM` again
with Deno 2.9.8, through the real child):

| Case | Video | Message (after `ERROR: [youtube] <id>: `) |
|---|---|---|
| Private | `yZIXLfi8CZQ` | Private video. If the owner of this video has granted you access, please sign in. Use --cookies-from-browser or --cookies for the authentication. See … |
| Age-restricted | `HtVdAasjOgU` | Sign in to confirm your age. This video may be inappropriate for some users. Use --cookies-from-browser … |
| Never existed | `aaaaaaaaaaa` | This video is unavailable |
| Removed | `Q39EVAstoRM`, `BaW_jenozKc` | This video is unavailable |
| Removed | `JOhiWY7XmoY` | This video is not available |
| Removed for policy | `6SJNVb0GnPI` | This video has been removed for violating YouTube's policy on hate speech. Learn more about combating hate speech in your country. |
| A stream's recording gone | `jfKfPfyJRdk` | This live stream recording is not available. |

The hate-speech removal mentions "your country", which is why the
classifier's geo-restriction pattern is "not made this video available in
your country", not "your country".

**From yt-dlp's own source** (2026.10.26): "Requested format is not
available. Use --list-formats for a list of available formats"; "No video
formats found!"; "This video is DRM protected"; "Failed to extract any player
response"; "Unable to extract …"; "Unsupported URL: …"; "No suitable extractor
found for URL …"; "All player responses are invalid. Your IP is likely being
blocked by Youtube"; YouTube's soft rate limit, which yt-dlp extends to "This
content isn't available, try again later. The current session has been
rate-limited by YouTube for up to an hour…"; "… YouTube is requiring a captcha
challenge before playback"; and the challenge warnings — "n challenge solving
failed: Some formats may be missing…", "Signature solving failed: …", "No
supported JavaScript runtime could be found…", "Remote component … was
skipped…", "Challenge solver … script version … is not supported".

**Reported, not reproduced here**: YouTube's own wording for members-only
("Join this channel to get access to members-only content like this video,
and other exclusive perks."), paid ("This video requires payment to watch."),
Music Premium, upcoming ("This live event will begin in 3 hours.", "Premieres
in 10 hours", "Premiere will begin shortly"), account terminations and
copyright claims, and the bot check ("Sign in to confirm you’re not a bot",
with a curly apostrophe). None could be triggered on demand from this
machine. They are the classifier's best evidence until `make smoke-url` or
the acceptance run records them; when yt-dlp or YouTube rewords one, a known
cause falls back to `unknown`, which is still `fetch_failed` and retried.

An upcoming premiere has no formats, so yt-dlp raises with YouTube's reason
before any metadata comes back: row L7 is caught by the message, with
`is_upcoming` as a second signal. Live and just-ended streams do come back
with metadata, and rows L6 and L8 are caught from `live_status`.

## The smoke-test video

**Open question 5, answered.** "Elephants Dream - 10 years of open movies",
`https://www.youtube.com/watch?v=kPdv44HtEoA`, on the Blender Foundation's
own channel: 37 seconds, licensed Creative Commons Attribution (the
`license` field yt-dlp reads from the page), format 140 at about 600 KB.
Found with YouTube's own "Creative Commons" and "under four minutes" search
filters; chosen over shorter candidates for its owner, whose channel is
likelier to stay up than a re-upload's. Its staying online is the smoke
test's one outside dependency.

## Not confirmed

- How YouTube treats a datacenter address (open decision 12). Every live
  check here ran from a residential connection.
- The members-only, upcoming, post-live, geo, bot-check and HTTP 429
  messages, above.
- Whether a stored Opus-in-WebM file plays in Safari: no video without an
  m4a format was found while checking. `acceptance.md` asks.

## The 2020 youtube-dl takedown

In October 2020 the RIAA sent GitHub a DMCA §1201 notice against
youtube-dl, arguing that its handling of YouTube's "rolling cipher" got around
a technical protection measure. GitHub reinstated the project in November 2020
after legal review. The argument was never tested in court. The spec's *Risks*
cite it because the legal exposure goes beyond YouTube's terms of service.
(From memory. Widely reported at the time.)

## The design system's link field

*Web mockups · WebHome* in the
[GuitarVis design system](https://claude.ai/artifact/3Zc4v6XxdR3viHReBX6weE)
puts the link field inside the upload card, under the drop zone. It has an
"or paste a link" divider, a field with the link icon and `https://…`, and a
*Get tab* button. The mockup's README shows every link failure as
"We couldn't fetch that audio. / Upload the file itself instead." The spec
splits that one message across three reasons.
