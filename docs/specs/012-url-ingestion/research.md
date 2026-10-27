# URL Ingestion — research notes

Facts the [spec](spec.md) leans on, with where each came from. Checked on
2026-10-26 unless marked otherwise. yt-dlp moves fast, so the plan re-checks
every item marked *confirm* against the version it pins.

## yt-dlp needs a JavaScript runtime for YouTube

- Since **yt-dlp 2025.11.12**, full YouTube support needs an external
  JavaScript runtime to solve the player's challenges. Without one, YouTube
  support is deprecated. Downloads still work, but fewer formats are offered,
  and sometimes far fewer.
- **Deno** is the only runtime enabled by default. Node, Bun and QuickJS
  have to be enabled explicitly (`--js-runtimes`, or the `js_runtimes` option
  in the library). yt-dlp-ejs lists Deno ≥ 2.3 and Node ≥ 22. *Confirm the
  minimums.*
- The runtime is driven by the **yt-dlp-ejs** component. It ships with the
  official binaries and with `pip install "yt-dlp[default]"`. That is why the
  spec depends on the `[default]` extra.

Sources: [yt-dlp issue #15012](https://github.com/yt-dlp/yt-dlp/issues/15012);
[Gigazine, 2025-11-13](https://gigazine.net/gsc_news/en/20251113-yt-dlp-required-deno-javascript-runtime);
[yt-dlp-ejs docs](https://www.mintlify.com/yt-dlp/ejs/installation).

## Library options the spec uses

From the option list in the `YoutubeDL` class docstring
([`yt_dlp/YoutubeDL.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py)):

| Option | Docstring says | Spec use |
|---|---|---|
| `allowed_extractors` | "List of regexes to match against extractor names that are allowed" | Only YouTube's extractors, so the generic one is unreachable |
| `match_filter` | A function called for every video. If it returns a message, the video is **skipped**; `None` lets it through | Not used. Skipping doesn't raise an error, so the child checks length and liveness itself |
| `js_runtimes` | "A dictionary of JavaScript runtime keys (in lower case) to enable"; Deno when None | Set explicitly |
| `remote_components` | "A list of remote components that are allowed to be fetched when required" | `[]`, so no code is downloaded at run time |
| `socket_timeout` | "Time to wait for unresponsive hosts, in seconds" | 15 |
| `noplaylist` | "Download single video instead of a playlist if in doubt" | On |
| `geo_bypass` | "Bypass geographic restriction via faking X-Forwarded-For" | Off |
| `cookiefile` | Where cookies are read from and written to | Never set |
| `extractor_retries` | "Number of times to retry for known errors (default: 3)" | Small. RQ retries the job |
| `progress_hooks` | Functions called during the download with its status | Byte fraction for progress, and the size cap |
| `max_filesize`, `retries` | Downloader options, not described in the docstring | Size cap, small retry count |

*Confirm:* the `YoutubeDL` class reads no `yt-dlp.conf`. As I remember it,
config files are loaded by the command line's option parsing, not by the
class. The spec relies on this to argue for library-in-a-child over the CLI.

## Info-dict fields the checks read

From memory of yt-dlp's documented output template fields. *Confirm against
the pinned version.*

- `live_status`: `not_live`, `is_live`, `is_upcoming`, `was_live`,
  `post_live`. The spec refuses `is_live`, `is_upcoming` and `post_live`.
- `availability`: `private`, `premium_only`, `subscriber_only`,
  `needs_auth`, `unlisted`, `public`. Usually yt-dlp raises an error before
  returning a private or members-only video, so this field is a second signal.
- `duration` is in seconds and is missing for live and upcoming streams.

## Exception types the classifier keys on

*Confirm.* `yt_dlp.utils.DownloadError` wraps the original exception, which is
reachable through `exc_info`. Under it sit `ExtractorError` (with `expected`),
`GeoRestrictedError` and `yt_dlp.networking.exceptions.HTTPError` (with
`.status`). Most causes are distinguishable only by message: "Private video",
"Video unavailable", "Sign in to confirm your age", "members-only", "Sign in
to confirm you're not a bot", "Unable to extract", "Requested format is not
available". The plan records real messages from the pinned version as
fixtures.

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
