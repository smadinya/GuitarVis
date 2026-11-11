# Acceptance

**Spec:** [013 — How the setup is verified](spec.md#how-the-setup-is-verified)

Every setup command in the docs, run in the order written, from a fresh
clone in a folder called `guitarvis-fresh` (its own Docker project and
volumes). The dev stack was stopped with `docker compose stop` for the
duration and started again afterwards.

**Run by:** an agent (Claude Code), on 2026-11-10.
**Machine:** Ubuntu 24.04 under WSL2, Linux 6.18 x86_64, Docker 28.4.0,
uv-managed Python 3.12.15 and 3.13.16 installed, system Python 3.12.3,
Node 22, Deno 2.9.8 (in `~/.deno/bin`, not on a non-interactive `PATH`),
yt-dlp 2026.10.26. No working GPU.

## Pass 1 — today's docs

Commit `f559d86`, whose README is `main`'s.

| Step | Command | Result | Doc change |
|---|---|---|---|
| Port clash | `make services` with the dev stack up | Fails: `Bind for 127.0.0.1:5432 failed: port is already allocated` | Troubleshooting entry |
| Getting started | `make install` | Pass, 1 m 45 s cold | — |
| | `make check` (no services) | Pass: 1,213 passed, 91 skipped; vitest 495 passed | — |
| Pipeline | `uv sync --extra ml` | **Fails.** uv chose its managed Python 3.13.16. `numpy==1.26.4` (pinned by the ML stack off macOS x86) has no 3.13 wheel, so uv builds it from source, and the build fails. | `.python-version` = `3.12` (see Ruling) |
| | same, after the pin | Pass; venv recreated on CPython 3.12.15 | — |
| | `guitarvis-worker process song.mp3 -o song.json`, cold model cache | Pass, 48 s for a 25 s clip. Downloads `htdemucs_6s` weights, 55 MB, into the Hugging Face cache. basic-pitch ships its model. | Guide: first-run download |
| | same with `--stems-dir ./stems` | Pass, 20 s warm. Six WAV stems, 26 MB for 25 s. | — |
| Extra drop | `make install` again, then `import torch` | **`ModuleNotFoundError: torch`.** `uv sync` is exact and uninstalled 66 packages. `uv sync --extra ml` restores them. | Guide caveat |
| Service | `make services`, `make migrate` | Pass | — |
| | `make api`, `make worker`, `make web` | Pass. Without Deno on `PATH` the worker warns: `links are on, but Deno 2.3.0 or later was not found` | — |
| | `curl -F file=@song.mp3 localhost:8000/jobs` | 202, a job id; `succeeded` in 43 s | — |
| | the same upload again | 200, the same job id | — |
| | `curl …/jobs/<id>/document` | The tab document | — |
| | `curl -L …/audio/mix -o mix` | 307 to storage, then the MP3 | — |
| | `curl -L …/audio/guitar` | The guitar stem (WAV); not in the README | Guide: add it |
| | `from-url` curl, api without Deno on `PATH` | **503 `fetch_failed`**: "We can't fetch from YouTube at the moment…". The api looks the link up before queueing, so it needs Deno too. | Troubleshooting entry |
| | `GUITARVIS_REQUIRE_SERVICES=1 make check` | Pass: 1,304 passed, 0 skipped | — |
| Links | `make smoke-url` (Deno on `PATH`) | Pass, 3 passed in 9 s | — |
| | `from-url` curl with `https://youtu.be/kPdv44HtEoA` | 202; the title *Elephants Dream - 10 years of open movies*; `succeeded` in 28 s | — |
| | the same video as `watch?v=…&t=5` | The same job id | — |
| Teardown | `docker compose down -v` in `guitarvis-fresh` only | Its two volumes removed; `guitarvis_*` untouched | — |

The live link run closes spec 012's open item: the fetcher changed in its
Task 22 had not been run against YouTube until now.

### Defects in today's docs

1. `uv sync --extra ml` fails wherever uv picks Python 3.13 or later. That
   is the default once uv has installed a newer Python, and on any machine
   without a 3.12. Fixed by `.python-version`, not by prose.
2. The README's requirements omit ffmpeg (only `CONTRIBUTING.md` has it)
   and Deno.
3. The README omits the `[` and `]` loop keys.
4. Nothing says that re-running `make install` removes the ML extra.
5. Nothing says that the first job downloads 55 MB of weights.
6. Deno must be on `PATH` for `make api` as well as `make worker`. Nothing
   says what a reader without it sees.
7. `audio/guitar`, `--tuning`, `--max-duration` and `serve --burst` are
   undocumented.
8. The layout table omits `eval/results` and `deploy`.

### Ruling

`.python-version` pins `3.12`. It is setup configuration, not app code, and
the spec's success condition 4 needs the documented commands to work as
written. A known-issue note on step two of the quick start would defeat the
spec's purpose. CI never installs the ML extra, so it could not have caught
this. The cost if wrong is one file to delete, in its own commit.

## Pass 2 — shipped docs

The branch at `de2731e`, cloned from GitHub
(`git clone --branch 013-readme-showcase https://github.com/smadinya/GuitarVis.git guitarvis-fresh`;
the folder name is the only departure from the guide, for isolation). The
steps follow [`run-locally.md`](../../guides/run-locally.md) and
[`command-line.md`](../../guides/command-line.md) top to bottom.

| Guide step | Command | Result |
|---|---|---|
| Install | `make install`, `uv sync --extra ml` | Pass; uv chose CPython 3.12.15 from `.python-version` with no flag |
| Services | `make services`, `make migrate` | Pass |
| Run | `make api`, `make worker`, `make web` (Deno on `PATH`) | Pass |
| First upload | a song dropped on the page, in Chromium | The page showed *Waiting for a worker* → *Isolating the guitar* → *Transcribing notes* → *Finding the beat and chords*, then the player; Play ran |
| Links | `deno --version`; `make smoke-url` | 2.9.8; 3 passed |
| CLI | `process song.mp3 -o song.json` | Pass, with the "notes … dropped" warning |
| | `--tuning D2,A2,D3,G3,B3,E4` | Pass; the document's tuning is drop D |
| | `--stems-dir ./stems` | Pass; six WAV stems |
| | `--max-duration 10` | `too_long`, "longer than 0 minutes": [#57](https://github.com/smadinya/GuitarVis/issues/57), noted in the guide |
| | `serve --burst` | Exits once the queue is empty |
| HTTP | `POST /jobs` | 202; `succeeded`; the same file again gives 200 and the same job |
| | `GET …/document`, `…/audio/mix`, `…/audio/guitar` | The document; one redirect each, to MP3 and WAV |
| | `GET /features`, `GET /health` | `{"url_ingestion":true}`; all three services `ok` |
| | `POST /jobs/from-url` (the CC video) | 202, *Elephants Dream - 10 years of open movies*, `succeeded` |
| Clean up | `docker compose stop`, `docker compose down -v` in `guitarvis-fresh` | Its volumes removed; the dev stack's untouched and restarted |
| Checks | `GUITARVIS_REQUIRE_SERVICES=1 make check` (working copy) | Pass: 1,304 passed, 0 skipped; vitest 495 passed |

Not run: `--device cuda` (no GPU, marked in the guides). The
troubleshooting entries for the port clash, the numpy build and the
Deno-less api come from pass 1, where each happened.

## GitHub render

`https://github.com/smadinya/GuitarVis/blob/<sha>/README.md`, rendered by
GitHub and captured with Playwright.

| Check | At `de2731e` | At `76ed171` |
|---|---|---|
| 1280 px: title, sentence, badges and GIF on the README's first screen | Pass | Pass |
| Mermaid renders as an SVG, not code | Pass | Pass |
| 390 px: the three view shots read | **Fail**: a three-column table squeezed them to 54–111 px | Pass: stacked, 324 px each |
| Dark theme: nothing dark-on-dark | Pass | Pass |
