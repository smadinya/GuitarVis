# URL Ingestion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user paste a YouTube link instead of uploading a file. The api checks the link and the video's metadata and queues a job; the worker downloads the audio in a child process, stores it as an upload is stored, and runs the four stages on it. Every way that can fail has a reason, a status, a message and a log line from one catalog, and one setting turns links off everywhere.

**Architecture:** A new workspace member, `packages/fetch` (`guitarvis_fetch`), holds everything links need: `links.py` parses a pasted string into one video and a canonical URL; `catalog.py` maps each kind of failure to its reason, status, message, level and retry rule; `fetcher.py` defines the `UrlFetcher` contract and `ChildFetcher`, which runs `python -I -m guitarvis_fetch.child` with a deadline and kills its process group; `child.py` is the only module that imports yt-dlp, and classifies every failure while yt-dlp's types are visible. The api gains `routes_links.py` (`POST /jobs/from-url`, `GET /features`); the worker gains `UrlSource` and one branch in `_run`; the job row gains `source_url` and a nullable `upload_key` (migration `r0002`); the client gains the link field. `GUITARVIS_URL_INGESTION` is off by default.

**Tech Stack:** Python 3.12, uv workspace; **yt-dlp 2026.10.26** with yt-dlp-ejs 0.8.0 (`yt-dlp[default]`, pinned by `uv.lock`), run in a child process; FastAPI 0.141 / Starlette 1.7 / Pydantic 2.13; SQLAlchemy 2 Core, Alembic; RQ; React 18.3, TypeScript 6.0, Vitest 5.0 with jsdom 29.1. Deno 2.3 or later on any host that fetches links; not in CI.

**Spec:** [spec.md](spec.md) · **Research:** [research.md](research.md) · **Parent:** [001-guitarvis-design](../001-guitarvis-design/spec.md) · **Builds on:** [005](../005-api-job-queue/spec.md), [006](../006-tab-view-sync/spec.md), [011](../011-player-redesign/spec.md) · **ADR added here:** 0010 (Task 16) · **Visual reference:** *Web mockups · WebHome* in the [design system](https://claude.ai/artifact/3Zc4v6XxdR3viHReBX6weE)

**Checked while writing:**
- The code in Tasks 1–18 was assembled from this plan in a scratch clone of the repo and run. Each task's tests were replayed on the task's parent commit and failed as its Step 2 says. `make check` then passed after every task, with `GUITARVIS_REQUIRE_SERVICES=1`, against real Postgres 16.2, Redis and an S3 server; at the end, 1,117 Python tests and 489 web tests. Docker was not reachable from that machine, so Postgres came from PyPI's `pgserver`, Redis from `redislite`, and object storage from `moto` standing in for RustFS.
- yt-dlp 2026.10.26's source was read for every option, exception and message the plan uses (research.md). The real child ran once against YouTube with Deno 2.9.8, installed outside the project: it looked up and downloaded the smoke video as format 140 (m4a, 600,184 bytes after yt-dlp's remux), ffprobe read 37.06 s, and a private and a removed video came back as `private` and `unavailable`.
- The code blocks below were then applied, in order, to a fresh checkout of the base commit by a script: the result matched that code byte for byte, and `uv lock` and `make schema` regenerated identical `uv.lock`, `api.schema.json` and `api.ts`.
- Not run: RustFS itself, `make services`, the CI workflow on GitHub, a browser, and `acceptance.md`, which is a person's job.
- A snippet that fails as written most likely has a transcription slip; check it against the task's other files before doubting the design.

## Before Task 1

The branch `012-url-ingestion` exists, with the spec, research notes and this plan committed. Work there; `.githooks/pre-commit` refuses `main`.

## Deviations from the spec

Each is fixed in the spec, in the same commit as this plan, where the spec was wrong.

1. **yt-dlp's library loads plugins, from the directories its config files live in.** The spec's *No stray config* is right that the `YoutubeDL` class reads no `yt-dlp.conf` (only the command line's option parser does). But the first `YoutubeDL()` in a process imports any plugin in `~/.config/yt-dlp/plugins/` and the system's equivalents, which is code, not config. Checked: a plugin there ran on `YoutubeDL({})`. The child sets `YTDLP_NO_PLUGINS=1`, and so does `ChildFetcher` in the child's environment; `test_the_child_loads_no_ytdlp_plugins` proves it with a control. Spec amended.
2. **Success condition 7 is too strict by three tests.** "Upload jobs are unchanged. Their tests pass unmodified, apart from those that pin the list of failure reasons." Upload behaviour is unchanged, but `test_a_queued_job` pins a whole `JobView` body, which gains `source_url` as the spec requires (Task 9), and `Job.upload_key` becomes `str | None`, so two upload tests need a one-line `assert … is not None` for mypy (Task 8). Spec amended.
3. **Row L7 (upcoming) is caught by its message, not by `is_upcoming`.** An upcoming premiere has no formats, and yt-dlp raises with YouTube's reason ("This live event will begin in …", "Premieres in …") before any metadata comes back. The classifier keys on those words; `check_info` still refuses `is_upcoming` when metadata does arrive. L6 (live) and L8 (just ended) do come back with metadata, so the child reads metadata before it chooses a format; choosing first would call a live stream "no audio". Spec amended.

## Decisions the spec leaves open, made here

- **The pinned version is yt-dlp 2026.10.26**, the latest on PyPI when this plan was written; its `default` extra pins yt-dlp-ejs 0.8.0. `pyproject.toml` says `>=2026.10.26`; the lock pins it.
- **The smoke video is "Elephants Dream - 10 years of open movies"** (`kPdv44HtEoA`), on the Blender Foundation's own channel: 37 seconds, Creative Commons Attribution (spec open question 5; research.md).
- **Deno's minimum is 2.3.0** for this yt-dlp; Node's would be 22.0.0 (open question 4). The child looks for Deno where yt-dlp does, beside the Python first and then on `PATH`, checks the version itself, and passes the path to yt-dlp.
- **`fetcher.py` comes before `child.py`** (Tasks 6 and 7), the reverse of the spec's list: the child speaks the JSON-lines protocol the fetcher defines, and imports `check_info` and `find_deno` from it.
- **yt-dlp's automatic container fixup stays on.** "No post-processors" means none configured. For a DASH m4a, which format 140 is, yt-dlp remuxes with ffmpeg (a stream copy); without it the stored file is one that, in yt-dlp's words, "only some players support". Seen in the live run.
- **`max_filesize` is not enough on its own.** yt-dlp gives up silently on a response larger than it, leaving no file and raising nothing. The child checks the chosen format's `filesize` first, counts bytes in its progress hook, checks the file on disk, and reads yt-dlp's "max-filesize" line to tell a too-large download from an empty one.
- **Classifier mappings beyond the spec's examples**, each from yt-dlp's source or a live run (fixtures): YouTube's soft limit ("This content isn't available, try again later"), "Your IP is likely being blocked" and a captcha are `rate_limited`; "This video is DRM protected", "requires payment", Music Premium and a trailer returned in place of a paid video are `members_only`; "This live stream recording is not available" is `unavailable`; an HTTP 403 for the media URL after challenge warnings is `extractor_broken`, and without them `unknown`; a full disk (`UnavailableVideoError`) is `local_io`.
- **Every `FetchKind` has an HTTP status**, including the worker-only ones (`download_timeout` 504, `media_refused` 502, `too_large` and `empty_download` and `unreadable` 422, `local_io` 500), so the api can never meet a kind it cannot answer.
- **`busy` (Q3) and `unreadable` (P1) are `FetchKind`s**, so their messages live in the catalog with the rest.
- **R1 is checked before the body is read**, by a custom `APIRoute` on the link route only: FastAPI parses JSON before any dependency runs. The same route class turns a validation error into `unsupported_link`, so the app's validation handler stays upload-only and links remain removable in one line.
- **`UploadSizeLimit` guards one path per instance**, `POST /jobs` by default; the link route adds one at 16 KB with its own message.
- **The upload route's steps become shared functions** in `routes.py` (`live_job`, `check_limit`, `enqueue`, `too_many_jobs`, `client_ip_of`), moved, not changed.
- **The schema's root type is renamed `ApiBody`** (it was `ApiResponse`), since it now includes a request body. Nothing imported `ApiResponse`.
- **A title loses every Unicode "C" character** (control, format, private use), not only ASCII controls, before the 200-character cut.
- **`r0002`'s downgrade deletes link jobs whose audio was never stored**: a 0001 row cannot exist without an `upload_key`. Going down is for development databases.
- **`WorkerDeps` also gains `max_download_bytes`** (from `GUITARVIS_MAX_UPLOAD_MB`) **and `probe`** (ffprobe, injectable for the tests).
- **The four-lookup semaphore lives on `Services`**, one per app, which is one per api process in production.
- **The api's and the worker's log lines** are the spec's format exactly, written by `log_failed` and `log_fetched` in `fetcher.py`, so the two cannot drift.

## Global Constraints

Every task inherits these.

- **Never commit to `main`.** Work on `012-url-ingestion`.
- **`make check` is the gate.** Run `make services` first, or the integration tests skip locally and fail in CI. Each task ends the same way: `make lint typecheck test` passes, the task is committed, then `make schema-check` passes. `schema-check` compares the working tree with git, so it fails on uncommitted generated files even when they are right; running it after the commit is the honest order.
- **Nothing in `make check` touches the network or needs Deno.** No test asks YouTube; `make smoke-url` is the only thing that does, and it is never reached from `check` (Task 15 makes a test of that).
- **Only `guitarvis_fetch.child` imports `yt_dlp`**, and only inside functions. `apps/api` must not import it (`test_boundaries.py`, Task 9), and importing any other `guitarvis_fetch` module must not load it (`test_fetch_package.py`, Task 4). Invariant 3 still holds for the ML stack.
- **yt-dlp's text never reaches a response body or a job row.** Messages come from `guitarvis_fetch.catalog`; `FetchError.detail` and `.tail` go to the log only. Every task that maps a failure has a sentinel test.
- **No change to `tabdoc.py`, `SCHEMA_VERSION` or `CACHE_VERSION`.** `schema/api.schema.json` and `web/src/types/api.ts` change only through `make schema` (Tasks 2 and 9); never edit them by hand.
- **Upload jobs behave exactly as before.** Their tests pass unchanged, but for the three named in Deviation 2 and those that pin the list of reasons (Task 2).
- **Test file basenames stay unique across the repo**, and there is no `conftest.py` (the Makefile's mypy note). Shared helpers live in `guitarvis_fetch.testing` and `guitarvis_jobs.testing`.
- **Web:** a test that needs the DOM begins with `// @vitest-environment jsdom`; everything else runs on `node`. `npm --prefix web test -- <path>` runs `tsc --noEmit` first, so a missing export fails there. Double quotes, semicolons, two-space indents; `npm --prefix web run lint` is authoritative.
- **Python:** run `uv run ruff format . && uv run ruff check --fix .` before each commit; ruff is authoritative for import order and wrapping in the snippets below.
- Dependency changes are `uv lock && uv sync`, and `uv.lock` is committed with them: CI runs `uv sync --locked`.
- **Exact values from the spec:** link at most 2,048 characters; body at most 16 KB; lookup deadline 30 s; download deadline 300 s; at most 4 lookups per api process; `socket_timeout` 15 s; size cap `GUITARVIS_MAX_UPLOAD_MB` (150); length limit 10 minutes; a link job's download fills 0–5% and the pipeline 5–100%; log `detail` cut to 500 characters and ERROR lines add the last 2 KB of the child's stderr; format `bestaudio[ext=m4a][protocol=https]/bestaudio[protocol=https]`; output template `source.%(ext)s`; media host suffix `.googlevideo.com`; the canonical URL `https://www.youtube.com/watch?v=ID`; the dedupe key `sha256("youtube:" + id)`.
- End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

Inputs the spec implies but its test list never names, most likely first. Each is pinned by a test in the task named.

1. **A private video's message also asks the viewer to sign in.** yt-dlp's real text: "Private video. If the owner of this video has granted you access, please sign in. Use --cookies-from-browser …". A classifier that tests for "sign in" first calls it age-restricted. Expected: `private`. → Task 7: `test_a_private_videos_sign_in_request_is_not_age_restriction`, and the recorded fixture.
2. **A removal for policy mentions "your country".** Recorded live: "This video has been removed for violating YouTube's policy on hate speech. Learn more about combating hate speech in your country." Expected: `unavailable`, not `geo_restricted`. → Task 7: the `unavailable` fixtures in `test_each_recorded_message_classifies_as_its_kind`.
3. **A live stream meets the format filter before its metadata is read.** A live stream has no audio-only HTTPS format, so choosing first raises "Requested format is not available". Expected: `live`, and no format chosen. → Task 7: `test_a_live_stream_is_refused_before_formats_are_chosen`.
4. **yt-dlp's own size cap fails silently.** Expected: `too_large`, not `empty_download`. → Task 7: `test_yt_dlps_quiet_size_cap_is_too_large_not_empty`.
5. **The worker's job timeout arrives mid-download.** It is a `BaseException` raised by a signal. Expected: the child and the runtime it started are killed all the same. → Task 6: `test_a_job_timeout_mid_download_still_kills_the_child`.
6. **A yt-dlp plugin on the host.** Expected: it never runs in the child. → Task 7: `test_the_child_loads_no_ytdlp_plugins`.
7. **yt-dlp, or Deno, prints to stdout.** Expected: only JSON answers on the protocol stream. → Task 7: `test_nothing_but_answers_reaches_the_childs_stdout`.
8. **Links off, with a body that is not JSON.** Expected: 403 `links_disabled`, not 422. → Task 10: `test_links_switched_off_are_refused_before_anything_is_read`.
9. **A link job retried after its download was kept, with links now off.** Expected: it runs from the stored audio and never asks YouTube. → Task 11: `test_links_off_still_runs_a_link_job_whose_download_is_stored` and `test_a_retry_finds_the_download_stored_and_never_fetches`.
10. **A link and an upload of the same bytes.** Expected: one cache entry serves both. → Task 11: `test_a_link_and_an_upload_of_the_same_bytes_share_the_cache`.

## File map

| Path | Responsibility | Task |
|---|---|---|
| `packages/core/src/guitarvis_core/contracts.py` | `PipelineError.retryable`; `FailureReason` + `link_unusable`, `links_disabled` | 1, 2 |
| `apps/api/src/guitarvis_api/errors.py` | `HttpReason.UNSUPPORTED_LINK` | 2 |
| `web/src/api/messages.ts` | text for the three reasons; new actions for `too_long`, `fetch_failed` | 2 |
| `packages/jobs/src/guitarvis_jobs/settings.py` | `url_ingestion`, boolean parsing | 3 |
| `packages/fetch/` | the new workspace member `guitarvis_fetch` | 4–7 |
| `…/guitarvis_fetch/links.py` | `parse`, `Link`, `LinkRefused`, `RefusalKind` | 4 |
| `…/guitarvis_fetch/catalog.py` | `FetchKind`, `CATALOG`, `REFUSALS`, the messages | 5 |
| `…/guitarvis_fetch/fetcher.py` | `UrlFetcher`, `VideoInfo`, `Download`, `FetchError`, `check_info`, `find_deno`, `ChildFetcher`, log lines | 6 |
| `…/guitarvis_fetch/testing.py` | `FakeFetcher` for the api's and worker's tests | 6 |
| `…/guitarvis_fetch/child.py` | the yt-dlp child: options, lookup, download, media checks, `classify` | 7 |
| `packages/fetch/tests/fixtures/youtube-messages.json` | yt-dlp's messages, each with where it came from | 7 |
| `packages/fetch/smoke/live_fetch.py` | `make smoke-url` | 15 |
| `packages/jobs/src/guitarvis_jobs/{models,store,postgres,testing}.py` | `source_url`, nullable `upload_key`, `attach_upload`, `sample_link_job` | 8 |
| `…/guitarvis_jobs/migrations/versions/r0002_link_jobs.py` | the migration | 8 |
| `apps/api/src/guitarvis_api/schemas.py`, `schema_export.py` | `JobView.source_url`, `LinkRequest`, `Features` | 9 |
| `apps/api/src/guitarvis_api/routes_links.py` | `POST /jobs/from-url`, `GET /features`, `install(app)` | 10 |
| `apps/api/src/guitarvis_api/{routes,uploads,services,app}.py` | shared upload steps, per-path body limit, fetcher and lookup slots, one `install_links` call; `get_mix` 409 | 8, 10 |
| `apps/worker/src/guitarvis_worker/ingest.py` | `UrlSource` | 11 |
| `apps/worker/src/guitarvis_worker/runner.py` | `retryable`; the fetch branch, progress band, `attach_upload`; `WorkerDeps` fields; start-up warning | 1, 8, 11 |
| `web/src/api/client.ts` | `createJobFromUrl`, `getFeatures` | 13 |
| `web/src/pages/UploadPage.tsx`, `link.ts`, `progress.ts` | the link field, `linkHint`, `download` stage text | 14 |
| `web/src/icons.tsx`, `web/src/styles.css`, `web/vite.config.ts` | `LinkIcon`, the field's styles, `/features` proxy | 13, 14 |
| `Makefile`, `pyproject.toml`, `mypy.ini` | workspace member, `PY_SOURCES`, `smoke-url`, the switch under `api`/`worker`, yt-dlp's mypy section | 4, 7, 15 |
| `docs/decisions/0010-…md`, `docs/decisions/README.md` | ADR 0010 | 16 |
| `CLAUDE.md`, `docs/CONVENTIONS.md`, `.claude/skills/pipeline-stage/SKILL.md`, `README.md`, `CONTRIBUTING.md`, specs 001 and 005 | the records | 17 |
| `docs/specs/012-url-ingestion/acceptance.md` | the manual record, a template | 18 |

---

### Task 1: A pipeline error says whether to retry

The worker's retry rule today is "only `internal` retries". A fetch that fails on the network is `fetch_failed`, and must retry too, and keep its own reason on the last attempt. `PipelineError` gains `retryable`, defaulting to today's rule, and the runner follows it. No reason is added yet, so nothing generated changes.

**Catalog rows:** Groundwork for D1, D2, D8, D9 and D10 (retried) and D3 to D7 (not).

**Files:**
- Modify: `apps/worker/src/guitarvis_worker/runner.py`
- Modify: `packages/core/src/guitarvis_core/contracts.py`
- Test: `apps/worker/tests/test_runner.py`
- Test: `packages/core/tests/test_contracts.py`

**Interfaces:**
- Produces: `PipelineError(reason, message, *, retryable: bool | None = None)`; `error.retryable` is `reason is FailureReason.INTERNAL` unless given.
- Changes: `runner._failed_attempt(..., error: PipelineError | None = None)` records `error.reason` and `str(error)` on the last attempt unless the reason is `internal`; `runner._shown(error)` hides an internal error's detail.

- [x] **Step 1: Write the failing tests**

In `apps/worker/tests/test_runner.py`:

```diff
--- a/apps/worker/tests/test_runner.py
+++ b/apps/worker/tests/test_runner.py
@@ -210,6 +210,56 @@ def test_an_internal_pipeline_error_on_the_last_attempt_hides_its_detail(
     assert row.failed_stage == "separation"
 
 
+UPSTREAM_DOWN = PipelineError(
+    FailureReason.FETCH_FAILED,
+    "We couldn't reach YouTube. Try again in a few minutes, or upload the audio file.",
+    retryable=True,
+)
+
+
+def test_a_retryable_failure_with_retries_left_requeues_and_reraises(
+    harness: Harness,
+) -> None:
+    harness.separator.error = UPSTREAM_DOWN
+
+    with pytest.raises(PipelineError):
+        harness.run(retries_left=1)
+
+    row = harness.row()
+    assert row.status is JobStatus.QUEUED
+    assert (row.stage, row.percent, row.attempts) == (None, 0, 1)
+
+
+def test_a_retryable_failure_on_the_last_attempt_keeps_its_own_reason(
+    harness: Harness,
+) -> None:
+    """A fetch that kept failing ends as fetch_failed, not as our fault."""
+    harness.separator.error = UPSTREAM_DOWN
+
+    with pytest.raises(PipelineError):
+        harness.run(retries_left=0)
+
+    row = harness.row()
+    assert row.status is JobStatus.FAILED
+    assert row.failure_reason is FailureReason.FETCH_FAILED
+    assert row.failure_message == str(UPSTREAM_DOWN)
+    assert row.failed_stage == "separation"
+
+
+def test_an_internal_failure_that_is_not_retryable_still_hides_its_detail(
+    harness: Harness,
+) -> None:
+    harness.separator.error = PipelineError(
+        FailureReason.INTERNAL, "Traceback: the detail", retryable=False
+    )
+
+    harness.run(retries_left=2)  # no retry, so it returns normally
+
+    row = harness.row()
+    assert row.failure_reason is FailureReason.INTERNAL
+    assert row.failure_message == INTERNAL_FAILURE_MESSAGE
+
+
 def test_a_file_the_worker_rejects_fails_before_any_stage(
     harness: Harness, monkeypatch: pytest.MonkeyPatch
 ) -> None:
```

In `packages/core/tests/test_contracts.py`:

```diff
--- a/packages/core/tests/test_contracts.py
+++ b/packages/core/tests/test_contracts.py
@@ -49,6 +49,21 @@ def test_pipeline_error_carries_a_typed_reason() -> None:
     assert "stem was silent" in str(error)
 
 
+def test_only_an_internal_failure_is_retried_by_default() -> None:
+    """Ours may pass; the input's gives the same answer every time."""
+    assert PipelineError(FailureReason.INTERNAL, "m").retryable
+    assert not PipelineError(FailureReason.TOO_LONG, "m").retryable
+    assert not PipelineError(FailureReason.FETCH_FAILED, "m").retryable
+
+
+def test_a_failure_can_say_whether_it_is_retryable() -> None:
+    network = PipelineError(FailureReason.FETCH_FAILED, "m", retryable=True)
+    refused = PipelineError(FailureReason.INTERNAL, "m", retryable=False)
+
+    assert network.retryable
+    assert not refused.retryable
+
+
 def test_note_event_is_immutable() -> None:
     event = NoteEvent(onset=1.0, duration=0.5, midi=52, confidence=0.8)
 
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/core/tests/test_contracts.py apps/worker/tests/test_runner.py`
Expected: FAIL at collection: `TypeError: PipelineError.__init__() got an unexpected keyword argument 'retryable'` (test_runner.py builds `UPSTREAM_DOWN` at import).

- [x] **Step 3: Implement**

In `apps/worker/src/guitarvis_worker/runner.py`:

```diff
--- a/apps/worker/src/guitarvis_worker/runner.py
+++ b/apps/worker/src/guitarvis_worker/runner.py
@@ -130,17 +130,17 @@ def process_job(job_id: str, deps: WorkerDeps, *, retries_left: int) -> None:
         # not a row left running until reconciliation notices it.
         stored = deps.store.succeed(job_id, document=document, stem_key=stem_key)
     except PipelineError as error:
-        if error.reason is FailureReason.INTERNAL:
-            # Ours, not the file's — Demucs killed for memory, say — so it
-            # may pass, and its detail is for the log, not the user.
-            _failed_attempt(job_id, deps, progress, retries_left)
+        if error.retryable:
+            # It may pass: Demucs killed for memory, say, or a network that
+            # dropped while fetching a link.
+            _failed_attempt(job_id, deps, progress, retries_left, error)
             raise
-        # The file's: another attempt gives the same answer. Returning
+        # The input's: another attempt gives the same answer. Returning
         # normally tells RQ not to retry.
         deps.store.fail(
             job_id,
             reason=error.reason,
-            message=str(error),
+            message=_shown(error),
             stage=progress.stage,
             expect=JobStatus.RUNNING,
         )
@@ -156,26 +156,40 @@ def process_job(job_id: str, deps: WorkerDeps, *, retries_left: int) -> None:
 
 
 def _failed_attempt(
-    job_id: str, deps: WorkerDeps, progress: _ProgressWriter, retries_left: int
+    job_id: str,
+    deps: WorkerDeps,
+    progress: _ProgressWriter,
+    retries_left: int,
+    error: PipelineError | None = None,
 ) -> None:
     """Requeue the row for RQ's retry, or on the last attempt fail it.
 
     The caller re-raises, so RQ schedules the retry, or on the last attempt
     files the job in its FailedJobRegistry — the dead-letter queue — with the
-    traceback. The row is what the user sees.
+    traceback. The row is what the user sees: the error's own reason and
+    message when it has one that is not internal, so a fetch that kept
+    failing ends as fetch_failed, with its own words.
     """
     if retries_left > 0:
         deps.store.requeue(job_id)
         return
+    reason = FailureReason.INTERNAL if error is None else error.reason
     deps.store.fail(
         job_id,
-        reason=FailureReason.INTERNAL,
-        message=INTERNAL_FAILURE_MESSAGE,
+        reason=reason,
+        message=INTERNAL_FAILURE_MESSAGE if error is None else _shown(error),
         stage=progress.stage,
         expect=JobStatus.RUNNING,
     )
 
 
+def _shown(error: PipelineError) -> str:
+    """What the row says: an internal error's detail is for the log only."""
+    if error.reason is FailureReason.INTERNAL:
+        return INTERNAL_FAILURE_MESSAGE
+    return str(error)
+
+
 def _run(
     job: Job, deps: WorkerDeps, progress: _ProgressWriter
 ) -> tuple[dict[str, Any], str]:
```

In `packages/core/src/guitarvis_core/contracts.py`:

```diff
--- a/packages/core/src/guitarvis_core/contracts.py
+++ b/packages/core/src/guitarvis_core/contracts.py
@@ -30,11 +30,22 @@ class FailureReason(StrEnum):
 
 
 class PipelineError(Exception):
-    """A job failure carrying a typed reason."""
+    """A job failure carrying a typed reason, and whether to try again.
 
-    def __init__(self, reason: FailureReason, message: str) -> None:
+    By default only `internal` is retryable: that failure is ours, and may
+    pass. Any other reason is the input's, and another attempt gives the same
+    answer. A fetch is the exception, since the network fails and recovers on
+    its own, so the error that knows says so (spec 012).
+    """
+
+    def __init__(
+        self, reason: FailureReason, message: str, *, retryable: bool | None = None
+    ) -> None:
         super().__init__(message)
         self.reason = reason
+        self.retryable = (
+            reason is FailureReason.INTERNAL if retryable is None else retryable
+        )
 
 
 # Notes within this long of a group's first onset sound together: one voicing
```

- [x] **Step 4: Run them to verify they pass**

Run: `uv run pytest packages/core/tests/test_contracts.py apps/worker/tests/test_runner.py`
Expected: PASS. The upload tests in test_runner.py pass unchanged.

- [x] **Step 5: Commit**

```bash
make lint typecheck test
git add apps/worker/src/guitarvis_worker/runner.py \
  apps/worker/tests/test_runner.py \
  packages/core/src/guitarvis_core/contracts.py \
  packages/core/tests/test_contracts.py
git commit -m "feat(core): a pipeline error says whether to retry

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 2: Three reasons for links, and actions that say what to try

The vocabulary grows from nine to twelve: `link_unusable` and `links_disabled` join `FailureReason`, and `unsupported_link` joins `HttpReason`. `make schema` regenerates `api.ts`, and `messages.ts`'s `Record<Reason, …>` then refuses to compile until each has text, so the text lands in the same task. `too_long` and `fetch_failed` get the spec's new actions. These are the only upload tests this plan changes for the vocabulary: the ones that pin the list of reasons.

**Catalog rows:** The vocabulary every row's reason comes from.

**Files:**
- Modify: `apps/api/src/guitarvis_api/errors.py`
- Modify: `docs/CONVENTIONS.md`
- Modify: `packages/core/src/guitarvis_core/contracts.py`
- Modify: `web/src/api/messages.ts`
- Test: `apps/api/tests/test_api_schema.py`
- Test: `apps/api/tests/test_job_routes.py`
- Test: `packages/core/tests/test_contracts.py`
- Test: `web/src/api/client.test.ts`
- Generated, by `make schema`: `schema/api.schema.json`
- Generated, by `make schema`: `web/src/types/api.ts`

**Interfaces:**
- Produces: `FailureReason.LINK_UNUSABLE`, `FailureReason.LINKS_DISABLED`, `HttpReason.UNSUPPORTED_LINK`; `MESSAGES` entries for all three.

- [x] **Step 1: Write the failing tests**

In `apps/api/tests/test_api_schema.py`:

```diff
--- a/apps/api/tests/test_api_schema.py
+++ b/apps/api/tests/test_api_schema.py
@@ -38,18 +38,18 @@ def test_the_export_writes_exactly_the_committed_file(tmp_path: Path) -> None:
     )
 
 
-def test_the_schema_names_all_nine_reasons() -> None:
+def test_the_schema_names_all_twelve_reasons() -> None:
     definitions = api_schema()["$defs"]
     named = set(definitions["FailureReason"]["enum"]) | set(
         definitions["HttpReason"]["enum"]
     )
 
     assert named == {r.value for r in FailureReason} | {r.value for r in HttpReason}
-    assert len(named) == 9
+    assert len(named) == 12
 
 
 def test_a_failed_job_can_carry_only_a_failure_reason() -> None:
-    """The four HttpReason values describe a request, never a job."""
+    """The five HttpReason values describe a request, never a job."""
     reason = api_schema()["$defs"]["FailureView"]["properties"]["reason"]
 
     assert reason == {"$ref": "#/$defs/FailureReason"}
```

In `apps/api/tests/test_job_routes.py`:

```diff
--- a/apps/api/tests/test_job_routes.py
+++ b/apps/api/tests/test_job_routes.py
@@ -222,10 +222,16 @@ def test_an_unexpected_error_uses_the_error_body_and_hides_the_detail() -> None:
     }
 
 
-def test_the_http_layer_adds_exactly_four_reasons() -> None:
+def test_the_http_layer_adds_exactly_five_reasons() -> None:
     http = {reason.value for reason in HttpReason}
 
-    assert http == {"too_large", "too_many_jobs", "not_found", "not_ready"}
+    assert http == {
+        "too_large",
+        "too_many_jobs",
+        "not_found",
+        "not_ready",
+        "unsupported_link",
+    }
     assert not http & {reason.value for reason in FailureReason}
 
 
```

In `packages/core/tests/test_contracts.py`:

```diff
--- a/packages/core/tests/test_contracts.py
+++ b/packages/core/tests/test_contracts.py
@@ -38,6 +38,8 @@ def test_failure_reasons_match_the_spec_exactly() -> None:
         "no_guitar_detected",
         "too_long",
         "fetch_failed",
+        "link_unusable",
+        "links_disabled",
         "internal",
     }
 
```

In `web/src/api/client.test.ts`:

```diff
--- a/web/src/api/client.test.ts
+++ b/web/src/api/client.test.ts
@@ -241,7 +241,7 @@ describe("MESSAGES", () => {
       expect(message.headline.length).toBeGreaterThan(0);
       expect(message.action.length).toBeGreaterThan(0);
     }
-    expect(Object.keys(MESSAGES)).toHaveLength(10); // nine from the api, plus unreachable
+    expect(Object.keys(MESSAGES)).toHaveLength(13); // twelve from the api, plus unreachable
     expect(isReason("toString")).toBe(false);
   });
 });
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/core/tests/test_contracts.py apps/api/tests/test_api_schema.py apps/api/tests/test_job_routes.py && npm --prefix web test -- src/api/client.test.ts`
Expected: FAIL: `assert 9 == 12` in `test_the_schema_names_all_twelve_reasons`; the reason-set tests miss `link_unusable`, `links_disabled` and `unsupported_link`. (vitest is not reached; run it alone and it fails on `toHaveLength(13)`.)

- [x] **Step 3: Implement**

Then regenerate the contract artifacts: `make schema`. `schema/api.schema.json` and `web/src/types/api.ts` change; never edit them by hand.

In `apps/api/src/guitarvis_api/errors.py`:

```diff
--- a/apps/api/src/guitarvis_api/errors.py
+++ b/apps/api/src/guitarvis_api/errors.py
@@ -1,7 +1,7 @@
 """One error vocabulary for every client.
 
 Every error body is {"error": {"reason": ..., "message": ...}}. `reason` is a
-FailureReason value or one of the four HttpReason values only the HTTP layer
+FailureReason value or one of the five HttpReason values only the HTTP layer
 produces, so a client maps one vocabulary to text.
 """
 
@@ -26,6 +26,7 @@ class HttpReason(StrEnum):
     TOO_MANY_JOBS = "too_many_jobs"
     NOT_FOUND = "not_found"
     NOT_READY = "not_ready"
+    UNSUPPORTED_LINK = "unsupported_link"
 
 
 Reason = FailureReason | HttpReason
```

In `docs/CONVENTIONS.md`:

```diff
--- a/docs/CONVENTIONS.md
+++ b/docs/CONVENTIONS.md
@@ -12,7 +12,7 @@ Rules that outlive any one change. The reasoning lives in
   fought with type errors; the contract should.
 - **Failures carry a typed reason**, never a bare string. `FailureReason` in
   `guitarvis_core.contracts` and the api's `HttpReason` together are the closed
-  set the api can send (`Reason`, nine values). `web/src/api/messages.ts` maps
+  set the api can send (`Reason`, twelve values). `web/src/api/messages.ts` maps
   each of them, and the client's own `unreachable`, to actionable text. Adding
   a reason means updating that mapping, and `tsc` refuses the build until you
   do.
```

In `packages/core/src/guitarvis_core/contracts.py`:

```diff
--- a/packages/core/src/guitarvis_core/contracts.py
+++ b/packages/core/src/guitarvis_core/contracts.py
@@ -26,6 +26,8 @@ class FailureReason(StrEnum):
     NO_GUITAR_DETECTED = "no_guitar_detected"
     TOO_LONG = "too_long"
     FETCH_FAILED = "fetch_failed"
+    LINK_UNUSABLE = "link_unusable"
+    LINKS_DISABLED = "links_disabled"
     INTERNAL = "internal"
 
 
```

In `web/src/api/messages.ts`:

```diff
--- a/web/src/api/messages.ts
+++ b/web/src/api/messages.ts
@@ -30,11 +30,19 @@ const JOB_MESSAGES: Record<FailureReason, Message> = {
   },
   too_long: {
     headline: "That recording is too long.",
-    action: "Upload a single song, up to ten minutes long.",
+    action: "Try a single song, up to ten minutes long.",
   },
   fetch_failed: {
     headline: "We couldn't fetch that audio.",
-    action: "Upload the file itself instead.",
+    action: "Try again later, or upload the audio file.",
+  },
+  link_unusable: {
+    headline: "We can't use that video.",
+    action: "Try a different link, or upload the audio file.",
+  },
+  links_disabled: {
+    headline: "Links are turned off.",
+    action: "Upload the audio file instead.",
   },
   internal: {
     headline: "Something went wrong on our side.",
@@ -60,6 +68,10 @@ export const MESSAGES: Record<Reason, Message> = {
     headline: "That song isn't ready yet.",
     action: "Wait a moment, then reload the page.",
   },
+  unsupported_link: {
+    headline: "We can't use that link.",
+    action: "Paste a link to a single YouTube video, or upload the audio file.",
+  },
   unreachable: {
     headline: "We couldn't reach GuitarVis.",
     action: "Check your connection, then try again.",
```

- [x] **Step 4: Run them to verify they pass**

Run: `uv run pytest packages/core/tests/test_contracts.py apps/api/tests/test_api_schema.py apps/api/tests/test_job_routes.py && npm --prefix web test -- src/api/client.test.ts`
Expected: PASS, and `npm --prefix web run typecheck` passes with the new `MESSAGES`.

- [x] **Step 5: Commit**

```bash
make lint typecheck test
git add apps/api/src/guitarvis_api/errors.py \
  apps/api/tests/test_api_schema.py \
  apps/api/tests/test_job_routes.py \
  docs/CONVENTIONS.md \
  packages/core/src/guitarvis_core/contracts.py \
  packages/core/tests/test_contracts.py \
  schema/api.schema.json \
  web/src/api/client.test.ts \
  web/src/api/messages.ts \
  web/src/types/api.ts
git commit -m "feat: three reasons for links, and actions that say what to try

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 3: `GUITARVIS_URL_INGESTION`, off by default

The kill switch. `Settings` learns booleans, read as strictly as numbers: `1`/`true`/`on` and `0`/`false`/`off` in any case, anything else failing at start. `settings_env` writes `str(True)`, so the round trip reads `True`/`False` too.

**Catalog rows:** R1, W1 and the client's switch all read this.

**Files:**
- Modify: `packages/jobs/src/guitarvis_jobs/settings.py`
- Test: `packages/jobs/tests/test_settings.py`

**Interfaces:**
- Produces: `Settings.url_ingestion: bool = False`.

- [x] **Step 1: Write the failing tests**

In `packages/jobs/tests/test_settings.py`:

```diff
--- a/packages/jobs/tests/test_settings.py
+++ b/packages/jobs/tests/test_settings.py
@@ -18,6 +18,33 @@ def test_defaults_match_compose_and_the_spec() -> None:
     assert settings.max_active_jobs_per_ip == 2
     assert settings.job_timeout_sec == 1800
     assert settings.device is None
+    assert settings.url_ingestion is False  # links stay off until turned on
+
+
+@pytest.mark.parametrize(
+    ("raw", "expected"),
+    [
+        ("1", True),
+        ("true", True),
+        ("on", True),
+        ("TRUE", True),
+        (" On ", True),
+        ("0", False),
+        ("false", False),
+        ("off", False),
+        ("False", False),
+    ],
+)
+def test_a_switch_reads_the_words_people_write(raw: str, expected: bool) -> None:
+    settings = Settings.from_env({"GUITARVIS_URL_INGESTION": raw})
+
+    assert settings.url_ingestion is expected
+
+
+@pytest.mark.parametrize("raw", ["yes", "2", "enabled", "tru"])
+def test_a_switch_that_is_not_a_switch_fails_at_start(raw: str) -> None:
+    with pytest.raises(ValueError, match="GUITARVIS_URL_INGESTION"):
+        Settings.from_env({"GUITARVIS_URL_INGESTION": raw})
 
 
 def test_from_env_reads_prefixed_variables() -> None:
@@ -68,7 +95,10 @@ def test_settings_env_round_trips_through_from_env() -> None:
     from guitarvis_jobs.testing import settings_env
 
     settings = Settings(
-        redis_url="redis://elsewhere:6380/15", max_upload_mb=3, device="cuda"
+        redis_url="redis://elsewhere:6380/15",
+        max_upload_mb=3,
+        device="cuda",
+        url_ingestion=True,
     )
 
     assert Settings.from_env(settings_env(settings)) == settings
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/jobs/tests/test_settings.py`
Expected: FAIL: `AttributeError: 'Settings' object has no attribute 'url_ingestion'`.

- [x] **Step 3: Implement**

In `packages/jobs/src/guitarvis_jobs/settings.py`:

```diff
--- a/packages/jobs/src/guitarvis_jobs/settings.py
+++ b/packages/jobs/src/guitarvis_jobs/settings.py
@@ -34,6 +34,10 @@ class Settings:
     max_active_jobs_per_ip: int = 2
     job_timeout_sec: int = 1800
     device: str | None = None  # worker only: the torch device, e.g. "cuda"
+    # Spec 012's kill switch. Off unless a deployment turns it on, so one
+    # that has not decided fetches nothing. The api and the worker each read
+    # their own, at start.
+    url_ingestion: bool = False
 
     @property
     def max_upload_bytes(self) -> int:
@@ -48,10 +52,30 @@ class Settings:
             raw = env.get(name, "")
             if raw == "":
                 continue
-            values[spec.name] = _parse_int(name, raw) if spec.type is int else raw
+            if spec.type is int:
+                values[spec.name] = _parse_int(name, raw)
+            elif spec.type is bool:
+                values[spec.name] = _parse_bool(name, raw)
+            else:
+                values[spec.name] = raw
         return cls(**values)
 
 
+_TRUE = frozenset({"1", "true", "on"})
+_FALSE = frozenset({"0", "false", "off"})
+
+
+def _parse_bool(name: str, raw: str) -> bool:
+    """A switch, read as strictly as a number: a typo fails at start, rather
+    than leaving a feature in a state nobody chose."""
+    value = raw.strip().lower()
+    if value in _TRUE:
+        return True
+    if value in _FALSE:
+        return False
+    raise ValueError(f"{name} must be 1, true, on, 0, false or off, got {raw!r}")
+
+
 def _parse_int(name: str, raw: str) -> int:
     try:
         value = int(raw)
```

- [x] **Step 4: Run them to verify they pass**

Run: `uv run pytest packages/jobs/tests/test_settings.py`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
make lint typecheck test
git add packages/jobs/src/guitarvis_jobs/settings.py \
  packages/jobs/tests/test_settings.py
git commit -m "feat(jobs): GUITARVIS_URL_INGESTION, a switch that is off by default

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 4: `packages/fetch`, and the parser that reads links

A new workspace member, `guitarvis-fetch`, and its first module. `links.parse` is pure and standard-library only: it refuses with a `RefusalKind` (rows R4 to R7) or returns one video on one site, with a canonical URL built from the id and the dedupe key `sha256("youtube:" + id)`. The package depends on core only, for now; yt-dlp arrives with the child in Task 7. The package boundary test ships now, and is what Task 7's child must not break: importing any module but `child` loads no `yt_dlp`.

**Catalog rows:** R4, R5, R6, R7 (and Q1's dedupe key).

**Files:**
- Modify: `Makefile`
- Create: `packages/fetch/pyproject.toml`
- Create: `packages/fetch/src/guitarvis_fetch/__init__.py`
- Create: `packages/fetch/src/guitarvis_fetch/links.py`
- Create: `packages/fetch/src/guitarvis_fetch/py.typed`
- Modify: `pyproject.toml`
- Test: `packages/core/tests/test_py_typed_markers.py`
- Test (new): `packages/fetch/tests/test_fetch_package.py`
- Test (new): `packages/fetch/tests/test_links.py`
- Generated, by `uv lock`: `uv.lock`

**Interfaces:**
- Produces: `guitarvis_fetch.links`: `MAX_LINK_CHARS = 2048`, `RefusalKind`, `LinkRefused(kind, *, host, segment)`, `Link(site, video_id, canonical_url)` with `.dedupe_key`, `Site`, `YOUTUBE`, `SITES`, `parse(raw) -> Link`.

- [x] **Step 1: Write the failing tests**

In `packages/core/tests/test_py_typed_markers.py`:

```diff
--- a/packages/core/tests/test_py_typed_markers.py
+++ b/packages/core/tests/test_py_typed_markers.py
@@ -22,6 +22,7 @@ REPO_ROOT = Path(__file__).resolve().parents[3]
 WORKSPACE_PACKAGES = {
     "guitarvis_core": REPO_ROOT / "packages" / "core" / "src" / "guitarvis_core",
     "guitarvis_jobs": REPO_ROOT / "packages" / "jobs" / "src" / "guitarvis_jobs",
+    "guitarvis_fetch": REPO_ROOT / "packages" / "fetch" / "src" / "guitarvis_fetch",
     "guitarvis_api": REPO_ROOT / "apps" / "api" / "src" / "guitarvis_api",
     "guitarvis_worker": REPO_ROOT / "apps" / "worker" / "src" / "guitarvis_worker",
     "guitarvis_eval": REPO_ROOT / "apps" / "eval" / "src" / "guitarvis_eval",
```

Create `packages/fetch/tests/test_fetch_package.py`:

```python
"""guitarvis_fetch is walled off: importing it, child aside, loads no yt-dlp,
and it never imports the api, the worker or the ML stack."""

import subprocess
import sys

FORBIDDEN_ROOTS = {
    "yt_dlp",
    "torch",
    "demucs",
    "basic_pitch",
    "librosa",
    "numpy",
    "guitarvis_api",
    "guitarvis_worker",
}


def test_fetch_exposes_a_version() -> None:
    import guitarvis_fetch

    assert guitarvis_fetch.__version__ == "0.1.0"


def test_importing_every_module_but_the_child_loads_nothing_forbidden() -> None:
    probe = (
        "import importlib, pkgutil, sys, guitarvis_fetch as package;"
        "[importlib.import_module(m.name) for m in "
        "pkgutil.walk_packages(package.__path__, 'guitarvis_fetch.') "
        "if m.name != 'guitarvis_fetch.child'];"
        "leaked = {name.split('.')[0] for name in sys.modules}"
        f" & {FORBIDDEN_ROOTS!r};"
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "", (
        f"importing guitarvis_fetch pulled in: {result.stdout.strip()}"
    )
```

Create `packages/fetch/tests/test_links.py`:

```python
"""Every form of a YouTube link maps to one id and one canonical URL, and
every refusal to its kind (spec 012, *Links*; catalog rows R4 to R7)."""

import hashlib

import pytest
from guitarvis_fetch.links import MAX_LINK_CHARS, LinkRefused, RefusalKind, parse

ID = "dQw4w9WgXcQ"
CANONICAL = f"https://www.youtube.com/watch?v={ID}"


@pytest.mark.parametrize(
    "raw",
    [
        f"https://www.youtube.com/watch?v={ID}",
        f"http://www.youtube.com/watch?v={ID}",
        f"https://youtube.com/watch?v={ID}",
        f"https://m.youtube.com/watch?v={ID}",
        f"https://music.youtube.com/watch?v={ID}&feature=share",
        f"www.youtube.com/watch?v={ID}",
        f"youtube.com/watch?v={ID}",
        f"//www.youtube.com/watch?v={ID}",
        f"HTTPS://WWW.YOUTUBE.COM/watch?v={ID}",
        f"https://www.youtube.com./watch?v={ID}",
        f"  https://www.youtube.com/watch?v={ID}  \n",
        f"https://www.youtube.com/watch?v={ID}&t=42s",
        f"https://www.youtube.com/watch?v={ID}&list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI&index=3",
        f"https://www.youtube.com/watch?feature=youtu.be&v={ID}#t=30",
        f"https://www.youtube.com/watch/?v={ID}",
        f"https://youtu.be/{ID}",
        f"https://youtu.be/{ID}?si=B_RZg_I-lLaa7UU-",
        f"https://youtu.be/{ID}?t=1:30",
        f"youtu.be/{ID}/",
        f"https://www.youtube.com/shorts/{ID}",
        f"https://www.youtube.com/live/{ID}?si=abc",
        f"https://www.youtube.com/embed/{ID}",
        f"https://www.youtube-nocookie.com/embed/{ID}",
        f"https://youtube-nocookie.com/embed/{ID}",
        f"https://www.youtube.com/v/{ID}",
    ],
)
def test_every_accepted_form_is_one_video_with_one_canonical_url(raw: str) -> None:
    link = parse(raw)

    assert (link.site, link.video_id, link.canonical_url) == ("youtube", ID, CANONICAL)


def test_the_dedupe_key_is_the_videos_identity() -> None:
    expected = hashlib.sha256(f"youtube:{ID}".encode()).hexdigest()

    assert parse(f"https://youtu.be/{ID}").dedupe_key == expected
    assert parse(f"https://www.youtube.com/shorts/{ID}").dedupe_key == expected


def test_ids_keep_their_case_and_their_dashes() -> None:
    assert parse("https://youtu.be/a-B_c1D2e3F").video_id == "a-B_c1D2e3F"


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        # R4: not a link
        ("", RefusalKind.NOT_A_LINK),
        ("   \t ", RefusalKind.NOT_A_LINK),
        (f"https://www.youtube.com/watch?v={ID} and more", RefusalKind.NOT_A_LINK),
        (f"https://www.youtube.com/watch?v=​{ID}", RefusalKind.NOT_A_LINK),
        (f"https://www.youtube.com/watch?v={ID}\x00", RefusalKind.NOT_A_LINK),
        (
            f"https://www.youtube.com\\@evil.example/watch?v={ID}",
            RefusalKind.NOT_A_LINK,
        ),
        ("https://", RefusalKind.NOT_A_LINK),
        (f"https:///watch?v={ID}", RefusalKind.NOT_A_LINK),
        ("https://[::1/watch", RefusalKind.NOT_A_LINK),
        ("x" * (MAX_LINK_CHARS + 1), RefusalKind.NOT_A_LINK),
        # R5: not a web link
        ("javascript:alert(1)", RefusalKind.BAD_SCHEME),
        ("file:///etc/passwd", RefusalKind.BAD_SCHEME),
        (f"ftp://www.youtube.com/watch?v={ID}", RefusalKind.BAD_SCHEME),
        ("mailto:someone@example.com", RefusalKind.BAD_SCHEME),
        ("data:text/html,<script>alert(1)</script>", RefusalKind.BAD_SCHEME),
        # R6: not a supported site
        (
            f"https://www.youtube.com.example.net/watch?v={ID}",
            RefusalKind.UNSUPPORTED_SITE,
        ),
        (f"https://example.com/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        (f"https://notyoutube.com/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        (f"https://user@www.youtube.com/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        (
            f"https://www.youtube.com@evil.example/watch?v={ID}",
            RefusalKind.UNSUPPORTED_SITE,
        ),
        (f"https://www.youtube.com:443/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        (f"www.youtube.com:8080/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        (f"https://www.youtube.com:http/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        ("http://169.254.169.254/latest/meta-data/", RefusalKind.UNSUPPORTED_SITE),
        ("http://127.0.0.1:6379/", RefusalKind.UNSUPPORTED_SITE),
        (f"http://[::1]/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        (
            f"https://www.y\u043eutube.com/watch?v={ID}",
            RefusalKind.UNSUPPORTED_SITE,
        ),  # Cyrillic o
        (f"https://xn--yutube-wqf.com/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        ("https://localhost/", RefusalKind.UNSUPPORTED_SITE),
        # R7: a supported site, but not one video
        ("https://www.youtube.com/", RefusalKind.NOT_A_VIDEO),
        (
            "https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI",
            RefusalKind.NOT_A_VIDEO,
        ),
        ("https://www.youtube.com/@BlenderOfficial", RefusalKind.NOT_A_VIDEO),
        (
            "https://www.youtube.com/channel/UCSMOQeBJ2RAnuFungnQOxLg",
            RefusalKind.NOT_A_VIDEO,
        ),
        (
            "https://www.youtube.com/results?search_query=guitar",
            RefusalKind.NOT_A_VIDEO,
        ),
        (
            "https://www.youtube.com/clip/UgkxU2HSeGL_NvmDJ-nQJrlLwllwMDBdGZFs",
            RefusalKind.NOT_A_VIDEO,
        ),
        ("https://www.youtube.com/watch?v=", RefusalKind.NOT_A_VIDEO),
        ("https://www.youtube.com/watch?v=tooShort", RefusalKind.NOT_A_VIDEO),
        (f"https://www.youtube.com/watch?v={ID}x", RefusalKind.NOT_A_VIDEO),
        (
            f"https://www.youtube.com/watch?v={ID}&v=YE7VzlLtp-4",
            RefusalKind.NOT_A_VIDEO,
        ),
        (f"https://www.youtube.com/shorts/{ID}/extra", RefusalKind.NOT_A_VIDEO),
        (f"https://www.youtube.com/watch/{ID}", RefusalKind.NOT_A_VIDEO),
        ("https://youtu.be/", RefusalKind.NOT_A_VIDEO),
        (f"https://youtu.be/{ID}/{ID}", RefusalKind.NOT_A_VIDEO),
    ],
)
def test_each_refusal_has_its_kind(raw: str, kind: RefusalKind) -> None:
    with pytest.raises(LinkRefused) as excinfo:
        parse(raw)

    assert excinfo.value.kind is kind


def test_a_link_at_the_limit_is_read_and_one_over_is_not() -> None:
    padding = "&x=" + "a" * (MAX_LINK_CHARS - len(CANONICAL) - 3)
    at_limit = CANONICAL + padding
    assert len(at_limit) == MAX_LINK_CHARS

    assert parse(at_limit).video_id == ID
    with pytest.raises(LinkRefused):
        parse(at_limit + "a")


def test_a_refusal_carries_only_the_host_and_first_segment_for_the_log() -> None:
    with pytest.raises(LinkRefused) as excinfo:
        parse("https://www.youtube.com/playlist?list=PL123&si=SHARER-ID")

    refused = excinfo.value
    assert (refused.host, refused.segment) == ("www.youtube.com", "playlist")
    assert "SHARER-ID" not in str(refused)


def test_the_canonical_url_is_built_from_the_id_never_edited_from_the_input() -> None:
    link = parse(f"https://youtu.be/{ID}?si=SHARER-ID&t=42")

    assert link.canonical_url == CANONICAL
    assert "SHARER-ID" not in link.canonical_url
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/fetch/tests packages/core/tests/test_py_typed_markers.py`
Expected: FAIL at collection: `ModuleNotFoundError: No module named 'guitarvis_fetch'`.

- [x] **Step 3: Implement**

Then lock and install the new member: `uv lock && uv sync`. CI runs `uv sync --locked`, so `uv.lock` is committed with it. Also create the empty marker `packages/fetch/src/guitarvis_fetch/py.typed`.

In `Makefile`:

```diff
--- a/Makefile
+++ b/Makefile
@@ -41,8 +41,10 @@ ARGS ?=
 # packages/core/tests, apps/api/tests, apps/worker/tests, apps/eval/tests all
 # have distinct basenames), but a future contributor adding a same-named test
 # file to two packages will hit this and should rename one of the files.
-PY_SOURCES := packages/core/src packages/jobs/src apps/api/src apps/worker/src apps/eval/src \
-              packages/core/tests packages/jobs/tests apps/api/tests apps/worker/tests apps/eval/tests
+PY_SOURCES := packages/core/src packages/jobs/src packages/fetch/src \
+              apps/api/src apps/worker/src apps/eval/src \
+              packages/core/tests packages/jobs/tests packages/fetch/tests \
+              apps/api/tests apps/worker/tests apps/eval/tests
 
 .PHONY: help install lint format typecheck test test-py test-web \
         schema schema-check check eval sweep eval-data services migrate api worker web clean
```

Create `packages/fetch/pyproject.toml`:

```toml
[project]
name = "guitarvis-fetch"
version = "0.1.0"
description = "Audio from links: parsing, the yt-dlp child process, the failure catalog."
requires-python = ">=3.12"
dependencies = ["guitarvis-core"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/guitarvis_fetch"]
```

Create `packages/fetch/src/guitarvis_fetch/__init__.py`:

```python
"""Audio from links: the part of the system most likely to break, walled off.

Spec 012. Only the api and the worker depend on this package, and only
guitarvis_fetch.child imports yt-dlp, in a process of its own. Removing links
for good means deleting this package, one call in the api's app.py and one
branch in the worker's runner.
"""

__version__ = "0.1.0"
```

Create `packages/fetch/src/guitarvis_fetch/links.py`:

```python
"""Links: parse, refuse, canonicalize. Pure, and standard library only.

The user's string never reaches the network. A link is accepted only when a
site's parser reads one video id out of it, and what goes on is a URL built
fresh from that id: no YouTube id can spell a private address. Supported
sites are code, not config, because each needs a parser (spec 012, D6).
Adding one is a new Site here, with its own spec.
"""

import hashlib
import ipaddress
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import SplitResult, parse_qs, urlsplit

MAX_LINK_CHARS = 2048

_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_YOUTUBE_ID = re.compile(r"[A-Za-z0-9_-]{11}")


class RefusalKind(StrEnum):
    """Why a string is not a link we can use: rows R4 to R7."""

    NOT_A_LINK = "not_a_link"
    BAD_SCHEME = "bad_scheme"
    UNSUPPORTED_SITE = "unsupported_site"
    NOT_A_VIDEO = "not_a_video"


class LinkRefused(ValueError):
    """`parse` refused the string. `host` and `segment` are what may be
    logged of it: never the whole string, which can carry a share id."""

    def __init__(self, kind: RefusalKind, *, host: str = "", segment: str = "") -> None:
        super().__init__(kind.value)
        self.kind = kind
        self.host = host
        self.segment = segment


@dataclass(frozen=True)
class Link:
    """One video on one supported site."""

    site: str
    video_id: str
    canonical_url: str

    @property
    def dedupe_key(self) -> str:
        """What a link job's `content_hash` holds: the video's identity, so a
        repeat in any form finds the same job without asking the site."""
        return hashlib.sha256(f"{self.site}:{self.video_id}".encode()).hexdigest()


@dataclass(frozen=True)
class Site:
    name: str
    hosts: frozenset[str]
    video_id: Callable[[str, SplitResult], str | None]
    canonical_url: Callable[[str], str]


def _youtube_id(host: str, parts: SplitResult) -> str | None:
    """The one video a YouTube URL names, or None when it names anything else."""
    segments = [segment for segment in parts.path.split("/") if segment]
    if host == "youtu.be":
        candidate = segments[0] if len(segments) == 1 else None
    elif segments == ["watch"]:
        values = parse_qs(parts.query).get("v", [])
        candidate = values[0] if len(values) == 1 else None
    elif len(segments) == 2 and segments[0] in ("shorts", "live", "embed", "v"):
        candidate = segments[1]
    else:
        candidate = None
    if candidate is None or not _YOUTUBE_ID.fullmatch(candidate):
        return None
    return candidate


YOUTUBE = Site(
    name="youtube",
    hosts=frozenset(
        {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtube-nocookie.com",
            "www.youtube-nocookie.com",
            "youtu.be",
        }
    ),
    video_id=_youtube_id,
    canonical_url=lambda video_id: f"https://www.youtube.com/watch?v={video_id}",
)

SITES = (YOUTUBE,)


def parse(raw: str) -> Link:
    """The link in `raw`, or LinkRefused. No I/O.

    The canonical URL is built from the id alone, so every other parameter —
    `t=`, `list=` and the `si=` share id — is dropped, never edited out.
    """
    text = raw.strip()
    if not text or len(text) > MAX_LINK_CHARS or "\\" in text:
        raise LinkRefused(RefusalKind.NOT_A_LINK)
    if any(_is_space_or_control(character) for character in text):
        raise LinkRefused(RefusalKind.NOT_A_LINK)

    try:
        parts = urlsplit(_with_scheme(text))
    except ValueError:  # an unbalanced [ in the host, say
        raise LinkRefused(RefusalKind.NOT_A_LINK) from None
    if parts.scheme not in ("http", "https"):
        raise LinkRefused(RefusalKind.BAD_SCHEME)
    host = _host_of(parts)
    site = next((site for site in SITES if host in site.hosts), None)
    if site is None:
        raise LinkRefused(RefusalKind.UNSUPPORTED_SITE, host=host)
    video_id = site.video_id(host, parts)
    if video_id is None:
        raise LinkRefused(
            RefusalKind.NOT_A_VIDEO, host=host, segment=_first_segment(parts)
        )
    return Link(
        site=site.name, video_id=video_id, canonical_url=site.canonical_url(video_id)
    )


def _is_space_or_control(character: str) -> bool:
    # Category C is control, format (zero-width and direction marks among
    # them), private use, surrogate and unassigned.
    return character.isspace() or unicodedata.category(character).startswith("C")


def _with_scheme(text: str) -> str:
    """`text` with https:// added when it has no scheme.

    `javascript:` and `mailto:` have no slashes, but they are schemes; a
    host and port (`youtube.com:443`) look like one but have a dot.
    """
    if text.startswith("//"):
        return "https:" + text
    scheme = _SCHEME.match(text)
    if scheme is None:
        return "https://" + text
    if text[scheme.end() :].startswith("//") or "." not in scheme.group():
        return text
    return "https://" + text


def _host_of(parts: SplitResult) -> str:
    """The host, lowercased and without a trailing dot; LinkRefused when the
    authority is anything but a plain host name."""
    try:
        port = parts.port
    except ValueError:  # not a number, or out of range
        raise LinkRefused(RefusalKind.UNSUPPORTED_SITE) from None
    host = parts.hostname or ""
    if not host:
        raise LinkRefused(RefusalKind.NOT_A_LINK)
    if "@" in parts.netloc or port is not None or not host.isascii():
        raise LinkRefused(RefusalKind.UNSUPPORTED_SITE)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host.removesuffix(".")
    raise LinkRefused(RefusalKind.UNSUPPORTED_SITE)


def _first_segment(parts: SplitResult) -> str:
    return next((segment for segment in parts.path.split("/") if segment), "")
```

Create the empty file `packages/fetch/src/guitarvis_fetch/py.typed`.

In `pyproject.toml`:

```diff
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -6,6 +6,7 @@ requires-python = ">=3.12"
 dependencies = [
     "guitarvis-core",
     "guitarvis-jobs",
+    "guitarvis-fetch",
     "guitarvis-api",
     "guitarvis-worker",
     "guitarvis-eval",
@@ -37,11 +38,19 @@ override-dependencies = [
 ]
 
 [tool.uv.workspace]
-members = ["packages/core", "packages/jobs", "apps/api", "apps/worker", "apps/eval"]
+members = [
+    "packages/core",
+    "packages/jobs",
+    "packages/fetch",
+    "apps/api",
+    "apps/worker",
+    "apps/eval",
+]
 
 [tool.uv.sources]
 guitarvis-core = { workspace = true }
 guitarvis-jobs = { workspace = true }
+guitarvis-fetch = { workspace = true }
 guitarvis-api = { workspace = true }
 guitarvis-worker = { workspace = true }
 guitarvis-eval = { workspace = true }
```

- [x] **Step 4: Run them to verify they pass**

Run: `uv run pytest packages/fetch/tests packages/core/tests/test_py_typed_markers.py`
Expected: PASS: every accepted form maps to one id; every refusal to its kind.

- [x] **Step 5: Commit**

```bash
make lint typecheck test
git add Makefile \
  packages/core/tests/test_py_typed_markers.py \
  packages/fetch/pyproject.toml \
  packages/fetch/src/guitarvis_fetch/__init__.py \
  packages/fetch/src/guitarvis_fetch/links.py \
  packages/fetch/src/guitarvis_fetch/py.typed \
  packages/fetch/tests/test_fetch_package.py \
  packages/fetch/tests/test_links.py \
  pyproject.toml \
  uv.lock
git commit -m "feat(fetch): a workspace member for links, and the parser that reads them

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 5: The failure catalog, as data

The spec's catalog becomes `catalog.py`: every `FetchKind` maps to a reason, an HTTP status (the api's answer for a lookup), the user's message, a log level, a retry rule and whether its log line carries the child's stderr. The request's messages (R1 to R3, W1) and the refusals' (R4 to R7) live here too, so one test can check that no message anywhere carries yt-dlp's words. `INTERNAL_MESSAGE` repeats `guitarvis_jobs.models.INTERNAL_FAILURE_MESSAGE`, since this package does not depend on jobs; a test keeps the two equal.

**Catalog rows:** Every row's reason, status, message, level and retry, asserted row by row.

**Files:**
- Create: `packages/fetch/src/guitarvis_fetch/catalog.py`
- Test (new): `packages/fetch/tests/test_catalog.py`

**Interfaces:**
- Produces: `guitarvis_fetch.catalog`: `FetchKind` (25 kinds), `Retry` (`no`, `later`, `rq`), `Entry(reason, status, message, level, retry, tail)` with `.retryable` (`retry is Retry.RQ`), `CATALOG`, `REFUSALS`, `message_for(kind, *, duration_sec=None)`, `clock(seconds)`, and the messages `INTERNAL_MESSAGE`, `LINKS_OFF_MESSAGE`, `BAD_REQUEST_MESSAGE`, `REQUEST_TOO_LARGE_MESSAGE`, `LINKS_OFF_IN_QUEUE_MESSAGE`.

- [x] **Step 1: Write the failing tests**

Create `packages/fetch/tests/test_catalog.py`:

```python
"""The catalog is spec 012's table, kept as data: every kind has an entry, and
no message carries yt-dlp's words."""

import logging

import pytest
from guitarvis_core.contracts import FailureReason
from guitarvis_fetch.catalog import (
    BAD_REQUEST_MESSAGE,
    CATALOG,
    INTERNAL_MESSAGE,
    LINKS_OFF_IN_QUEUE_MESSAGE,
    LINKS_OFF_MESSAGE,
    REFUSALS,
    REQUEST_TOO_LARGE_MESSAGE,
    FetchKind,
    Retry,
    clock,
    message_for,
)
from guitarvis_fetch.links import RefusalKind
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE

UNUSABLE = FailureReason.LINK_UNUSABLE
FAILED = FailureReason.FETCH_FAILED
INFO, WARNING, ERROR = logging.INFO, logging.WARNING, logging.ERROR


def every_message() -> list[str]:
    return [
        *(message_for(kind, duration_sec=721) for kind in FetchKind),
        *REFUSALS.values(),
        LINKS_OFF_MESSAGE,
        LINKS_OFF_IN_QUEUE_MESSAGE,
        BAD_REQUEST_MESSAGE,
        REQUEST_TOO_LARGE_MESSAGE,
    ]


def test_every_fetch_kind_has_an_entry() -> None:
    assert set(CATALOG) == set(FetchKind)


def test_every_refusal_kind_has_a_message() -> None:
    assert set(REFUSALS) == set(RefusalKind)


@pytest.mark.parametrize("message", every_message())
def test_no_message_carries_ytdlp_text(message: str) -> None:
    lowered = message.lower()
    for forbidden in ("yt-dlp", "youtube-dl", "error:", "traceback", "[youtube]"):
        assert forbidden not in lowered, f"{forbidden!r} in {message!r}"


@pytest.mark.parametrize(
    ("row", "kind", "reason", "status", "level", "retry", "tail"),
    [
        ("L1", FetchKind.PRIVATE, UNUSABLE, 422, INFO, Retry.NO, False),
        ("L2", FetchKind.UNAVAILABLE, UNUSABLE, 422, INFO, Retry.NO, False),
        ("L3", FetchKind.GEO_RESTRICTED, UNUSABLE, 422, INFO, Retry.NO, False),
        ("L4", FetchKind.AGE_RESTRICTED, UNUSABLE, 422, INFO, Retry.NO, False),
        ("L5", FetchKind.MEMBERS_ONLY, UNUSABLE, 422, INFO, Retry.NO, False),
        ("L6", FetchKind.LIVE, UNUSABLE, 422, INFO, Retry.LATER, False),
        ("L7", FetchKind.UPCOMING, UNUSABLE, 422, INFO, Retry.LATER, False),
        ("L8", FetchKind.POST_LIVE, UNUSABLE, 422, INFO, Retry.LATER, False),
        ("L9", FetchKind.NO_DURATION, UNUSABLE, 422, WARNING, Retry.NO, False),
        ("L10", FetchKind.TOO_LONG, FailureReason.TOO_LONG, 422, INFO, Retry.NO, False),
        ("L11", FetchKind.NO_AUDIO, UNUSABLE, 422, WARNING, Retry.NO, False),
        ("L12", FetchKind.RATE_LIMITED, FAILED, 503, WARNING, Retry.LATER, False),
        ("L13", FetchKind.NETWORK, FAILED, 502, WARNING, Retry.RQ, False),
        ("L14", FetchKind.LOOKUP_TIMEOUT, FAILED, 504, WARNING, Retry.LATER, False),
        ("L15", FetchKind.EXTRACTOR_BROKEN, FAILED, 502, ERROR, Retry.LATER, True),
        ("L16", FetchKind.MISCONFIGURED, FAILED, 503, ERROR, Retry.LATER, False),
        ("L17", FetchKind.UNKNOWN, FAILED, 502, ERROR, Retry.RQ, True),
        ("L18", FetchKind.CRASHED, FailureReason.INTERNAL, 500, ERROR, Retry.RQ, True),
        ("D2", FetchKind.DOWNLOAD_TIMEOUT, FAILED, 504, WARNING, Retry.RQ, False),
        ("D5", FetchKind.MEDIA_REFUSED, FAILED, 502, ERROR, Retry.NO, False),
        ("D6", FetchKind.TOO_LARGE, UNUSABLE, 422, WARNING, Retry.NO, False),
        ("D7", FetchKind.EMPTY_DOWNLOAD, UNUSABLE, 422, WARNING, Retry.NO, False),
        ("D8", FetchKind.LOCAL_IO, FailureReason.INTERNAL, 500, ERROR, Retry.RQ, True),
        ("P1", FetchKind.UNREADABLE, UNUSABLE, 422, WARNING, Retry.NO, False),
        ("Q3", FetchKind.BUSY, FAILED, 503, WARNING, Retry.LATER, False),
    ],
)
def test_each_kind_is_its_catalog_row(
    row: str,
    kind: FetchKind,
    reason: FailureReason,
    status: int,
    level: int,
    retry: Retry,
    tail: bool,
) -> None:
    entry = CATALOG[kind]

    assert (entry.reason, entry.status, entry.level, entry.retry, entry.tail) == (
        reason,
        status,
        level,
        retry,
        tail,
    ), row


def test_only_upstream_trouble_and_our_own_failures_are_retried_by_rq() -> None:
    retried = {kind for kind, entry in CATALOG.items() if entry.retryable}

    assert retried == {
        FetchKind.NETWORK,
        FetchKind.DOWNLOAD_TIMEOUT,
        FetchKind.UNKNOWN,
        FetchKind.CRASHED,
        FetchKind.LOCAL_IO,
    }


def test_messages_shared_between_rows_are_the_same_words() -> None:
    assert (
        CATALOG[FetchKind.MISCONFIGURED].message
        == CATALOG[FetchKind.EXTRACTOR_BROKEN].message
    )  # L16 as L15
    assert (
        CATALOG[FetchKind.MEDIA_REFUSED].message == CATALOG[FetchKind.UNKNOWN].message
    )  # D5 as L17
    assert (
        CATALOG[FetchKind.EMPTY_DOWNLOAD].message == CATALOG[FetchKind.NO_AUDIO].message
    )  # D7 as L11


def test_internal_kinds_say_what_every_internal_failure_says() -> None:
    assert INTERNAL_MESSAGE == INTERNAL_FAILURE_MESSAGE
    for kind in (FetchKind.CRASHED, FetchKind.LOCAL_IO):
        assert message_for(kind) == INTERNAL_FAILURE_MESSAGE


def test_too_long_names_the_videos_length_and_the_limit() -> None:
    assert message_for(FetchKind.TOO_LONG, duration_sec=721) == (
        "That video is 12:01 long. The limit is 10 minutes: try a link to a "
        "single song."
    )
    assert "3:00:00 long" in message_for(FetchKind.TOO_LONG, duration_sec=10800)


@pytest.mark.parametrize(
    ("seconds", "shown"),
    [(0, "0:00"), (59.9, "0:59"), (601, "10:01"), (3723, "1:02:03")],
)
def test_clock(seconds: float, shown: str) -> None:
    assert clock(seconds) == shown
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/fetch/tests/test_catalog.py`
Expected: FAIL at collection: `ModuleNotFoundError: No module named 'guitarvis_fetch.catalog'`.

- [x] **Step 3: Implement**

Create `packages/fetch/src/guitarvis_fetch/catalog.py`:

```python
"""The failure catalog: what each way of failing to fetch a link means.

Spec 012's *Failure catalog*, as data. Every reason, HTTP status, message,
log level and retry rule a link failure produces comes from here, keyed by
kind, so the api, the worker and the tests cannot drift apart. The reason
says what to do, the message says why, and the kind, logged, says what broke
(D9). yt-dlp's own words never reach a message: they go to the log only.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum

from guitarvis_core.audio import MAX_DURATION_SEC
from guitarvis_core.contracts import FailureReason

from guitarvis_fetch.links import RefusalKind

# guitarvis_jobs.models.INTERNAL_FAILURE_MESSAGE, which this package does not
# depend on; test_catalog.py keeps the two the same.
INTERNAL_MESSAGE = "Something went wrong on our side. Try again later."

# The request (R1 to R3), and the worker's switch (W1).
LINKS_OFF_MESSAGE = (
    "Links are turned off on this server. Upload the audio file instead."
)
BAD_REQUEST_MESSAGE = "Send the link as JSON, in a field named `url`."
REQUEST_TOO_LARGE_MESSAGE = "That request is too large. Send only the link."
LINKS_OFF_IN_QUEUE_MESSAGE = (
    "Links were turned off before this song could be fetched. "
    "Upload the audio file instead."
)

REFUSALS: dict[RefusalKind, str] = {
    RefusalKind.NOT_A_LINK: (
        "That doesn't look like a link. Copy the video's address from your "
        "browser and paste it here."
    ),
    RefusalKind.BAD_SCHEME: (
        "Only web links (https://…) can be used. Copy the video's address "
        "from your browser."
    ),
    RefusalKind.UNSUPPORTED_SITE: (
        "We can only fetch songs from YouTube for now. For anything else, "
        "upload the audio file."
    ),
    RefusalKind.NOT_A_VIDEO: (
        "That link isn't to a single video. Open the video itself and copy its address."
    ),
}


class FetchKind(StrEnum):
    """What went wrong, finer than the reason. Logged, never shown."""

    PRIVATE = "private"
    UNAVAILABLE = "unavailable"
    GEO_RESTRICTED = "geo_restricted"
    AGE_RESTRICTED = "age_restricted"
    MEMBERS_ONLY = "members_only"
    LIVE = "live"
    UPCOMING = "upcoming"
    POST_LIVE = "post_live"
    NO_DURATION = "no_duration"
    TOO_LONG = "too_long"
    NO_AUDIO = "no_audio"
    RATE_LIMITED = "rate_limited"
    NETWORK = "network"
    LOOKUP_TIMEOUT = "lookup_timeout"
    EXTRACTOR_BROKEN = "extractor_broken"
    MISCONFIGURED = "misconfigured"
    UNKNOWN = "unknown"
    CRASHED = "crashed"
    DOWNLOAD_TIMEOUT = "download_timeout"
    MEDIA_REFUSED = "media_refused"
    TOO_LARGE = "too_large"
    EMPTY_DOWNLOAD = "empty_download"
    LOCAL_IO = "local_io"
    UNREADABLE = "unreadable"
    BUSY = "busy"


class Retry(StrEnum):
    """The catalog's Retry column."""

    NO = "no"  # the same link fails the same way
    LATER = "later"  # it may work later, but nothing retries it for the user
    RQ = "rq"  # the worker's attempt is retried automatically


@dataclass(frozen=True)
class Entry:
    """One catalog row. `status` is the api's answer for a lookup; a worker
    failure is recorded on the row instead. `tail` adds the end of the
    child's stderr to the log line."""

    reason: FailureReason
    status: int
    message: str
    level: int
    retry: Retry
    tail: bool = False

    @property
    def retryable(self) -> bool:
        return self.retry is Retry.RQ


_UNREACHABLE = (
    "We couldn't reach YouTube. Try again in a few minutes, or upload the audio file."
)
_BROKEN = (
    "We can't fetch from YouTube at the moment. Upload the audio file instead, "
    "or try the link again tomorrow."
)
_UNRECOGNISED = (
    "We couldn't fetch that video. Try again in a few minutes, or upload the "
    "audio file."
)
_NO_AUDIO = (
    "That video has no audio we can use. Try a different link, or upload the "
    "audio file."
)
_LIMITED = (
    "YouTube is limiting how often we can fetch right now. Try again later, or "
    "upload the audio file."
)

_UNUSABLE = FailureReason.LINK_UNUSABLE
_FAILED = FailureReason.FETCH_FAILED
_INFO, _WARNING, _ERROR = logging.INFO, logging.WARNING, logging.ERROR

CATALOG: dict[FetchKind, Entry] = {
    FetchKind.PRIVATE: Entry(  # L1
        _UNUSABLE,
        422,
        "That video is private. Try a different link, or upload the audio file.",
        _INFO,
        Retry.NO,
    ),
    FetchKind.UNAVAILABLE: Entry(  # L2
        _UNUSABLE,
        422,
        "That video isn't available. It may have been removed. Check the link, "
        "or upload the audio file.",
        _INFO,
        Retry.NO,
    ),
    FetchKind.GEO_RESTRICTED: Entry(  # L3
        _UNUSABLE,
        422,
        "That video can't be watched from where our server is. Try a different "
        "link, or upload the audio file.",
        _INFO,
        Retry.NO,
    ),
    FetchKind.AGE_RESTRICTED: Entry(  # L4
        _UNUSABLE,
        422,
        "That video is age-restricted, and we don't sign in to YouTube. Upload "
        "the audio file instead.",
        _INFO,
        Retry.NO,
    ),
    FetchKind.MEMBERS_ONLY: Entry(  # L5
        _UNUSABLE,
        422,
        "That video is only for channel members or paying viewers. Upload the "
        "audio file instead.",
        _INFO,
        Retry.NO,
    ),
    FetchKind.LIVE: Entry(  # L6
        _UNUSABLE,
        422,
        "That's a live stream. Once it has ended and been saved as a video, try "
        "the link again.",
        _INFO,
        Retry.LATER,
    ),
    FetchKind.UPCOMING: Entry(  # L7
        _UNUSABLE,
        422,
        "That video hasn't premiered yet. Try the link again once it has.",
        _INFO,
        Retry.LATER,
    ),
    FetchKind.POST_LIVE: Entry(  # L8
        _UNUSABLE,
        422,
        "That stream has only just ended, and YouTube is still processing it. "
        "Try the link again in a few hours.",
        _INFO,
        Retry.LATER,
    ),
    FetchKind.NO_DURATION: Entry(  # L9
        _UNUSABLE,
        422,
        "We couldn't tell how long that video is, so we didn't fetch it. Upload "
        "the audio file instead.",
        _WARNING,
        Retry.NO,
    ),
    FetchKind.TOO_LONG: Entry(  # L10; the message is message_for's
        FailureReason.TOO_LONG,
        422,
        "That video is {length} long. The limit is {limit} minutes: try a link "
        "to a single song.",
        _INFO,
        Retry.NO,
    ),
    FetchKind.NO_AUDIO: Entry(_UNUSABLE, 422, _NO_AUDIO, _WARNING, Retry.NO),  # L11
    FetchKind.RATE_LIMITED: Entry(
        _FAILED, 503, _LIMITED, _WARNING, Retry.LATER
    ),  # L12, D3
    FetchKind.NETWORK: Entry(_FAILED, 502, _UNREACHABLE, _WARNING, Retry.RQ),  # L13, D1
    FetchKind.LOOKUP_TIMEOUT: Entry(  # L14
        _FAILED,
        504,
        "YouTube took too long to answer. Try again in a few minutes, or upload "
        "the audio file.",
        _WARNING,
        Retry.LATER,
    ),
    FetchKind.EXTRACTOR_BROKEN: Entry(  # L15, D4
        _FAILED, 502, _BROKEN, _ERROR, Retry.LATER, tail=True
    ),
    FetchKind.MISCONFIGURED: Entry(
        _FAILED, 503, _BROKEN, _ERROR, Retry.LATER
    ),  # L16, D4
    FetchKind.UNKNOWN: Entry(  # L17, D10
        _FAILED, 502, _UNRECOGNISED, _ERROR, Retry.RQ, tail=True
    ),
    FetchKind.CRASHED: Entry(  # L18, D9
        FailureReason.INTERNAL, 500, INTERNAL_MESSAGE, _ERROR, Retry.RQ, tail=True
    ),
    FetchKind.DOWNLOAD_TIMEOUT: Entry(  # D2
        _FAILED,
        504,
        "Fetching that video took too long. Try again in a few minutes, or "
        "upload the audio file.",
        _WARNING,
        Retry.RQ,
    ),
    FetchKind.MEDIA_REFUSED: Entry(_FAILED, 502, _UNRECOGNISED, _ERROR, Retry.NO),  # D5
    FetchKind.TOO_LARGE: Entry(  # D6
        _UNUSABLE,
        422,
        "That video's audio is larger than we accept. Try a shorter video, or "
        "upload the audio file.",
        _WARNING,
        Retry.NO,
    ),
    FetchKind.EMPTY_DOWNLOAD: Entry(
        _UNUSABLE, 422, _NO_AUDIO, _WARNING, Retry.NO
    ),  # D7
    FetchKind.LOCAL_IO: Entry(  # D8
        FailureReason.INTERNAL, 500, INTERNAL_MESSAGE, _ERROR, Retry.RQ, tail=True
    ),
    FetchKind.UNREADABLE: Entry(  # P1
        _UNUSABLE,
        422,
        "The audio we fetched from that video couldn't be read. Try a different "
        "link, or upload the audio file.",
        _WARNING,
        Retry.NO,
    ),
    FetchKind.BUSY: Entry(  # Q3
        _FAILED,
        503,
        "We're checking a lot of links right now. Try again in a minute.",
        _WARNING,
        Retry.LATER,
    ),
}


def message_for(kind: FetchKind, *, duration_sec: float | None = None) -> str:
    """The user's message for `kind`. Only too_long has blanks to fill."""
    template = CATALOG[kind].message
    if kind is not FetchKind.TOO_LONG:
        return template
    length = "over" if duration_sec is None else clock(duration_sec)
    return template.format(length=length, limit=f"{MAX_DURATION_SEC / 60:.0f}")


def clock(seconds: float) -> str:
    """`12:01`, or `1:02:03` past an hour."""
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
```

- [x] **Step 4: Run them to verify they pass**

Run: `uv run pytest packages/fetch/tests/test_catalog.py`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
make lint typecheck test
git add packages/fetch/src/guitarvis_fetch/catalog.py \
  packages/fetch/tests/test_catalog.py
git commit -m "feat(fetch): the failure catalog, as data

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 6: `ChildFetcher`, the metadata checks, and the log lines

`fetcher.py` holds everything about fetching that does not import yt-dlp: the `UrlFetcher` protocol, `VideoInfo`, `Download`, `FetchError` (whose `message` is the catalog's and whose `detail` is for the log only), `check_info` (step 6, and the child's check before downloading), `find_deno`, the child's environment, the JSON-lines protocol, and the log lines. `ChildFetcher` runs the child in its own session, reads its lines on a thread, and kills the whole process group at the deadline or on any way out, a job timeout's `BaseException` included. It comes before the child (Task 7) because the child speaks the protocol defined here. Its tests run a fake child script, never yt-dlp. `guitarvis_fetch.testing` gives the api's and the worker's tests a `FakeFetcher`.

**Catalog rows:** L1, L4 to L10 by metadata (`check_info`); L14 and D2 (deadlines, process group); L16 (`find_deno`); L18 and D9 (crash, garbage, silence, a bad result).

**Files:**
- Create: `packages/fetch/src/guitarvis_fetch/fetcher.py`
- Create: `packages/fetch/src/guitarvis_fetch/testing.py`
- Test (new): `packages/fetch/tests/fake_child.py`
- Test (new): `packages/fetch/tests/test_fetcher.py`

**Interfaces:**
- Produces (`guitarvis_fetch.fetcher`): `LOOKUP_DEADLINE_SEC = 30`, `DOWNLOAD_DEADLINE_SEC = 300`, `MIN_DENO_VERSION = (2, 3, 0)`, `Versions`, `VideoInfo(title, duration_sec, live_status, availability, versions)`, `Download(path, info, format_id, ext, size)`, `FetchError(kind, detail, *, duration_sec, tail, exit_code, versions)` with `.entry`, `.message`, `.as_pipeline_error()`, `UrlFetcher` (`lookup(link)`, `download(link, work_dir, *, max_bytes, progress=None)`), `check_info(info) -> float`, `JsRuntime`, `find_deno(*, which=shutil.which)`, `child_environment(environ=None)`, `ChildFetcher(*, command=None, lookup_deadline_sec, download_deadline_sec)`, `log_failed(...)`, `log_fetched(...)`.
- Produces (`guitarvis_fetch.testing`): `FakeFetcher`, `video_info(...)`, `write_wav(path)`, `VERSIONS`.

- [x] **Step 1: Write the failing tests**

Create `packages/fetch/tests/fake_child.py`:

```python
"""A stand-in for guitarvis_fetch.child, run by ChildFetcher in the tests.

argv: SCENARIO [EXTRA] then what ChildFetcher appends (`lookup URL` or
`download URL WORK_DIR MAX_BYTES`). Never imported; run as a script.
"""

import json
import os
import subprocess
import sys
import time

VERSIONS = {"ytdlp": "2026.10.26", "js": "deno/2.5.4"}
INFO = {
    "title": "Elephants Dream - 10 years of open movies",
    "duration_sec": 37,
    "live_status": "not_live",
    "availability": "public",
}


def say(message: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> None:
    scenario, rest = sys.argv[1], sys.argv[2:]
    if scenario == "lookup-ok":
        say({"result": INFO, **VERSIONS})
    elif scenario == "download-ok":
        work_dir = rest[-2]
        path = os.path.join(work_dir, "source.m4a")
        with open(path, "wb") as out:
            out.write(b"\x00" * 1000)
        for fraction in (0.0, 0.25, float("nan"), 2.0, 1.0):
            say({"progress": fraction})
        say(
            {
                "result": {
                    **INFO,
                    "path": path,
                    "format_id": "140",
                    "ext": "m4a",
                    "size": 1000,
                },
                **VERSIONS,
            }
        )
    elif scenario == "error":
        sys.stderr.write("ERROR: [youtube] the tail of what yt-dlp said\n")
        sys.stderr.flush()
        say(
            {
                "error": {
                    "kind": rest[0],
                    "detail": "ERROR: [youtube] SENTINEL-4f2a",
                    "duration_sec": 721,
                },
                **VERSIONS,
            }
        )
    elif scenario == "unknown-kind":
        say({"error": {"kind": "brand_new", "detail": "?"}, **VERSIONS})
    elif scenario == "garbage":
        sys.stdout.write("Traceback (most recent call last): not json\n")
        sys.stdout.flush()
        time.sleep(60)
    elif scenario == "crash":
        sys.stderr.write("Traceback (most recent call last):\nMemoryError: boom\n")
        sys.exit(3)
    elif scenario == "silent":
        sys.exit(0)
    elif scenario == "bad-result":
        say(
            {
                "result": {
                    **INFO,
                    "path": "/nowhere",
                    "format_id": "140",
                    "ext": "m4a",
                },
                **VERSIONS,
            }
        )
    elif scenario == "env":
        seen = sorted(name for name in os.environ if name.startswith("GUITARVIS_"))
        info = {**INFO, "title": json.dumps([seen, os.environ.get("YTDLP_NO_PLUGINS")])}
        say({"result": info, **VERSIONS})
    elif scenario == "hang":
        # A grandchild, as yt-dlp starts Deno, and its pid for the test.
        grandchild = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        with open(rest[0], "w") as out:
            out.write(str(grandchild.pid))
        say({"progress": 0.1})
        time.sleep(60)
    else:
        raise SystemExit(f"unknown scenario {scenario}")


main()
```

Create `packages/fetch/tests/test_fetcher.py`:

```python
"""The UrlFetcher contract, the metadata checks, and ChildFetcher against a
fake child: results, progress, each error, garbage, a crash, and a hang
killed at its deadline along with its process group."""

import logging
import os
import stat
import sys
import time
from pathlib import Path

import pytest
from guitarvis_core.contracts import FailureReason
from guitarvis_fetch.catalog import FetchKind
from guitarvis_fetch.fetcher import (
    ChildFetcher,
    FetchError,
    UrlFetcher,
    Versions,
    VideoInfo,
    check_info,
    child_environment,
    find_deno,
    log_failed,
    log_fetched,
)
from guitarvis_fetch.links import parse
from guitarvis_fetch.testing import FakeFetcher, video_info

FAKE_CHILD = Path(__file__).with_name("fake_child.py")
LINK = parse("https://youtu.be/kPdv44HtEoA")
SENTINEL = "SENTINEL-4f2a"


def child(*scenario: str, **deadlines: float) -> ChildFetcher:
    return ChildFetcher(
        command=[sys.executable, "-I", str(FAKE_CHILD), *scenario], **deadlines
    )


def gone(pid: int) -> bool:
    """Whether `pid` is dead: no such process, or a zombie awaiting its reaper."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    status = Path(f"/proc/{pid}/stat")
    return status.exists() and status.read_text().split(")")[-1].split()[0] == "Z"


def wait_until_gone(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if gone(pid):
            return True
        time.sleep(0.05)
    return False


# The fetchers


def test_child_fetcher_and_the_fake_satisfy_the_protocol() -> None:
    assert isinstance(ChildFetcher(), UrlFetcher)
    assert isinstance(FakeFetcher(), UrlFetcher)


# check_info: step 6, and the child's check before downloading


@pytest.mark.parametrize(
    ("info", "kind"),
    [
        (video_info(live_status="is_live", duration_sec=None), FetchKind.LIVE),  # L6
        (video_info(live_status="is_upcoming"), FetchKind.UPCOMING),  # L7
        (
            video_info(live_status="post_live", duration_sec=7200),
            FetchKind.POST_LIVE,
        ),  # L8
        (video_info(availability="private"), FetchKind.PRIVATE),  # L1
        (video_info(availability="needs_auth"), FetchKind.AGE_RESTRICTED),  # L4
        (video_info(availability="subscriber_only"), FetchKind.MEMBERS_ONLY),  # L5
        (video_info(availability="premium_only"), FetchKind.MEMBERS_ONLY),  # L5
        (video_info(duration_sec=None), FetchKind.NO_DURATION),  # L9
        (video_info(duration_sec=0), FetchKind.NO_DURATION),  # L9
        (video_info(duration_sec=float("nan")), FetchKind.NO_DURATION),  # L9
        (video_info(duration_sec=721), FetchKind.TOO_LONG),  # L10
    ],
)
def test_check_info_refuses_what_we_cannot_use(
    info: VideoInfo, kind: FetchKind
) -> None:
    with pytest.raises(FetchError) as excinfo:
        check_info(info)

    assert excinfo.value.kind is kind


@pytest.mark.parametrize("live_status", ["not_live", "was_live", None])
def test_check_info_passes_a_finished_video_and_gives_its_length(
    live_status: str | None,
) -> None:
    assert check_info(video_info(live_status=live_status, duration_sec=600)) == 600


def test_too_long_carries_the_length_for_its_message() -> None:
    with pytest.raises(FetchError) as excinfo:
        check_info(video_info(duration_sec=721))

    assert "12:01" in excinfo.value.message


# FetchError: the catalog's words out, yt-dlp's words in the log only


def test_a_fetch_errors_message_is_the_catalogs_never_its_detail() -> None:
    error = FetchError(
        FetchKind.PRIVATE, f"ERROR: [youtube] x: Private video. {SENTINEL}"
    )

    assert SENTINEL not in error.message
    assert error.message.startswith("That video is private.")


@pytest.mark.parametrize(
    ("kind", "reason", "retryable"),
    [
        (FetchKind.NETWORK, FailureReason.FETCH_FAILED, True),
        (FetchKind.RATE_LIMITED, FailureReason.FETCH_FAILED, False),
        (FetchKind.PRIVATE, FailureReason.LINK_UNUSABLE, False),
        (FetchKind.CRASHED, FailureReason.INTERNAL, True),
    ],
)
def test_as_a_pipeline_error_a_fetch_error_keeps_its_row(
    kind: FetchKind, reason: FailureReason, retryable: bool
) -> None:
    error = FetchError(kind, SENTINEL).as_pipeline_error()

    assert (error.reason, error.retryable) == (reason, retryable)
    assert SENTINEL not in str(error)


# The JavaScript runtime


def fake_deno(directory: Path, answer: str) -> str:
    path = directory / "deno"
    path.write_text(f"#!/bin/sh\necho '{answer}'\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_find_deno_takes_a_new_enough_deno(tmp_path: Path) -> None:
    path = fake_deno(tmp_path, "deno 2.5.4 (stable, release, x86_64-unknown-linux-gnu)")

    found = find_deno(which=lambda name: path)

    assert found is not None
    assert (found.path, found.label) == (path, "deno/2.5.4")


@pytest.mark.parametrize("answer", ["deno 2.2.9 (stable)", "node v22.20.0", ""])
def test_find_deno_refuses_an_old_one_or_something_else(
    tmp_path: Path, answer: str
) -> None:
    path = fake_deno(tmp_path, answer)

    assert find_deno(which=lambda name: path) is None


def test_find_deno_finds_nothing_when_there_is_nothing() -> None:
    assert find_deno(which=lambda name: None) is None


# ChildFetcher


def test_the_childs_environment_has_no_guitarvis_variables() -> None:
    env = child_environment(
        {
            "PATH": "/usr/bin",
            "GUITARVIS_DATABASE_URL": "postgresql://secret",
            "HOME": "/h",
        }
    )

    assert env == {"PATH": "/usr/bin", "HOME": "/h", "YTDLP_NO_PLUGINS": "1"}


def test_the_child_runs_without_the_parents_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GUITARVIS_S3_SECRET_KEY", "hunter2")

    info = child("env").lookup(LINK)

    assert info.title == '[[], "1"]'  # no GUITARVIS_* names; plugins off


def test_a_lookup_returns_the_childs_result() -> None:
    info = child("lookup-ok").lookup(LINK)

    assert info == VideoInfo(
        title="Elephants Dream - 10 years of open movies",
        duration_sec=37.0,
        live_status="not_live",
        availability="public",
        versions=Versions(ytdlp="2026.10.26", js="deno/2.5.4"),
    )


def test_a_download_reports_clamped_progress_and_returns_the_file(
    tmp_path: Path,
) -> None:
    seen: list[float] = []

    download = child("download-ok").download(
        LINK, tmp_path, max_bytes=10_000, progress=seen.append
    )

    assert seen == [0.0, 0.25, 1.0, 1.0]  # NaN dropped, 2.0 clamped
    assert download.path == tmp_path / "source.m4a"
    assert (download.format_id, download.ext, download.size) == ("140", "m4a", 1000)
    assert download.info.title == "Elephants Dream - 10 years of open movies"


@pytest.mark.parametrize("kind", list(FetchKind))
def test_a_classified_error_comes_back_as_its_kind(kind: FetchKind) -> None:
    with pytest.raises(FetchError) as excinfo:
        child("error", kind.value).lookup(LINK)

    error = excinfo.value
    assert error.kind is kind
    assert SENTINEL in error.detail  # for the log
    assert SENTINEL not in error.message  # never for the user
    assert "the tail of what yt-dlp said" in error.tail
    assert error.versions == Versions(ytdlp="2026.10.26", js="deno/2.5.4")


def test_too_long_from_the_child_keeps_its_length() -> None:
    with pytest.raises(FetchError) as excinfo:
        child("error", "too_long").lookup(LINK)

    assert "12:01" in excinfo.value.message


def test_a_kind_this_build_does_not_know_is_unknown() -> None:
    with pytest.raises(FetchError) as excinfo:
        child("unknown-kind").lookup(LINK)

    assert excinfo.value.kind is FetchKind.UNKNOWN


def test_garbage_on_stdout_is_a_crash_at_once() -> None:  # L18
    started = time.monotonic()
    with pytest.raises(FetchError) as excinfo:
        child("garbage").lookup(LINK)

    assert excinfo.value.kind is FetchKind.CRASHED
    assert time.monotonic() - started < 10  # not the 30 s deadline


def test_a_child_that_crashes_is_a_crash_with_its_exit_code_and_tail() -> (
    None
):  # L18, D9
    with pytest.raises(FetchError) as excinfo:
        child("crash").lookup(LINK)

    error = excinfo.value
    assert (error.kind, error.exit_code) == (FetchKind.CRASHED, 3)
    assert "MemoryError: boom" in error.tail


def test_a_child_that_exits_without_an_answer_is_a_crash() -> None:  # L18
    with pytest.raises(FetchError) as excinfo:
        child("silent").lookup(LINK)

    assert (excinfo.value.kind, excinfo.value.exit_code) == (FetchKind.CRASHED, 0)


def test_a_result_missing_a_field_is_a_crash(tmp_path: Path) -> None:
    with pytest.raises(FetchError) as excinfo:
        child("bad-result").download(LINK, tmp_path, max_bytes=10)

    assert excinfo.value.kind is FetchKind.CRASHED


def test_a_lookup_past_its_deadline_is_killed_with_its_process_group(
    tmp_path: Path,
) -> None:  # L14
    pid_file = tmp_path / "grandchild.pid"
    started = time.monotonic()

    with pytest.raises(FetchError) as excinfo:
        child("hang", str(pid_file), lookup_deadline_sec=2).lookup(LINK)

    assert excinfo.value.kind is FetchKind.LOOKUP_TIMEOUT
    assert time.monotonic() - started < 10
    assert wait_until_gone(int(pid_file.read_text())), (
        "the grandchild outlived its group"
    )


def test_a_download_past_its_deadline_is_a_download_timeout(
    tmp_path: Path,
) -> None:  # D2
    with pytest.raises(FetchError) as excinfo:
        child("hang", str(tmp_path / "pid"), download_deadline_sec=2).download(
            LINK, tmp_path, max_bytes=10
        )

    assert excinfo.value.kind is FetchKind.DOWNLOAD_TIMEOUT


class JobTimeout(BaseException):
    """Stands in for the worker's JobTimedOut, which is not an Exception."""


def test_a_job_timeout_mid_download_still_kills_the_child(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"

    def time_runs_out(fraction: float) -> None:
        raise JobTimeout

    with pytest.raises(JobTimeout):
        child("hang", str(pid_file)).download(
            LINK, tmp_path, max_bytes=10, progress=time_runs_out
        )

    assert wait_until_gone(int(pid_file.read_text()))


# The log lines


def test_a_failure_is_one_line_at_its_catalog_level(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = logging.getLogger("test.fetch")
    error = FetchError(
        FetchKind.PRIVATE,
        "x" * 600,
        tail="STDERR-TAIL",
        versions=Versions(ytdlp="2026.10.26", js="deno/2.5.4"),
    )

    with caplog.at_level(logging.INFO, logger="test.fetch"):
        log_failed(log, error, phase="lookup", link=LINK, elapsed_sec=1.84)

    [record] = caplog.records
    assert record.levelno == logging.INFO
    line = record.getMessage()
    assert line.startswith(
        "link fetch failed kind=private phase=lookup site=youtube "
        "video=kPdv44HtEoA job=- attempt=- elapsed=1.8s ytdlp=2026.10.26 "
        'js=deno/2.5.4 detail="'
    )
    assert "x" * 500 + '"' in line and "x" * 501 not in line
    assert "STDERR-TAIL" not in line  # INFO rows carry no tail


def test_an_error_level_failure_adds_the_childs_stderr(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = logging.getLogger("test.fetch")
    error = FetchError(
        FetchKind.EXTRACTOR_BROKEN, "Unable to extract", tail="STDERR-TAIL"
    )

    with caplog.at_level(logging.INFO, logger="test.fetch"):
        log_failed(
            log,
            error,
            phase="download",
            link=LINK,
            elapsed_sec=3,
            job_id="j",
            attempt=2,
        )

    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert "job=j attempt=2" in record.getMessage()
    assert record.getMessage().endswith("\nSTDERR-TAIL")


def test_a_success_is_logged_with_its_format(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    log = logging.getLogger("test.fetch")
    download = FakeFetcher(ext="m4a", content=b"abc").download(
        LINK, tmp_path, max_bytes=10
    )

    with caplog.at_level(logging.INFO, logger="test.fetch"):
        log_fetched(
            log,
            phase="download",
            link=LINK,
            versions=download.info.versions,
            elapsed_sec=2.0,
            download=download,
        )

    assert caplog.records[0].getMessage().endswith("format=140 ext=m4a bytes=3")
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/fetch/tests/test_fetcher.py`
Expected: FAIL at collection: `ModuleNotFoundError: No module named 'guitarvis_fetch.fetcher'`.

- [x] **Step 3: Implement**

Create `packages/fetch/src/guitarvis_fetch/fetcher.py`:

```python
"""Fetching: the UrlFetcher contract, and ChildFetcher, which runs yt-dlp in a
process of its own (spec 012, *Where yt-dlp runs*).

Nothing here imports yt-dlp. ChildFetcher starts `python -I -m
guitarvis_fetch.child`, reads JSON lines from it, and kills its whole process
group at a deadline or on any way out, which a thread could not do. The
child runs with every GUITARVIS_* variable removed, so it cannot read the
database URL or the storage secret.

The protocol, one JSON object per line on the child's stdout:

    {"progress": 0.42}
    {"result": {...}, "ytdlp": "2026.10.26", "js": "deno/2.5.4"}
    {"error": {"kind": "private", "detail": "...", "duration_sec": null},
     "ytdlp": "...", "js": "..."}
"""

import contextlib
import json
import logging
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Protocol, runtime_checkable

from guitarvis_core.audio import MAX_DURATION_SEC, check_duration
from guitarvis_core.contracts import FailureReason, PipelineError

from guitarvis_fetch.catalog import CATALOG, Entry, FetchKind, message_for
from guitarvis_fetch.links import Link

LOOKUP_DEADLINE_SEC = 30.0
DOWNLOAD_DEADLINE_SEC = 300.0
DETAIL_CHARS = 500
TAIL_BYTES = 2048
# yt_dlp.utils._jsruntime.DenoJsRuntime.MIN_SUPPORTED_VERSION in 2026.10.26.
MIN_DENO_VERSION = (2, 3, 0)

Progress = Callable[[float], None]


@dataclass(frozen=True)
class Versions:
    """Which yt-dlp and which JavaScript runtime answered: on every log line,
    so "it broke on Tuesday" can be traced to a version."""

    ytdlp: str = "-"
    js: str = "-"


@dataclass(frozen=True)
class VideoInfo:
    """What a lookup learns. `live_status` and `availability` are yt-dlp's
    words for them; `duration_sec` is None when the metadata has none."""

    title: str
    duration_sec: float | None
    live_status: str | None = None
    availability: str | None = None
    versions: Versions = field(default_factory=Versions)


@dataclass(frozen=True)
class Download:
    """A downloaded file in the job's directory, and what it came from."""

    path: Path
    info: VideoInfo
    format_id: str
    ext: str
    size: int


class FetchError(Exception):
    """A classified failure. `kind` picks the catalog row; `detail` is
    yt-dlp's text and `tail` the end of the child's stderr, for the log
    only. `str()` of this error is a log line, never a message."""

    def __init__(
        self,
        kind: FetchKind,
        detail: str = "",
        *,
        duration_sec: float | None = None,
        tail: str = "",
        exit_code: int | None = None,
        versions: Versions | None = None,
    ) -> None:
        super().__init__(f"{kind.value}: {detail}")
        self.kind = kind
        self.detail = detail
        self.duration_sec = duration_sec
        self.tail = tail
        self.exit_code = exit_code
        self.versions = versions or Versions()

    @property
    def entry(self) -> Entry:
        return CATALOG[self.kind]

    @property
    def message(self) -> str:
        """What the user is told: the catalog's words, never yt-dlp's."""
        return message_for(self.kind, duration_sec=self.duration_sec)

    def as_pipeline_error(self) -> PipelineError:
        """The worker's form of this failure: reason, message, retry rule."""
        return PipelineError(
            self.entry.reason, self.message, retryable=self.entry.retryable
        )


@runtime_checkable
class UrlFetcher(Protocol):
    """Looks a link up, and downloads its audio. Raises FetchError."""

    def lookup(self, link: Link) -> VideoInfo: ...

    def download(
        self,
        link: Link,
        work_dir: Path,
        *,
        max_bytes: int,
        progress: Progress | None = None,
    ) -> Download: ...


_REFUSED_LIVE = {
    "is_live": FetchKind.LIVE,
    "is_upcoming": FetchKind.UPCOMING,
    "post_live": FetchKind.POST_LIVE,
}
_REFUSED_AVAILABILITY = {
    "private": FetchKind.PRIVATE,
    "premium_only": FetchKind.MEMBERS_ONLY,
    "subscriber_only": FetchKind.MEMBERS_ONLY,
    "needs_auth": FetchKind.AGE_RESTRICTED,
}


def check_info(info: VideoInfo, *, max_duration_sec: float = MAX_DURATION_SEC) -> float:
    """Refuse a video we cannot use, from its metadata alone; else its length.

    The api runs this after a lookup (step 6), and the child again on fresh
    metadata before downloading, since a video can change while queued.
    Missing duration is refused here, not left to ffprobe: the size cap
    would stop a three-hour download only after 150 MB of it had arrived.
    """
    live = _REFUSED_LIVE.get(info.live_status or "")
    if live is not None:
        raise FetchError(live, f"live_status={info.live_status}")
    refused = _REFUSED_AVAILABILITY.get(info.availability or "")
    if refused is not None:
        raise FetchError(refused, f"availability={info.availability}")
    if info.duration_sec is None:
        raise FetchError(FetchKind.NO_DURATION, "no duration in the metadata")
    try:
        check_duration(info.duration_sec, max_duration_sec)
    except PipelineError as error:
        if error.reason is FailureReason.TOO_LONG:
            raise FetchError(
                FetchKind.TOO_LONG,
                f"duration={info.duration_sec}",
                duration_sec=info.duration_sec,
            ) from None
        raise FetchError(  # zero, negative or NaN
            FetchKind.NO_DURATION, f"duration={info.duration_sec}"
        ) from None
    return info.duration_sec


@dataclass(frozen=True)
class JsRuntime:
    name: str
    path: str
    version: str

    @property
    def label(self) -> str:
        return f"{self.name}/{self.version}"


_DENO_VERSION = re.compile(r"deno (\d+)\.(\d+)\.(\d+)")


def find_deno(*, which: Callable[[str], str | None] = shutil.which) -> JsRuntime | None:
    """Deno, where yt-dlp itself looks first — beside this Python, then on
    PATH — if it is new enough for the pinned yt-dlp. None otherwise."""
    beside = Path(sysconfig.get_path("scripts")) / "deno"
    for candidate in (str(beside) if beside.is_file() else None, which("deno")):
        if candidate is None:
            continue
        try:
            answer = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        match = _DENO_VERSION.search(answer.stdout)
        if match is None:
            continue
        version = tuple(int(part) for part in match.groups())
        if version >= MIN_DENO_VERSION:
            return JsRuntime("deno", candidate, ".".join(match.groups()))
    return None


def child_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The child's environment: ours, minus every GUITARVIS_* variable, with
    yt-dlp's plugins switched off (it loads them from config directories)."""
    source = os.environ if environ is None else environ
    env = {
        name: value
        for name, value in source.items()
        if not name.startswith("GUITARVIS_")
    }
    env["YTDLP_NO_PLUGINS"] = "1"
    return env


class ChildFetcher:
    """Implements UrlFetcher with yt-dlp, in `python -I -m guitarvis_fetch.child`.

    `command` is for tests, which run a fake child instead.
    """

    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        lookup_deadline_sec: float = LOOKUP_DEADLINE_SEC,
        download_deadline_sec: float = DOWNLOAD_DEADLINE_SEC,
    ) -> None:
        self._command = (
            list(command)
            if command is not None
            else [sys.executable, "-I", "-m", "guitarvis_fetch.child"]
        )
        self._lookup_deadline_sec = lookup_deadline_sec
        self._download_deadline_sec = download_deadline_sec

    def lookup(self, link: Link) -> VideoInfo:
        result, versions = self._run(
            ["lookup", link.canonical_url],
            deadline_sec=self._lookup_deadline_sec,
            timeout_kind=FetchKind.LOOKUP_TIMEOUT,
        )
        return _video_info(result, versions)

    def download(
        self,
        link: Link,
        work_dir: Path,
        *,
        max_bytes: int,
        progress: Progress | None = None,
    ) -> Download:
        result, versions = self._run(
            ["download", link.canonical_url, str(work_dir), str(max_bytes)],
            deadline_sec=self._download_deadline_sec,
            timeout_kind=FetchKind.DOWNLOAD_TIMEOUT,
            progress=progress,
        )
        try:
            return Download(
                path=Path(_text(result, "path")),
                info=_video_info(result, versions),
                format_id=_text(result, "format_id"),
                ext=_text(result, "ext"),
                size=int(result["size"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FetchError(
                FetchKind.CRASHED, f"unreadable result: {error!r}", versions=versions
            ) from None

    def _run(
        self,
        args: list[str],
        *,
        deadline_sec: float,
        timeout_kind: FetchKind,
        progress: Progress | None = None,
    ) -> tuple[dict[str, Any], Versions]:
        with tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                [*self._command, *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=stderr,
                env=child_environment(),
                start_new_session=True,  # its own process group, to kill whole
            )
            lines: queue.Queue[bytes | None] = queue.Queue()
            reader = threading.Thread(
                target=_read_lines, args=(process.stdout, lines), daemon=True
            )
            reader.start()
            try:
                return _answer(
                    lines,
                    process,
                    stderr,
                    deadline=time.monotonic() + deadline_sec,
                    timeout_kind=timeout_kind,
                    progress=progress,
                )
            finally:
                # Every way out, a job timeout's BaseException included: no
                # child, and no JavaScript runtime it started, outlives this.
                _kill_group(process)
                process.wait()


def _answer(
    lines: "queue.Queue[bytes | None]",
    process: "subprocess.Popen[bytes]",
    stderr: IO[bytes],
    *,
    deadline: float,
    timeout_kind: FetchKind,
    progress: Progress | None,
) -> tuple[dict[str, Any], Versions]:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError(
                timeout_kind, "no answer before the deadline", tail=_tail(stderr)
            )
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            continue
        if line is None:
            code = _exit_code(process)
            raise FetchError(
                FetchKind.CRASHED,
                f"exited with {code} and no answer",
                tail=_tail(stderr),
                exit_code=code,
            )
        message = _decode(line, stderr)
        versions = Versions(
            ytdlp=str(message.get("ytdlp") or "-"), js=str(message.get("js") or "-")
        )
        if "progress" in message:
            if progress is not None:
                _report(progress, message["progress"])
            continue
        if isinstance(message.get("result"), dict):
            return message["result"], versions
        if isinstance(message.get("error"), dict):
            raise _error_from(message["error"], versions, _tail(stderr))
        raise FetchError(
            FetchKind.CRASHED, f"unexpected line: {line[:200]!r}", tail=_tail(stderr)
        )


def _read_lines(stream: IO[bytes] | None, lines: "queue.Queue[bytes | None]") -> None:
    if stream is not None:
        for line in stream:
            lines.put(line)
    lines.put(None)  # end of output: the child has exited, or closed stdout


def _decode(line: bytes, stderr: IO[bytes]) -> dict[str, Any]:
    try:
        message = json.loads(line)
    except ValueError:
        message = None
    if not isinstance(message, dict):
        raise FetchError(
            FetchKind.CRASHED, f"unreadable line: {line[:200]!r}", tail=_tail(stderr)
        )
    return message


def _report(progress: Progress, value: object) -> None:
    """Pass on a fraction, clamped; anything else the child sent is dropped."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return
    if math.isfinite(value):
        progress(min(max(float(value), 0.0), 1.0))


def _error_from(error: dict[str, Any], versions: Versions, tail: str) -> FetchError:
    try:
        kind = FetchKind(str(error.get("kind")))
    except ValueError:
        kind = FetchKind.UNKNOWN
    duration = error.get("duration_sec")
    return FetchError(
        kind,
        str(error.get("detail") or ""),
        duration_sec=float(duration) if isinstance(duration, int | float) else None,
        tail=tail,
        versions=versions,
    )


def _exit_code(process: "subprocess.Popen[bytes]") -> int | None:
    try:
        return process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return None


def _kill_group(process: "subprocess.Popen[bytes]") -> None:
    with contextlib.suppress(ProcessLookupError):  # the group is already gone
        os.killpg(process.pid, signal.SIGKILL)


def _tail(stderr: IO[bytes]) -> str:
    stderr.flush()
    size = stderr.seek(0, os.SEEK_END)
    stderr.seek(max(0, size - TAIL_BYTES))
    return stderr.read().decode(errors="replace")


def _text(result: dict[str, Any], key: str) -> str:
    value = result[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} is not text")
    return value


def _video_info(result: dict[str, Any], versions: Versions) -> VideoInfo:
    title = result.get("title")
    duration = result.get("duration_sec")
    live_status = result.get("live_status")
    availability = result.get("availability")
    return VideoInfo(
        title=title if isinstance(title, str) else "",
        duration_sec=float(duration)
        if isinstance(duration, int | float) and not isinstance(duration, bool)
        else None,
        live_status=live_status if isinstance(live_status, str) else None,
        availability=availability if isinstance(availability, str) else None,
        versions=versions,
    )


def log_failed(
    log: logging.Logger,
    error: FetchError,
    *,
    phase: str,
    link: Link,
    elapsed_sec: float,
    job_id: str | None = None,
    attempt: int | None = None,
) -> None:
    """One line per failure, at the catalog's level (spec 012, *Logging*)."""
    entry = error.entry
    detail = error.detail[:DETAIL_CHARS].replace('"', "'")
    line = (
        f"link fetch failed kind={error.kind} phase={phase} site={link.site} "
        f"video={link.video_id} job={job_id or '-'} attempt={attempt or '-'} "
        f"elapsed={elapsed_sec:.1f}s ytdlp={error.versions.ytdlp} "
        f'js={error.versions.js} detail="{detail}"'
    )
    if error.exit_code is not None:
        line += f" exit={error.exit_code}"
    if entry.tail and error.tail:
        line += f"\n{error.tail}"
    log.log(entry.level, "%s", line)


def log_fetched(
    log: logging.Logger,
    *,
    phase: str,
    link: Link,
    versions: Versions,
    elapsed_sec: float,
    job_id: str | None = None,
    attempt: int | None = None,
    download: Download | None = None,
) -> None:
    """Successes too: a broken extractor shows as a change in the ratio of
    ERROR lines to these, and the format ids show how often m4a is missing."""
    line = (
        f"link fetched phase={phase} site={link.site} video={link.video_id} "
        f"job={job_id or '-'} attempt={attempt or '-'} elapsed={elapsed_sec:.1f}s "
        f"ytdlp={versions.ytdlp} js={versions.js}"
    )
    if download is not None:
        line += f" format={download.format_id} ext={download.ext} bytes={download.size}"
    log.info("%s", line)


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    _conforms: UrlFetcher = ChildFetcher()
```

Create `packages/fetch/src/guitarvis_fetch/testing.py`:

```python
"""A UrlFetcher for tests: records its calls, answers as told. No process,
no network. Imported by tests only, as guitarvis_jobs.testing is."""

import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_fetch.fetcher import (
    Download,
    FetchError,
    Progress,
    UrlFetcher,
    Versions,
    VideoInfo,
)
from guitarvis_fetch.links import Link

VERSIONS = Versions(ytdlp="2026.10.26", js="deno/2.5.4")


def video_info(
    *,
    title: str = "Elephants Dream - 10 years of open movies",
    duration_sec: float | None = 37.0,
    live_status: str | None = "not_live",
    availability: str | None = "public",
) -> VideoInfo:
    return VideoInfo(
        title=title,
        duration_sec=duration_sec,
        live_status=live_status,
        availability=availability,
        versions=VERSIONS,
    )


def write_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> Path:
    """A short wav, from the standard library, as a download's file."""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x01\x00" * int(rate * seconds))
    return path


@dataclass
class FakeFetcher:
    """Implements UrlFetcher. `info` answers lookups unless `lookup_error`
    is set; a download writes `content` (a wav by default) to
    `work_dir/source.<ext>` unless `download_error` is set."""

    info: VideoInfo = field(default_factory=video_info)
    lookup_error: FetchError | None = None
    download_error: FetchError | None = None
    content: bytes | None = None
    ext: str = "wav"
    progress_steps: tuple[float, ...] = (0.0, 0.5, 1.0)
    lookups: list[Link] = field(default_factory=list)
    downloads: list[Link] = field(default_factory=list)

    def lookup(self, link: Link) -> VideoInfo:
        self.lookups.append(link)
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.info

    def download(
        self,
        link: Link,
        work_dir: Path,
        *,
        max_bytes: int,
        progress: Progress | None = None,
    ) -> Download:
        self.downloads.append(link)
        if self.download_error is not None:
            raise self.download_error
        path = work_dir / f"source.{self.ext}"
        if self.content is None:
            write_wav(path)
        else:
            path.write_bytes(self.content)
        for step in self.progress_steps:
            if progress is not None:
                progress(step)
        return Download(
            path=path,
            info=self.info,
            format_id="140",
            ext=self.ext,
            size=path.stat().st_size,
        )


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    _conforms: UrlFetcher = FakeFetcher()
```

- [x] **Step 4: Run them to verify they pass**

Run: `uv run pytest packages/fetch/tests/test_fetcher.py`
Expected: PASS, in about five seconds: two tests wait out a two-second deadline. The hang tests check that the fake child's grandchild, standing in for Deno, is dead too.

- [x] **Step 5: Commit**

```bash
make lint typecheck test
git add packages/fetch/src/guitarvis_fetch/fetcher.py \
  packages/fetch/src/guitarvis_fetch/testing.py \
  packages/fetch/tests/fake_child.py \
  packages/fetch/tests/test_fetcher.py
git commit -m "feat(fetch): ChildFetcher, the checks on a video's metadata, and the log lines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 7: The yt-dlp child, and the classifier

`child.py` is the only module that imports yt-dlp, and it does so inside functions, so a yt-dlp that will not import still yields an answer (`misconfigured`). Its first act is to keep its stdout for the protocol and point file descriptor 1 at stderr, so nothing yt-dlp or Deno prints can corrupt an answer. A lookup reads metadata without choosing a format (`extract_info(process=False)`), runs `check_info`, then chooses (`process_ie_result`), so a live stream is `live`, not "no audio". A download does the same on fresh metadata, then checks the one media URL (HTTPS, a `.googlevideo.com` host, public addresses only, within the size cap) before `process_info` fetches it. `classify` walks yt-dlp's exception chain (`exc_info`, `cause`, `__cause__`, `__context__`) and keys on types first, messages second. Plugins are switched off (`YTDLP_NO_PLUGINS`). The fixtures file holds messages recorded live, taken from yt-dlp's source, or reported, each marked (research.md, *Messages*).

**Catalog rows:** L1 to L5, L11, L12, L13, L15, L16, L17 (classify); L6 and W2 (checks before formats and before downloading); D5, D6, D7, D8 (in the child).

**Files:**
- Modify: `mypy.ini`
- Modify: `packages/fetch/pyproject.toml`
- Create: `packages/fetch/src/guitarvis_fetch/child.py`
- Test (new): `packages/fetch/tests/fixtures/youtube-messages.json`
- Test (new): `packages/fetch/tests/test_child.py`
- Test (new): `packages/fetch/tests/test_classify.py`
- Generated, by `uv lock`: `uv.lock`

**Interfaces:**
- Produces (`guitarvis_fetch.child`): `FORMAT`, `OUTPUT_TEMPLATE`, `SOCKET_TIMEOUT_SEC = 15`, `MEDIA_HOST_SUFFIX`, `ydl_options(*, deno, logger, work_dir=None, max_bytes=None, hooks=())`, `ChildLog`, `lookup(ydl, url)`, `download(ydl, url, work_dir, max_bytes, log, *, resolve)`, `check_media(selected, max_bytes, *, resolve)`, `ProgressHook`, `classify(error, warnings=()) -> FetchKind`, `exception_chain(error)`, `main(argv=None)`.

- [x] **Step 1: Write the failing tests**

Create `packages/fetch/tests/fixtures/youtube-messages.json`:

```json
[
  {
    "kind": "private",
    "source": "live: recorded 2026-10-26 with yt-dlp 2026.10.26, no JavaScript runtime",
    "message": "ERROR: [youtube] yZIXLfi8CZQ: Private video. If the owner of this video has granted you access, please sign in. Use --cookies-from-browser or --cookies for the authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp  for how to manually pass cookies. Also see  https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies  for tips on effectively exporting YouTube cookies"
  },
  {
    "kind": "age_restricted",
    "source": "live: recorded 2026-10-26 with yt-dlp 2026.10.26, no JavaScript runtime",
    "message": "ERROR: [youtube] HtVdAasjOgU: Sign in to confirm your age. This video may be inappropriate for some users. Use --cookies-from-browser or --cookies for the authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp  for how to manually pass cookies. Also see  https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies  for tips on effectively exporting YouTube cookies",
    "warnings": [
      "[youtube] No supported JavaScript runtime could be found. Only deno is enabled by default; to use another runtime add  --js-runtimes RUNTIME[:PATH]  to your command/config. YouTube extraction without a JS runtime has been deprecated, and some formats may be missing. See  https://github.com/yt-dlp/yt-dlp/wiki/EJS  for details on installing one",
      "[youtube] HtVdAasjOgU: n challenge solving failed: Some formats may be missing. Ensure you have a supported JavaScript runtime and challenge solver script distribution installed. Review any warnings presented before this message. For more details, refer to  https://github.com/yt-dlp/yt-dlp/wiki/EJS"
    ]
  },
  {
    "kind": "unavailable",
    "source": "live: recorded 2026-10-26 with yt-dlp 2026.10.26, no JavaScript runtime",
    "message": "ERROR: [youtube] Q39EVAstoRM: This video is unavailable"
  },
  {
    "kind": "unavailable",
    "source": "live: recorded 2026-10-26 with yt-dlp 2026.10.26, no JavaScript runtime",
    "message": "ERROR: [youtube] JOhiWY7XmoY: This video is not available"
  },
  {
    "kind": "unavailable",
    "source": "live: recorded 2026-10-26 with yt-dlp 2026.10.26, no JavaScript runtime",
    "message": "ERROR: [youtube] 6SJNVb0GnPI: This video has been removed for violating YouTube's policy on hate speech. Learn more about combating hate speech in your country."
  },
  {
    "kind": "unavailable",
    "source": "live: recorded 2026-10-26 with yt-dlp 2026.10.26, no JavaScript runtime",
    "message": "ERROR: [youtube] jfKfPfyJRdk: This live stream recording is not available."
  },
  {
    "kind": "no_audio",
    "source": "source: yt-dlp 2026.10.26's own text (YoutubeDL.py, extractor/youtube/_video.py)",
    "message": "[youtube] kPdv44HtEoA: Requested format is not available. Use --list-formats for a list of available formats"
  },
  {
    "kind": "no_audio",
    "source": "source: yt-dlp 2026.10.26's own text (YoutubeDL.py, extractor/youtube/_video.py); the warning is one that is not about challenges",
    "message": "ERROR: [youtube] kPdv44HtEoA: Requested format is not available. Use --list-formats for a list of available formats",
    "warnings": [
      "[youtube] kPdv44HtEoA: This video is age-restricted; some formats may be missing without authentication. Use --cookies-from-browser or --cookies for the authentication."
    ]
  },
  {
    "kind": "extractor_broken",
    "source": "source: yt-dlp 2026.10.26's own text (YoutubeDL.py, extractor/youtube/_video.py)",
    "message": "[youtube] kPdv44HtEoA: Requested format is not available. Use --list-formats for a list of available formats",
    "warnings": [
      "[youtube] HtVdAasjOgU: n challenge solving failed: Some formats may be missing. Ensure you have a supported JavaScript runtime and challenge solver script distribution installed. Review any warnings presented before this message. For more details, refer to  https://github.com/yt-dlp/yt-dlp/wiki/EJS"
    ]
  },
  {
    "kind": "extractor_broken",
    "source": "source: yt-dlp 2026.10.26's own text (YoutubeDL.py, extractor/youtube/_video.py)",
    "message": "[youtube] kPdv44HtEoA: Requested format is not available. Use --list-formats for a list of available formats",
    "warnings": [
      "[youtube] No supported JavaScript runtime could be found. Only deno is enabled by default; to use another runtime add  --js-runtimes RUNTIME[:PATH]  to your command/config. YouTube extraction without a JS runtime has been deprecated, and some formats may be missing. See  https://github.com/yt-dlp/yt-dlp/wiki/EJS  for details on installing one"
    ]
  },
  {
    "kind": "extractor_broken",
    "source": "source: yt-dlp 2026.10.26's own text (YoutubeDL.py, extractor/youtube/_video.py)",
    "message": "ERROR: [youtube] kPdv44HtEoA: Failed to extract any player response; please report this issue on  https://github.com/yt-dlp/yt-dlp/issues?q= , filling out the appropriate issue template. Confirm you are on the latest version using  yt-dlp -U"
  },
  {
    "kind": "extractor_broken",
    "source": "source: yt-dlp 2026.10.26's own text (YoutubeDL.py, extractor/youtube/_video.py)",
    "message": "ERROR: [youtube] kPdv44HtEoA: Unable to extract yt initial data; please report this issue on  https://github.com/yt-dlp/yt-dlp/issues?q= , filling out the appropriate issue template. Confirm you are on the latest version using  yt-dlp -U"
  },
  {
    "kind": "extractor_broken",
    "source": "source: yt-dlp 2026.10.26's own text (YoutubeDL.py, extractor/youtube/_video.py)",
    "message": "ERROR: Unsupported URL: https://www.youtube.com/watch?v=kPdv44HtEoA"
  },
  {
    "kind": "extractor_broken",
    "source": "source: yt-dlp 2026.10.26's own text (YoutubeDL.py, extractor/youtube/_video.py)",
    "message": "ERROR: No suitable extractor found for URL https://www.youtube.com/watch?v=kPdv44HtEoA"
  },
  {
    "kind": "rate_limited",
    "source": "source: yt-dlp 2026.10.26's own text (YoutubeDL.py, extractor/youtube/_video.py)",
    "message": "ERROR: [youtube] kPdv44HtEoA: This content isn't available, try again later. The current session has been rate-limited by YouTube for up to an hour. It is recommended to use `-t sleep` to add a delay between video requests to avoid exceeding the rate limit. For more information, refer to  https://github.com/yt-dlp/yt-dlp/wiki/Extractors#this-content-isnt-available-try-again-later"
  },
  {
    "kind": "rate_limited",
    "source": "source: yt-dlp 2026.10.26's own text (YoutubeDL.py, extractor/youtube/_video.py)",
    "message": "ERROR: [youtube] kPdv44HtEoA: All player responses are invalid. Your IP is likely being blocked by Youtube"
  },
  {
    "kind": "rate_limited",
    "source": "source: yt-dlp 2026.10.26's own text (YoutubeDL.py, extractor/youtube/_video.py)",
    "message": "ERROR: [youtube] kPdv44HtEoA: This video is unavailable. YouTube is requiring a captcha challenge before playback"
  },
  {
    "kind": "members_only",
    "source": "source: yt-dlp 2026.10.26's own text (YoutubeDL.py, extractor/youtube/_video.py)",
    "message": "ERROR: [youtube] kPdv44HtEoA: This video is DRM protected"
  },
  {
    "kind": "rate_limited",
    "source": "reported: YouTube's reason as yt-dlp users report it, wrapped as the source does; not reproduced here",
    "message": "ERROR: [youtube] kPdv44HtEoA: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies for the authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp  for how to manually pass cookies. Also see  https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies  for tips on effectively exporting YouTube cookies"
  },
  {
    "kind": "rate_limited",
    "source": "reported: YouTube's reason as yt-dlp users report it, wrapped as the source does; not reproduced here",
    "message": "ERROR: [youtube] kPdv44HtEoA: Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies for the authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp  for how to manually pass cookies. Also see  https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies  for tips on effectively exporting YouTube cookies"
  },
  {
    "kind": "members_only",
    "source": "reported: YouTube's reason as yt-dlp users report it, wrapped as the source does; not reproduced here",
    "message": "ERROR: [youtube] kPdv44HtEoA: Join this channel to get access to members-only content like this video, and other exclusive perks."
  },
  {
    "kind": "members_only",
    "source": "reported: YouTube's reason as yt-dlp users report it, wrapped as the source does; not reproduced here",
    "message": "ERROR: [youtube] kPdv44HtEoA: This video is available to this channel's members on level: Fan (or any higher level). Join this channel to get access to members-only content and other exclusive perks."
  },
  {
    "kind": "members_only",
    "source": "reported: YouTube's reason as yt-dlp users report it, wrapped as the source does; not reproduced here",
    "message": "ERROR: [youtube] kPdv44HtEoA: This video requires payment to watch."
  },
  {
    "kind": "members_only",
    "source": "reported: YouTube's reason as yt-dlp users report it, wrapped as the source does; not reproduced here",
    "message": "ERROR: [youtube] kPdv44HtEoA: This video is only available to Music Premium members"
  },
  {
    "kind": "upcoming",
    "source": "reported: YouTube's reason as yt-dlp users report it, wrapped as the source does; not reproduced here",
    "message": "ERROR: [youtube] kPdv44HtEoA: This live event will begin in 3 hours."
  },
  {
    "kind": "upcoming",
    "source": "reported: YouTube's reason as yt-dlp users report it, wrapped as the source does; not reproduced here",
    "message": "ERROR: [youtube] kPdv44HtEoA: This live event will begin in a few moments."
  },
  {
    "kind": "upcoming",
    "source": "reported: YouTube's reason as yt-dlp users report it, wrapped as the source does; not reproduced here",
    "message": "ERROR: [youtube] kPdv44HtEoA: Premieres in 10 hours"
  },
  {
    "kind": "upcoming",
    "source": "reported: YouTube's reason as yt-dlp users report it, wrapped as the source does; not reproduced here",
    "message": "ERROR: [youtube] kPdv44HtEoA: Premiere will begin shortly"
  },
  {
    "kind": "unavailable",
    "source": "reported: YouTube's reason as yt-dlp users report it, wrapped as the source does; not reproduced here",
    "message": "ERROR: [youtube] kPdv44HtEoA: Video unavailable. This video is no longer available because the YouTube account associated with this video has been terminated."
  },
  {
    "kind": "unavailable",
    "source": "reported: YouTube's reason as yt-dlp users report it, wrapped as the source does; not reproduced here",
    "message": "ERROR: [youtube] kPdv44HtEoA: Video unavailable. This video is no longer available due to a copyright claim by Example Records"
  },
  {
    "kind": "geo_restricted",
    "source": "reported: YouTube's reason as yt-dlp users report it, wrapped as the source does; not reproduced here",
    "message": "ERROR: [youtube] kPdv44HtEoA: Video unavailable. The uploader has not made this video available in your country"
  },
  {
    "kind": "unknown",
    "source": "made up: a message no rule knows",
    "message": "ERROR: [youtube] kPdv44HtEoA: Something YouTube has never said before"
  }
]
```

Create `packages/fetch/tests/test_child.py`:

```python
"""The child, in-process against a fake YoutubeDL, and as a process: the
options it gives yt-dlp, the checks before any byte is downloaded, and its
answers. No network: nothing here asks YouTube anything."""

import io
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yt_dlp
from guitarvis_fetch.catalog import FetchKind
from guitarvis_fetch.child import (
    FORMAT,
    ChildLog,
    ProgressHook,
    check_media,
    download,
    lookup,
    ydl_options,
)
from guitarvis_fetch.fetcher import ChildFetcher, FetchError
from guitarvis_fetch.links import parse

URL = "https://www.youtube.com/watch?v=kPdv44HtEoA"
RAW = {
    "id": "kPdv44HtEoA",
    "title": "Elephants Dream - 10 years of open movies",
    "duration": 37,
    "live_status": "not_live",
    "availability": "public",
    "formats": [{"format_id": "140"}],
}
SELECTED = {
    **RAW,
    "format_id": "140",
    "ext": "m4a",
    "protocol": "https",
    "url": "https://rr1---sn-qja5mc-54.googlevideo.com/videoplayback?itag=140",
    "filesize": 600547,
}
PUBLIC = [(2, 1, 6, "", ("74.125.170.113", 443))]


def resolving(*addresses: str) -> Any:
    return lambda host, port, **kwargs: [(2, 1, 6, "", (a, port)) for a in addresses]


class FakeYdl:
    """The three YoutubeDL calls the child makes, recorded."""

    def __init__(
        self,
        raw: Any = None,
        selected: dict[str, Any] | None = None,
        select_error: Exception | None = None,
        writes: bytes | None = b"\x00" * 1000,
    ) -> None:
        self.raw = dict(RAW) if raw is None else raw
        self.selected = dict(SELECTED) if selected is None else selected
        self.select_error = select_error
        self.writes = writes
        self.calls: list[str] = []
        self.work_dir: Path | None = None

    def extract_info(self, url: str, *, download: bool, process: bool) -> Any:
        assert (url, download, process) == (URL, False, False)
        self.calls.append("extract")
        return self.raw

    def process_ie_result(self, raw: Any, *, download: bool) -> dict[str, Any]:
        assert download is False
        self.calls.append("select")
        if self.select_error is not None:
            raise self.select_error
        return self.selected

    def process_info(self, info: dict[str, Any]) -> None:
        self.calls.append("download")
        if self.writes is not None and self.work_dir is not None:
            (self.work_dir / f"source.{info['ext']}").write_bytes(self.writes)


def log() -> ChildLog:
    return ChildLog(io.StringIO())


def fetch(
    ydl: FakeYdl, work_dir: Path, max_bytes: int = 10**7, **kwargs: Any
) -> dict[str, Any]:
    ydl.work_dir = work_dir
    return download(
        ydl,
        URL,
        work_dir,
        max_bytes,
        kwargs.pop("child_log", log()),
        resolve=kwargs.pop("resolve", resolving("74.125.170.113")),
        **kwargs,
    )


# What yt-dlp is told


def test_the_options_are_exactly_these() -> None:
    logger = log()

    assert ydl_options(deno="/usr/bin/deno", logger=logger) == {
        "logger": logger,
        "quiet": True,
        "noprogress": True,
        "color": "never",
        "ignoreerrors": False,
        "allowed_extractors": ["youtube"],
        "noplaylist": True,
        "format": "bestaudio[ext=m4a][protocol=https]/bestaudio[protocol=https]",
        "js_runtimes": {"deno": {"path": "/usr/bin/deno"}},
        "remote_components": [],
        "geo_bypass": False,
        "socket_timeout": 15,
        "retries": 1,
        "fragment_retries": 1,
        "extractor_retries": 1,
        "file_access_retries": 1,
        "postprocessors": [],
    }


def test_a_download_adds_a_fixed_template_in_the_job_directory_and_the_cap(
    tmp_path: Path,
) -> None:
    hook = ProgressHook(io.StringIO(), 100)

    options = ydl_options(
        deno="deno", logger=log(), work_dir=tmp_path, max_bytes=100, hooks=[hook]
    )

    assert options["paths"] == {"home": str(tmp_path), "temp": str(tmp_path)}
    assert options["outtmpl"] == {"default": "source.%(ext)s"}
    assert (options["max_filesize"], options["progress_hooks"]) == (100, [hook])
    assert options["overwrites"] is True
    for key in ("cookiefile", "cookiesfrombrowser", "proxy", "username", "usenetrc"):
        assert key not in options


def test_yt_dlp_accepts_the_options_and_loads_only_the_youtube_extractor() -> None:
    with yt_dlp.YoutubeDL(ydl_options(deno="deno", logger=log())) as ydl:
        # _ies is private, but it is the one place this is visible, and it
        # is what keeps the generic extractor, which fetches anything, away.
        assert set(ydl._ies) == {"Youtube"}
        assert ydl.params["format"] == FORMAT


def run_python(code: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_child_loads_no_ytdlp_plugins(tmp_path: Path) -> None:
    """yt-dlp loads plugins from the user's config directory when a
    YoutubeDL is made; the child's must not run anyone's code."""
    plugin = (
        tmp_path
        / "config"
        / "yt-dlp"
        / "plugins"
        / "evil"
        / "yt_dlp_plugins"
        / "extractor"
    )
    plugin.mkdir(parents=True)
    marker = tmp_path / "ran"
    (plugin / "marker.py").write_text(f"open({str(marker)!r}, 'w').write('ran')\n")
    env = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "config")}
    env.pop("YTDLP_NO_PLUGINS", None)

    control = run_python("import yt_dlp; yt_dlp.YoutubeDL({'quiet': True})", env)
    assert control.returncode == 0, control.stderr
    assert marker.exists(), (
        "the control did not load the plugin: this test proves nothing"
    )
    marker.unlink()

    ours = run_python(
        "from guitarvis_fetch.child import _new_ydl; _new_ydl({'quiet': True})", env
    )
    assert ours.returncode == 0, ours.stderr
    assert not marker.exists()


# A lookup


def test_a_lookup_checks_the_metadata_then_chooses_a_format() -> None:
    ydl = FakeYdl()

    info = lookup(ydl, URL)

    assert info == {
        "title": "Elephants Dream - 10 years of open movies",
        "duration_sec": 37.0,
        "live_status": "not_live",
        "availability": "public",
    }
    assert ydl.calls == ["extract", "select"]


def test_a_live_stream_is_refused_before_formats_are_chosen() -> None:  # L6
    ydl = FakeYdl(raw={**RAW, "live_status": "is_live", "duration": None})

    with pytest.raises(FetchError) as excinfo:
        lookup(ydl, URL)

    assert excinfo.value.kind is FetchKind.LIVE
    assert ydl.calls == ["extract"]  # choosing first would have said "no audio"


def test_a_trailer_in_place_of_a_paid_video_is_members_only() -> None:  # L5
    ydl = FakeYdl(
        raw={"_type": "url", "url": "https://www.youtube.com/watch?v=trailer0000"}
    )

    with pytest.raises(FetchError) as excinfo:
        lookup(ydl, URL)

    assert excinfo.value.kind is FetchKind.MEMBERS_ONLY


def test_a_format_error_is_left_for_the_classifier() -> None:  # L11
    error = yt_dlp.utils.ExtractorError(
        "Requested format is not available", expected=True
    )

    with pytest.raises(yt_dlp.utils.ExtractorError):
        lookup(FakeYdl(select_error=error), URL)


# A download


def test_a_download_returns_the_file_and_its_format(tmp_path: Path) -> None:
    ydl = FakeYdl()

    result = fetch(ydl, tmp_path)

    assert result["path"] == str(tmp_path / "source.m4a")
    assert (result["format_id"], result["ext"], result["size"]) == ("140", "m4a", 1000)
    assert result["title"] == "Elephants Dream - 10 years of open movies"
    assert ydl.calls == ["extract", "select", "download"]


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ({**RAW, "availability": "private"}, FetchKind.PRIVATE),
        ({**RAW, "live_status": "is_upcoming"}, FetchKind.UPCOMING),
        ({**RAW, "duration": 721}, FetchKind.TOO_LONG),
        ({**RAW, "duration": None}, FetchKind.NO_DURATION),
    ],
)
def test_a_video_that_changed_in_the_queue_is_refused_before_downloading(
    tmp_path: Path, raw: dict[str, Any], kind: FetchKind
) -> None:  # W2
    ydl = FakeYdl(raw=raw)

    with pytest.raises(FetchError) as excinfo:
        fetch(ydl, tmp_path)

    assert excinfo.value.kind is kind
    assert "download" not in ydl.calls


@pytest.mark.parametrize(
    ("selected", "addresses"),
    [
        (
            {**SELECTED, "protocol": "http", "url": "http://rr1.googlevideo.com/x"},
            ["74.125.170.113"],
        ),
        ({**SELECTED, "protocol": "m3u8_native"}, ["74.125.170.113"]),
        ({**SELECTED, "url": "https://evil.example/videoplayback"}, ["74.125.170.113"]),
        (
            {**SELECTED, "url": "https://googlevideo.com.evil.example/x"},
            ["74.125.170.113"],
        ),
        (SELECTED, ["10.0.0.7"]),
        (SELECTED, ["74.125.170.113", "127.0.0.1"]),
        (SELECTED, ["169.254.169.254"]),
        (SELECTED, ["fd00::1"]),
        ({**SELECTED, "requested_formats": [{}, {}]}, ["74.125.170.113"]),
    ],
)
def test_a_media_url_we_did_not_expect_is_refused_before_connecting(
    tmp_path: Path, selected: dict[str, Any], addresses: list[str]
) -> None:  # D5
    ydl = FakeYdl(selected=selected)

    with pytest.raises(FetchError) as excinfo:
        fetch(ydl, tmp_path, resolve=resolving(*addresses))

    assert excinfo.value.kind is FetchKind.MEDIA_REFUSED
    assert "download" not in ydl.calls


def test_a_format_larger_than_the_cap_is_refused_before_downloading(
    tmp_path: Path,
) -> None:  # D6
    ydl = FakeYdl(selected={**SELECTED, "filesize": 10_001})

    with pytest.raises(FetchError) as excinfo:
        fetch(ydl, tmp_path, max_bytes=10_000)

    assert excinfo.value.kind is FetchKind.TOO_LARGE
    assert "download" not in ydl.calls


def test_a_file_larger_than_the_cap_on_disk_is_refused(tmp_path: Path) -> None:  # D6
    ydl = FakeYdl(selected={**SELECTED, "filesize": None}, writes=b"\x00" * 2000)

    with pytest.raises(FetchError) as excinfo:
        fetch(ydl, tmp_path, max_bytes=1000)

    assert excinfo.value.kind is FetchKind.TOO_LARGE


def test_yt_dlps_quiet_size_cap_is_too_large_not_empty(tmp_path: Path) -> None:  # D6
    child_log = log()
    child_log.debug(
        "[download] File is larger than max-filesize (2000 bytes > 1000 bytes). "
        "Aborting."
    )

    with pytest.raises(FetchError) as excinfo:
        fetch(
            FakeYdl(selected={**SELECTED, "filesize": None}, writes=None),
            tmp_path,
            max_bytes=1000,
            child_log=child_log,
        )

    assert excinfo.value.kind is FetchKind.TOO_LARGE


@pytest.mark.parametrize("writes", [None, b""])
def test_a_download_that_leaves_no_file_or_an_empty_one_is_unusable(
    tmp_path: Path, writes: bytes | None
) -> None:  # D7
    with pytest.raises(FetchError) as excinfo:
        fetch(FakeYdl(writes=writes), tmp_path)

    assert excinfo.value.kind is FetchKind.EMPTY_DOWNLOAD


def test_check_media_passes_youtubes_own_host_at_a_public_address() -> None:
    check_media(SELECTED, 10**9, resolve=lambda *args, **kwargs: PUBLIC)


# Progress, and the cap for a response with no length


def test_the_hook_reports_each_whole_percent_once() -> None:
    out = io.StringIO()
    hook = ProgressHook(out, 10_000)

    for done in (0, 10, 4999, 5000, 5001, 10_000):
        hook({"status": "downloading", "downloaded_bytes": done, "total_bytes": 10_000})

    sent = [json.loads(line)["progress"] for line in out.getvalue().splitlines()]
    assert sent == [0.0, 0.49, 0.5, 1.0]


def test_the_hook_stops_a_download_past_the_cap_with_no_length() -> None:  # D6
    hook = ProgressHook(io.StringIO(), 1000)

    with pytest.raises(FetchError) as excinfo:
        hook({"status": "downloading", "downloaded_bytes": 1001, "total_bytes": None})

    assert excinfo.value.kind is FetchKind.TOO_LARGE


# The child as a process


def empty_path(tmp_path: Path) -> str:
    beside = Path(sys.executable).with_name("deno")
    if beside.exists():
        pytest.skip("a deno is installed beside this Python; it cannot be hidden")
    path = tmp_path / "bin"
    path.mkdir()
    return str(path)


def test_without_a_javascript_runtime_the_child_says_misconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # L16
    monkeypatch.setenv("PATH", empty_path(tmp_path))

    with pytest.raises(FetchError) as excinfo:
        ChildFetcher().lookup(parse(URL))

    assert excinfo.value.kind is FetchKind.MISCONFIGURED
    assert "Deno 2.3.0 or later" in excinfo.value.detail


def test_when_yt_dlp_will_not_import_the_child_says_misconfigured(
    tmp_path: Path,
) -> None:  # L16
    bin_dir = Path(empty_path(tmp_path))
    deno = bin_dir / "deno"
    deno.write_text("#!/bin/sh\necho 'deno 2.5.4 (stable)'\n")
    deno.chmod(deno.stat().st_mode | stat.S_IEXEC)
    code = (
        "import sys; sys.modules['yt_dlp'] = None; sys.argv[1:] = ['lookup', "
        f"{URL!r}]; import runpy; "
        "runpy.run_module('guitarvis_fetch.child', run_name='__main__')"
    )

    answer = run_python(code, {**os.environ, "PATH": str(bin_dir)})

    [line] = answer.stdout.splitlines()
    error = json.loads(line)["error"]
    assert error["kind"] == "misconfigured"
    assert "yt-dlp will not import" in error["detail"]


def test_nothing_but_answers_reaches_the_childs_stdout() -> None:
    """yt-dlp and Deno print; fd 1 points at stderr, so only JSON is on stdout."""
    code = (
        "import guitarvis_fetch.child as child\n"
        "from guitarvis_fetch.fetcher import JsRuntime\n"
        "child.find_deno = lambda: JsRuntime('deno', 'deno', '2.5.4')\n"
        "def answer(args, runtime, log, out):\n"
        "    print('[youtube] chatter on stdout')\n"
        "    import os; os.write(1, b'and from a subprocess\\n')\n"
        "    return {'title': 't'}\n"
        "child._answer = answer\n"
        "child.main(['lookup', 'x'])\n"
    )

    answer = run_python(code, dict(os.environ))

    assert answer.returncode == 0, answer.stderr
    [line] = answer.stdout.splitlines()
    assert json.loads(line)["result"] == {"title": "t"}
    assert "chatter on stdout" in answer.stderr
    assert "and from a subprocess" in answer.stderr
```

Create `packages/fetch/tests/test_classify.py`:

```python
"""The child's classifier: yt-dlp's exception types, built offline, and the
messages yt-dlp gives for real failures (fixtures/youtube-messages.json, each
with where it came from). `make smoke-url` prints fresh ones to compare."""

import errno
import io
import json
import socket
import ssl
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from guitarvis_fetch.catalog import FetchKind
from guitarvis_fetch.child import classify, exception_chain
from yt_dlp.networking import Response
from yt_dlp.networking.exceptions import (
    CertificateVerifyError,
    HTTPError,
    ProxyError,
    SSLError,
    TransportError,
)
from yt_dlp.utils import (
    ContentTooShortError,
    DownloadError,
    ExtractorError,
    GeoRestrictedError,
    UnavailableVideoError,
)

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "youtube-messages.json").read_text()
)
ID = "kPdv44HtEoA"
CHALLENGE = "[youtube] x: n challenge solving failed: Some formats may be missing."


def reported(raise_it: Callable[[], None]) -> DownloadError:
    """What yt-dlp hands back for an error: YoutubeDL.trouble's DownloadError,
    whose exc_info is the ExtractorError's own cause when it has one."""
    try:
        raise_it()
    except Exception as error:
        exc_info: Any = getattr(error, "exc_info", None)
        return DownloadError(
            f"ERROR: {error}", exc_info if exc_info and exc_info[0] else sys.exc_info()
        )
    raise AssertionError("raise_it did not raise")


def while_extracting(cause: Exception) -> Callable[[], None]:
    """A network failure inside the extractor, wrapped as it wraps one."""

    def extract() -> None:
        try:
            raise cause
        except Exception as error:
            raise ExtractorError(
                f"Unable to download API page: {error}",
                cause=error,
                video_id=ID,
                ie="youtube",
            ) from None

    return extract


def http_error(status: int, reason: str) -> HTTPError:
    response = Response(
        fp=io.BytesIO(b""),
        url="https://www.youtube.com/youtubei/v1/player",
        headers={},
        status=status,
        reason=reason,
    )
    return HTTPError(response)


def raises(error: BaseException) -> Callable[[], None]:
    def go() -> None:
        raise error

    return go


def caught(raise_it: Callable[[], None]) -> BaseException:
    """The exception itself, as the child sees one process_info raised."""
    try:
        raise_it()
    except Exception as error:
        return error
    raise AssertionError("raise_it did not raise")


def disk_full() -> None:
    # YoutubeDL.process_info, when writing the file fails.
    try:
        raise OSError(errno.ENOSPC, "No space left on device")
    except OSError as error:
        raise UnavailableVideoError(error)  # noqa: B904 -- as yt-dlp does


@pytest.mark.parametrize(
    "fixture",
    FIXTURES,
    ids=[f"{item['kind']}-{n}" for n, item in enumerate(FIXTURES)],
)
def test_each_recorded_message_classifies_as_its_kind(fixture: dict[str, Any]) -> None:
    error = DownloadError(fixture["message"])

    assert classify(error, fixture.get("warnings", [])) is FetchKind(fixture["kind"])


def test_every_fixture_says_where_it_came_from() -> None:
    assert all(item["source"] for item in FIXTURES)


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (  # L3
            reported(
                raises(
                    GeoRestrictedError(
                        "The uploader has not made this video available in your "
                        "country",
                        countries=["US"],
                    )
                )
            ),
            FetchKind.GEO_RESTRICTED,
        ),
        (
            reported(while_extracting(http_error(429, "Too Many Requests"))),
            FetchKind.RATE_LIMITED,
        ),  # L12
        (
            reported(while_extracting(http_error(503, "Service Unavailable"))),
            FetchKind.NETWORK,
        ),  # L13
        (
            reported(while_extracting(http_error(500, "Internal Server Error"))),
            FetchKind.NETWORK,
        ),
        (
            reported(
                while_extracting(
                    TransportError(
                        cause=socket.gaierror(-2, "Name or service not known")
                    )
                )
            ),
            FetchKind.NETWORK,
        ),
        (
            reported(while_extracting(TransportError(cause=ConnectionRefusedError()))),
            FetchKind.NETWORK,
        ),
        (
            reported(while_extracting(SSLError(cause=ssl.SSLError(1, "bad record")))),
            FetchKind.NETWORK,
        ),
        (
            reported(while_extracting(CertificateVerifyError(cause="expired"))),
            FetchKind.NETWORK,
        ),
        (reported(while_extracting(ProxyError(cause="refused"))), FetchKind.NETWORK),
        (reported(raises(ContentTooShortError(1000, 2000))), FetchKind.NETWORK),  # D1
        (reported(raises(TimeoutError("timed out"))), FetchKind.NETWORK),
        (caught(disk_full), FetchKind.LOCAL_IO),  # D8: process_info raises it
        (reported(disk_full), FetchKind.LOCAL_IO),  # D8, through YoutubeDL.download
        (
            UnavailableVideoError(OSError(errno.ENOSPC, "No space left on device")),
            FetchKind.LOCAL_IO,
        ),
        (OSError(errno.EACCES, "Permission denied"), FetchKind.LOCAL_IO),
        (
            reported(while_extracting(http_error(404, "Not Found"))),
            FetchKind.UNKNOWN,
        ),  # L17
        (RuntimeError("something new"), FetchKind.UNKNOWN),  # L17, D10
    ],
)
def test_ytdlp_exception_types_classify(error: BaseException, kind: FetchKind) -> None:
    assert classify(error) is kind


def test_a_forbidden_media_url_after_challenge_warnings_is_a_broken_extractor() -> None:
    error = reported(
        raises(
            DownloadError(
                "ERROR: unable to download video data: HTTP Error 403: Forbidden",
                (HTTPError, http_error(403, "Forbidden"), None),
            )
        )
    )

    assert classify(error) is FetchKind.UNKNOWN
    assert classify(error, [CHALLENGE]) is FetchKind.EXTRACTOR_BROKEN


def test_a_format_error_is_no_audio_unless_challenges_failed() -> None:  # L11, L15
    error = reported(
        raises(
            ExtractorError(
                "Requested format is not available. Use --list-formats for a "
                "list of available formats",
                expected=True,
                video_id=ID,
                ie="youtube",
            )
        )
    )

    assert classify(error) is FetchKind.NO_AUDIO
    assert classify(error, [CHALLENGE]) is FetchKind.EXTRACTOR_BROKEN


def test_a_private_videos_sign_in_request_is_not_age_restriction() -> None:
    error = DownloadError(
        "ERROR: [youtube] x: Private video. If the owner of this video has granted "
        "you access, please sign in."
    )

    assert classify(error) is FetchKind.PRIVATE


def test_the_chain_follows_exc_info_cause_and_context() -> None:
    network = TransportError(cause=ConnectionResetError())
    error = reported(while_extracting(network))

    chain = list(exception_chain(error))

    assert chain[0] is error
    assert network in chain
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/fetch/tests/test_classify.py packages/fetch/tests/test_child.py`
Expected: FAIL at collection: `ModuleNotFoundError: No module named 'yt_dlp'` and `No module named 'guitarvis_fetch.child'`.

- [x] **Step 3: Implement**

Add the dependency (the `pyproject.toml` change below), then `uv lock && uv sync`. The lock should resolve `yt-dlp 2026.10.26` and `yt-dlp-ejs 0.8.0`; check with `grep -A1 'name = "yt-dlp"' uv.lock`. yt-dlp ships no `py.typed`, so mypy.ini names it, as it names boto3.

In `mypy.ini`:

```diff
--- a/mypy.ini
+++ b/mypy.ini
@@ -68,6 +68,14 @@ ignore_missing_imports = True
 [mypy-mir_eval]
 ignore_missing_imports = True
 
+; yt-dlp ships no type information (no py.typed). Only guitarvis_fetch.child
+; imports it, and only that module and its tests need these.
+[mypy-yt_dlp]
+ignore_missing_imports = True
+
+[mypy-yt_dlp.*]
+ignore_missing_imports = True
+
 ; boto3 and botocore ship no type information (stubs exist as boto3-stubs,
 ; not worth a dependency for the handful of calls in guitarvis_jobs.blobs).
 ; Only the modules actually imported are named: warn_unused_configs reports
```

In `packages/fetch/pyproject.toml`:

```diff
--- a/packages/fetch/pyproject.toml
+++ b/packages/fetch/pyproject.toml
@@ -3,7 +3,9 @@ name = "guitarvis-fetch"
 version = "0.1.0"
 description = "Audio from links: parsing, the yt-dlp child process, the failure catalog."
 requires-python = ">=3.12"
-dependencies = ["guitarvis-core"]
+# yt-dlp[default] brings yt-dlp-ejs, which YouTube's player challenges need.
+# A plain dependency, not an optional extra: the setting is the one switch.
+dependencies = ["guitarvis-core", "yt-dlp[default]>=2026.10.26"]
 
 [build-system]
 requires = ["hatchling"]
```

Create `packages/fetch/src/guitarvis_fetch/child.py`:

```python
"""The child process, and the only module that imports yt-dlp (spec 012).

ChildFetcher runs `python -I -m guitarvis_fetch.child lookup URL`, or
`... download URL WORK_DIR MAX_BYTES`, and reads JSON lines from stdout
(guitarvis_fetch.fetcher describes them). Every failure is classified here,
while yt-dlp's exception types are still visible: only a kind crosses the
process boundary, with yt-dlp's text beside it for the log.

yt-dlp is imported inside functions. If it will not import, the child still
answers, as misconfigured, instead of dying with a traceback the parent can
only call a crash.
"""

import ipaddress
import json
import os
import re
import socket
import ssl
import sys
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import IO, Any
from urllib.parse import urlsplit

from guitarvis_fetch.catalog import FetchKind
from guitarvis_fetch.fetcher import (
    MIN_DENO_VERSION,
    FetchError,
    JsRuntime,
    Versions,
    VideoInfo,
    check_info,
    find_deno,
)

# Audio only, over plain HTTPS, so the download is one GET whose host can be
# checked first. m4a first: Opus in WebM does not play in older Safari.
FORMAT = "bestaudio[ext=m4a][protocol=https]/bestaudio[protocol=https]"
OUTPUT_TEMPLATE = "source.%(ext)s"  # fixed: a title never becomes a path
SOCKET_TIMEOUT_SEC = 15
MEDIA_HOST_SUFFIX = ".googlevideo.com"

Resolve = Callable[..., list[tuple[Any, ...]]]
Hook = Callable[[dict[str, Any]], None]


def ydl_options(
    *,
    deno: str,
    logger: Any,
    work_dir: Path | None = None,
    max_bytes: int | None = None,
    hooks: Sequence[Hook] = (),
) -> dict[str, Any]:
    """Everything yt-dlp is told, and nothing more: the YouTube extractor
    only, one video, no cookies, no geo-bypass, no post-processors of ours,
    no code fetched at run time, and low retry counts, since RQ retries the
    job. yt-dlp's own fixup still remuxes a DASH m4a with ffmpeg, which
    makes it a file every browser plays."""
    options: dict[str, Any] = {
        "logger": logger,
        "quiet": True,
        "noprogress": True,
        "color": "never",
        "ignoreerrors": False,
        "allowed_extractors": ["youtube"],
        "noplaylist": True,
        "format": FORMAT,
        "js_runtimes": {"deno": {"path": deno}},
        "remote_components": [],
        "geo_bypass": False,
        "socket_timeout": SOCKET_TIMEOUT_SEC,
        "retries": 1,
        "fragment_retries": 1,
        "extractor_retries": 1,
        "file_access_retries": 1,
        "postprocessors": [],
    }
    if work_dir is not None:
        options |= {
            "paths": {"home": str(work_dir), "temp": str(work_dir)},
            "outtmpl": {"default": OUTPUT_TEMPLATE},
            "overwrites": True,
            "max_filesize": max_bytes,
            "progress_hooks": list(hooks),
        }
    return options


class ChildLog:
    """yt-dlp's logger: everything to stderr, where the parent keeps the
    tail. Warnings are kept too: a format error means "no audio" without
    challenge warnings, and a broken extractor with them."""

    def __init__(self, stream: IO[str]) -> None:
        self._stream = stream
        self.warnings: list[str] = []
        self.hit_size_cap = False

    def debug(self, message: str) -> None:
        # yt-dlp's max_filesize gives up quietly: no error, and no file.
        if "max-filesize" in message:
            self.hit_size_cap = True
        self._write(message)

    def info(self, message: str) -> None:
        self._write(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)
        self._write(f"WARNING: {message}")

    def error(self, message: str) -> None:
        self._write(message)

    def _write(self, message: str) -> None:
        self._stream.write(message + "\n")
        self._stream.flush()


def lookup(ydl: Any, url: str) -> dict[str, Any]:
    """The video's metadata, checked, then its formats chosen, so a video
    with no audio we can use is refused now rather than in the queue.

    Metadata first, without choosing formats: a live stream has no format
    our filter accepts, and choosing first would call it "no audio".
    """
    raw = ydl.extract_info(url, download=False, process=False)
    info = _checked(raw)
    ydl.process_ie_result(raw, download=False)
    return info


def download(
    ydl: Any,
    url: str,
    work_dir: Path,
    max_bytes: int,
    log: ChildLog,
    *,
    resolve: Resolve = socket.getaddrinfo,
) -> dict[str, Any]:
    """Fresh metadata and the same checks as a lookup, then the one GET.

    Not the api's format URLs: those are bound to the api's address, they
    expire, and the worker may be on another host.
    """
    raw = ydl.extract_info(url, download=False, process=False)
    info = _checked(raw)
    selected = ydl.process_ie_result(raw, download=False)
    check_media(selected, max_bytes, resolve=resolve)
    ydl.process_info(selected)

    path = work_dir / f"source.{selected.get('ext')}"
    if not path.is_file():
        kind = FetchKind.TOO_LARGE if log.hit_size_cap else FetchKind.EMPTY_DOWNLOAD
        raise FetchError(kind, f"no file at {path.name}")
    size = path.stat().st_size
    if size == 0:
        raise FetchError(FetchKind.EMPTY_DOWNLOAD, f"{path.name} is empty")
    if size > max_bytes:
        raise FetchError(FetchKind.TOO_LARGE, f"{path.name} is {size} bytes")
    return {
        **info,
        "path": str(path),
        "format_id": str(selected.get("format_id") or "-"),
        "ext": path.suffix.removeprefix("."),
        "size": size,
    }


def check_media(
    selected: dict[str, Any], max_bytes: int, *, resolve: Resolve = socket.getaddrinfo
) -> None:
    """The download is one HTTPS GET to YouTube's media hosts, at public
    addresses, and no larger than we accept. Refused before connecting.

    Redirects yt-dlp follows mid-download, and DNS answers that change after
    this check, are not re-checked: only egress rules at hosting close that.
    """
    if selected.get("requested_formats"):
        raise FetchError(FetchKind.MEDIA_REFUSED, "more than one format selected")
    parts = urlsplit(str(selected.get("url") or ""))
    host = parts.hostname or ""
    if selected.get("protocol") != "https" or parts.scheme != "https":
        raise FetchError(
            FetchKind.MEDIA_REFUSED,
            f"protocol={selected.get('protocol')} scheme={parts.scheme}",
        )
    if not host.endswith(MEDIA_HOST_SUFFIX):
        raise FetchError(FetchKind.MEDIA_REFUSED, f"host={host}")
    addresses = {
        answer[4][0] for answer in resolve(host, 443, proto=socket.IPPROTO_TCP)
    }
    if not addresses or not all(_is_public(address) for address in addresses):
        raise FetchError(
            FetchKind.MEDIA_REFUSED, f"host={host} resolves to {sorted(addresses)}"
        )
    size = selected.get("filesize") or selected.get("filesize_approx")
    if isinstance(size, int | float) and size > max_bytes:
        raise FetchError(FetchKind.TOO_LARGE, f"filesize={size}")


def _is_public(address: str) -> bool:
    try:
        return ipaddress.ip_address(address.split("%")[0]).is_global
    except ValueError:
        return False


def _checked(raw: Any) -> dict[str, Any]:
    """The fields a lookup returns, once check_info has passed them."""
    if not isinstance(raw, dict) or raw.get("_type", "video") != "video":
        # YouTube answers a paid video with its trailer instead.
        raise FetchError(FetchKind.MEMBERS_ONLY, "not one video: a trailer, perhaps")
    duration = raw.get("duration")
    info = VideoInfo(
        title=str(raw.get("title") or ""),
        duration_sec=float(duration)
        if isinstance(duration, int | float) and not isinstance(duration, bool)
        else None,
        live_status=raw.get("live_status"),
        availability=raw.get("availability"),
    )
    check_info(info)
    return {
        "title": info.title,
        "duration_sec": info.duration_sec,
        "live_status": info.live_status,
        "availability": info.availability,
    }


class ProgressHook:
    """yt-dlp's progress hook: the byte fraction to the parent, each whole
    percent once, and the size cap again for a response with no length."""

    def __init__(self, out: IO[str], max_bytes: int) -> None:
        self._out = out
        self._max_bytes = max_bytes
        self._shown = -1

    def __call__(self, status: dict[str, Any]) -> None:
        done = status.get("downloaded_bytes") or 0
        if done > self._max_bytes:
            raise FetchError(FetchKind.TOO_LARGE, f"{done} bytes and counting")
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        if not total:
            return
        percent = int(min(done / total, 1.0) * 100)
        if percent > self._shown:
            self._shown = percent
            send(self._out, {"progress": percent / 100})


# The classifier. Order matters: a private video's message also asks the
# viewer to sign in, and a hate-speech removal mentions "your country".
_MESSAGES: list[tuple[FetchKind, re.Pattern[str]]] = [
    (FetchKind.PRIVATE, re.compile(r"private video|this video is private")),
    (
        FetchKind.RATE_LIMITED,
        # "not a bot" matches YouTube's curly apostrophe and a straight one.
        re.compile(
            r"not a bot|try again later|rate-limited|captcha|likely being blocked"
            r"|too many requests"
        ),
    ),
    (
        FetchKind.AGE_RESTRICTED,
        re.compile(r"confirm your age|age-restricted|inappropriate for some users"),
    ),
    (
        FetchKind.MEMBERS_ONLY,
        re.compile(
            r"members-only|channel's members|join this channel|requires payment"
            r"|drm protected|premium members"
        ),
    ),
    (
        FetchKind.UPCOMING,
        re.compile(r"live event will begin|premieres in|premiere will begin"),
    ),
    (
        FetchKind.GEO_RESTRICTED,
        re.compile(r"not made this video available in your country|from your location"),
    ),
    (
        FetchKind.UNAVAILABLE,
        re.compile(
            r"video unavailable|video is unavailable|video is not available"
            r"|has been removed|no longer available|been terminated"
            r"|recording is not available|does not exist"
        ),
    ),
]
_FORMAT_ERROR = re.compile(
    r"requested format is not available|no video formats found"
    r"|only images are available"
)
_BROKEN = re.compile(
    r"unable to extract|unsupported url|no suitable extractor"
    r"|failed to extract any player response|signature extraction failed"
)
_CHALLENGE_WARNING = re.compile(
    r"challenge|javascript runtime|signature solving|remote components?", re.IGNORECASE
)


def classify(error: BaseException, warnings: Sequence[str] = ()) -> FetchKind:
    """The kind of a failure, from yt-dlp's exception types first and its
    messages second. Anything unrecognised is unknown: fetch_failed, and
    retried, which is honest if less helpful."""
    from yt_dlp.networking.exceptions import HTTPError, TransportError
    from yt_dlp.utils import (
        ContentTooShortError,
        GeoRestrictedError,
        UnavailableVideoError,
    )

    chain = list(exception_chain(error))
    text = " ".join(str(exc) for exc in chain).lower()
    statuses = {exc.status for exc in chain if isinstance(exc, HTTPError)}
    challenged = any(_CHALLENGE_WARNING.search(warning) for warning in warnings)

    if any(isinstance(exc, GeoRestrictedError) for exc in chain):
        return FetchKind.GEO_RESTRICTED
    if 429 in statuses:
        return FetchKind.RATE_LIMITED
    for kind, pattern in _MESSAGES:
        if pattern.search(text):
            return kind
    if _FORMAT_ERROR.search(text):
        # Without a working runtime YouTube offers few formats, and "no
        # audio" would blame every video for our own problem.
        return FetchKind.EXTRACTOR_BROKEN if challenged else FetchKind.NO_AUDIO
    if _BROKEN.search(text):
        return FetchKind.EXTRACTOR_BROKEN
    network = (
        TransportError,
        ContentTooShortError,
        ConnectionError,
        TimeoutError,
        socket.gaierror,
        ssl.SSLError,
    )
    if any(isinstance(exc, network) for exc in chain):
        return FetchKind.NETWORK
    if any(status >= 500 for status in statuses):
        return FetchKind.NETWORK
    if 403 in statuses and challenged:
        return FetchKind.EXTRACTOR_BROKEN
    # yt-dlp raises UnavailableVideoError when writing the file fails.
    if any(isinstance(exc, OSError | UnavailableVideoError) for exc in chain):
        return FetchKind.LOCAL_IO  # a full disk, say
    return FetchKind.UNKNOWN


def exception_chain(error: BaseException) -> Iterator[BaseException]:
    """`error` and everything behind it: yt-dlp's `exc_info` and `cause`,
    and Python's own __cause__ and __context__. Each once."""
    seen: set[int] = set()
    pending: list[BaseException | None] = [error]
    while pending:
        exc = pending.pop(0)
        if exc is None or id(exc) in seen:
            continue
        seen.add(id(exc))
        yield exc
        exc_info = getattr(exc, "exc_info", None)
        if isinstance(exc_info, tuple) and len(exc_info) == 3:
            pending.append(exc_info[1])
        cause = getattr(exc, "cause", None)
        if isinstance(cause, BaseException):
            pending.append(cause)
        pending += [exc.__cause__, exc.__context__]


def send(out: IO[str], message: dict[str, Any]) -> None:
    out.write(json.dumps(message) + "\n")
    out.flush()


def _protocol_stream() -> IO[str]:
    """Our stdout, kept for the protocol. File descriptor 1 then points at
    stderr, so nothing yt-dlp or Deno prints can corrupt an answer."""
    sys.stdout.flush()
    protocol = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    return protocol


def _new_ydl(options: dict[str, Any]) -> Any:
    # yt-dlp loads plugins from the user's and the system's config
    # directories when a YoutubeDL is made; the parent sets this too.
    os.environ["YTDLP_NO_PLUGINS"] = "1"
    import yt_dlp

    return yt_dlp.YoutubeDL(options)


def _answer(
    args: list[str], runtime: JsRuntime, log: ChildLog, out: IO[str]
) -> dict[str, Any]:
    if len(args) == 2 and args[0] == "lookup":
        with _new_ydl(ydl_options(deno=runtime.path, logger=log)) as ydl:
            return lookup(ydl, args[1])
    if len(args) == 4 and args[0] == "download":
        work_dir, max_bytes = Path(args[2]), int(args[3])
        hook = ProgressHook(out, max_bytes)
        options = ydl_options(
            deno=runtime.path,
            logger=log,
            work_dir=work_dir,
            max_bytes=max_bytes,
            hooks=[hook],
        )
        with _new_ydl(options) as ydl:
            return download(ydl, args[1], work_dir, max_bytes, log)
    raise FetchError(
        FetchKind.CRASHED, f"usage: lookup URL | download URL DIR BYTES, got {args!r}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    out = _protocol_stream()
    log = ChildLog(sys.stderr)
    versions = Versions()
    try:
        runtime = find_deno()
        if runtime is None:
            minimum = ".".join(str(part) for part in MIN_DENO_VERSION)
            raise FetchError(
                FetchKind.MISCONFIGURED,
                f"no JavaScript runtime: Deno {minimum} or later is not installed",
            )
        try:
            from yt_dlp.version import __version__ as ytdlp_version
        except ImportError as error:
            raise FetchError(
                FetchKind.MISCONFIGURED, f"yt-dlp will not import: {error!r}"
            ) from None
        versions = Versions(ytdlp=ytdlp_version, js=runtime.label)
        result = _answer(args, runtime, log, out)
    except FetchError as error:
        _send_error(out, error.kind, error.detail, error.duration_sec, versions)
    except Exception as error:  # yt-dlp's, classified while its types are here
        _send_error(out, classify(error, log.warnings), str(error), None, versions)
    else:
        send(out, {"result": result, "ytdlp": versions.ytdlp, "js": versions.js})
    return 0


def _send_error(
    out: IO[str],
    kind: FetchKind,
    detail: str,
    duration_sec: float | None,
    versions: Versions,
) -> None:
    sys.stderr.flush()  # so the parent's tail has all of it
    send(
        out,
        {
            "error": {
                "kind": kind.value,
                "detail": detail,
                "duration_sec": duration_sec,
            },
            "ytdlp": versions.ytdlp,
            "js": versions.js,
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Run them to verify they pass**

Run: `uv run pytest packages/fetch/tests/test_classify.py packages/fetch/tests/test_child.py`
Expected: PASS, with no network and no Deno: the tests that run the child as a process hide Deno by emptying `PATH`, or fake one.

- [x] **Step 5: Commit**

```bash
make lint typecheck test
git add mypy.ini \
  packages/fetch/pyproject.toml \
  packages/fetch/src/guitarvis_fetch/child.py \
  packages/fetch/tests/fixtures/youtube-messages.json \
  packages/fetch/tests/test_child.py \
  packages/fetch/tests/test_classify.py \
  uv.lock
git commit -m "feat(fetch): the yt-dlp child, and the classifier that names each failure

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 8: Link jobs in the store: `r0002`, `source_url`, `attach_upload`

A link job's row has its canonical URL and no `upload_key` until the worker has stored the download. Migration `r0002` adds `source_url`, makes `upload_key` nullable, and adds the check constraint that every row has a way to its audio; `NewJob` refuses the same in Python. `attach_upload` is a conditional write on running rows, in the shared contract suite for both stores. The two readers of `upload_key` handle null now: `GET /jobs/{id}/audio/mix` answers 409 (G1), and the runner fails a link job whose audio is not stored with `links_disabled`, since nothing fetches yet (W1; Task 11 adds the fetch). Two upload tests gain a one-line `assert … is not None` for mypy, now that `Job.upload_key` is optional (Deviation 2).

**Catalog rows:** E1 (store), S3 (store), G1, W1.

**Files:**
- Modify: `apps/api/src/guitarvis_api/routes.py`
- Modify: `apps/worker/src/guitarvis_worker/runner.py`
- Create: `packages/jobs/src/guitarvis_jobs/migrations/versions/r0002_link_jobs.py`
- Modify: `packages/jobs/src/guitarvis_jobs/models.py`
- Modify: `packages/jobs/src/guitarvis_jobs/postgres.py`
- Modify: `packages/jobs/src/guitarvis_jobs/store.py`
- Modify: `packages/jobs/src/guitarvis_jobs/testing.py`
- Test: `apps/api/tests/test_job_routes.py`
- Test: `apps/worker/tests/test_runner.py`
- Test: `packages/jobs/tests/test_job_store.py`
- Test: `packages/jobs/tests/test_migrations.py`

**Interfaces:**
- Produces: `NewJob.upload_key: str | None`, `NewJob.source_url: str | None = None`; `Job.upload_key: str | None`, `Job.source_url: str | None = None`; `JobStore.attach_upload(job_id, *, upload_key, duration_sec) -> bool`; `guitarvis_jobs.testing.sample_link_job(...)`; revision `0002`.

- [x] **Step 1: Write the failing tests**

In `apps/api/tests/test_job_routes.py`:

```diff
--- a/apps/api/tests/test_job_routes.py
+++ b/apps/api/tests/test_job_routes.py
@@ -14,7 +14,7 @@ from guitarvis_core.tabdoc import Instrument, Source, TabDocument, Timing
 from guitarvis_jobs.blobs import PRESIGN_EXPIRES_SEC
 from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, JobStatus
 from guitarvis_jobs.store import InMemoryJobStore
-from guitarvis_jobs.testing import FakeClock, sample_new_job
+from guitarvis_jobs.testing import FakeClock, sample_link_job, sample_new_job
 
 MISSING_ID = "5f0c6c2e-0000-4000-8000-0000000000ff"
 STEM_KEY = "cache/v1/" + "a" * 64 + "/separation/stem.wav"
@@ -172,9 +172,34 @@ def test_the_mix_redirects_to_a_presigned_url() -> None:
 
     response = api.client.get(f"/jobs/{job_id}/audio/mix", follow_redirects=False)
 
+    key = api.job(job_id).upload_key
+    assert key is not None  # an upload's, from the start
     assert response.status_code == 307
     assert response.headers["location"] == api.blobs.presign_get(
-        api.job(job_id).upload_key, expires_sec=PRESIGN_EXPIRES_SEC
+        key, expires_sec=PRESIGN_EXPIRES_SEC
+    )
+
+
+def test_the_mix_of_a_link_job_is_not_ready_until_its_download_is_stored() -> None:
+    """G1: never a presigned URL for a key that does not exist yet."""
+    api = make_api()
+    job, _ = api.store.create(sample_link_job())
+    api.store.mark_running(job.id)
+
+    before = api.client.get(f"/jobs/{job.id}/audio/mix", follow_redirects=False)
+    api.store.attach_upload(job.id, upload_key="uploads/e.m4a", duration_sec=37.0)
+    after = api.client.get(f"/jobs/{job.id}/audio/mix", follow_redirects=False)
+
+    assert before.status_code == 409
+    assert before.json() == {
+        "error": {
+            "reason": "not_ready",
+            "message": "The audio is not ready yet. Poll the job until it succeeds.",
+        }
+    }
+    assert after.status_code == 307
+    assert after.headers["location"] == api.blobs.presign_get(
+        "uploads/e.m4a", expires_sec=PRESIGN_EXPIRES_SEC
     )
 
 
```

In `apps/worker/tests/test_runner.py`:

```diff
--- a/apps/worker/tests/test_runner.py
+++ b/apps/worker/tests/test_runner.py
@@ -31,6 +31,7 @@ from guitarvis_jobs.store import InMemoryJobStore
 from guitarvis_jobs.testing import (
     integration_settings,
     redis_connection,
+    sample_link_job,
     sample_new_job,
 )
 from guitarvis_worker import runner
@@ -119,6 +120,7 @@ def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
     store = InMemoryJobStore()
     blobs = InMemoryBlobStore()
     job, _ = store.create(sample_new_job(title="My Song"))
+    assert job.upload_key is not None  # an upload's, from the start
     blobs.put_bytes(job.upload_key, b"pretend mp3 bytes")
     return Harness(store, blobs, StubSeparator(), StubTranscriber(), job.id)
 
@@ -376,6 +378,23 @@ def test_a_result_after_the_row_was_failed_is_dropped(harness: Harness) -> None:
     assert row.document is None
 
 
+def test_a_link_job_with_no_stored_audio_fails_when_nothing_fetches(
+    harness: Harness,
+) -> None:  # W1
+    job, _ = harness.store.create(sample_link_job())
+
+    process_job(job.id, harness.deps(), retries_left=2)  # no retry: returns
+
+    row = harness.store.get(job.id)
+    assert row is not None
+    assert row.failure_reason is FailureReason.LINKS_DISABLED
+    assert row.failure_message == (
+        "Links were turned off before this song could be fetched. "
+        "Upload the audio file instead."
+    )
+    assert harness.separator.calls == 0
+
+
 def test_an_unknown_job_is_dropped(harness: Harness) -> None:
     process_job("5f0c6c2e-0000-4000-8000-0000000000ff", harness.deps(), retries_left=2)
 
```

In `packages/jobs/tests/test_job_store.py`:

```diff
--- a/packages/jobs/tests/test_job_store.py
+++ b/packages/jobs/tests/test_job_store.py
@@ -9,9 +9,14 @@ from concurrent.futures import ThreadPoolExecutor
 
 import pytest
 from guitarvis_core.contracts import FailureReason
-from guitarvis_jobs.models import JobStatus
+from guitarvis_jobs.models import JobStatus, NewJob
 from guitarvis_jobs.store import InMemoryJobStore, JobStore, TooManyActiveJobs
-from guitarvis_jobs.testing import FakeClock, postgres_store, sample_new_job
+from guitarvis_jobs.testing import (
+    FakeClock,
+    postgres_store,
+    sample_link_job,
+    sample_new_job,
+)
 
 HASH_B = "b" * 64
 
@@ -391,3 +396,78 @@ def test_many_creates_through_one_store_keep_deduping(store: JobStore) -> None:
         assert created
         assert not created_again
         assert again.id == job.id
+
+
+# Link jobs (spec 012): no audio stored until the worker has downloaded it.
+
+
+def test_a_link_job_starts_with_its_link_and_no_stored_audio(store: JobStore) -> None:
+    job, created = store.create(sample_link_job())
+
+    assert created
+    assert job.upload_key is None
+    assert job.source_url == "https://www.youtube.com/watch?v=kPdv44HtEoA"
+    assert store.get(job.id) == job
+
+
+def test_an_upload_has_no_source_url(store: JobStore) -> None:
+    job, _ = store.create(sample_new_job())
+
+    assert job.source_url is None
+
+
+def test_the_same_video_again_is_the_same_job(store: JobStore) -> None:  # E1
+    first, _ = store.create(sample_link_job())
+    again, created = store.create(sample_link_job(client_ip="198.51.100.1"))
+
+    assert not created
+    assert again.id == first.id
+
+
+def test_attach_upload_records_the_key_and_the_probed_length(
+    store: JobStore, clock: FakeClock
+) -> None:
+    job, _ = store.create(sample_link_job(duration_sec=37.0))
+    store.mark_running(job.id)
+    clock.advance(seconds=1)
+
+    assert store.attach_upload(
+        job.id, upload_key="uploads/" + "e" * 64 + ".m4a", duration_sec=37.059
+    )
+
+    row = store.get(job.id)
+    assert row is not None
+    assert row.upload_key == "uploads/" + "e" * 64 + ".m4a"
+    assert row.duration_sec == 37.059
+    assert row.content_hash == job.content_hash  # the dedupe key stays the video's
+    assert row.updated_at == clock.now
+
+
+def test_attach_upload_changes_nothing_once_the_row_is_not_running(
+    store: JobStore,
+) -> None:  # S3
+    queued, _ = store.create(sample_link_job())
+    failed, _ = store.create(sample_link_job(video_id="YE7VzlLtp-4"))
+    store.mark_running(failed.id)
+    store.fail(
+        failed.id,
+        reason=FailureReason.INTERNAL,
+        message="lost",
+        stage="download",
+        expect=JobStatus.RUNNING,
+    )
+
+    for job_id in (queued.id, failed.id, "not-a-uuid"):
+        assert not store.attach_upload(job_id, upload_key="k", duration_sec=1.0)
+    assert store.get(queued.id) == queued
+
+
+def test_a_new_job_needs_an_upload_or_a_link() -> None:
+    with pytest.raises(ValueError, match="upload_key or a source_url"):
+        NewJob(
+            content_hash="a" * 64,
+            title="t",
+            duration_sec=1.0,
+            upload_key=None,
+            client_ip="203.0.113.7",
+        )
```

In `packages/jobs/tests/test_migrations.py`:

```diff
--- a/packages/jobs/tests/test_migrations.py
+++ b/packages/jobs/tests/test_migrations.py
@@ -1,6 +1,8 @@
 """The Alembic migration and the table the code queries must agree."""
 
+import pytest
 import sqlalchemy as sa
+from alembic import command
 from alembic.autogenerate import compare_metadata
 from alembic.migration import MigrationContext
 from alembic.script import ScriptDirectory
@@ -36,3 +38,36 @@ def test_migration_files_have_importable_names() -> None:
 
     assert versions, "no migrations found"
     assert all(path.stem.isidentifier() for path in versions)
+
+
+def test_r0002_goes_down_and_up_again() -> None:
+    url = integration_settings().database_url
+
+    with postgres_store() as store:
+        command.downgrade(alembic_config(url), "0001")
+        with store.engine.connect() as connection:
+            columns = {c["name"]: c for c in sa.inspect(connection).get_columns("jobs")}
+            assert "source_url" not in columns
+            assert columns["upload_key"]["nullable"] is False
+
+        upgrade(url)
+        with store.engine.connect() as connection:
+            columns = {c["name"]: c for c in sa.inspect(connection).get_columns("jobs")}
+            assert columns["source_url"]["nullable"] is True
+            assert columns["upload_key"]["nullable"] is True
+
+
+def test_the_table_refuses_a_row_with_no_way_to_its_audio() -> None:
+    insert = sa.text(
+        "INSERT INTO jobs (id, content_hash, status, percent, attempts, title, "
+        "duration_sec, upload_key, client_ip, created_at, updated_at, source_url) "
+        "VALUES (gen_random_uuid(), 'h', 'queued', 0, 0, 't', 1, NULL, 'ip', "
+        "now(), now(), NULL)"
+    )
+
+    with (
+        postgres_store() as store,
+        pytest.raises(sa.exc.IntegrityError, match="jobs_has_audio_source"),
+        store.engine.begin() as connection,
+    ):
+        connection.execute(insert)
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/jobs/tests/test_job_store.py packages/jobs/tests/test_migrations.py apps/api/tests/test_job_routes.py apps/worker/tests/test_runner.py`
Expected: FAIL at collection: `ImportError: cannot import name 'sample_link_job' from 'guitarvis_jobs.testing'`.

- [x] **Step 3: Implement**

In `apps/api/src/guitarvis_api/routes.py`:

```diff
--- a/apps/api/src/guitarvis_api/routes.py
+++ b/apps/api/src/guitarvis_api/routes.py
@@ -184,6 +184,8 @@ def get_mix(job_id: str, request: Request) -> RedirectResponse:
     # which seeking needs, and the api stays thin.
     services = services_of(request)
     job = _load(services, job_id)
+    if job.upload_key is None:  # a link job whose download is not stored yet
+        raise _not_ready(job, "audio")
     url = services.blobs.presign_get(job.upload_key, expires_sec=PRESIGN_EXPIRES_SEC)
     return RedirectResponse(url, status_code=307)
 
```

In `apps/worker/src/guitarvis_worker/runner.py`:

```diff
--- a/apps/worker/src/guitarvis_worker/runner.py
+++ b/apps/worker/src/guitarvis_worker/runner.py
@@ -193,6 +193,13 @@ def _shown(error: PipelineError) -> str:
 def _run(
     job: Job, deps: WorkerDeps, progress: _ProgressWriter
 ) -> tuple[dict[str, Any], str]:
+    if job.upload_key is None:
+        # A link job whose download is not stored, and nothing here fetches.
+        raise PipelineError(
+            FailureReason.LINKS_DISABLED,
+            "Links were turned off before this song could be fetched. "
+            "Upload the audio file instead.",
+        )
     keys = CacheKeys(job.content_hash)
     with tempfile.TemporaryDirectory(prefix="guitarvis-job-") as tmp:
         work_dir = Path(tmp)
```

Create `packages/jobs/src/guitarvis_jobs/migrations/versions/r0002_link_jobs.py`:

```python
"""Link jobs: source_url, and an upload_key that waits for the download.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("source_url", sa.Text(), nullable=True))
    op.alter_column("jobs", "upload_key", existing_type=sa.Text(), nullable=True)
    op.create_check_constraint(
        "jobs_has_audio_source",
        "jobs",
        "upload_key IS NOT NULL OR source_url IS NOT NULL",
    )


def downgrade() -> None:
    # A link job whose download was never stored has nothing a 0001 row
    # could point at. It goes: going down is for development databases.
    op.execute("DELETE FROM jobs WHERE upload_key IS NULL")
    op.drop_constraint("jobs_has_audio_source", "jobs", type_="check")
    op.alter_column("jobs", "upload_key", existing_type=sa.Text(), nullable=False)
    op.drop_column("jobs", "source_url")
```

In `packages/jobs/src/guitarvis_jobs/models.py`:

```diff
--- a/packages/jobs/src/guitarvis_jobs/models.py
+++ b/packages/jobs/src/guitarvis_jobs/models.py
@@ -37,18 +37,32 @@ def canonical_id(raw: str) -> str | None:
 
 @dataclass(frozen=True)
 class NewJob:
-    """What an upload contributes to a fresh row."""
+    """What an upload or a link contributes to a fresh row.
+
+    An upload has its `upload_key` already. A link job has `source_url`, and
+    its key arrives when the worker has stored the download (spec 012).
+    """
 
     content_hash: str
     title: str
     duration_sec: float
-    upload_key: str
+    upload_key: str | None
     client_ip: str
+    source_url: str | None = None
+
+    def __post_init__(self) -> None:
+        if self.upload_key is None and self.source_url is None:
+            raise ValueError("a job needs an upload_key or a source_url")
 
 
 @dataclass(frozen=True)
 class Job:
-    """One row of the jobs table; spec 005 describes each column."""
+    """One row of the jobs table; spec 005 describes each column.
+
+    `content_hash` is the dedupe key: the hash of an upload's bytes, or for a
+    link job the video's identity, sha256("youtube:" + id). The hash of a
+    link job's bytes is in its `upload_key`, once the worker sets it.
+    """
 
     id: str
     content_hash: str
@@ -61,9 +75,10 @@ class Job:
     failed_stage: str | None
     title: str
     duration_sec: float
-    upload_key: str
+    upload_key: str | None
     stem_key: str | None
     client_ip: str
     document: dict[str, Any] | None
     created_at: datetime
     updated_at: datetime
+    source_url: str | None = None
```

In `packages/jobs/src/guitarvis_jobs/postgres.py`:

```diff
--- a/packages/jobs/src/guitarvis_jobs/postgres.py
+++ b/packages/jobs/src/guitarvis_jobs/postgres.py
@@ -41,17 +41,23 @@ jobs = sa.Table(
     sa.Column("failed_stage", sa.Text(), nullable=True),
     sa.Column("title", sa.Text(), nullable=False),
     sa.Column("duration_sec", sa.Float(), nullable=False),
-    sa.Column("upload_key", sa.Text(), nullable=False),
+    sa.Column("upload_key", sa.Text(), nullable=True),
     sa.Column("stem_key", sa.Text(), nullable=True),
     sa.Column("client_ip", sa.Text(), nullable=False),
     sa.Column("document", JSONB(), nullable=True),
     sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
     sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
+    sa.Column("source_url", sa.Text(), nullable=True),
     sa.CheckConstraint(
         "status IN ('queued', 'running', 'succeeded', 'failed')",
         name="jobs_status_valid",
     ),
     sa.CheckConstraint("percent BETWEEN 0 AND 100", name="jobs_percent_range"),
+    # Every row has a way to its audio: stored, or a link to fetch it from.
+    sa.CheckConstraint(
+        "upload_key IS NOT NULL OR source_url IS NOT NULL",
+        name="jobs_has_audio_source",
+    ),
     # The dedupe rule: one live job per upload; a failed one never blocks.
     sa.Index(
         "jobs_content_hash_live",
@@ -99,6 +105,7 @@ class PostgresJobStore:
                     client_ip=new.client_ip,
                     created_at=now,
                     updated_at=now,
+                    source_url=new.source_url,
                 )
                 .on_conflict_do_nothing(
                     index_elements=[jobs.c.content_hash],
@@ -166,6 +173,16 @@ class PostgresJobStore:
         )
         return changed is not None
 
+    def attach_upload(
+        self, job_id: str, *, upload_key: str, duration_sec: float
+    ) -> bool:
+        changed = self._update(
+            job_id,
+            {JobStatus.RUNNING},
+            {"upload_key": upload_key, "duration_sec": duration_sec},
+        )
+        return changed is not None
+
     def succeed(self, job_id: str, *, document: dict[str, Any], stem_key: str) -> bool:
         changed = self._update(
             job_id,
@@ -308,6 +325,7 @@ def _to_job(row: sa.RowMapping) -> Job:
         document=row["document"],
         created_at=row["created_at"],
         updated_at=row["updated_at"],
+        source_url=row["source_url"],
     )
 
 
```

In `packages/jobs/src/guitarvis_jobs/store.py`:

```diff
--- a/packages/jobs/src/guitarvis_jobs/store.py
+++ b/packages/jobs/src/guitarvis_jobs/store.py
@@ -73,6 +73,14 @@ class JobStore(Protocol):
 
     def set_progress(self, job_id: str, stage: str, percent: int) -> bool: ...
 
+    def attach_upload(
+        self, job_id: str, *, upload_key: str, duration_sec: float
+    ) -> bool:
+        """Record where a link job's download is stored, and its probed
+        length, while the row is running. False when it is not: the api's
+        reconciliation failed it meanwhile."""
+        ...
+
     def succeed(
         self, job_id: str, *, document: dict[str, Any], stem_key: str
     ) -> bool: ...
@@ -139,6 +147,7 @@ class InMemoryJobStore:
                 document=None,
                 created_at=now,
                 updated_at=now,
+                source_url=new.source_url,
             )
             self._rows[job.id] = job
             return job, True
@@ -190,6 +199,16 @@ class InMemoryJobStore:
         )
         return changed is not None
 
+    def attach_upload(
+        self, job_id: str, *, upload_key: str, duration_sec: float
+    ) -> bool:
+        changed = self._transition(
+            job_id,
+            {JobStatus.RUNNING},
+            lambda row: replace(row, upload_key=upload_key, duration_sec=duration_sec),
+        )
+        return changed is not None
+
     def succeed(self, job_id: str, *, document: dict[str, Any], stem_key: str) -> bool:
         stored = copy.deepcopy(document)
         changed = self._transition(
```

In `packages/jobs/src/guitarvis_jobs/testing.py`:

```diff
--- a/packages/jobs/src/guitarvis_jobs/testing.py
+++ b/packages/jobs/src/guitarvis_jobs/testing.py
@@ -8,6 +8,7 @@ Makefile).
 """
 
 import functools
+import hashlib
 import os
 from collections.abc import Callable, Iterator
 from contextlib import contextmanager
@@ -65,6 +66,25 @@ def sample_new_job(
     )
 
 
+def sample_link_job(
+    *,
+    video_id: str = "kPdv44HtEoA",
+    title: str = "Elephants Dream - 10 years of open movies",
+    duration_sec: float = 37.0,
+    client_ip: str = "203.0.113.7",
+) -> NewJob:
+    """A link job as the api creates it: no audio stored yet, and the
+    video's identity as its dedupe key (guitarvis_fetch.links.Link)."""
+    return NewJob(
+        content_hash=hashlib.sha256(f"youtube:{video_id}".encode()).hexdigest(),
+        title=title,
+        duration_sec=duration_sec,
+        upload_key=None,
+        client_ip=client_ip,
+        source_url=f"https://www.youtube.com/watch?v={video_id}",
+    )
+
+
 REQUIRE_SERVICES_ENV = "GUITARVIS_REQUIRE_SERVICES"
 TEST_DATABASE = "guitarvis_test"
 TEST_REDIS_DB = 15
```

- [x] **Step 4: Run them to verify they pass**

Run: `uv run pytest packages/jobs/tests/test_job_store.py packages/jobs/tests/test_migrations.py apps/api/tests/test_job_routes.py apps/worker/tests/test_runner.py`
Expected: PASS. With `make services` up, the `[postgres]` variants and the migration tests run too; without it they skip, and CI fails them under `GUITARVIS_REQUIRE_SERVICES=1`.

- [x] **Step 5: Commit**

```bash
make lint typecheck test
git add apps/api/src/guitarvis_api/routes.py \
  apps/api/tests/test_job_routes.py \
  apps/worker/src/guitarvis_worker/runner.py \
  apps/worker/tests/test_runner.py \
  packages/jobs/src/guitarvis_jobs/migrations/versions/r0002_link_jobs.py \
  packages/jobs/src/guitarvis_jobs/models.py \
  packages/jobs/src/guitarvis_jobs/postgres.py \
  packages/jobs/src/guitarvis_jobs/store.py \
  packages/jobs/src/guitarvis_jobs/testing.py \
  packages/jobs/tests/test_job_store.py \
  packages/jobs/tests/test_migrations.py
git commit -m "feat(jobs): link jobs, whose audio is stored once the worker has it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 9: The api's contract: `source_url`, `LinkRequest`, `Features`

`JobView` gains `source_url`, and the request and response models of the link routes join the schema, so `make schema` gives the client `LinkRequest` and `Features`. The schema's root union now includes a request body, so it is renamed `ApiBody`; nothing used `ApiResponse`. The api now depends on `guitarvis-fetch` (for `MAX_LINK_CHARS`), and `test_boundaries.py` gains spec 012's own rule: the api never imports `yt_dlp`. `test_a_queued_job`, which pins a whole `JobView` body, gains `"source_url": None` (Deviation 2). The web test helper `jobView()` gains `source_url: null`, or `tsc` fails.

**Catalog rows:** R2's length limit; the schema every link response follows.

**Files:**
- Modify: `apps/api/pyproject.toml`
- Modify: `apps/api/src/guitarvis_api/schema_export.py`
- Modify: `apps/api/src/guitarvis_api/schemas.py`
- Test: `apps/api/tests/test_api_schema.py`
- Test: `apps/api/tests/test_boundaries.py`
- Test: `apps/api/tests/test_job_routes.py`
- Test: `web/src/test/jobs.ts`
- Generated, by `make schema`: `schema/api.schema.json`
- Generated, by `uv lock`: `uv.lock`
- Generated, by `make schema`: `web/src/types/api.ts`

**Interfaces:**
- Produces: `JobView.source_url: str | None`; `LinkRequest(url: str, max 2048)`; `Features(url_ingestion: bool)`; generated `LinkRequest`, `Features`, `ApiBody` in `web/src/types/api.ts`.

- [x] **Step 1: Write the failing tests**

In `apps/api/tests/test_api_schema.py`:

```diff
--- a/apps/api/tests/test_api_schema.py
+++ b/apps/api/tests/test_api_schema.py
@@ -48,6 +48,21 @@ def test_the_schema_names_all_twelve_reasons() -> None:
     assert len(named) == 12
 
 
+def test_the_schema_describes_features_and_the_link_request() -> None:
+    definitions = api_schema()["$defs"]
+
+    assert definitions["Features"]["properties"] == {
+        "url_ingestion": {"type": "boolean"}
+    }
+    assert definitions["Features"]["required"] == ["url_ingestion"]
+    assert definitions["LinkRequest"]["properties"] == {
+        "url": {"type": "string", "maxLength": 2048}
+    }
+    assert definitions["JobView"]["properties"]["source_url"] == {
+        "anyOf": [{"type": "string"}, {"type": "null"}]
+    }
+
+
 def test_a_failed_job_can_carry_only_a_failure_reason() -> None:
     """The five HttpReason values describe a request, never a job."""
     reason = api_schema()["$defs"]["FailureView"]["properties"]["reason"]
```

In `apps/api/tests/test_boundaries.py`:

```diff
--- a/apps/api/tests/test_boundaries.py
+++ b/apps/api/tests/test_boundaries.py
@@ -89,3 +89,20 @@ def test_importing_api_loads_no_ml_modules() -> None:
     assert result.stdout.strip() == "", (
         f"importing guitarvis_api pulled in: {result.stdout.strip()}"
     )
+
+
+def test_the_api_never_imports_yt_dlp() -> None:
+    """Spec 012's rule, not invariant 3's: yt-dlp is not ML, but it runs only
+    in guitarvis_fetch.child's own process, never in the api's."""
+    offenders = [
+        str(source_file)
+        for source_file in sorted(API_SOURCE.rglob("*.py"))
+        if "yt_dlp" in imported_roots(source_file)
+    ]
+    probe = "import sys, guitarvis_api.app; print('yt_dlp' in sys.modules)"
+    loaded = subprocess.run(
+        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
+    ).stdout.strip()
+
+    assert offenders == [], f"the api imports yt_dlp in {offenders}"
+    assert loaded == "False", "importing the api loaded yt_dlp"
```

In `apps/api/tests/test_job_routes.py`:

```diff
--- a/apps/api/tests/test_job_routes.py
+++ b/apps/api/tests/test_job_routes.py
@@ -87,11 +87,23 @@ def test_a_queued_job() -> None:
         "title": "song",
         "duration_sec": 30.0,
         "failure": None,
+        "source_url": None,
         "created_at": "2026-10-08T12:00:00Z",
         "updated_at": "2026-10-08T12:00:00Z",
     }
 
 
+def test_a_job_names_the_link_it_was_made_from_and_an_upload_none() -> None:
+    api = make_api()
+    upload = queued(api)
+    link, _ = api.store.create(sample_link_job())
+
+    assert api.client.get(f"/jobs/{upload}").json()["source_url"] is None
+    assert api.client.get(f"/jobs/{link.id}").json()["source_url"] == (
+        "https://www.youtube.com/watch?v=kPdv44HtEoA"
+    )
+
+
 def test_timestamps_are_utc_whatever_offset_the_store_returns() -> None:
     """Postgres answers in its session's time zone; the body must not."""
     plus_two = FakeClock(
```

In `web/src/test/jobs.ts`:

```diff
--- a/web/src/test/jobs.ts
+++ b/web/src/test/jobs.ts
@@ -13,6 +13,7 @@ export function jobView(fields: Partial<JobView> = {}): JobView {
     title: "Song",
     duration_sec: 13.871,
     failure: null,
+    source_url: null,
     created_at: "2026-10-08T12:00:00Z",
     updated_at: "2026-10-08T12:00:00Z",
     ...fields,
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest apps/api/tests/test_api_schema.py apps/api/tests/test_job_routes.py apps/api/tests/test_boundaries.py`
Expected: FAIL: `KeyError: 'Features'` in the schema test, and `test_a_queued_job`'s body lacks `source_url`.

- [x] **Step 3: Implement**

Then `uv lock && uv sync` (the api's new dependency) and `make schema`.

In `apps/api/pyproject.toml`:

```diff
--- a/apps/api/pyproject.toml
+++ b/apps/api/pyproject.toml
@@ -6,6 +6,7 @@ requires-python = ">=3.12"
 dependencies = [
     "guitarvis-core",
     "guitarvis-jobs",
+    "guitarvis-fetch",
     "fastapi>=0.115",
     "uvicorn>=0.30",
     "python-multipart>=0.0.18",
```

In `apps/api/src/guitarvis_api/schema_export.py`:

```diff
--- a/apps/api/src/guitarvis_api/schema_export.py
+++ b/apps/api/src/guitarvis_api/schema_export.py
@@ -18,25 +18,36 @@ from guitarvis_core.schema_export import strip_property_titles
 from pydantic.json_schema import models_json_schema
 
 from guitarvis_api.errors import ErrorBody
-from guitarvis_api.schemas import JobView
+from guitarvis_api.schemas import Features, JobView, LinkRequest
 
 DEFAULT_OUTPUT = Path("schema/api.schema.json")
 
 
 def api_schema() -> dict[str, Any]:
-    """Every body the api answers with: a job, or an error.
+    """Every body the api answers with — a job, an error, its features — and
+    the one body it reads as JSON, a link.
 
-    The root is the union of the two, so the generator emits a type for each
-    model without needing a list of unreachable definitions.
+    The root is the union of all four, so the generator emits a type for
+    each model without needing a list of unreachable definitions.
     """
     _, definitions = models_json_schema(
-        [(JobView, "serialization"), (ErrorBody, "serialization")],
+        [
+            (JobView, "serialization"),
+            (ErrorBody, "serialization"),
+            (Features, "serialization"),
+            (LinkRequest, "validation"),
+        ],
         ref_template="#/$defs/{model}",
     )
     schema: dict[str, Any] = {
         "$schema": "https://json-schema.org/draft/2020-12/schema",
-        "title": "ApiResponse",
-        "anyOf": [{"$ref": "#/$defs/JobView"}, {"$ref": "#/$defs/ErrorBody"}],
+        "title": "ApiBody",
+        "anyOf": [
+            {"$ref": "#/$defs/JobView"},
+            {"$ref": "#/$defs/ErrorBody"},
+            {"$ref": "#/$defs/Features"},
+            {"$ref": "#/$defs/LinkRequest"},
+        ],
         **definitions,
     }
     strip_property_titles(schema)
```

In `apps/api/src/guitarvis_api/schemas.py`:

```diff
--- a/apps/api/src/guitarvis_api/schemas.py
+++ b/apps/api/src/guitarvis_api/schemas.py
@@ -3,8 +3,9 @@
 from datetime import UTC, datetime
 
 from guitarvis_core.contracts import FailureReason
+from guitarvis_fetch.links import MAX_LINK_CHARS
 from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, Job, JobStatus
-from pydantic import BaseModel, field_serializer
+from pydantic import BaseModel, Field, field_serializer
 
 
 class FailureView(BaseModel):
@@ -17,7 +18,11 @@ class FailureView(BaseModel):
 
 
 class JobView(BaseModel):
-    """`failure` is set only when `status` is failed; `stage` only while running."""
+    """`failure` is set only when `status` is failed; `stage` only while running.
+
+    `source_url` is the link a link job was made from, in canonical form, and
+    null for an upload.
+    """
 
     id: str
     status: JobStatus
@@ -27,6 +32,7 @@ class JobView(BaseModel):
     title: str
     duration_sec: float
     failure: FailureView | None
+    source_url: str | None
     created_at: datetime
     updated_at: datetime
 
@@ -54,6 +60,20 @@ class JobView(BaseModel):
             title=job.title,
             duration_sec=job.duration_sec,
             failure=failure,
+            source_url=job.source_url,
             created_at=job.created_at,
             updated_at=job.updated_at,
         )
+
+
+class LinkRequest(BaseModel):
+    """POST /jobs/from-url's body: one link, as the user pasted it."""
+
+    url: str = Field(max_length=MAX_LINK_CHARS)
+
+
+class Features(BaseModel):
+    """GET /features: what this api has switched on, so the client shows only
+    what will work. Read from the api's own settings at start."""
+
+    url_ingestion: bool
```

- [x] **Step 4: Run them to verify they pass**

Run: `uv run pytest apps/api/tests/test_api_schema.py apps/api/tests/test_job_routes.py apps/api/tests/test_boundaries.py`
Expected: PASS, and `npm --prefix web run typecheck` passes with the new `jobView()`.

- [x] **Step 5: Commit**

```bash
make lint typecheck test
git add apps/api/pyproject.toml \
  apps/api/src/guitarvis_api/schema_export.py \
  apps/api/src/guitarvis_api/schemas.py \
  apps/api/tests/test_api_schema.py \
  apps/api/tests/test_boundaries.py \
  apps/api/tests/test_job_routes.py \
  schema/api.schema.json \
  uv.lock \
  web/src/test/jobs.ts \
  web/src/types/api.ts
git commit -m "feat(api): a job names the link it came from; the schema gains features and the link request

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 10: `POST /jobs/from-url` and `GET /features`

Everything links add to the api is `routes_links.py`, wired by one call in `app.py`. A custom `APIRoute` checks the switch before the body is read (R1), since FastAPI parses JSON before any dependency runs, and turns a body it cannot validate into `unsupported_link` (R2) without touching the app's upload-only validation handler. `UploadSizeLimit` learns to guard any one path, so the link route gets a 16 KB cap with its own message (R3). The route reuses the upload path's steps, now public in `routes.py` without changing behaviour: `live_job` (dedupe, reconciling), `check_limit`, `enqueue`. `Services` gains the fetcher (`ChildFetcher` when links are on, else `None`) and a four-slot semaphore taken without waiting (Q3).

**Catalog rows:** R1 to R7, Q1 to Q3, L1 to L18, E1 to E4, G1.

**Files:**
- Modify: `apps/api/src/guitarvis_api/app.py`
- Modify: `apps/api/src/guitarvis_api/routes.py`
- Create: `apps/api/src/guitarvis_api/routes_links.py`
- Modify: `apps/api/src/guitarvis_api/services.py`
- Modify: `apps/api/src/guitarvis_api/uploads.py`
- Test: `apps/api/tests/api_fixture.py`
- Test (new): `apps/api/tests/test_links_route.py`

**Interfaces:**
- Produces: `routes_links.install(app)`, `LINK_PATH`, `LINK_BODY_MAX_BYTES`; `Services.fetcher`, `Services.lookups`, `MAX_CONCURRENT_LOOKUPS = 4`; `UploadSizeLimit(app, *, path, limit, refuse)`; `routes.check_limit`, `routes.enqueue`, `routes.live_job`, `routes.too_many_jobs`, `routes.client_ip_of`; `make_api(..., fetcher=...)` in the test fixture.

- [ ] **Step 1: Write the failing tests**

In `apps/api/tests/api_fixture.py`:

```diff
--- a/apps/api/tests/api_fixture.py
+++ b/apps/api/tests/api_fixture.py
@@ -12,6 +12,7 @@ from typing import Any
 from fastapi.testclient import TestClient
 from guitarvis_api.app import create_app
 from guitarvis_api.services import Services
+from guitarvis_fetch.fetcher import UrlFetcher
 from guitarvis_jobs.blobs import InMemoryBlobStore
 from guitarvis_jobs.models import Job
 from guitarvis_jobs.queue import InMemoryJobQueue
@@ -51,6 +52,7 @@ def make_api(
     probe: Callable[[Path], float] = thirty_seconds,
     store: InMemoryJobStore | None = None,
     blobs: InMemoryBlobStore | None = None,
+    fetcher: UrlFetcher | None = None,
     raise_server_exceptions: bool = True,
     **settings: Any,  # Settings fields to override, e.g. max_upload_mb=1
 ) -> Api:
@@ -66,6 +68,7 @@ def make_api(
         settings=resolved,
         probe=probe,
         clock=clock,
+        fetcher=fetcher,
     )
     client = TestClient(
         create_app(services),
```

Create `apps/api/tests/test_links_route.py`:

```python
"""POST /jobs/from-url and GET /features (spec 012): every R, Q, L, E and G
row of the failure catalog, on in-memory stores and a fake fetcher that
records its calls. Nothing here makes a network request."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import httpx2
import pytest
from api_fixture import CLIENT_IP, Api, make_api
from fastapi.testclient import TestClient
from guitarvis_fetch.catalog import CATALOG, FetchKind, message_for
from guitarvis_fetch.fetcher import FetchError, VideoInfo
from guitarvis_fetch.links import parse
from guitarvis_fetch.testing import FakeFetcher, video_info
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, JobStatus, NewJob
from guitarvis_jobs.store import InMemoryJobStore

ID = "kPdv44HtEoA"
LINK = f"https://www.youtube.com/watch?v={ID}"
DEDUPE_KEY = parse(LINK).dedupe_key
SENTINEL = "SENTINEL-4f2a"
ROUTE_LOG = "guitarvis_api.routes_links"


def links_api(fetcher: FakeFetcher | None = None, **settings: Any) -> Api:
    return make_api(
        fetcher=fetcher if fetcher is not None else FakeFetcher(),
        url_ingestion=settings.pop("url_ingestion", True),
        **settings,
    )


def fake(api: Api) -> FakeFetcher:
    fetcher = api.services.fetcher
    assert isinstance(fetcher, FakeFetcher)
    return fetcher


def post_link(client: TestClient, url: str = LINK) -> httpx2.Response:
    return client.post("/jobs/from-url", json={"url": url})


def error_of(response: httpx2.Response) -> tuple[int, str, str]:
    body = response.json()["error"]
    return response.status_code, body["reason"], body["message"]


# Success


def test_a_new_link_is_looked_up_queued_and_accepted() -> None:
    api = links_api()

    response = post_link(api.client, f"https://youtu.be/{ID}?si=SHARER&t=42")

    assert response.status_code == 202
    body = response.json()
    assert response.headers["location"] == f"/jobs/{body['id']}"
    assert (body["status"], body["title"], body["duration_sec"]) == (
        "queued",
        "Elephants Dream - 10 years of open movies",
        37.0,
    )
    assert body["source_url"] == LINK  # canonical: no si=, no t=
    job = api.job(body["id"])
    assert (job.content_hash, job.upload_key, job.client_ip) == (
        DEDUPE_KEY,
        None,
        CLIENT_IP,
    )
    assert fake(api).lookups == [parse(LINK)]
    assert api.queue.enqueued == [body["id"]]


@pytest.mark.parametrize(
    ("title", "stored"),
    [
        ("Song\x00 with\x1b[31m controls​", "Song with[31m controls"),
        ("x" * 250, "x" * 200),
        ("   ", "Untitled"),
        ("", "Untitled"),
    ],
)
def test_the_title_is_the_videos_cleaned(title: str, stored: str) -> None:
    api = links_api(FakeFetcher(info=video_info(title=title)))

    assert post_link(api.client).json()["title"] == stored


# GET /features


@pytest.mark.parametrize("on", [True, False])
def test_features_says_whether_links_are_on(on: bool) -> None:
    api = links_api(url_ingestion=on)

    response = api.client.get("/features")

    assert (response.status_code, response.json()) == (200, {"url_ingestion": on})


# R. The request, before any network


def test_links_switched_off_are_refused_before_anything_is_read() -> None:  # R1
    api = links_api(url_ingestion=False)

    responses = [
        post_link(api.client),
        api.client.post("/jobs/from-url", content=b"not json"),
    ]

    for response in responses:
        assert error_of(response) == (
            403,
            "links_disabled",
            "Links are turned off on this server. Upload the audio file instead.",
        )
    assert fake(api).lookups == []


@pytest.mark.parametrize(
    "send",
    [
        pytest.param(
            {"content": b"not json", "headers": {"content-type": "application/json"}},
            id="not-json",
        ),
        pytest.param(
            {
                "content": b"url=x",
                "headers": {"content-type": "application/x-www-form-urlencoded"},
            },
            id="a-form",
        ),
        pytest.param({"content": b""}, id="empty"),
        pytest.param({"json": {}}, id="no-url"),
        pytest.param({"json": {"link": LINK}}, id="misnamed"),
        pytest.param({"json": {"url": 42}}, id="not-a-string"),
        pytest.param({"json": [LINK]}, id="a-list"),
        pytest.param({"json": {"url": LINK + "&x=" + "a" * 2048}}, id="over-2048"),
    ],
)
def test_a_body_that_is_not_a_link_in_json_is_refused(
    send: dict[str, Any],
) -> None:  # R2
    api = links_api()

    response = api.client.post("/jobs/from-url", **send)

    assert error_of(response) == (
        422,
        "unsupported_link",
        "Send the link as JSON, in a field named `url`.",
    )
    assert fake(api).lookups == []


def test_a_body_over_16_kb_is_refused_before_it_is_read() -> None:  # R3
    api = links_api()

    response = api.client.post(
        "/jobs/from-url",
        content=b'{"url": "' + b"a" * (16 * 1024) + b'"}',
        headers={"content-type": "application/json"},
    )

    assert error_of(response) == (
        413,
        "too_large",
        "That request is too large. Send only the link.",
    )
    assert fake(api).lookups == []


def test_the_upload_limit_still_guards_uploads_only() -> None:
    api = links_api(max_upload_mb=1)

    upload = api.client.post(
        "/jobs", files={"file": ("a.mp3", b"x" * (1024 * 1024 + 1), "audio/mpeg")}
    )

    assert error_of(upload)[:2] == (413, "too_large")
    assert "1 MB" in error_of(upload)[2]


@pytest.mark.parametrize(
    ("url", "row", "message"),
    [
        (
            "   ",
            "R4",
            "That doesn't look like a link. Copy the video's address from your "
            "browser and paste it here.",
        ),
        (
            "javascript:alert(1)",
            "R5",
            "Only web links (https://…) can be used. Copy the video's address "
            "from your browser.",
        ),
        (
            "http://169.254.169.254/latest/meta-data/",
            "R6",
            "We can only fetch songs from YouTube for now. For anything else, "
            "upload the audio file.",
        ),
        (
            "https://www.youtube.com/playlist?list=PL123",
            "R7",
            "That link isn't to a single video. Open the video itself and copy "
            "its address.",
        ),
    ],
)
def test_a_link_we_cannot_use_is_refused_without_a_lookup(
    url: str, row: str, message: str
) -> None:  # R4 to R7
    api = links_api()

    assert error_of(post_link(api.client, url)) == (422, "unsupported_link", message), (
        row
    )
    assert fake(api).lookups == []
    assert api.queue.enqueued == []


def test_a_refused_link_is_logged_by_its_kind_host_and_first_segment_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = links_api()

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        post_link(api.client, "https://www.youtube.com/playlist?list=PL123&si=SHARER")

    assert caplog.messages == [
        "link refused kind=not_a_video host=www.youtube.com path=playlist"
    ]


# Q. Dedupe and limits, before any network


@pytest.mark.parametrize(
    "again",
    [
        f"https://youtu.be/{ID}",
        f"https://www.youtube.com/shorts/{ID}",
        f"https://m.youtube.com/watch?v={ID}&t=30",
        f"youtube.com/watch?v={ID}&list=PL123",
    ],
)
def test_the_same_video_in_any_form_is_the_same_job_without_a_lookup(
    again: str,
) -> None:  # Q1
    api = links_api()
    first = post_link(api.client).json()["id"]

    response = post_link(api.client, again)

    assert (response.status_code, response.json()["id"]) == (200, first)
    assert len(fake(api).lookups) == 1
    assert api.queue.enqueued == [first]


def test_a_link_whose_job_the_queue_lost_starts_a_fresh_one() -> None:  # Q1
    api = links_api()
    first = post_link(api.client).json()["id"]
    api.queue.lose(first)
    api.clock.advance(seconds=61)

    again = post_link(api.client)

    assert again.status_code == 202
    assert again.json()["id"] != first
    assert api.job(first).status is JobStatus.FAILED


def test_an_address_at_its_limit_is_refused_without_a_lookup() -> None:  # Q2
    api = links_api(max_active_jobs_per_ip=1)
    post_link(api.client)

    response = post_link(api.client, "https://youtu.be/YE7VzlLtp-4")

    assert error_of(response) == (
        429,
        "too_many_jobs",
        "You already have 1 song processing. Wait for one to finish, then try again.",
    )
    assert len(fake(api).lookups) == 1


def test_a_fifth_lookup_at_once_is_turned_away_without_waiting() -> None:  # Q3
    api = links_api()
    for _ in range(4):
        assert api.services.lookups.acquire(blocking=False)

    response = post_link(api.client)

    assert error_of(response) == (
        503,
        "fetch_failed",
        "We're checking a lot of links right now. Try again in a minute.",
    )
    assert fake(api).lookups == []


class BlockingFetcher(FakeFetcher):
    """Holds every lookup until released, counting those in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()
        self.four_waiting = threading.Barrier(5)

    def lookup(self, link: Any) -> VideoInfo:
        self.four_waiting.wait(timeout=10)
        self.release.wait(timeout=10)
        return super().lookup(link)


def test_four_lookups_run_at_once_and_a_fifth_is_refused() -> None:  # Q3
    fetcher = BlockingFetcher()
    api = links_api(fetcher, max_active_jobs_per_ip=10)
    ids = ["YE7VzlLtp-4", "M4gD1WSo5mA", "rKb_Uyn56Dw", "ejNMjg5b1lg"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        held = [
            pool.submit(post_link, api.client, f"https://youtu.be/{i}") for i in ids
        ]
        fetcher.four_waiting.wait(timeout=10)  # all four are inside lookup
        fifth = post_link(api.client)
        fetcher.release.set()
        statuses = [future.result().status_code for future in held]

    assert error_of(fifth)[:2] == (503, "fetch_failed")
    assert statuses == [202, 202, 202, 202]


# L. The lookup


LOOKUP_ROWS = [
    ("L1", FetchKind.PRIVATE, 422, "link_unusable"),
    ("L2", FetchKind.UNAVAILABLE, 422, "link_unusable"),
    ("L3", FetchKind.GEO_RESTRICTED, 422, "link_unusable"),
    ("L4", FetchKind.AGE_RESTRICTED, 422, "link_unusable"),
    ("L5", FetchKind.MEMBERS_ONLY, 422, "link_unusable"),
    ("L11", FetchKind.NO_AUDIO, 422, "link_unusable"),
    ("L12", FetchKind.RATE_LIMITED, 503, "fetch_failed"),
    ("L13", FetchKind.NETWORK, 502, "fetch_failed"),
    ("L14", FetchKind.LOOKUP_TIMEOUT, 504, "fetch_failed"),
    ("L15", FetchKind.EXTRACTOR_BROKEN, 502, "fetch_failed"),
    ("L16", FetchKind.MISCONFIGURED, 503, "fetch_failed"),
    ("L17", FetchKind.UNKNOWN, 502, "fetch_failed"),
    ("L18", FetchKind.CRASHED, 500, "internal"),
]


@pytest.mark.parametrize(("row", "kind", "status", "reason"), LOOKUP_ROWS)
def test_a_failed_lookup_answers_with_its_catalog_row(
    row: str, kind: FetchKind, status: int, reason: str
) -> None:
    api = links_api(
        FakeFetcher(lookup_error=FetchError(kind, f"ERROR: [youtube] {SENTINEL}"))
    )

    response = post_link(api.client)

    assert error_of(response) == (status, reason, message_for(kind)), row
    assert api.queue.enqueued == []
    assert api.store.find_live(DEDUPE_KEY) is None


def test_an_internal_lookup_failure_says_what_every_internal_failure_says() -> (
    None
):  # L18
    api = links_api(FakeFetcher(lookup_error=FetchError(FetchKind.CRASHED, "Killed")))

    assert error_of(post_link(api.client))[2] == INTERNAL_FAILURE_MESSAGE


@pytest.mark.parametrize(
    ("row", "info", "reason", "message"),
    [
        (
            "L6",
            video_info(live_status="is_live", duration_sec=None),
            "link_unusable",
            message_for(FetchKind.LIVE),
        ),
        (
            "L7",
            video_info(live_status="is_upcoming"),
            "link_unusable",
            message_for(FetchKind.UPCOMING),
        ),
        (
            "L8",
            video_info(live_status="post_live"),
            "link_unusable",
            message_for(FetchKind.POST_LIVE),
        ),
        (
            "L9",
            video_info(duration_sec=None),
            "link_unusable",
            message_for(FetchKind.NO_DURATION),
        ),
        (
            "L10",
            video_info(duration_sec=10800),
            "too_long",
            "That video is 3:00:00 long. The limit is 10 minutes: try a link to "
            "a single song.",
        ),
    ],
)
def test_metadata_we_cannot_use_is_refused_before_queueing(
    row: str, info: VideoInfo, reason: str, message: str
) -> None:
    api = links_api(FakeFetcher(info=info))

    response = post_link(api.client)

    assert error_of(response) == (422, reason, message), row
    assert api.queue.enqueued == []


def test_ytdlp_text_reaches_the_log_and_never_the_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    detail = f"ERROR: [youtube] {ID}: Private video. {SENTINEL} Traceback"
    api = links_api(FakeFetcher(lookup_error=FetchError(FetchKind.PRIVATE, detail)))

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        response = post_link(api.client)

    assert SENTINEL not in response.text
    assert "yt-dlp" not in response.text and "Traceback" not in response.text
    [line] = [m for m in caplog.messages if m.startswith("link fetch failed")]
    assert line.startswith(
        f"link fetch failed kind=private phase=lookup site=youtube video={ID} job=- "
    )
    assert SENTINEL in line
    assert [r.levelno for r in caplog.records if "fetch failed" in r.message] == [
        CATALOG[FetchKind.PRIVATE].level
    ]


def test_a_successful_lookup_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    api = links_api()

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        post_link(api.client)

    assert any(
        m.startswith(f"link fetched phase=lookup site=youtube video={ID}")
        and "ytdlp=2026.10.26 js=deno/2.5.4" in m
        for m in caplog.messages
    )


def test_a_lookup_slot_is_given_back_whatever_the_outcome() -> None:
    api = links_api(FakeFetcher(lookup_error=FetchError(FetchKind.NETWORK)))
    for _ in range(6):
        post_link(api.client)

    for _ in range(4):
        assert api.services.lookups.acquire(blocking=False)


# E. Queueing


def test_the_same_video_created_at_the_same_moment_returns_the_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # E1
    api = links_api()
    winner, _ = api.store.create(
        NewJob(DEDUPE_KEY, "t", 37.0, None, "198.51.100.1", source_url=LINK)
    )
    # As if the winner committed between this request's dedupe and its insert.
    monkeypatch.setattr(api.store, "find_live", lambda content_hash: None)

    response = post_link(api.client)

    assert (response.status_code, response.json()["id"]) == (200, winner.id)
    assert api.queue.enqueued == []


def test_an_address_that_races_past_the_count_is_refused_when_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # E2
    api = links_api(max_active_jobs_per_ip=1)
    post_link(api.client, "https://youtu.be/YE7VzlLtp-4")
    monkeypatch.setattr(api.store, "count_active", lambda client_ip: 0)

    response = post_link(api.client)

    assert error_of(response)[:2] == (429, "too_many_jobs")
    assert len(api.queue.enqueued) == 1


def test_a_queue_that_refuses_the_job_fails_the_row() -> None:  # E3
    api = links_api()
    api.queue.fail_next = True

    response = post_link(api.client)

    assert error_of(response) == (
        503,
        "internal",
        "We could not queue that song. Try again in a minute.",
    )
    assert api.store.find_live(DEDUPE_KEY) is None
    assert post_link(api.client).status_code == 202


def test_a_store_that_cannot_be_reached_is_our_failure() -> None:  # E4
    class Down(InMemoryJobStore):
        def find_live(self, content_hash: str) -> None:
            raise ConnectionError("postgres went away")

    api = make_api(
        store=Down(),
        fetcher=FakeFetcher(),
        url_ingestion=True,
        raise_server_exceptions=False,
    )

    assert error_of(post_link(api.client)) == (
        500,
        "internal",
        INTERNAL_FAILURE_MESSAGE,
    )


# G. Reading


def test_a_link_jobs_mix_is_not_ready_until_the_worker_stores_it() -> None:  # G1
    api = links_api()
    job_id = post_link(api.client).json()["id"]

    response = api.client.get(f"/jobs/{job_id}/audio/mix", follow_redirects=False)

    assert error_of(response) == (
        409,
        "not_ready",
        "The audio is not ready yet. Poll the job until it succeeds.",
    )


# The switch, for jobs made before it was turned off


def test_links_off_still_serves_the_jobs_links_made() -> None:
    api = links_api()
    job_id = post_link(api.client).json()["id"]
    off = make_api(store=api.store, blobs=api.blobs, fetcher=None, url_ingestion=False)

    assert off.client.get(f"/jobs/{job_id}").json()["source_url"] == LINK


def test_switching_links_off_in_settings_alone_turns_the_route_off() -> None:
    api = links_api()
    services = replace(
        api.services, settings=replace(api.settings, url_ingestion=False)
    )
    api.client.app.state.services = services  # type: ignore[attr-defined]

    assert post_link(api.client).status_code == 403
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest apps/api/tests`
Expected: FAIL: `TypeError: Services.__init__() got an unexpected keyword argument 'fetcher'`, from the updated `make_api`, in every test of the new file.

- [ ] **Step 3: Implement**

In `apps/api/src/guitarvis_api/app.py`:

```diff
--- a/apps/api/src/guitarvis_api/app.py
+++ b/apps/api/src/guitarvis_api/app.py
@@ -18,6 +18,7 @@ from guitarvis_jobs.settings import Settings
 from guitarvis_api import __version__
 from guitarvis_api.errors import install_error_handlers
 from guitarvis_api.routes import router
+from guitarvis_api.routes_links import install as install_links
 from guitarvis_api.services import Services, build_services
 from guitarvis_api.uploads import UploadSizeLimit
 
@@ -40,6 +41,7 @@ def create_app(services: Services | None = None) -> FastAPI:
     install_error_handlers(app)
     app.add_middleware(UploadSizeLimit)
     app.include_router(router)
+    install_links(app)  # spec 012; deleting this line removes links
     return app
 
 
```

In `apps/api/src/guitarvis_api/routes.py`:

```diff
--- a/apps/api/src/guitarvis_api/routes.py
+++ b/apps/api/src/guitarvis_api/routes.py
@@ -29,6 +29,10 @@ def services_of(request: Request) -> Services:
     return cast(Services, request.app.state.services)
 
 
+def client_ip_of(request: Request) -> str:
+    return request.client.host if request.client is not None else "unknown"
+
+
 def _load(services: Services, job_id: str) -> Job:
     job = services.store.get(job_id)
     if job is None:
@@ -53,7 +57,7 @@ def create_job(file: UploadFile, request: Request, response: Response) -> JobVie
     """Validate, dedupe, limit, store and enqueue — cheapest check first."""
     services = services_of(request)
     settings = services.settings
-    client_ip = request.client.host if request.client is not None else "unknown"
+    client_ip = client_ip_of(request)
 
     with tempfile.TemporaryDirectory(prefix="guitarvis-upload-") as tmp:
         upload = receive(
@@ -61,18 +65,14 @@ def create_job(file: UploadFile, request: Request, response: Response) -> JobVie
         )
         duration = _probe(services, upload.path)
 
-        live = _live_job(services, upload.content_hash)
+        live = live_job(services, upload.content_hash)
         if live is not None:  # starts no work, so it is not counted below
             response.status_code = 200
             return JobView.of(live)
 
         # Counted before the blob is stored, so a refused upload costs no
         # storage. Uploads that race past it are refused by `create`.
-        active = services.store.count_active(client_ip)
-        if active >= settings.max_active_jobs_per_ip:
-            active = _active_after_repair(services, client_ip)
-        if active >= settings.max_active_jobs_per_ip:
-            raise _too_many_jobs(active)
+        check_limit(services, client_ip)
 
         key = upload_key(upload.content_hash, file.filename)
         if not services.blobs.exists(key):
@@ -90,11 +90,30 @@ def create_job(file: UploadFile, request: Request, response: Response) -> JobVie
             max_active=settings.max_active_jobs_per_ip,
         )
     except TooManyActiveJobs as error:
-        raise _too_many_jobs(error.active) from error
+        raise too_many_jobs(error.active) from error
     if not created:  # the same file, uploaded at the same moment, got there first
         response.status_code = 200
         return JobView.of(job)
 
+    enqueue(services, job)
+    response.headers["Location"] = f"/jobs/{job.id}"
+    return JobView.of(job)
+
+
+def check_limit(services: Services, client_ip: str) -> None:
+    """Refuse an address at its limit of active jobs, after repairing the
+    rows the queue lost. Requests that race past it are refused by `create`."""
+    limit = services.settings.max_active_jobs_per_ip
+    active = services.store.count_active(client_ip)
+    if active >= limit:
+        active = _active_after_repair(services, client_ip)
+    if active >= limit:
+        raise too_many_jobs(active)
+
+
+def enqueue(services: Services, job: Job) -> None:
+    """Queue a fresh row, or fail it and refuse: a row left queued with no
+    RQ job would wait out reconciliation's grace."""
     try:
         services.queue.enqueue(job.id)
     except Exception as exc:
@@ -112,9 +131,6 @@ def create_job(file: UploadFile, request: Request, response: Response) -> JobVie
             "We could not queue that song. Try again in a minute.",
         ) from exc
 
-    response.headers["Location"] = f"/jobs/{job.id}"
-    return JobView.of(job)
-
 
 def _active_after_repair(services: Services, client_ip: str) -> int:
     """The count again, once the rows it counted have been reconciled.
@@ -129,7 +145,7 @@ def _active_after_repair(services: Services, client_ip: str) -> int:
     return services.store.count_active(client_ip)
 
 
-def _too_many_jobs(active: int) -> ApiError:
+def too_many_jobs(active: int) -> ApiError:
     songs = "song" if active == 1 else "songs"
     return ApiError(
         429,
@@ -151,7 +167,7 @@ def _probe(services: Services, path: Path) -> float:
     return duration
 
 
-def _live_job(services: Services, content_hash: str) -> Job | None:
+def live_job(services: Services, content_hash: str) -> Job | None:
     """The live job for this upload, repaired first if the queue lost it.
 
     A lookup is a read like any other, so it reconciles: a dead job must not
```

Create `apps/api/src/guitarvis_api/routes_links.py`:

```python
"""Links: POST /jobs/from-url and GET /features (spec 012).

Everything links add to the api is here, so removing them for good is
deleting this module and its one line in app.py. The checks run cheapest
first, and nothing touches the network until the lookup: the switch, the
link's form, dedupe by video, the address's limit, then one child process.
"""

import logging
import time
import unicodedata
from collections.abc import Callable, Coroutine
from typing import Any, NoReturn

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from guitarvis_core.contracts import FailureReason
from guitarvis_fetch.catalog import (
    BAD_REQUEST_MESSAGE,
    LINKS_OFF_MESSAGE,
    REFUSALS,
    REQUEST_TOO_LARGE_MESSAGE,
    FetchKind,
)
from guitarvis_fetch.fetcher import (
    FetchError,
    VideoInfo,
    check_info,
    log_failed,
    log_fetched,
)
from guitarvis_fetch.links import Link, LinkRefused, parse
from guitarvis_jobs.models import NewJob
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.store import TooManyActiveJobs

from guitarvis_api.errors import ApiError, HttpReason
from guitarvis_api.routes import (
    check_limit,
    client_ip_of,
    enqueue,
    live_job,
    services_of,
    too_many_jobs,
)
from guitarvis_api.schemas import Features, JobView, LinkRequest
from guitarvis_api.services import Services
from guitarvis_api.uploads import MAX_TITLE_CHARS, UploadSizeLimit

log = logging.getLogger(__name__)

LINK_PATH = "/jobs/from-url"
LINK_BODY_MAX_BYTES = 16 * 1024


class _LinkRoute(APIRoute):
    """POST /jobs/from-url's own front door.

    The switch is checked before the body is read, and a body FastAPI cannot
    validate is answered as a link we cannot use (R2). The app's validation
    handler speaks for uploads, and this keeps links out of it.
    """

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def route(request: Request) -> Response:
            if not services_of(request).settings.url_ingestion:  # R1
                raise ApiError(403, FailureReason.LINKS_DISABLED, LINKS_OFF_MESSAGE)
            try:
                return await handler(request)
            except RequestValidationError as exc:  # R2
                log.info("link refused kind=bad_request")
                raise ApiError(
                    422, HttpReason.UNSUPPORTED_LINK, BAD_REQUEST_MESSAGE
                ) from exc

        return route


links = APIRouter(route_class=_LinkRoute)
router = APIRouter()


@router.get("/features", response_model=Features)
def features(request: Request) -> Features:
    """What this api has switched on. The client shows the link field only
    when this says so."""
    return Features(url_ingestion=services_of(request).settings.url_ingestion)


@links.post(LINK_PATH, status_code=202, response_model=JobView)
def create_job_from_url(
    body: LinkRequest, request: Request, response: Response
) -> JobView:
    services = services_of(request)
    client_ip = client_ip_of(request)
    link = _parse(body.url)

    live = live_job(services, link.dedupe_key)  # Q1: in any form, no lookup
    if live is not None:
        response.status_code = 200
        return JobView.of(live)

    check_limit(services, client_ip)  # Q2: before any outbound request
    info, duration = _lookup(services, link)
    try:
        job, created = services.store.create(
            NewJob(
                content_hash=link.dedupe_key,
                title=_title(info.title),
                duration_sec=duration,
                upload_key=None,
                client_ip=client_ip,
                source_url=link.canonical_url,
            ),
            max_active=services.settings.max_active_jobs_per_ip,
        )
    except TooManyActiveJobs as error:  # E2
        raise too_many_jobs(error.active) from error
    if not created:  # E1: the same video, submitted at the same moment
        response.status_code = 200
        return JobView.of(job)

    enqueue(services, job)  # E3
    response.headers["Location"] = f"/jobs/{job.id}"
    return JobView.of(job)


def _parse(raw: str) -> Link:
    try:
        return parse(raw)
    except LinkRefused as refused:  # R4 to R7
        # Its kind, host and first path segment: never the whole string,
        # which can carry the sharer's si= id.
        log.info(
            "link refused kind=%s host=%s path=%s",
            refused.kind,
            refused.host or "-",
            refused.segment or "-",
        )
        raise ApiError(
            422, HttpReason.UNSUPPORTED_LINK, REFUSALS[refused.kind]
        ) from None


def _lookup(services: Services, link: Link) -> tuple[VideoInfo, float]:
    """Ask the site, in a child process with its deadline; then step 6.
    The video's metadata, and its length."""
    started = time.monotonic()
    if not services.lookups.acquire(blocking=False):  # Q3
        _refuse(FetchError(FetchKind.BUSY, "lookups at their limit"), link, started)
    try:
        if services.fetcher is None:  # the switch is on, but nothing can fetch
            raise FetchError(FetchKind.MISCONFIGURED, "links are on with no fetcher")
        info = services.fetcher.lookup(link)
        duration = check_info(info)
    except FetchError as error:
        _refuse(error, link, started)
    finally:
        services.lookups.release()
    log_fetched(
        log,
        phase="lookup",
        link=link,
        versions=info.versions,
        elapsed_sec=time.monotonic() - started,
    )
    return info, duration


def _refuse(error: FetchError, link: Link, started: float) -> NoReturn:
    log_failed(
        log, error, phase="lookup", link=link, elapsed_sec=time.monotonic() - started
    )
    entry = error.entry
    raise ApiError(entry.status, entry.reason, error.message) from None


def _title(raw: str) -> str:
    """The video's title as a job's: no control characters, at most 200
    characters, and "Untitled" when nothing is left."""
    kept = "".join(c for c in raw if not unicodedata.category(c).startswith("C"))
    return kept.strip()[:MAX_TITLE_CHARS].strip() or "Untitled"


def _link_body_limit(settings: Settings) -> int:
    return LINK_BODY_MAX_BYTES


def _link_body_too_large(settings: Settings) -> ApiError:  # R3
    return ApiError(413, HttpReason.TOO_LARGE, REQUEST_TOO_LARGE_MESSAGE)


def install(app: FastAPI) -> None:
    """Everything links add to the api: the routes, and a body limit for
    the link's own route."""
    app.add_middleware(
        UploadSizeLimit,
        path=LINK_PATH,
        limit=_link_body_limit,
        refuse=_link_body_too_large,
    )
    app.include_router(router)


router.include_router(links)
```

In `apps/api/src/guitarvis_api/services.py`:

```diff
--- a/apps/api/src/guitarvis_api/services.py
+++ b/apps/api/src/guitarvis_api/services.py
@@ -1,16 +1,22 @@
 """What a request handler needs, bundled so tests can hand in the twins."""
 
+import threading
 from collections.abc import Callable
-from dataclasses import dataclass
+from dataclasses import dataclass, field
 from pathlib import Path
 
 from guitarvis_core.audio import probe_duration
+from guitarvis_fetch.fetcher import ChildFetcher, UrlFetcher
 from guitarvis_jobs.blobs import BlobStore, S3BlobStore
 from guitarvis_jobs.postgres import PostgresJobStore
 from guitarvis_jobs.queue import JobQueue, RQJobQueue
 from guitarvis_jobs.settings import Settings
 from guitarvis_jobs.store import Clock, JobStore, utc_now
 
+# Spec 012: a lookup holds a thread until its child answers, so a process
+# runs at most this many at once and turns the next away at once.
+MAX_CONCURRENT_LOOKUPS = 4
+
 
 @dataclass(frozen=True)
 class Services:
@@ -20,6 +26,11 @@ class Services:
     settings: Settings
     probe: Callable[[Path], float] = probe_duration
     clock: Clock = utc_now
+    # None when links are off: then nothing in the api can fetch.
+    fetcher: UrlFetcher | None = None
+    lookups: threading.Semaphore = field(
+        default_factory=lambda: threading.BoundedSemaphore(MAX_CONCURRENT_LOOKUPS)
+    )
 
 
 def build_services(settings: Settings) -> Services:
@@ -29,4 +40,5 @@ def build_services(settings: Settings) -> Services:
         blobs=S3BlobStore.from_settings(settings),
         queue=RQJobQueue.from_settings(settings),
         settings=settings,
+        fetcher=ChildFetcher() if settings.url_ingestion else None,
     )
```

In `apps/api/src/guitarvis_api/uploads.py`:

```diff
--- a/apps/api/src/guitarvis_api/uploads.py
+++ b/apps/api/src/guitarvis_api/uploads.py
@@ -8,12 +8,14 @@ arrives; `receive` then counts the file's own bytes exactly while hashing.
 
 import hashlib
 import re
+from collections.abc import Callable
 from dataclasses import dataclass
 from pathlib import Path, PurePosixPath
 from typing import BinaryIO
 
 from fastapi.responses import JSONResponse
 from guitarvis_core.contracts import FailureReason
+from guitarvis_jobs.settings import Settings
 from starlette.types import ASGIApp, Message, Receive, Scope, Send
 
 from guitarvis_api.errors import ApiError, HttpReason, error_body
@@ -34,32 +36,53 @@ def too_large(max_bytes: int) -> ApiError:
     )
 
 
+def _upload_limit(settings: Settings) -> int:
+    return settings.max_upload_bytes + MULTIPART_ALLOWANCE
+
+
+def _upload_too_large(settings: Settings) -> ApiError:
+    return too_large(settings.max_upload_bytes)
+
+
 class UploadSizeLimit:
-    """ASGI middleware: refuse an oversized POST /jobs before it lands.
+    """ASGI middleware: refuse an oversized POST body before it lands.
 
     A declared Content-Length over the limit is refused before a byte is
     read. A body that declares none (chunked) is counted as it streams and
     abandoned the moment it passes the limit: the ApiError raised here comes
     out of FastAPI's body parsing untouched, as the 413 itself.
+
+    One instance guards one path: POST /jobs by default, at the upload limit.
+    The link route adds another for its own body (spec 012).
     """
 
-    def __init__(self, app: ASGIApp) -> None:
+    def __init__(
+        self,
+        app: ASGIApp,
+        *,
+        path: str = "/jobs",
+        limit: Callable[[Settings], int] = _upload_limit,
+        refuse: Callable[[Settings], ApiError] = _upload_too_large,
+    ) -> None:
         self.app = app
+        self.path = path
+        self.limit = limit
+        self.refuse = refuse
 
     async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
         if (
             scope["type"] != "http"
             or scope["method"] != "POST"
-            or scope["path"] != "/jobs"
+            or scope["path"] != self.path
         ):
             await self.app(scope, receive, send)
             return
 
-        max_bytes: int = scope["app"].state.services.settings.max_upload_bytes
-        limit = max_bytes + MULTIPART_ALLOWANCE
+        settings: Settings = scope["app"].state.services.settings
+        limit = self.limit(settings)
         declared = _content_length(scope)
         if declared is not None and declared > limit:
-            error = too_large(max_bytes)
+            error = self.refuse(settings)
             response = JSONResponse(
                 error_body(error.reason, error.message), status_code=413
             )
@@ -74,7 +97,7 @@ class UploadSizeLimit:
             if message["type"] == "http.request":
                 received += len(message.get("body", b""))
                 if received > limit:
-                    raise too_large(max_bytes)
+                    raise self.refuse(settings)
             return message
 
         await self.app(scope, counted, send)
```

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run pytest apps/api/tests`
Expected: PASS, every upload test included, unchanged.

- [ ] **Step 5: Commit**

```bash
make lint typecheck test
git add apps/api/src/guitarvis_api/app.py \
  apps/api/src/guitarvis_api/routes.py \
  apps/api/src/guitarvis_api/routes_links.py \
  apps/api/src/guitarvis_api/services.py \
  apps/api/src/guitarvis_api/uploads.py \
  apps/api/tests/api_fixture.py \
  apps/api/tests/test_links_route.py
git commit -m "feat(api): POST /jobs/from-url and GET /features

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 11: The worker fetches a link job's audio

`UrlSource` implements `AudioSource`: it downloads through a `UrlFetcher`, turns a `FetchError` into the catalog's `PipelineError` (reason, message, retry rule), logs one line either way, and probes the file as `UploadSource` does, mapping an unreadable file to `link_unusable` (P1). The runner's `_run` gains one branch: a link job with no stored audio is fetched (or fails `links_disabled` when `WorkerDeps.fetcher` is `None`), hashed, stored at `uploads/{hash}{ext}` unless already there, and recorded with `attach_upload`; if the row is no longer running it is dropped (S3). Caching keys by the bytes' hash, never the video. A link job's progress runs through `download` (0 to 5) and then the pipeline scaled onto 5 to 100; upload jobs' percentages do not change. The worker warns at start when links are on and Deno is missing.

**Catalog rows:** W1, W2, D1 to D10, P1 to P3, S1 to S3.

**Files:**
- Modify: `apps/worker/pyproject.toml`
- Modify: `apps/worker/src/guitarvis_worker/ingest.py`
- Modify: `apps/worker/src/guitarvis_worker/runner.py`
- Test: `apps/worker/tests/test_ingest.py`
- Test (new): `apps/worker/tests/test_link_jobs.py`
- Generated, by `uv lock`: `uv.lock`

**Interfaces:**
- Produces: `guitarvis_worker.ingest.UrlSource(link, work_dir, fetcher, *, max_bytes, progress=None, probe=probe_duration, max_duration_sec, job_id=None, attempt=None)`; `WorkerDeps.fetcher`, `WorkerDeps.max_download_bytes`, `WorkerDeps.probe`; `runner.DOWNLOAD_PERCENT = 5`.

- [ ] **Step 1: Write the failing tests**

In `apps/worker/tests/test_ingest.py`:

```diff
--- a/apps/worker/tests/test_ingest.py
+++ b/apps/worker/tests/test_ingest.py
@@ -6,7 +6,9 @@ from pathlib import Path
 
 import pytest
 from guitarvis_core.contracts import AudioSource, FailureReason, PipelineError
-from guitarvis_worker.ingest import UploadSource
+from guitarvis_fetch.links import parse
+from guitarvis_fetch.testing import FakeFetcher
+from guitarvis_worker.ingest import UploadSource, UrlSource
 
 requires_ffprobe = pytest.mark.skipif(
     shutil.which("ffprobe") is None,
@@ -28,6 +30,25 @@ def test_upload_source_satisfies_the_protocol(tmp_path: Path) -> None:
     assert isinstance(UploadSource(write_wav(tmp_path / "a.wav")), AudioSource)
 
 
+def test_url_source_satisfies_the_protocol(tmp_path: Path) -> None:
+    link = parse("https://youtu.be/kPdv44HtEoA")
+
+    assert isinstance(
+        UrlSource(link, tmp_path, FakeFetcher(), max_bytes=1), AudioSource
+    )
+
+
+@requires_ffprobe
+def test_url_source_probes_the_download_with_ffprobe(tmp_path: Path) -> None:
+    link = parse("https://youtu.be/kPdv44HtEoA")
+
+    ingested = UrlSource(link, tmp_path, FakeFetcher(), max_bytes=10**6).fetch()
+
+    assert ingested.path == tmp_path / "source.wav"
+    assert ingested.title == "Elephants Dream - 10 years of open movies"
+    assert ingested.duration_sec == pytest.approx(1.0, abs=0.05)
+
+
 @requires_ffprobe
 def test_fetch_returns_path_title_and_duration(tmp_path: Path) -> None:
     ingested = UploadSource(write_wav(tmp_path / "my song.wav", seconds=1.5)).fetch()
```

Create `apps/worker/tests/test_link_jobs.py`:

```python
"""Link jobs in the worker (spec 012): every W, D, P and S row of the failure
catalog, retried or not as it says, with a fake fetcher and in-memory stores.
The download is a stage of its own and fills the first 5% of progress."""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from guitarvis_core.contracts import (
    FailureReason,
    IngestedAudio,
    NoteEvent,
    PipelineError,
    SeparationProgress,
    SeparationResult,
    StructureResult,
)
from guitarvis_core.tabdoc import TabDocument, Timing
from guitarvis_fetch.catalog import FetchKind, message_for
from guitarvis_fetch.fetcher import ChildFetcher, FetchError
from guitarvis_fetch.links import parse
from guitarvis_fetch.testing import FakeFetcher, write_wav
from guitarvis_jobs.blobs import InMemoryBlobStore
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, Job, JobStatus
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.store import InMemoryJobStore
from guitarvis_jobs.testing import sample_link_job, sample_new_job
from guitarvis_worker import runner
from guitarvis_worker.caching import CacheKeys
from guitarvis_worker.runner import Stages, WorkerDeps, open_deps, process_job
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper

LINK = parse("https://www.youtube.com/watch?v=kPdv44HtEoA")
SENTINEL = "SENTINEL-4f2a"
PROBED = 37.059


class StubSeparator:
    def __init__(self) -> None:
        self.calls = 0

    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        self.calls += 1
        if progress is not None:
            progress(0.5)
        return SeparationResult(stem_path=audio_path)


class StubTranscriber:
    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        return [NoteEvent(onset=1.0, duration=0.5, midi=52, confidence=0.8)]


class StubAnalyzer:
    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        return StructureResult(timing=Timing(), chords=[], sections=[])


@dataclass
class Harness:
    store: InMemoryJobStore = field(default_factory=InMemoryJobStore)
    blobs: InMemoryBlobStore = field(default_factory=InMemoryBlobStore)
    fetcher: FakeFetcher = field(default_factory=FakeFetcher)
    separator: StubSeparator = field(default_factory=StubSeparator)
    probe: Callable[[Path], float] = lambda path: PROBED
    links_on: bool = True
    job_id: str = ""

    def __post_init__(self) -> None:
        job, _ = self.store.create(sample_link_job())
        self.job_id = job.id

    def deps(self) -> WorkerDeps:
        return WorkerDeps(
            store=self.store,
            blobs=self.blobs,
            stages=lambda work_dir: Stages(
                separator=self.separator,
                transcriber=StubTranscriber(),
                analyzer=StubAnalyzer(),
                mapper=ViterbiFretboardMapper(),
            ),
            fetcher=self.fetcher if self.links_on else None,
            max_download_bytes=1024 * 1024,
            probe=self.probe,
        )

    def run(self, retries_left: int = 2) -> None:
        process_job(self.job_id, self.deps(), retries_left=retries_left)

    def row(self) -> Job:
        row = self.store.get(self.job_id)
        assert row is not None
        return row


@pytest.fixture
def harness() -> Harness:
    return Harness()


def wav_bytes(tmp_path: Path) -> bytes:
    return write_wav(tmp_path / "w.wav").read_bytes()


# Success


def test_a_link_job_downloads_stores_and_runs(harness: Harness, tmp_path: Path) -> None:
    harness.fetcher.content = wav_bytes(tmp_path)
    content_hash = hashlib.sha256(harness.fetcher.content).hexdigest()

    harness.run()

    row = harness.row()
    assert (row.status, row.percent, row.attempts) == (JobStatus.SUCCEEDED, 100, 1)
    assert row.upload_key == f"uploads/{content_hash}.wav"  # content-addressed
    assert harness.blobs.get_bytes(row.upload_key) == harness.fetcher.content
    assert row.duration_sec == PROBED  # ffprobe's, not the metadata's 37.0
    assert row.content_hash == LINK.dedupe_key  # still the video's identity
    assert row.stem_key == CacheKeys(content_hash).stem  # cached by the bytes
    document = TabDocument.model_validate(row.document)
    assert document.source.title == row.title
    assert document.source.duration_sec == PROBED
    assert document.source.audio_url == f"/jobs/{row.id}/audio/mix"
    assert harness.fetcher.downloads == [LINK]


def test_a_link_jobs_progress_runs_from_download_into_five_to_a_hundred(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, int]] = []
    write = harness.store.set_progress

    def recording(job_id: str, stage: str, percent: int) -> bool:
        seen.append((stage, percent))
        return write(job_id, stage, percent)

    monkeypatch.setattr(harness.store, "set_progress", recording)
    harness.run()

    assert seen == [
        ("download", 0),
        ("download", 2),
        ("download", 5),
        ("separation", 5),
        ("separation", 24),
        ("transcription", 43),
        ("structure", 66),
        ("fretboard", 81),
    ]


def test_a_link_and_an_upload_of_the_same_bytes_share_the_cache(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = wav_bytes(tmp_path)
    harness.fetcher.content = content
    harness.run()
    upload, _ = harness.store.create(
        sample_new_job(
            content_hash=hashlib.sha256(content).hexdigest(), upload_key="u.wav"
        )
    )
    harness.blobs.put_bytes("u.wav", content)
    monkeypatch.setattr(runner, "UploadSource", _NoProbeSource)

    process_job(upload.id, harness.deps(), retries_left=2)

    assert harness.separator.calls == 1  # the upload found the link's stem


class _NoProbeSource:
    def __init__(self, path: Path, **kwargs: object) -> None:
        self.path = path

    def fetch(self) -> IngestedAudio:
        return IngestedAudio(path=self.path, title="t", duration_sec=1.0)


# W. Before fetching


def test_links_off_fails_a_link_job_with_no_stored_audio(
    harness: Harness,
) -> None:  # W1
    harness.links_on = False

    harness.run()  # not retried: returns

    row = harness.row()
    assert row.failure_reason is FailureReason.LINKS_DISABLED
    assert row.failure_message == (
        "Links were turned off before this song could be fetched. "
        "Upload the audio file instead."
    )
    assert harness.fetcher.downloads == []


def test_links_off_still_runs_a_link_job_whose_download_is_stored(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:  # W1
    harness.store.mark_running(harness.job_id)
    harness.store.attach_upload(
        harness.job_id, upload_key="uploads/abc.wav", duration_sec=1.0
    )
    harness.store.requeue(harness.job_id)
    harness.blobs.put_bytes("uploads/abc.wav", b"stored")
    monkeypatch.setattr(runner, "UploadSource", _NoProbeSource)
    harness.links_on = False

    harness.run()

    assert harness.row().status is JobStatus.SUCCEEDED
    assert harness.row().stem_key == CacheKeys("abc").stem


def test_a_retry_finds_the_download_stored_and_never_fetches(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    write = harness.store.set_progress
    crashed: list[bool] = []

    def crash_once_at_separation(job_id: str, stage: str, percent: int) -> bool:
        if stage == "separation" and not crashed:
            crashed.append(True)
            raise ConnectionError("postgres went away")
        return write(job_id, stage, percent)

    monkeypatch.setattr(harness.store, "set_progress", crash_once_at_separation)
    with pytest.raises(ConnectionError):
        harness.run(retries_left=1)
    monkeypatch.setattr(runner, "UploadSource", _NoProbeSource)

    harness.run(retries_left=0)

    assert harness.row().status is JobStatus.SUCCEEDED
    assert len(harness.fetcher.downloads) == 1


@pytest.mark.parametrize(
    "kind",
    [
        FetchKind.PRIVATE,  # L1
        FetchKind.UNAVAILABLE,  # L2
        FetchKind.GEO_RESTRICTED,  # L3
        FetchKind.AGE_RESTRICTED,  # L4
        FetchKind.MEMBERS_ONLY,  # L5
        FetchKind.LIVE,  # L6
        FetchKind.UPCOMING,  # L7
        FetchKind.POST_LIVE,  # L8
        FetchKind.NO_DURATION,  # L9
        FetchKind.TOO_LONG,  # L10
        FetchKind.NO_AUDIO,  # L11
    ],
)
def test_a_video_that_changed_in_the_queue_fails_with_its_own_reason(
    harness: Harness, kind: FetchKind
) -> None:  # W2
    harness.fetcher.download_error = FetchError(kind, duration_sec=721)

    harness.run(retries_left=2)  # no retry: returns

    row = harness.row()
    assert row.failure_reason is FetchError(kind).entry.reason
    assert row.failure_message == message_for(kind, duration_sec=721)
    assert row.failed_stage == "download"
    assert harness.separator.calls == 0


# D. The download


RETRIED = [
    (
        "D1",
        FetchKind.NETWORK,
        FailureReason.FETCH_FAILED,
        message_for(FetchKind.NETWORK),
    ),
    (
        "D2",
        FetchKind.DOWNLOAD_TIMEOUT,
        FailureReason.FETCH_FAILED,
        message_for(FetchKind.DOWNLOAD_TIMEOUT),
    ),
    ("D8", FetchKind.LOCAL_IO, FailureReason.INTERNAL, INTERNAL_FAILURE_MESSAGE),
    ("D9", FetchKind.CRASHED, FailureReason.INTERNAL, INTERNAL_FAILURE_MESSAGE),
    (
        "D10",
        FetchKind.UNKNOWN,
        FailureReason.FETCH_FAILED,
        message_for(FetchKind.UNKNOWN),
    ),
]


@pytest.mark.parametrize(("row", "kind", "reason", "message"), RETRIED)
def test_a_download_that_may_pass_is_retried(
    harness: Harness, row: str, kind: FetchKind, reason: FailureReason, message: str
) -> None:
    harness.fetcher.download_error = FetchError(kind, SENTINEL)

    with pytest.raises(PipelineError):
        harness.run(retries_left=1)

    assert harness.row().status is JobStatus.QUEUED, row


@pytest.mark.parametrize(("row", "kind", "reason", "message"), RETRIED)
def test_the_last_attempt_keeps_the_downloads_own_reason(
    harness: Harness, row: str, kind: FetchKind, reason: FailureReason, message: str
) -> None:
    harness.fetcher.download_error = FetchError(kind, SENTINEL)

    with pytest.raises(PipelineError):
        harness.run(retries_left=0)

    failed = harness.row()
    assert (failed.status, failed.failure_reason, failed.failure_message) == (
        JobStatus.FAILED,
        reason,
        message,
    ), row
    assert failed.failed_stage == "download"


@pytest.mark.parametrize(
    ("row", "kind", "reason"),
    [
        ("D3", FetchKind.RATE_LIMITED, FailureReason.FETCH_FAILED),
        ("D4", FetchKind.EXTRACTOR_BROKEN, FailureReason.FETCH_FAILED),
        ("D4", FetchKind.MISCONFIGURED, FailureReason.FETCH_FAILED),
        ("D5", FetchKind.MEDIA_REFUSED, FailureReason.FETCH_FAILED),
        ("D6", FetchKind.TOO_LARGE, FailureReason.LINK_UNUSABLE),
        ("D7", FetchKind.EMPTY_DOWNLOAD, FailureReason.LINK_UNUSABLE),
    ],
)
def test_a_download_that_will_not_pass_soon_is_not_retried(
    harness: Harness, row: str, kind: FetchKind, reason: FailureReason
) -> None:
    harness.fetcher.download_error = FetchError(kind, SENTINEL)

    harness.run(retries_left=2)  # returns: RQ does not retry

    failed = harness.row()
    assert (failed.failure_reason, failed.failure_message) == (
        reason,
        message_for(kind),
    ), row


def test_ytdlp_text_reaches_the_log_and_never_the_row(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    harness.fetcher.download_error = FetchError(
        FetchKind.UNKNOWN, f"ERROR: [youtube] {SENTINEL} Traceback", tail="STDERR"
    )

    with (
        caplog.at_level(logging.INFO, logger="guitarvis_worker"),
        pytest.raises(PipelineError),
    ):
        harness.run(retries_left=0)

    row = harness.row()
    assert SENTINEL not in (row.failure_message or "")
    [line] = [m for m in caplog.messages if m.startswith("link fetch failed")]
    assert (
        f"phase=download site=youtube video={LINK.video_id} job={row.id} attempt=1"
        in line
    )
    assert SENTINEL in line and line.endswith("\nSTDERR")


def test_a_successful_download_is_logged_with_its_format(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="guitarvis_worker"):
        harness.run()

    assert any(
        m.startswith("link fetched phase=download") and "format=140 ext=wav bytes=" in m
        for m in caplog.messages
    )


# P. After the download


def test_audio_ffprobe_cannot_read_is_unusable(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:  # P1
    def unreadable(path: Path) -> float:
        raise PipelineError(
            FailureReason.UNSUPPORTED_FORMAT, "That file could not be read"
        )

    harness.probe = unreadable

    with caplog.at_level(logging.WARNING, logger="guitarvis_worker"):
        harness.run(retries_left=2)

    row = harness.row()
    assert row.failure_reason is FailureReason.LINK_UNUSABLE
    assert row.failure_message == (
        "The audio we fetched from that video couldn't be read. Try a different "
        "link, or upload the audio file."
    )
    assert any("link audio unreadable" in m and "ext=wav" in m for m in caplog.messages)


@pytest.mark.parametrize("probed", [0.0, float("nan")])
def test_audio_with_no_length_is_unusable(
    harness: Harness, probed: float
) -> None:  # P1
    harness.probe = lambda path: probed

    harness.run(retries_left=2)

    assert harness.row().failure_reason is FailureReason.LINK_UNUSABLE


def test_audio_over_ten_minutes_by_ffprobe_is_too_long(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:  # P2
    harness.probe = lambda path: 721.0

    with caplog.at_level(logging.INFO, logger="guitarvis_worker"):
        harness.run(retries_left=2)

    row = harness.row()
    assert row.failure_reason is FailureReason.TOO_LONG
    assert row.failure_message == (
        "That recording is longer than 10 minutes. Try a single song rather than a "
        "full set."
    )
    assert any("metadata=37.0 probed=721.0" in m for m in caplog.messages)


def test_a_missing_ffprobe_after_a_download_is_retried_then_internal(
    harness: Harness,
) -> None:  # P3
    def missing(path: Path) -> float:
        raise PipelineError(FailureReason.INTERNAL, "ffprobe is not installed.")

    harness.probe = missing

    with pytest.raises(PipelineError):
        harness.run(retries_left=0)

    assert harness.row().failure_message == INTERNAL_FAILURE_MESSAGE


# S. Storing the download


def test_a_failed_store_of_the_download_is_retried_and_downloads_again(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:  # S1
    put = harness.blobs.put_file
    broken: list[bool] = []

    def put_once_broken(key: str, path: Path) -> None:
        if not broken:
            broken.append(True)
            raise ConnectionError("storage went away")
        put(key, path)

    monkeypatch.setattr(harness.blobs, "put_file", put_once_broken)
    with pytest.raises(ConnectionError):
        harness.run(retries_left=1)
    assert harness.row().status is JobStatus.QUEUED

    harness.run(retries_left=0)

    assert harness.row().status is JobStatus.SUCCEEDED
    assert len(harness.fetcher.downloads) == 2


def test_a_failed_attach_is_retried_then_internal(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:  # S2
    def broken(job_id: str, *, upload_key: str, duration_sec: float) -> bool:
        raise ConnectionError("postgres went away")

    monkeypatch.setattr(harness.store, "attach_upload", broken)

    with pytest.raises(ConnectionError):
        harness.run(retries_left=1)
    assert harness.row().status is JobStatus.QUEUED
    with pytest.raises(ConnectionError):
        harness.run(retries_left=0)
    assert harness.row().failure_reason is FailureReason.INTERNAL


def test_a_download_for_a_row_failed_meanwhile_is_dropped(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:  # S3
    attach = harness.store.attach_upload

    def reconciled_first(job_id: str, *, upload_key: str, duration_sec: float) -> bool:
        harness.store.fail(
            job_id,
            reason=FailureReason.INTERNAL,
            message="lost",
            stage="download",
            expect=JobStatus.RUNNING,
        )
        return attach(job_id, upload_key=upload_key, duration_sec=duration_sec)

    monkeypatch.setattr(harness.store, "attach_upload", reconciled_first)

    with caplog.at_level(logging.WARNING, logger="guitarvis_worker"):
        harness.run()  # no exception

    row = harness.row()
    assert (row.status, row.failure_message, row.upload_key) == (
        JobStatus.FAILED,
        "lost",
        None,
    )
    assert harness.separator.calls == 0
    assert any("dropping" in m for m in caplog.messages)


# Wiring


def test_open_deps_gives_a_fetcher_only_when_links_are_on() -> None:
    with open_deps(Settings(url_ingestion=True, max_upload_mb=7)) as on:
        assert isinstance(on.fetcher, ChildFetcher)
        assert on.max_download_bytes == 7 * 1024 * 1024
    with open_deps(Settings()) as off:
        assert off.fetcher is None


class FakeWorker:
    def __init__(self, queues: object, connection: object) -> None:
        pass

    def work(self, **kwargs: object) -> bool:
        return False


@pytest.mark.parametrize(("links_on", "warned"), [(True, True), (False, False)])
def test_serve_warns_when_links_are_on_and_no_runtime_is_found(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    links_on: bool,
    warned: bool,
) -> None:
    monkeypatch.setattr(runner, "find_deno", lambda: None)
    monkeypatch.setattr(runner, "JobWorker", FakeWorker)

    with caplog.at_level(logging.WARNING, logger="guitarvis_worker"):
        runner.serve(Settings(url_ingestion=links_on), burst=True)

    assert (
        any("Deno 2.3 or later was not found" in m for m in caplog.messages) is warned
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest apps/worker/tests/test_link_jobs.py apps/worker/tests/test_ingest.py`
Expected: FAIL at collection: `ImportError: cannot import name 'UrlSource' from 'guitarvis_worker.ingest'`.

- [ ] **Step 3: Implement**

Then `uv lock && uv sync` (the worker's new dependency).

In `apps/worker/pyproject.toml`:

```diff
--- a/apps/worker/pyproject.toml
+++ b/apps/worker/pyproject.toml
@@ -3,7 +3,13 @@ name = "guitarvis-worker"
 version = "0.1.0"
 description = "The pipeline. The only component that needs torch or weights."
 requires-python = ">=3.12"
-dependencies = ["guitarvis-core", "guitarvis-jobs", "redis>=5.0", "rq>=2.0"]
+dependencies = [
+    "guitarvis-core",
+    "guitarvis-jobs",
+    "guitarvis-fetch",
+    "redis>=5.0",
+    "rq>=2.0",
+]
 
 # Heavy ML dependencies are opt-in so that `uv sync` and CI stay light.
 # Install with `uv sync --extra ml`.
```

Replace `apps/worker/src/guitarvis_worker/ingest.py` with:

```python
"""Getting audio into the pipeline.

UploadSource and UrlSource implement AudioSource, and nothing downstream
knows which ran. Guards run here, at the front door, because rejecting a
three-hour DJ set after separation has already run is the expensive way to
find out. The probe itself lives in guitarvis_core.audio, because the api runs
the same check before queueing.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_core.audio import MAX_DURATION_SEC, check_duration, probe_duration
from guitarvis_core.contracts import (
    AudioSource,
    FailureReason,
    IngestedAudio,
    PipelineError,
)
from guitarvis_fetch.catalog import FetchKind, message_for
from guitarvis_fetch.fetcher import (
    Download,
    FetchError,
    Progress,
    UrlFetcher,
    log_failed,
    log_fetched,
)
from guitarvis_fetch.links import Link

log = logging.getLogger(__name__)


class UploadSource:
    """Implements guitarvis_core.contracts.AudioSource for a local file."""

    def __init__(
        self, path: Path | str, *, max_duration_sec: float = MAX_DURATION_SEC
    ) -> None:
        self.path = Path(path)
        self.max_duration_sec = max_duration_sec

    def fetch(self) -> IngestedAudio:
        if not self.path.is_file():
            raise PipelineError(
                FailureReason.UNSUPPORTED_FORMAT, f"No such audio file: {self.path}"
            )

        duration = probe_duration(self.path)
        check_duration(duration, self.max_duration_sec)
        return IngestedAudio(
            path=self.path, title=self.path.stem, duration_sec=duration
        )


class UrlSource:
    """Implements AudioSource for a link (spec 012).

    Downloads into the job's directory through a UrlFetcher, then probes the
    file as UploadSource does: ffprobe's length is the one that counts,
    since metadata is rounded and can be wrong.
    """

    def __init__(
        self,
        link: Link,
        work_dir: Path,
        fetcher: UrlFetcher,
        *,
        max_bytes: int,
        progress: Progress | None = None,
        probe: Callable[[Path], float] = probe_duration,
        max_duration_sec: float = MAX_DURATION_SEC,
        job_id: str | None = None,
        attempt: int | None = None,
    ) -> None:
        self.link = link
        self.work_dir = work_dir
        self.fetcher = fetcher
        self.max_bytes = max_bytes
        self.progress = progress
        self.probe = probe
        self.max_duration_sec = max_duration_sec
        self.job_id = job_id
        self.attempt = attempt

    def fetch(self) -> IngestedAudio:
        download = self._download()
        try:
            duration = self.probe(download.path)
            check_duration(duration, self.max_duration_sec)
        except PipelineError as error:
            if error.reason is FailureReason.UNSUPPORTED_FORMAT:  # P1
                log.warning(
                    "link audio unreadable job=%s video=%s format=%s ext=%s ffprobe=%r",
                    self.job_id,
                    self.link.video_id,
                    download.format_id,
                    download.ext,
                    _ffprobe_tail(error),
                )
                raise PipelineError(
                    FailureReason.LINK_UNUSABLE, message_for(FetchKind.UNREADABLE)
                ) from error
            if error.reason is FailureReason.TOO_LONG:  # P2
                log.info(
                    "link audio too long job=%s video=%s metadata=%s probed=%s",
                    self.job_id,
                    self.link.video_id,
                    download.info.duration_sec,
                    duration,
                )
            raise  # P2 too_long, or P3: ffprobe missing is ours
        return IngestedAudio(
            path=download.path, title=download.info.title, duration_sec=duration
        )

    def _download(self) -> Download:
        started = time.monotonic()
        try:
            download = self.fetcher.download(
                self.link,
                self.work_dir,
                max_bytes=self.max_bytes,
                progress=self.progress,
            )
        except FetchError as error:
            log_failed(
                log,
                error,
                phase="download",
                link=self.link,
                elapsed_sec=time.monotonic() - started,
                job_id=self.job_id,
                attempt=self.attempt,
            )
            raise error.as_pipeline_error() from error
        log_fetched(
            log,
            phase="download",
            link=self.link,
            versions=download.info.versions,
            elapsed_sec=time.monotonic() - started,
            job_id=self.job_id,
            attempt=self.attempt,
            download=download,
        )
        return download


def _ffprobe_tail(error: PipelineError) -> str:
    stderr = getattr(error.__cause__, "stderr", None)
    return stderr[-500:] if isinstance(stderr, str) else ""


if TYPE_CHECKING:  # Static conformance: the typed assignments are what mypy checks.
    from typing import cast

    _upload: AudioSource = UploadSource(Path())
    _url: AudioSource = UrlSource(
        Link("youtube", "", ""), Path(), cast(UrlFetcher, None), max_bytes=0
    )
```

In `apps/worker/src/guitarvis_worker/runner.py`:

```diff
--- a/apps/worker/src/guitarvis_worker/runner.py
+++ b/apps/worker/src/guitarvis_worker/runner.py
@@ -11,7 +11,9 @@ so every write after the job starts is conditional on the row still being
 running; when one changes nothing, the worker logs and drops its result.
 """
 
+import hashlib
 import logging
+import re
 import tempfile
 from collections.abc import Callable, Iterator
 from contextlib import contextmanager
@@ -19,14 +21,19 @@ from dataclasses import dataclass, replace
 from pathlib import Path, PurePosixPath
 from typing import Any
 
+from guitarvis_core.audio import probe_duration
 from guitarvis_core.contracts import (
     FailureReason,
     FretboardMapper,
+    IngestedAudio,
     PipelineError,
     Separator,
     StructureAnalyzer,
     Transcriber,
 )
+from guitarvis_fetch.catalog import LINKS_OFF_IN_QUEUE_MESSAGE
+from guitarvis_fetch.fetcher import ChildFetcher, UrlFetcher, find_deno
+from guitarvis_fetch.links import Link, LinkRefused, parse
 from guitarvis_jobs.blobs import BlobStore, S3BlobStore
 from guitarvis_jobs.models import (
     FINISHED_STATUSES,
@@ -47,8 +54,8 @@ from guitarvis_worker.caching import (
     CachedTranscriber,
     CacheKeys,
 )
-from guitarvis_worker.ingest import UploadSource
-from guitarvis_worker.pipeline import StageProgress, run_pipeline
+from guitarvis_worker.ingest import UploadSource, UrlSource
+from guitarvis_worker.pipeline import ProgressCallback, StageProgress, run_pipeline
 from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper
 from guitarvis_worker.stages.separation import DemucsSeparator
 from guitarvis_worker.stages.structure import LibrosaStructureAnalyzer
@@ -57,6 +64,12 @@ from guitarvis_worker.timeouts import JobTimedOut, JobTimeoutDeathPenalty
 
 log = logging.getLogger(__name__)
 
+# A link job's download fills its first 5%, and the pipeline's 0-100 is
+# scaled onto the rest: a ten-minute song downloads in seconds and separates
+# in minutes (spec 012).
+DOWNLOAD_PERCENT = 5
+_EXTENSION = re.compile(r"\.[a-z0-9]{1,5}")
+
 
 @dataclass(frozen=True)
 class Stages:
@@ -81,6 +94,10 @@ class WorkerDeps:
     store: JobStore
     blobs: BlobStore
     stages: Callable[[Path], Stages]
+    # None when links are off: a link job whose audio is not stored fails.
+    fetcher: UrlFetcher | None = None
+    max_download_bytes: int = Settings().max_upload_bytes
+    probe: Callable[[Path], float] = probe_duration
 
 
 class _ProgressWriter:
@@ -110,6 +127,34 @@ class _ProgressWriter:
             )
 
 
+class _LinkProgress:
+    """A link job's percent: `download` fills 0-5, then the pipeline's 0-100
+    is scaled onto 5-100. As for uploads, an update reaches the row only
+    when the stage changes or the whole percent rises."""
+
+    def __init__(self, writer: _ProgressWriter) -> None:
+        self._writer = writer
+        self._last: StageProgress | None = None
+
+    def download(self, fraction: float) -> None:
+        clamped = min(max(fraction, 0.0), 1.0)
+        self._emit(StageProgress("download", int(clamped * DOWNLOAD_PERCENT)))
+
+    def pipeline(self, update: StageProgress) -> None:
+        share = update.percent * (100 - DOWNLOAD_PERCENT) // 100
+        self._emit(StageProgress(update.stage, DOWNLOAD_PERCENT + share))
+
+    def _emit(self, update: StageProgress) -> None:
+        last = self._last
+        if last is not None and (last.stage, last.percent) == (
+            update.stage,
+            max(last.percent, update.percent),
+        ):
+            return  # the same stage, and no whole percent gained
+        self._last = update
+        self._writer(update)
+
+
 def process_job(job_id: str, deps: WorkerDeps, *, retries_left: int) -> None:
     """Run one delivery of a job. `retries_left` is RQ's count; 0 means last."""
     job = deps.store.get(job_id)
@@ -119,13 +164,18 @@ def process_job(job_id: str, deps: WorkerDeps, *, retries_left: int) -> None:
     if job.status in FINISHED_STATUSES:
         log.info("job %s is already %s; ignoring a repeat delivery", job_id, job.status)
         return
-    if deps.store.mark_running(job_id) is None:
+    started = deps.store.mark_running(job_id)
+    if started is None:
         log.info("job %s finished elsewhere before it could start", job_id)
         return
 
     progress = _ProgressWriter(deps.store, job_id)
     try:
-        document, stem_key = _run(job, deps, progress)
+        result = _run(started, deps, progress)
+        if result is None:  # S3: the row was failed while the audio was fetched
+            log.warning("job %s was failed while it fetched; dropping it", job_id)
+            return
+        document, stem_key = result
         # Inside the try: a write that fails here is a failed attempt too,
         # not a row left running until reconciliation notices it.
         stored = deps.store.succeed(job_id, document=document, stem_key=stem_key)
@@ -192,21 +242,35 @@ def _shown(error: PipelineError) -> str:
 
 def _run(
     job: Job, deps: WorkerDeps, progress: _ProgressWriter
-) -> tuple[dict[str, Any], str]:
-    if job.upload_key is None:
-        # A link job whose download is not stored, and nothing here fetches.
-        raise PipelineError(
-            FailureReason.LINKS_DISABLED,
-            "Links were turned off before this song could be fetched. "
-            "Upload the audio file instead.",
-        )
-    keys = CacheKeys(job.content_hash)
+) -> tuple[dict[str, Any], str] | None:
+    """The document and the stem's key; None when the row was failed while
+    a link's audio was fetched."""
+    link_progress = None if job.source_url is None else _LinkProgress(progress)
+    report: ProgressCallback = (
+        progress if link_progress is None else link_progress.pipeline
+    )
     with tempfile.TemporaryDirectory(prefix="guitarvis-job-") as tmp:
         work_dir = Path(tmp)
-        upload = work_dir / f"upload{PurePosixPath(job.upload_key).suffix}"
-        deps.blobs.get_file(job.upload_key, upload)
-        # Probed again here: the worker must not trust its caller.
-        audio = replace(UploadSource(upload).fetch(), title=job.title)
+        if job.upload_key is not None:
+            # An upload, exactly as before links; or a link job retried after
+            # its download was kept, so YouTube is not asked again and the
+            # switch does not apply.
+            audio = _stored_audio(job, job.upload_key, deps, work_dir)
+            content_hash = (
+                job.content_hash
+                if job.source_url is None
+                else PurePosixPath(job.upload_key).stem
+            )
+        else:
+            fetched = _fetch(
+                job, deps, work_dir, link_progress or _LinkProgress(progress)
+            )
+            if fetched is None:
+                return None
+            audio, content_hash = fetched
+        # Cached by the bytes, never by the video: a stem from one download
+        # must not meet the mix from another, whose encoder delay may differ.
+        keys = CacheKeys(content_hash)
         stages = deps.stages(work_dir)
         result = run_pipeline(
             audio,
@@ -214,12 +278,71 @@ def _run(
             transcriber=CachedTranscriber(stages.transcriber, deps.blobs, keys),
             analyzer=CachedAnalyzer(stages.analyzer, deps.blobs, keys),
             mapper=stages.mapper,
-            progress=progress,
+            progress=report,
             audio_url=f"/jobs/{job.id}/audio/mix",
         )
     return result.document.model_dump(mode="json"), keys.stem
 
 
+def _stored_audio(
+    job: Job, upload_key: str, deps: WorkerDeps, work_dir: Path
+) -> IngestedAudio:
+    upload = work_dir / f"upload{PurePosixPath(upload_key).suffix}"
+    deps.blobs.get_file(upload_key, upload)
+    # Probed again here: the worker must not trust its caller.
+    return replace(UploadSource(upload).fetch(), title=job.title)
+
+
+def _fetch(
+    job: Job, deps: WorkerDeps, work_dir: Path, progress: _LinkProgress
+) -> tuple[IngestedAudio, str] | None:
+    """Download a link job's audio, store it as an upload is stored, and
+    record its key. The audio and the hash of its bytes; None when the row
+    is no longer running."""
+    if deps.fetcher is None:  # W1
+        raise PipelineError(FailureReason.LINKS_DISABLED, LINKS_OFF_IN_QUEUE_MESSAGE)
+    progress.download(0.0)
+    audio = UrlSource(
+        _link_of(job),
+        work_dir,
+        deps.fetcher,
+        max_bytes=deps.max_download_bytes,
+        progress=progress.download,
+        probe=deps.probe,
+        job_id=job.id,
+        attempt=job.attempts,
+    ).fetch()
+    content_hash = _sha256(audio.path)
+    suffix = audio.path.suffix.lower()
+    key = f"uploads/{content_hash}{suffix if _EXTENSION.fullmatch(suffix) else ''}"
+    if not deps.blobs.exists(key):
+        deps.blobs.put_file(key, audio.path)  # S1: a failure is retried
+    if not deps.store.attach_upload(  # S2: a failure is retried
+        job.id, upload_key=key, duration_sec=audio.duration_sec
+    ):
+        return None  # S3
+    return replace(audio, title=job.title), content_hash
+
+
+def _link_of(job: Job) -> Link:
+    if job.source_url is None:
+        raise PipelineError(FailureReason.INTERNAL, f"job {job.id} has no audio")
+    try:
+        return parse(job.source_url)
+    except LinkRefused as error:  # the api stored it canonical: ours
+        raise PipelineError(
+            FailureReason.INTERNAL, f"job {job.id}'s link is {error.kind}"
+        ) from error
+
+
+def _sha256(path: Path) -> str:
+    digest = hashlib.sha256()
+    with path.open("rb") as source:
+        while chunk := source.read(1024 * 1024):
+            digest.update(chunk)
+    return digest.hexdigest()
+
+
 def run_job(job_id: str) -> None:
     """RQ's entry point, enqueued by name (guitarvis_jobs.queue.RUN_JOB)."""
     current = get_current_job()
@@ -245,6 +368,8 @@ def open_deps(settings: Settings) -> Iterator[WorkerDeps]:
             store=store,
             blobs=S3BlobStore.from_settings(settings),
             stages=lambda work_dir: build_stages(work_dir, settings.device),
+            fetcher=ChildFetcher() if settings.url_ingestion else None,
+            max_download_bytes=settings.max_upload_bytes,
         )
     finally:
         store.engine.dispose()
@@ -262,6 +387,11 @@ def serve(settings: Settings, *, burst: bool = False) -> None:
     The scheduler is on because RQ needs it to run retries after their
     intervals.
     """
+    if settings.url_ingestion and find_deno() is None:
+        log.warning(
+            "links are on, but Deno 2.3 or later was not found: every link job "
+            "will fail as fetch_failed until it is installed"
+        )
     connection = Redis.from_url(settings.redis_url)
     JobWorker([QUEUE_NAME], connection=connection).work(
         with_scheduler=True, burst=burst
```

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run pytest apps/worker/tests/test_link_jobs.py apps/worker/tests/test_ingest.py`
Expected: PASS, and every test in test_runner.py still passes.

- [ ] **Step 5: Commit**

```bash
make lint typecheck test
git add apps/worker/pyproject.toml \
  apps/worker/src/guitarvis_worker/ingest.py \
  apps/worker/src/guitarvis_worker/runner.py \
  apps/worker/tests/test_ingest.py \
  apps/worker/tests/test_link_jobs.py \
  uv.lock
git commit -m "feat(worker): fetch a link job's audio, store it as an upload, and run it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 12: A link job end to end, on real services

The end-to-end test gains a link job: the api with links on, the fake fetcher at both ends (the api's lookup, and the worker's `ChildFetcher` patched to it), real Postgres, Redis and object storage, ffprobe and a real RQ worker. This task adds a test of what Tasks 8 to 11 built, so it passes at once; there is no failing step.

**Catalog rows:** The whole path: Q1 (a repeat in another form asks nothing), G1, then success.

**Files:**
- Test: `apps/worker/tests/test_end_to_end.py`

- [ ] **Step 1: Write the test**

In `apps/worker/tests/test_end_to_end.py`:

```diff
--- a/apps/worker/tests/test_end_to_end.py
+++ b/apps/worker/tests/test_end_to_end.py
@@ -6,10 +6,12 @@ the job runner are all real. It lives with the worker because it drives
 run_job; the api's own tests never import the worker.
 """
 
+import hashlib
 import shutil
 import urllib.request
 import wave
 from collections.abc import Iterator
+from dataclasses import replace
 from pathlib import Path
 
 import pytest
@@ -23,6 +25,7 @@ from guitarvis_core.contracts import (
     StructureResult,
 )
 from guitarvis_core.tabdoc import TabDocument, Timing
+from guitarvis_fetch.testing import FakeFetcher
 from guitarvis_jobs.queue import QUEUE_NAME, RQJobQueue
 from guitarvis_jobs.testing import (
     integration_settings,
@@ -140,3 +143,72 @@ def test_upload_process_and_fetch(
 
     guitar = client.get(f"/jobs/{job_id}/audio/guitar", follow_redirects=False)
     assert guitar.status_code == 307
+
+
+@pytest.fixture
+def link_service(
+    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
+) -> Iterator[tuple[TestClient, Redis, FakeFetcher]]:
+    """The same service with links on, and a fake fetcher at both ends: the
+    api's lookup and, through open_deps, the worker's download."""
+    content = write_wav(tmp_path / "fetched.wav", seconds=2.0).read_bytes()
+    fetcher = FakeFetcher(content=content)
+    with (
+        postgres_store() as store,
+        s3_blob_store() as blobs,
+        redis_connection() as redis,
+    ):
+        settings = replace(integration_settings(), url_ingestion=True)
+        for name, value in settings_env(settings).items():
+            monkeypatch.setenv(name, value)
+        monkeypatch.setattr(runner, "build_stages", stub_stages)
+        monkeypatch.setattr(runner, "ChildFetcher", lambda: fetcher)
+        services = Services(
+            store=store,
+            blobs=blobs,
+            queue=RQJobQueue(redis, job_timeout_sec=settings.job_timeout_sec),
+            settings=settings,
+            fetcher=fetcher,
+        )
+        yield TestClient(create_app(services)), redis, fetcher
+
+
+@requires_ffprobe
+def test_a_link_job_end_to_end(
+    link_service: tuple[TestClient, Redis, FakeFetcher],
+) -> None:
+    client, redis, fetcher = link_service
+    assert client.get("/features").json() == {"url_ingestion": True}
+
+    created = client.post(
+        "/jobs/from-url", json={"url": "https://youtu.be/kPdv44HtEoA"}
+    )
+    assert created.status_code == 202, created.text
+    job_id = created.json()["id"]
+    assert created.json()["source_url"] == "https://www.youtube.com/watch?v=kPdv44HtEoA"
+    again = client.post(
+        "/jobs/from-url", json={"url": "https://www.youtube.com/shorts/kPdv44HtEoA"}
+    )
+    assert (again.status_code, again.json()["id"]) == (200, job_id)
+    assert len(fetcher.lookups) == 1  # the repeat asked YouTube nothing
+    not_yet = client.get(f"/jobs/{job_id}/audio/mix", follow_redirects=False)
+    assert not_yet.status_code == 409
+
+    SimpleWorker([Queue(QUEUE_NAME, connection=redis)], connection=redis).work(
+        burst=True
+    )
+
+    job = client.get(f"/jobs/{job_id}").json()
+    assert (job["status"], job["percent"], job["attempts"]) == ("succeeded", 100, 1), (
+        job
+    )
+    assert job["title"] == "Elephants Dream - 10 years of open movies"
+    assert job["duration_sec"] == pytest.approx(2.0, abs=0.05)  # ffprobe's
+    document = TabDocument.model_validate(client.get(f"/jobs/{job_id}/document").json())
+    assert document.source.audio_url == f"/jobs/{job_id}/audio/mix"
+
+    mix = client.get(f"/jobs/{job_id}/audio/mix", follow_redirects=False)
+    assert mix.status_code == 307
+    assert hashlib.sha256(fetcher.content or b"").hexdigest() in mix.headers["location"]
+    with urllib.request.urlopen(mix.headers["location"], timeout=10) as response:
+        assert response.read() == fetcher.content
```

- [ ] **Step 2: Run it to verify it passes**

Run: `GUITARVIS_REQUIRE_SERVICES=1 uv run pytest apps/worker/tests/test_end_to_end.py`
Expected: PASS with `make services` up (both tests). Without the services this command fails, as CI's would; without `GUITARVIS_REQUIRE_SERVICES=1` the two tests skip.

- [ ] **Step 3: Commit**

```bash
make lint typecheck test
git add apps/worker/tests/test_end_to_end.py
git commit -m "test: a link job end to end, on real Postgres, Redis and storage

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 13: The web client: `createJobFromUrl` and `getFeatures`

`createJobFromUrl` posts JSON through `fetch` (a link has no upload progress) and maps errors exactly as `createJob` does. `getFeatures` treats anything but a literal `true` as off. `vite.config.ts` proxies `/features`.

**Catalog rows:** R1, R2, L*, Q2, Q3 as the client receives them.

**Files:**
- Modify: `web/src/api/client.ts`
- Modify: `web/vite.config.ts`
- Test: `web/src/api/client.test.ts`

**Interfaces:**
- Produces: `createJobFromUrl(url, signal?, fetcher?) -> Promise<Upload>`; `getFeatures(fetcher?) -> Promise<Features>`.

- [ ] **Step 1: Write the failing tests**

In `web/src/api/client.test.ts`:

```diff
--- a/web/src/api/client.test.ts
+++ b/web/src/api/client.test.ts
@@ -6,8 +6,10 @@ import {
   ApiError,
   MAX_UPLOAD_BYTES,
   createJob,
+  createJobFromUrl,
   errorFrom,
   getDocument,
+  getFeatures,
   getJob,
   type Fetch,
 } from "./client";
@@ -234,6 +236,105 @@ describe("createJob", () => {
   });
 });
 
+describe("createJobFromUrl", () => {
+  const LINK = "https://youtu.be/kPdv44HtEoA";
+
+  it("posts the link as JSON in a field named url", async () => {
+    const sent: Array<[string, RequestInit | undefined]> = [];
+    const recording: Fetch = async (path, init) => {
+      sent.push([path, init]);
+      return new Response(JSON.stringify(jobView()), { status: 202 });
+    };
+
+    await createJobFromUrl(LINK, undefined, recording);
+
+    const [[path, init]] = sent;
+    expect([path, init?.method]).toEqual(["/jobs/from-url", "POST"]);
+    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
+    expect(JSON.parse(String(init?.body))).toEqual({ url: LINK });
+  });
+
+  it("resolves a new job on 202 and an existing one on 200", async () => {
+    await expect(createJobFromUrl(LINK, undefined, answering(202, jobView()))).resolves.toEqual({
+      job: jobView(),
+      created: true,
+    });
+    await expect(
+      createJobFromUrl(LINK, undefined, answering(200, jobView({ status: "running" }))),
+    ).resolves.toMatchObject({ created: false });
+  });
+
+  it.each<[number, string]>([
+    [403, "links_disabled"],
+    [422, "unsupported_link"],
+    [422, "link_unusable"],
+    [422, "too_long"],
+    [429, "too_many_jobs"],
+    [503, "fetch_failed"],
+    [504, "fetch_failed"],
+    [500, "internal"],
+  ])("rejects a %i carrying %s with the server's message", async (status, reason) => {
+    const error = await rejection(
+      createJobFromUrl(LINK, undefined, answering(status, errorBody(reason, "Server words."))),
+    );
+
+    expect(error).toMatchObject({ status, reason, message: "Server words." });
+  });
+
+  it("rejects as unreachable when nothing answers, or when told to stop", async () => {
+    const offline: Fetch = async () => {
+      throw new TypeError("Failed to fetch");
+    };
+    const controller = new AbortController();
+    const listening: Fetch = (_path, init) =>
+      new Promise((_resolve, reject) =>
+        init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))),
+      );
+
+    const stopped = createJobFromUrl(LINK, controller.signal, listening);
+    controller.abort();
+
+    expect(await rejection(createJobFromUrl(LINK, undefined, offline))).toMatchObject({
+      status: null,
+      reason: "unreachable",
+    });
+    expect(await rejection(stopped)).toMatchObject({ reason: "unreachable" });
+  });
+
+  it("reads an answer that is not JSON as no answer", async () => {
+    const error = await rejection(createJobFromUrl(LINK, undefined, answering(202, "<html>")));
+
+    expect(error.reason).toBe("unreachable");
+  });
+});
+
+describe("getFeatures", () => {
+  it("says links are on only when the api says true", async () => {
+    await expect(getFeatures(answering(200, { url_ingestion: true }))).resolves.toEqual({
+      url_ingestion: true,
+    });
+    for (const body of [{ url_ingestion: false }, { url_ingestion: "yes" }, {}, [], null]) {
+      await expect(getFeatures(answering(200, body))).resolves.toEqual({ url_ingestion: false });
+    }
+  });
+
+  it("asks /features", async () => {
+    const paths: string[] = [];
+    await getFeatures(async (path) => {
+      paths.push(path);
+      return new Response("{}");
+    });
+
+    expect(paths).toEqual(["/features"]);
+  });
+
+  it("rejects like every other call when the api cannot be reached", async () => {
+    expect(await rejection(getFeatures(answering(404, "nope")))).toMatchObject({
+      reason: "unreachable",
+    });
+  });
+});
+
 describe("MESSAGES", () => {
   it("gives every reason a headline and an action", () => {
     for (const [reason, message] of Object.entries(MESSAGES)) {
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/api/client.test.ts`
Expected: FAIL in `tsc`: `Module '"./client"' has no exported member 'createJobFromUrl'` (and `getFeatures`).

- [ ] **Step 3: Implement**

In `web/src/api/client.ts`:

```diff
--- a/web/src/api/client.ts
+++ b/web/src/api/client.ts
@@ -5,7 +5,7 @@
  * Paths are relative: the client is served from the api's origin (in
  * development, through the Vite proxy), so there is no CORS.
  */
-import type { FailureView, JobView } from "../types/api";
+import type { FailureView, Features, JobView, LinkRequest } from "../types/api";
 import type { TabDocument } from "../types/tabDocument";
 import { isFailureReason, isReason, type Reason } from "./messages";
 
@@ -91,6 +91,51 @@ export function createJob(
   });
 }
 
+/**
+ * POST /jobs/from-url. Through fetch, since a link has no upload progress to
+ * report. Aborting `signal` stops the request, which then rejects as
+ * unreachable, as an aborted upload does.
+ */
+export async function createJobFromUrl(
+  url: string,
+  signal?: AbortSignal,
+  fetcher: Fetch = browserFetch,
+): Promise<Upload> {
+  const request: LinkRequest = { url };
+  let response: Response;
+  let body: string;
+  try {
+    response = await fetcher("/jobs/from-url", {
+      method: "POST",
+      headers: { "Content-Type": "application/json", Accept: "application/json" },
+      body: JSON.stringify(request),
+      signal,
+    });
+    body = await response.text();
+  } catch {
+    throw noAnswer();
+  }
+  if (response.status !== 200 && response.status !== 202) {
+    throw errorFrom(response.status, body);
+  }
+  try {
+    return { job: knownReasons(JSON.parse(body) as WireJob), created: response.status === 202 };
+  } catch {
+    throw new ApiError(response.status, "unreachable", "The answer was not JSON.");
+  }
+}
+
+/**
+ * GET /features: what the api has switched on. Anything but a plain `true`
+ * reads as off, so the page never offers what the api would refuse.
+ */
+export async function getFeatures(fetcher: Fetch = browserFetch): Promise<Features> {
+  const body = await getJson("/features", fetcher);
+  const on =
+    typeof body === "object" && body !== null && "url_ingestion" in body && body.url_ingestion === true;
+  return { url_ingestion: on };
+}
+
 /**
  * The ApiError for an error response. The api always answers with its error
  * body. A response without one came from something in between, a proxy
```

In `web/vite.config.ts`:

```diff
--- a/web/vite.config.ts
+++ b/web/vite.config.ts
@@ -11,7 +11,7 @@ export default defineConfig({
     // The api's paths go through to it, so in development the client and the
     // api share an origin: no CORS, and <audio> loads /jobs/{id}/audio/...
     // directly. Client routes live under /songs, never /jobs.
-    proxy: { "/jobs": API, "/health": API },
+    proxy: { "/jobs": API, "/health": API, "/features": API },
   },
   build: {
     // three.js ships in the guitar's lazy chunk, about 605 kB before gzip
```

- [ ] **Step 4: Run them to verify they pass**

Run: `npm --prefix web test -- src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
make lint typecheck test
git add web/src/api/client.test.ts \
  web/src/api/client.ts \
  web/vite.config.ts
git commit -m "feat(web): createJobFromUrl and getFeatures

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 14: The link field on the upload page

Under the drop zone, as the WebHome mockup has it: an "or paste a link" divider, a URL field with the link icon and `https://…`, and *Get tab*. It shows only when `/features` says true; a failed call leaves it hidden. Before sending, `linkHint` (a pure module, tested on `node`) asks for a link or says the text does not look like one, under the field with `aria-invalid` and `aria-describedby`, and nothing is sent. While sending, "Checking the link…" and both inputs disabled. A refusal shows `Failure` with the server's message as detail; `links_disabled` also removes the field. Uploads behave exactly as before, and their tests pass unmodified. `stageText` names the `download` stage.

**Catalog rows:** Client side of R1 (the field removed), and every reason's text.

**Files:**
- Modify: `web/src/icons.tsx`
- Modify: `web/src/pages/UploadPage.tsx`
- Create: `web/src/pages/link.ts`
- Modify: `web/src/pages/progress.ts`
- Modify: `web/src/styles.css`
- Test: `web/src/pages/UploadPage.test.tsx`
- Test (new): `web/src/pages/link.test.ts`
- Test: `web/src/pages/progress.test.ts`

**Interfaces:**
- Produces: `UploadPage({ upload?, sendLink?, features? })`; `pages/link.ts`: `linkHint`, `BLANK_HINT`, `NOT_A_LINK_HINT`; `icons.LinkIcon`; `STAGES.download = "Fetching the audio"`.

- [ ] **Step 1: Write the failing tests**

In `web/src/pages/UploadPage.test.tsx`:

```diff
--- a/web/src/pages/UploadPage.test.tsx
+++ b/web/src/pages/UploadPage.test.tsx
@@ -3,7 +3,8 @@ import { act, fireEvent, render, screen } from "@testing-library/react";
 import { beforeEach, describe, expect, it, vi } from "vitest";
 
 import { ApiError, type Upload } from "../api/client";
-import { MESSAGES } from "../api/messages";
+import { MESSAGES, type Reason } from "../api/messages";
+import type { Features } from "../types/api";
 import { JOB_ID, jobView } from "../test/jobs";
 import { UploadPage } from "./UploadPage";
 
@@ -150,4 +151,162 @@ describe("UploadPage", () => {
     expect(later.defaultPrevented).toBe(false);
     expect(laterOver.defaultPrevented).toBe(false);
   });
+
+  describe("the link field", () => {
+    const LINK = "https://youtu.be/kPdv44HtEoA";
+    const on = async (): Promise<Features> => ({ url_ingestion: true });
+    const never = () => new Promise<Upload>(() => {});
+
+    async function showLinks(sendLink: (url: string, signal?: AbortSignal) => Promise<Upload>) {
+      render(<UploadPage upload={never} sendLink={sendLink} features={on} />);
+      await act(async () => {});
+    }
+
+    function field() {
+      return screen.getByRole("textbox", { name: "Link to a YouTube video" }) as HTMLInputElement;
+    }
+
+    function paste(text: string) {
+      fireEvent.change(field(), { target: { value: text } });
+      fireEvent.click(screen.getByRole("button", { name: "Get tab" }));
+    }
+
+    it.each<[string, () => Promise<Features>]>([
+      ["says links are off", async () => ({ url_ingestion: false })],
+      [
+        "cannot be reached",
+        async () => {
+          throw new ApiError(null, "unreachable", "No answer from the server.");
+        },
+      ],
+    ])("is hidden when the api %s", async (_case, features) => {
+      render(<UploadPage upload={never} sendLink={never} features={features} />);
+      await act(async () => {});
+
+      expect(screen.queryByRole("textbox", { name: "Link to a YouTube video" })).toBeNull();
+      expect(screen.queryByText("or paste a link")).toBeNull();
+    });
+
+    it("shows under the drop zone when the api says links are on", async () => {
+      await showLinks(never);
+
+      expect(field().placeholder).toBe("https://…");
+      expect(screen.getByText("or paste a link")).toBeTruthy();
+    });
+
+    it.each<[string, string]>([
+      ["", "Paste a link first."],
+      ["never gonna give you up", "That doesn't look like a link."],
+      ["javascript:alert(1)", "That doesn't look like a link."],
+    ])("hints and sends nothing for %j", async (text, hint) => {
+      const sendLink = vi.fn(never);
+      await showLinks(sendLink);
+
+      paste(text);
+
+      expect(sendLink).not.toHaveBeenCalled();
+      const shown = screen.getByText(hint);
+      expect(field().getAttribute("aria-invalid")).toBe("true");
+      expect(field().getAttribute("aria-describedby")).toBe(shown.id);
+    });
+
+    it("clears the hint once the text changes", async () => {
+      await showLinks(never);
+      paste("");
+
+      fireEvent.change(field(), { target: { value: "y" } });
+
+      expect(screen.queryByText("Paste a link first.")).toBeNull();
+      expect(field().getAttribute("aria-invalid")).toBe("false");
+    });
+
+    it("sends the link, says it is checking, and goes to the song", async () => {
+      let answer: (upload: Upload) => void = () => {};
+      const sendLink = vi.fn<(url: string, signal?: AbortSignal) => Promise<Upload>>(
+        () => new Promise((resolve) => (answer = resolve)),
+      );
+      await showLinks(sendLink);
+
+      paste(`  ${LINK}  `);
+
+      expect(sendLink).toHaveBeenCalledOnce();
+      expect(sendLink.mock.calls[0][0]).toBe(LINK);
+      expect(screen.getByRole("status").textContent).toBe("Checking the link…");
+      expect(field().disabled).toBe(true);
+      expect((screen.getByLabelText(/choose one/i) as HTMLInputElement).disabled).toBe(true);
+      await act(async () => answer({ job: jobView(), created: true }));
+      expect(window.location.pathname).toBe(`/songs/${JOB_ID}`);
+    });
+
+    it.each<[Reason, number]>([
+      ["unsupported_link", 422],
+      ["link_unusable", 422],
+      ["too_long", 422],
+      ["too_many_jobs", 429],
+      ["fetch_failed", 503],
+      ["internal", 500],
+    ])("shows %s's text with the server's words as detail", async (reason, status) => {
+      await showLinks(async () => {
+        throw new ApiError(status, reason, "Words from the server.");
+      });
+
+      paste(LINK);
+      await act(async () => {});
+
+      expect(screen.getByText(MESSAGES[reason].headline)).toBeTruthy();
+      expect(screen.getByText(MESSAGES[reason].action)).toBeTruthy();
+      expect(screen.getByText("Words from the server.")).toBeTruthy();
+      expect(field()).toBeTruthy(); // still there to try another link
+      expect(window.location.pathname).toBe("/");
+    });
+
+    it("removes itself when the api says links were turned off", async () => {
+      await showLinks(async () => {
+        throw new ApiError(403, "links_disabled", "Links are turned off on this server.");
+      });
+
+      paste(LINK);
+      await act(async () => {});
+
+      expect(screen.getByText(MESSAGES.links_disabled.headline)).toBeTruthy();
+      expect(screen.getByText("Links are turned off on this server.")).toBeTruthy();
+      expect(screen.queryByRole("textbox", { name: "Link to a YouTube video" })).toBeNull();
+    });
+
+    it("calls no answer unreachable, without a detail of its own", async () => {
+      await showLinks(async () => {
+        throw new ApiError(null, "unreachable", "No answer from the server.");
+      });
+
+      paste(LINK);
+      await act(async () => {});
+
+      expect(screen.getByText(MESSAGES.unreachable.headline)).toBeTruthy();
+      expect(screen.queryByText("No answer from the server.")).toBeNull();
+    });
+
+    it("stops the request and stays put if the user leaves first", async () => {
+      let answer: (upload: Upload) => void = () => {};
+      let signal: AbortSignal | undefined;
+      const { unmount } = render(
+        <UploadPage
+          upload={never}
+          features={on}
+          sendLink={(_url, given) => {
+            signal = given;
+            return new Promise<Upload>((resolve) => (answer = resolve));
+          }}
+        />,
+      );
+      await act(async () => {});
+      paste(LINK);
+
+      unmount();
+      window.history.pushState(null, "", "/songs/somewhere-else");
+      await act(async () => answer({ job: jobView(), created: true }));
+
+      expect(signal?.aborted).toBe(true);
+      expect(window.location.pathname).toBe("/songs/somewhere-else");
+    });
+  });
 });
```

Create `web/src/pages/link.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { BLANK_HINT, NOT_A_LINK_HINT, linkHint } from "./link";

describe("linkHint", () => {
  it.each(["", "   ", "\t\n"])("asks for a link when the field is blank: %j", (raw) => {
    expect(linkHint(raw)).toBe(BLANK_HINT);
  });

  it.each([
    "never gonna give you up",
    "hello",
    "javascript:alert(1)",
    "ftp://example.com/song.mp3",
    "file:///etc/passwd",
    "https://",
    "https://exa mple.com/",
  ])("says %j does not look like a link", (raw) => {
    expect(linkHint(raw)).toBe(NOT_A_LINK_HINT);
  });

  it.each([
    "https://www.youtube.com/watch?v=kPdv44HtEoA",
    "  youtu.be/kPdv44HtEoA  ",
    "http://example.com/anything",
    "www.youtube.com/playlist?list=PL123",
  ])("lets %j through, for the api to judge", (raw) => {
    expect(linkHint(raw)).toBeNull();
  });
});
```

In `web/src/pages/progress.test.ts`:

```diff
--- a/web/src/pages/progress.test.ts
+++ b/web/src/pages/progress.test.ts
@@ -1,6 +1,13 @@
 import { describe, expect, it } from "vitest";
 
-import { MAX_POLL_MS, POLL_MS, backoff } from "./progress";
+import { MAX_POLL_MS, POLL_MS, backoff, stageText } from "./progress";
+
+describe("stageText", () => {
+  it("names a link job's download, which comes before the four stages", () => {
+    expect(stageText("download")).toBe("Fetching the audio");
+    expect(stageText("separation")).toBe("Isolating the guitar");
+  });
+});
 
 describe("backoff", () => {
   it("doubles from the polling interval and stops at the cap", () => {
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/pages`
Expected: FAIL in `tsc`: `Property 'sendLink' does not exist on type 'IntrinsicAttributes & UploadPageProps'` (and `features`), and `link.test.ts` cannot find `./link`.

- [ ] **Step 3: Implement**

In `web/src/icons.tsx`:

```diff
--- a/web/src/icons.tsx
+++ b/web/src/icons.tsx
@@ -65,6 +65,15 @@ export function ForwardIcon() {
   );
 }
 
+/** The link field's marker: two chain links. */
+export function LinkIcon() {
+  return (
+    <Icon>
+      <path d="M3.9 12a3.1 3.1 0 0 1 3.1-3.1h4V7H7a5 5 0 0 0 0 10h4v-1.9H7A3.1 3.1 0 0 1 3.9 12zM8 13h8v-2H8v2zm9-6h-4v1.9h4a3.1 3.1 0 0 1 0 6.2h-4V17h4a5 5 0 0 0 0-10z" />
+    </Icon>
+  );
+}
+
 /** The warnings line's marker. */
 export function AlertIcon() {
   return (
```

Replace `web/src/pages/UploadPage.tsx` with:

```tsx
import { useEffect, useId, useRef, useState, type DragEvent, type FormEvent } from "react";

import { ApiError, createJob, createJobFromUrl, getFeatures } from "../api/client";
import type { Reason } from "../api/messages";
import { LinkIcon } from "../icons";
import { navigate, songPath } from "../routing";
import type { Features } from "../types/api";
import { Failure } from "./Failure";
import { linkHint } from "./link";

type Upload =
  | { kind: "idle" }
  | { kind: "sending"; name: string; fraction: number }
  | { kind: "checking" }
  | { kind: "refused"; reason: Reason; detail?: string };

export interface UploadPageProps {
  upload?: typeof createJob;
  sendLink?: typeof createJobFromUrl;
  features?: () => Promise<Features>;
}

/** Drop or pick a song, or paste a link; POST it; go to its page. A repeat
 * lands on the existing song, which may already be playable. */
export function UploadPage({
  upload = createJob,
  sendLink = createJobFromUrl,
  features = getFeatures,
}: UploadPageProps) {
  const [state, setState] = useState<Upload>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);
  const linksOn = useLinksOn(features);
  const [linksRefused, setLinksRefused] = useState(false);
  const sending = state.kind === "sending" || state.kind === "checking";
  const inFlight = useRef<AbortController | null>(null);

  // A user who leaves mid-request has gone somewhere else: stop it, and
  // never pull them back to the song when it would have finished.
  useEffect(() => () => inFlight.current?.abort(), []);

  const start = () => {
    const controller = new AbortController();
    inFlight.current = controller;
    return () => !controller.signal.aborted;
  };

  const send = (file: File) => {
    if (sending) return;
    const live = start();
    setState({ kind: "sending", name: file.name, fraction: 0 });
    const onProgress = (fraction: number) => {
      if (live()) setState({ kind: "sending", name: file.name, fraction });
    };
    upload(file, onProgress, inFlight.current?.signal)
      .then(({ job }) => {
        if (live()) navigate(songPath(job.id));
      })
      .catch((error: unknown) => {
        if (!live()) return;
        setState({
          kind: "refused",
          reason: error instanceof ApiError ? error.reason : "unreachable",
        });
      });
  };

  const sendUrl = (url: string) => {
    if (sending) return;
    const live = start();
    setState({ kind: "checking" });
    sendLink(url, inFlight.current?.signal)
      .then(({ job }) => {
        if (live()) navigate(songPath(job.id));
      })
      .catch((error: unknown) => {
        if (!live()) return;
        if (!(error instanceof ApiError)) {
          setState({ kind: "refused", reason: "unreachable" });
          return;
        }
        // Turned off since the page asked: the field goes, the reason stays.
        if (error.reason === "links_disabled") setLinksRefused(true);
        setState({
          kind: "refused",
          reason: error.reason,
          detail: error.status === null ? undefined : error.message,
        });
      });
  };

  // A file dropped just outside the drop zone would otherwise be opened by the
  // browser, and the app lost. Only the drop zone takes a drop.
  useEffect(() => {
    const refuse = (event: Event) => event.preventDefault();
    window.addEventListener("dragover", refuse);
    window.addEventListener("drop", refuse);
    return () => {
      window.removeEventListener("dragover", refuse);
      window.removeEventListener("drop", refuse);
    };
  }, []);

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file !== undefined) send(file);
  };

  return (
    <main className="upload-page">
      <h1>Turn a song into guitar tab</h1>
      <p>Upload a recording. We isolate the guitar, transcribe it, and play it back with the tab.</p>
      <label
        className={dragging ? "drop-zone dragging" : "drop-zone"}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <span>Drop an audio file here, or choose one</span>
        <input
          type="file"
          accept="audio/*"
          disabled={sending}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file !== undefined) send(file);
          }}
        />
      </label>
      {linksOn && !linksRefused && <LinkForm disabled={sending} onSend={sendUrl} />}
      {state.kind === "sending" && (
        <p role="status">
          {state.fraction < 1 ? (
            <>
              Uploading {state.name} <progress value={state.fraction} max={1} />{" "}
              {Math.round(state.fraction * 100)}%
            </>
          ) : (
            // Every byte is sent; the api hashes, probes and stores the file
            // before it answers, which takes seconds for a large one.
            "Checking the file…"
          )}
        </p>
      )}
      {state.kind === "checking" && <p role="status">Checking the link…</p>}
      {state.kind === "refused" && <Failure reason={state.reason} detail={state.detail} />}
    </main>
  );
}

/** Whether to offer links: only once the api says they are on. No answer,
 * or any other answer, leaves the field hidden. */
function useLinksOn(features: () => Promise<Features>): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    let live = true;
    features().then(
      (answer) => {
        if (live && answer.url_ingestion) setOn(true);
      },
      () => {},
    );
    return () => {
      live = false;
    };
  }, [features]);
  return on;
}

/** The link field, under the drop zone (the WebHome mockup). A hint shows
 * under the field, and nothing is sent, until the text looks like a link. */
function LinkForm({ disabled, onSend }: { disabled: boolean; onSend: (url: string) => void }) {
  const [text, setText] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const hintId = useId();

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const problem = linkHint(text);
    setHint(problem);
    if (problem === null) onSend(text.trim());
  };

  return (
    <form className="link-form" onSubmit={submit} noValidate>
      <p className="divider">or paste a link</p>
      <div className="link-row">
        <label className="link-field">
          <LinkIcon />
          <input
            type="url"
            inputMode="url"
            placeholder="https://…"
            aria-label="Link to a YouTube video"
            value={text}
            disabled={disabled}
            aria-invalid={hint !== null}
            aria-describedby={hint !== null ? hintId : undefined}
            onChange={(event) => {
              setText(event.target.value);
              setHint(null);
            }}
          />
        </label>
        <button type="submit" disabled={disabled}>
          Get tab
        </button>
      </div>
      {hint !== null && (
        <p id={hintId} className="link-hint">
          {hint}
        </p>
      )}
    </form>
  );
}
```

Create `web/src/pages/link.ts`:

```ts
/**
 * What the link field says before anything is sent (spec 012). The client
 * checks only that the text is a web address. Which sites work is the api's
 * call, so there is no list here to drift from it.
 */
export const BLANK_HINT = "Paste a link first.";
export const NOT_A_LINK_HINT = "That doesn't look like a link.";

/** A hint for the user, or null when the text may be sent. */
export function linkHint(raw: string): string | null {
  const text = raw.trim();
  if (text === "") return BLANK_HINT;
  if (/\s/.test(text)) return NOT_A_LINK_HINT;
  const candidate = /^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : `https://${text}`;
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return NOT_A_LINK_HINT;
  }
  const web = url.protocol === "http:" || url.protocol === "https:";
  return web && url.hostname.includes(".") ? null : NOT_A_LINK_HINT;
}
```

In `web/src/pages/progress.ts`:

```diff
--- a/web/src/pages/progress.ts
+++ b/web/src/pages/progress.ts
@@ -7,6 +7,7 @@ export const MAX_POLL_MS = 10_000;
 export const MAX_ATTEMPTS = 3;
 
 const STAGES: Record<string, string> = {
+  download: "Fetching the audio",
   separation: "Isolating the guitar",
   transcription: "Transcribing notes",
   structure: "Finding the beat and chords",
```

In `web/src/styles.css`:

```diff
--- a/web/src/styles.css
+++ b/web/src/styles.css
@@ -872,3 +872,80 @@ progress {
   width: 100%;
   max-width: 400px;
 }
+
+/* The link field, under the drop zone (spec 012; the WebHome mockup). */
+.link-form .divider {
+  display: flex;
+  gap: 12px;
+  align-items: center;
+  margin: 16px 0 12px;
+  color: var(--muted);
+  font-size: 14px;
+}
+
+.link-form .divider::before,
+.link-form .divider::after {
+  flex: 1;
+  border-top: 1px solid var(--border);
+  content: "";
+}
+
+.link-row {
+  display: flex;
+  gap: 8px;
+}
+
+.link-field {
+  display: flex;
+  flex: 1;
+  gap: 8px;
+  align-items: center;
+  min-width: 0;
+  padding: 0 12px;
+  border: 1px solid var(--border);
+  border-radius: 8px;
+  background: var(--bg-raised);
+  color: var(--muted);
+}
+
+.link-field:focus-within {
+  border-color: var(--accent);
+}
+
+.link-field input {
+  flex: 1;
+  min-width: 0;
+  padding: 10px 0;
+  border: 0;
+  background: transparent;
+  color: var(--fg);
+  font: inherit;
+  outline: none;
+}
+
+.link-field:has(input[aria-invalid="true"]) {
+  border-color: var(--accent);
+}
+
+.link-row button {
+  padding: 0 16px;
+  border: 0;
+  border-radius: 8px;
+  background: var(--accent);
+  color: var(--on-accent);
+  font: inherit;
+  font-weight: 700;
+  cursor: pointer;
+}
+
+.link-row button:disabled,
+.link-field input:disabled {
+  cursor: not-allowed;
+  opacity: 0.6;
+}
+
+.link-hint {
+  margin: 8px 0 0;
+  color: var(--accent);
+  font-size: 14px;
+}
```

- [ ] **Step 4: Run them to verify they pass**

Run: `npm --prefix web test -- src/pages`
Expected: PASS, the existing upload tests unchanged.

- [ ] **Step 5: Commit**

```bash
make lint typecheck test
git add web/src/icons.tsx \
  web/src/pages/UploadPage.test.tsx \
  web/src/pages/UploadPage.tsx \
  web/src/pages/link.test.ts \
  web/src/pages/link.ts \
  web/src/pages/progress.test.ts \
  web/src/pages/progress.ts \
  web/src/styles.css
git commit -m "feat(web): paste a link on the upload page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 15: `make smoke-url`, and links on under `make api` and `make worker`

The live test is `packages/fetch/smoke/live_fetch.py`: not named `test_*.py`, so `make check`'s pytest never collects it, and skipping unless `GUITARVIS_LIVE_FETCH=1` besides. It looks up and downloads the smoke video, probes it, and prints what YouTube says for a private and a removed video, for refreshing the fixtures. A tripwire test keeps it out of `check` and CI, as `test_eval_never_gates_ci.py` does for evaluation. The Makefile's `api` and `worker` targets turn links on, overridable with `make api GUITARVIS_URL_INGESTION=0`. CI's workflow does not change: it needs no Deno and makes no request to YouTube.

**Catalog rows:** None directly: the smoke test checks the real path end to end.

**Files:**
- Modify: `Makefile`
- Create: `packages/fetch/smoke/live_fetch.py`
- Test (new): `packages/fetch/tests/test_smoke_never_gates_ci.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/fetch/tests/test_smoke_never_gates_ci.py`:

```python
"""`make smoke-url` asks YouTube, so it must never gate the build: CI would
fail whenever YouTube changed, or refused a datacenter address. These keep
it out of `make check`, as test_eval_never_gates_ci keeps evaluation out."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SMOKE = REPO / "packages" / "fetch" / "smoke" / "live_fetch.py"


def test_pytest_never_collects_the_smoke_test_on_its_own() -> None:
    assert SMOKE.is_file()
    assert not SMOKE.name.startswith("test_"), "pytest would collect it in make check"


def test_check_does_not_reach_the_smoke_test() -> None:
    makefile = (REPO / "Makefile").read_text()
    check = re.search(r"^check:(.*)$", makefile, re.MULTILINE)

    assert check is not None
    assert "smoke" not in check.group(1)


def test_ci_never_fetches_live() -> None:
    for workflow in (REPO / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text()
        assert "smoke-url" not in text, workflow.name
        assert "GUITARVIS_LIVE_FETCH" not in text, workflow.name


def test_the_smoke_test_skips_unless_asked() -> None:
    assert 'os.environ.get("GUITARVIS_LIVE_FETCH") != "1"' in SMOKE.read_text()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/fetch/tests/test_smoke_never_gates_ci.py`
Expected: FAIL: `packages/fetch/smoke/live_fetch.py` does not exist yet.

- [ ] **Step 3: Implement**

In `Makefile`:

```diff
--- a/Makefile
+++ b/Makefile
@@ -3,7 +3,8 @@
 #
 # `eval` and `sweep` are deliberately absent from `check`. Evaluation is
 # measured, never gated: a suite that fails because a model got two percent
-# worse on a Tuesday is a suite people learn to ignore.
+# worse on a Tuesday is a suite people learn to ignore. `smoke-url` is absent
+# too: it asks YouTube, whose answer changes by the day and by the address.
 
 .DEFAULT_GOAL := help
 UV  := uv
@@ -44,10 +45,17 @@ ARGS ?=
 PY_SOURCES := packages/core/src packages/jobs/src packages/fetch/src \
               apps/api/src apps/worker/src apps/eval/src \
               packages/core/tests packages/jobs/tests packages/fetch/tests \
+              packages/fetch/smoke \
               apps/api/tests apps/worker/tests apps/eval/tests
 
 .PHONY: help install lint format typecheck test test-py test-web \
-        schema schema-check check eval sweep eval-data services migrate api worker web clean
+        schema schema-check check eval sweep eval-data smoke-url services migrate \
+        api worker web clean
+
+# Spec 012's switch is off unless a deployment turns it on; `make api` and
+# `make worker` turn it on for local development. Override with
+# `make api GUITARVIS_URL_INGESTION=0`, or in the environment.
+GUITARVIS_URL_INGESTION ?= 1
 
 help: ## Show this help
 	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
@@ -126,17 +134,20 @@ sweep: ## Tune MapperCosts and transcription settings on dev. Never gated.
 eval-data: ## Download GuitarSet into ~/.cache (ARGS=--audio for full mode's audio)
 	$(UV) run python -m guitarvis_eval.download $(ARGS)
 
+smoke-url: ## Live: fetch a Creative Commons video from YouTube. Needs Deno. Never gated.
+	GUITARVIS_LIVE_FETCH=1 $(UV) run pytest -s -p no:cacheprovider packages/fetch/smoke/live_fetch.py
+
 services: ## Start Postgres, Redis and object storage (docker compose)
 	docker compose up -d --wait
 
 migrate: ## Bring the schema up to date and create the bucket
 	$(UV) run python -m guitarvis_jobs.migrate
 
-api: ## Serve the api on localhost:8000, reloading on change
-	$(UV) run uvicorn guitarvis_api.app:app --reload
+api: ## Serve the api on localhost:8000, reloading on change; links on
+	GUITARVIS_URL_INGESTION=$(GUITARVIS_URL_INGESTION) $(UV) run uvicorn guitarvis_api.app:app --reload
 
-worker: ## Run jobs from the queue (ARGS="--device cuda"; needs `uv sync --extra ml`)
-	$(UV) run guitarvis-worker serve $(ARGS)
+worker: ## Run jobs from the queue (ARGS="--device cuda"; needs `uv sync --extra ml`); links on
+	GUITARVIS_URL_INGESTION=$(GUITARVIS_URL_INGESTION) $(UV) run guitarvis-worker serve $(ARGS)
 
 web: ## Serve the web client on localhost:5173, proxying the api on :8000
 	$(NPM) run dev
```

Create `packages/fetch/smoke/live_fetch.py`:

```python
"""`make smoke-url`: one real lookup and download from YouTube (spec 012).

Never part of `make check`: it depends on YouTube's behaviour that day, and
from a CI runner's datacenter address YouTube usually demands sign-in. The
file is not named test_*.py, so pytest finds it only when given its path;
it also skips unless GUITARVIS_LIVE_FETCH=1. Needs Deno 2.3 or later.

Run it after bumping yt-dlp and before a release. The messages it prints
for a private and a removed video refresh tests/fixtures/youtube-messages.json.
"""

import os
from pathlib import Path

import pytest
from guitarvis_core.audio import probe_duration
from guitarvis_fetch.catalog import FetchKind
from guitarvis_fetch.fetcher import ChildFetcher, FetchError, check_info
from guitarvis_fetch.links import parse

pytestmark = pytest.mark.skipif(
    os.environ.get("GUITARVIS_LIVE_FETCH") != "1",
    reason="live fetching is opt-in: run `make smoke-url`",
)

# "Elephants Dream - 10 years of open movies", on the Blender Foundation's own
# channel: 37 seconds, Creative Commons Attribution. Its staying online is
# this test's one outside dependency; if it goes, pick another short CC-BY
# video and say so in the commit.
SMOKE_VIDEO = "https://www.youtube.com/watch?v=kPdv44HtEoA"
SMOKE_SECONDS = 37.0
PRIVATE_VIDEO = "https://www.youtube.com/watch?v=yZIXLfi8CZQ"
REMOVED_VIDEO = "https://www.youtube.com/watch?v=Q39EVAstoRM"


def test_a_creative_commons_video_is_looked_up_downloaded_and_probed(
    tmp_path: Path,
) -> None:
    fetcher = ChildFetcher()
    link = parse(SMOKE_VIDEO)

    info = fetcher.lookup(link)
    download = fetcher.download(link, tmp_path, max_bytes=150 * 1024 * 1024)
    probed = probe_duration(download.path)

    print(f"\nlookup: {info}\ndownload: {download}\nffprobe: {probed:.2f} s")
    assert check_info(info) == pytest.approx(SMOKE_SECONDS, abs=1)
    assert download.path.parent == tmp_path
    assert probed == pytest.approx(SMOKE_SECONDS, abs=1)


@pytest.mark.parametrize(
    ("url", "kind"),
    [(PRIVATE_VIDEO, FetchKind.PRIVATE), (REMOVED_VIDEO, FetchKind.UNAVAILABLE)],
)
def test_what_youtube_says_for_a_private_and_a_removed_video(
    url: str, kind: FetchKind
) -> None:
    with pytest.raises(FetchError) as excinfo:
        ChildFetcher().lookup(parse(url))

    error = excinfo.value
    print(f"\n{kind}: ytdlp={error.versions.ytdlp} message={error.detail!r}")
    assert error.kind is kind
```

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run pytest packages/fetch/tests/test_smoke_never_gates_ci.py`
Expected: PASS. Then, with Deno 2.3 or later installed and a network, `make smoke-url` should print the lookup, a download of format 140 (`ext=m4a`, about 600 KB) and ffprobe's 37.06 s, then `private` and `unavailable` with yt-dlp's text: `3 passed`. Without Deno it fails with `kind=misconfigured`; that is not a `make check` failure.

- [ ] **Step 5: Commit**

```bash
make lint typecheck test
git add Makefile \
  packages/fetch/smoke/live_fetch.py \
  packages/fetch/tests/test_smoke_never_gates_ci.py
git commit -m "build: make smoke-url, and links on under make api and make worker

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 16: ADR 0010

Records D3 and D4: yt-dlp as a library in a child process, behind a switch that is off by default. From `docs/decisions/template.md`, linked from the index.

**Files:**
- Create: `docs/decisions/0010-yt-dlp-in-a-child-behind-a-switch.md`
- Modify: `docs/decisions/README.md`

- [ ] **Step 1: Write the documents**

Create `docs/decisions/0010-yt-dlp-in-a-child-behind-a-switch.md`:

```markdown
# 0010. Links are fetched by yt-dlp in a child process, behind a switch that is off by default

**Status:** Accepted
**Date:** 2026-10-26
**Spec:** [012-url-ingestion](../specs/012-url-ingestion/spec.md#where-yt-dlp-runs)

## Context

Phase 6 lets a user paste a YouTube link instead of uploading a file. The
part that fetches is the part most likely to break, since YouTube changes
often and extraction tooling follows days later, and the part most likely to
need removing, since fetching from YouTube breaks its terms of service and
carries legal exposure beyond them. The parent spec asked for it to be
swappable, testable on its own, and possible to turn off in config.

The api must answer a lookup within a deadline, and a library call in a
thread cannot be stopped. A fetch runs on user input next to the database URL
and the storage secret. yt-dlp's command line reads `yt-dlp.conf` from the
host, and the library loads plugins from the same configuration directories.

## Decision

yt-dlp runs as a library inside a child process of our own,
`python -I -m guitarvis_fetch.child`, started by the api for a lookup and by
the worker for a download. The child gets no `GUITARVIS_*` variables and has
plugins switched off. It answers in JSON lines, classifies every failure while
yt-dlp's exception types are visible, and is killed with its whole process
group at its deadline. Deno is its JavaScript runtime.

`GUITARVIS_URL_INGESTION` turns links on, and it is off by default. The api
refuses links with 403 `links_disabled` when it is off, the worker fails a
queued link job with `links_disabled`, and the client hides the link field.

## Consequences

A hang, a crash or a memory blow-up in yt-dlp costs one child, never the api
or a worker. Failures arrive typed, not as English on stderr, and the failure
catalog maps each kind to a reason, a status, a message and a log level. The
whole path is one package, one call in the api's `app.py` and one branch in
the worker, so removing it touches no upload code.

The costs: an interpreter starts for every lookup (a few hundred
milliseconds); every host that fetches needs Deno 2.3 or later, as it needs
ffmpeg; and yt-dlp needs bumping when YouTube breaks it, with `make smoke-url`
as the check. A deployment that has not decided takes no risk, and a fresh
checkout shows the link field only under `make api`.

Revisit if hosting cannot fetch from YouTube at all (open decision 12), if
retention rules make stored fetches untenable (open decision 13), or if a
switch that works without a restart becomes necessary, which needs the admin
surface that open decision 11 has not provided.
```

In `docs/decisions/README.md`:

```diff
--- a/docs/decisions/README.md
+++ b/docs/decisions/README.md
@@ -18,6 +18,7 @@ New decisions take the next number and start from [`template.md`](template.md).
 | [0007](0007-postgres-is-the-record.md) | Postgres is the record of a job; Redis carries only its id |
 | [0008](0008-native-time-stretch.md) | Slow-down uses the browser's own time-stretching, on one media element |
 | [0009](0009-procedural-guitar-model.md) | The guitar is built in code, not loaded from a model file |
+| [0010](0010-yt-dlp-in-a-child-behind-a-switch.md) | Links are fetched by yt-dlp in a child process, behind a switch that is off by default |
 
 ## Still open
 
```

- [ ] **Step 2: Check and commit**

```bash
make lint typecheck test
git add docs/decisions/0010-yt-dlp-in-a-child-behind-a-switch.md \
  docs/decisions/README.md
git commit -m "docs: ADR 0010, yt-dlp in a child process behind a switch

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 17: CLAUDE.md, the conventions, the skill, and the specs this amends

CLAUDE.md: phase 6 done, `make smoke-url`, and four new things that will bite (the switch, Deno, bumping yt-dlp, the catalog). CONVENTIONS.md: the yt-dlp rule, `/features` beside `/jobs` and `/health`, and three rows of mechanisms. The `pipeline-stage` skill's failure section gains the two job reasons and `retryable`. 001's reason list, retries and phase 6, and 005's job table, as the spec's *Consequences* list. README and CONTRIBUTING: the package, Deno, the link curl, the new target.

**Files:**
- Modify: `.claude/skills/pipeline-stage/SKILL.md`
- Modify: `CLAUDE.md`
- Modify: `CONTRIBUTING.md`
- Modify: `README.md`
- Modify: `docs/CONVENTIONS.md`
- Modify: `docs/specs/001-guitarvis-design/spec.md`
- Modify: `docs/specs/005-api-job-queue/spec.md`

- [ ] **Step 1: Write the documents**

In `.claude/skills/pipeline-stage/SKILL.md`:

```diff
--- a/.claude/skills/pipeline-stage/SKILL.md
+++ b/.claude/skills/pipeline-stage/SKILL.md
@@ -69,9 +69,15 @@ outright only when there is no usable guitar audio.
 When a stage fails, omit its track from the tab document and continue. Raise
 `PipelineError` with a typed `FailureReason` only when the job genuinely cannot
 produce anything: `unsupported_format`, `no_guitar_detected`, `too_long`,
-`fetch_failed`, `internal`. Those strings are a contract — the UI maps each to
-actionable text so the user knows whether to try a different file, a different
-song, or come back later.
+`fetch_failed`, `link_unusable`, `links_disabled`, `internal`. Those strings are
+a contract — the UI maps each to actionable text so the user knows whether to
+try a different file, a different song, or come back later.
+
+`PipelineError` also says whether another attempt might pass: `retryable`
+defaults to true for `internal` only. The runner retries whatever is
+retryable, and on the final attempt records the error's own reason and
+message, unless the reason is `internal`, whose detail stays in the log. A
+fetch that fails on the network is `fetch_failed` and retryable (spec 012).
 
 ## Testing a stage
 
```

In `CLAUDE.md`:

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -10,8 +10,8 @@ Start here: [`docs/specs/001-guitarvis-design/spec.md`](docs/specs/001-guitarvis
 ## Commands
 
 `make install` · `make check` · `make test` · `make schema` · `make eval-data` · `make eval` ·
-`make sweep` · `make services` · `make migrate` · `make api` · `make worker` · `make web` ·
-`make help`
+`make sweep` · `make smoke-url` · `make services` · `make migrate` · `make api` · `make worker` ·
+`make web` · `make help`
 
 `make check` is what CI runs. Run it before claiming anything works.
 
@@ -49,9 +49,9 @@ any default that would write specs elsewhere — see
 3. API and job queue
 4. Web client: tab view and sync
 5. 2D fretboard, then 3D guitar
-6. URL ingestion ← **next**
+6. URL ingestion (spec 012)
 
-Phases 1–2 hold the technical risk. The rest is conventional work.
+All six are built. Phases 1–2 held the technical risk.
 
 ## Things that will bite you
 
@@ -85,3 +85,18 @@ Phases 1–2 hold the technical risk. The rest is conventional work.
 - The guitar's tests run without WebGL. Pure modules in `web/src/guitar/` run
   on `node`, three.js included. `Guitar` and `Stage` take a fake renderer under
   jsdom.
+- Links (spec 012) live in `packages/fetch`, walled off: deleting it, one line
+  in the api's `app.py` and one branch in the worker's runner removes them.
+  They are off unless `GUITARVIS_URL_INGESTION` is on. `make api` and
+  `make worker` turn it on; bare `uvicorn` does not. The api and the worker
+  read it at start, so flipping it means restarting both.
+- Fetching a link needs Deno 2.3 or later on the host, yt-dlp's JavaScript
+  runtime for YouTube. Without it a link job fails as `fetch_failed`, and the
+  worker warns at start. `make check` needs neither Deno nor the network.
+- yt-dlp breaks when YouTube changes. `uv lock --upgrade-package yt-dlp`, then
+  `make smoke-url`, then commit; the switch is the stopgap meanwhile. Only
+  `guitarvis_fetch.child` imports `yt_dlp`, in its own process, and the api
+  must not (`test_boundaries.py`).
+- A link failure's reason, status and message come from
+  `packages/fetch/src/guitarvis_fetch/catalog.py`, never from yt-dlp, whose
+  text goes to the log only. Add a row there before raising a new kind.
```

In `CONTRIBUTING.md`:

```diff
--- a/CONTRIBUTING.md
+++ b/CONTRIBUTING.md
@@ -9,7 +9,9 @@ make check
 
 Requires Python 3.12+, Node 22+, [uv](https://docs.astral.sh/uv/)
 (`curl -LsSf https://astral.sh/uv/install.sh | sh`), and ffmpeg (provides
-`ffprobe`, used to probe uploaded audio).
+`ffprobe`, used to probe uploaded audio). Fetching links also needs
+[Deno](https://deno.com) 2.3+, yt-dlp's JavaScript runtime; `make check` does
+not.
 The integration tests and `make api`/`make worker` also need Docker, for
 `make services`.
 
@@ -30,10 +32,11 @@ the hook that refuses commits on `main`.
 | `make check` | Everything CI runs |
 | `make eval-data` | Download GuitarSet into `~/.cache` (`ARGS=--audio` for full mode) |
 | `make eval` | GuitarSet evaluation — measured, never gated (`ARGS="--full"`, `ARGS="--split dev"`) |
+| `make smoke-url` | Look up and download one Creative Commons video from YouTube — live, never gated, needs Deno |
 | `make services` | Start Postgres, Redis and RustFS in Docker |
 | `make migrate` | Create or upgrade the jobs table, and create the bucket |
-| `make api` | Serve the api on `localhost:8000`, reloading on change |
-| `make worker` | Run jobs from the queue (`ARGS="--device cuda"`; needs the `ml` extra) |
+| `make api` | Serve the api on `localhost:8000`, reloading on change, links on |
+| `make worker` | Run jobs from the queue (`ARGS="--device cuda"`; needs the `ml` extra), links on |
 | `make web` | Serve the web client on `localhost:5173`, proxying the api |
 | `make clean` | Remove caches and build output |
 | `make help` | List these targets with their one-line descriptions |
```

In `README.md`:

````diff
--- a/README.md
+++ b/README.md
@@ -50,6 +50,7 @@ v1 has no editing, so transcription errors cannot be corrected by hand.
 |---|---|
 | `packages/core` | The tab document, the stage interfaces, the fretboard invariant |
 | `packages/jobs` | The job record, object storage and the queue, shared by the api and the worker |
+| `packages/fetch` | Links: parsing, the yt-dlp child process and the failure catalog. Walled off (ADR 0010) |
 | `apps/api` | FastAPI. Thin; no ML code, enforced by test |
 | `apps/worker` | The pipeline. The only component that needs torch |
 | `apps/eval` | GuitarSet evaluation harness |
@@ -120,9 +121,15 @@ curl -F file=@song.mp3 localhost:8000/jobs        # → 202 and a job id
 curl localhost:8000/jobs/<id>                      # stage and percent
 curl localhost:8000/jobs/<id>/document             # the tab document
 curl -L localhost:8000/jobs/<id>/audio/mix -o mix  # a redirect to storage
+curl -H 'content-type: application/json' \
+  -d '{"url": "https://youtu.be/kPdv44HtEoA"}' localhost:8000/jobs/from-url
 ```
 
-Uploading the same file again returns the same job, unless that job failed.
+Uploading the same file again returns the same job, unless that job failed;
+so does pasting the same video again, in any form of its link. Links are on
+under `make api` and `make worker`, and need [Deno](https://deno.com) 2.3 or
+later installed. Hosting must route `/features` to the api beside `/jobs` and
+`/health`.
 Uploads and stems stay in storage until you run `docker compose down -v`.
 
 ## Documentation
````

In `docs/CONVENTIONS.md`:

```diff
--- a/docs/CONVENTIONS.md
+++ b/docs/CONVENTIONS.md
@@ -24,6 +24,9 @@ Rules that outlive any one change. The reasoning lives in
 - `apps/api` imports nothing from the ML stack, and never `guitarvis_worker`:
   it enqueues the worker's entry point by name. This is enforced by
   `apps/api/tests/test_boundaries.py`, not by good intentions.
+- **yt-dlp runs only in `guitarvis_fetch.child`**, a process of its own
+  (ADR 0010). Nothing else imports `yt_dlp`, and a link failure's words come
+  from `guitarvis_fetch.catalog`, never from yt-dlp.
 - **Postgres is the record of a job; Redis carries its id** (ADR 0007). Every
   write after a job starts is conditional on the status it expects.
 
@@ -35,7 +38,7 @@ Rules that outlive any one change. The reasoning lives in
   document. They hold no playback state and never talk to sibling views. A
   new view is one more `onFrame` listener, not a refactor.
 - **The client and the api share an origin.** Client code uses relative
-  paths. `make web` proxies `/jobs` and `/health` to the api, and hosting must
+  paths. `make web` proxies `/jobs`, `/health` and `/features` to the api, and hosting must
   keep both behind one origin, or add CORS deliberately. Client routes live
   under `/songs/`, never `/jobs/`.
 - **Confidence rendering lives in one shared function**, used identically by
@@ -103,6 +106,9 @@ Where a rule matters, it is enforced by something that fails:
 | In-memory store twins behave like the real stores | shared contract suites in `packages/jobs/tests` |
 | The migration matches the table the code queries | `packages/jobs/tests/test_migrations.py` |
 | CI cannot pass by skipping the integration suite | `packages/jobs/tests/test_services_gate_ci.py` |
+| The api never imports yt-dlp | `apps/api/tests/test_boundaries.py` |
+| Every link failure has a catalog row, and no message carries yt-dlp's text | `packages/fetch/tests/test_catalog.py` |
+| Fetching from YouTube never gates CI | `packages/fetch/tests/test_smoke_never_gates_ci.py` |
 | Every failure reason has UI text | `Record<Reason, …>` in `web/src/api/messages.ts`, over the generated `web/src/types/api.ts` |
 
 Adding a rule to this document without a mechanism is worth doing, but expect
```

In `docs/specs/001-guitarvis-design/spec.md`:

```diff
--- a/docs/specs/001-guitarvis-design/spec.md
+++ b/docs/specs/001-guitarvis-design/spec.md
@@ -338,7 +338,9 @@ around this table.
 
 **Honest failure messages.** Failures carry a typed reason —
 `unsupported_format`, `no_guitar_detected`, `too_long`, `fetch_failed`,
-`internal` — which the UI maps to actionable text. The user needs to know
+`link_unusable`, `links_disabled`, `internal` — which the UI maps to
+actionable text (`link_unusable` and `links_disabled` arrived with
+[012](../012-url-ingestion/spec.md)). The user needs to know
 whether to try a different file, a different song, or come back later.
 
 **Ingestion guards.** Max duration (~10 min), max file size, format validation
@@ -346,7 +348,9 @@ before any expensive work begins, and per-IP concurrent-job limits.
 
 **Retries.** Stages are idempotent and intermediates are cached by content
 hash, so a retry resumes rather than re-running separation. Three attempts,
-then dead-letter with the failing stage recorded.
+then dead-letter with the failing stage recorded. A failure says whether it is
+retryable: by default only `internal`, plus a fetch that failed on the network
+(012).
 
 ## Testing
 
@@ -459,7 +463,7 @@ This spec covers the whole system; the implementation plan should not.
 3. **API + job queue** — wrap the pipeline in the service.
 4. **Web client: tab view + sync** — first real end-to-end experience.
 5. **2D fretboard**, then **3D guitar**.
-6. **URL ingestion.**
+6. **URL ingestion** — [012](../012-url-ingestion/spec.md).
 
 Phases 1–2 hold all the technical risk and should form the first
 implementation plan. The remainder is comparatively conventional work.
```

In `docs/specs/005-api-job-queue/spec.md`:

```diff
--- a/docs/specs/005-api-job-queue/spec.md
+++ b/docs/specs/005-api-job-queue/spec.md
@@ -98,7 +98,7 @@ pending work, not history.
 | Column | Type | Notes |
 |---|---|---|
 | `id` | uuid | primary key, public, unguessable |
-| `content_hash` | text | sha256 of the uploaded bytes |
+| `content_hash` | text | the dedupe key: sha256 of the uploaded bytes; for a link job (012), sha256 of `youtube:` and the video id |
 | `status` | text | `queued` · `running` · `succeeded` · `failed` |
 | `stage` | text, null | stage currently running |
 | `percent` | int | 0–100, overall |
@@ -108,7 +108,8 @@ pending work, not history.
 | `failed_stage` | text, null | where it broke |
 | `title` | text | upload's filename without extension |
 | `duration_sec` | float | from the upload-time probe |
-| `upload_key` | text | blob key of the original audio |
+| `upload_key` | text, null | blob key of the original audio; for a link job, null until the worker stores the download at `uploads/{sha256 of bytes}{ext}` |
+| `source_url` | text, null | a link job's canonical URL (012); null for an upload |
 | `stem_key` | text, null | blob key of the stem the tab came from |
 | `client_ip` | text | for the active-job limit |
 | `document` | jsonb, null | the tab document, once succeeded |
```

- [ ] **Step 2: Check and commit**

```bash
make lint typecheck test
git add .claude/skills/pipeline-stage/SKILL.md \
  CLAUDE.md \
  CONTRIBUTING.md \
  README.md \
  docs/CONVENTIONS.md \
  docs/specs/001-guitarvis-design/spec.md \
  docs/specs/005-api-job-queue/spec.md
git commit -m "docs: links in CLAUDE.md, the conventions, the skill and the specs they amend

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 18: The acceptance record, a template

`acceptance.md`, to be filled in by hand before the PR is merged, as 011's was: links in every form (with `t=` and `list=`), each refusal by row, the switch with a job queued, the network cut during a lookup, a stored m4a in Chrome, Firefox and Safari, and each case's log line, read by eye.

**Files:**
- Create: `docs/specs/012-url-ingestion/acceptance.md`

- [ ] **Step 1: Write the documents**

Create `docs/specs/012-url-ingestion/acceptance.md`:

````markdown
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
````

- [ ] **Step 2: Check and commit**

```bash
make lint typecheck test
git add docs/specs/012-url-ingestion/acceptance.md
git commit -m "docs(012): the acceptance record, to be filled in by hand

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make schema-check
```

Expected: the first command passes; after the commit, `schema-check` prints nothing and exits 0.

---

### Task 19: The whole gate, and the record

Nothing new: the full check on the finished branch, with every service up, and this plan's boxes ticked.

**Files:**
- Modify: `docs/specs/012-url-ingestion/plan.md` (checkboxes only)

- [ ] **Step 1: Start the services and migrate**

```bash
make services
make migrate
```

Expected: `database up to date: …` and `bucket ready: guitarvis at http://localhost:9000`. `make migrate` brings the dev database to revision `0002`. If Docker is not available on this machine, say so in the PR and rely on CI's run; do not report the integration suite as passed.

- [ ] **Step 2: Run the gate as CI runs it**

```bash
GUITARVIS_REQUIRE_SERVICES=1 make check
```

Expected: exit 0. ruff and ESLint clean, mypy clean across `PY_SOURCES` (now including `packages/fetch/src`, `packages/fetch/tests` and `packages/fetch/smoke`), about 1,120 Python tests passing with only the eval suite's `mir_eval` skips, about 490 web tests passing, and `schema-check` silent. Any other skip under `GUITARVIS_REQUIRE_SERVICES=1` is a failure.

- [ ] **Step 3: Check the boundaries by hand once**

```bash
uv run python -c "import sys, guitarvis_api.app; print('yt_dlp' in sys.modules)"
grep -rn "import yt_dlp\|from yt_dlp" --include=*.py apps packages | grep -v "packages/fetch/tests/"
git diff main --stat -- packages/core/src/guitarvis_core/tabdoc.py schema/tab-document.schema.json web/src/types/tabDocument.ts apps/worker/src/guitarvis_worker/caching.py
```

Expected: `False`; only `packages/fetch/src/guitarvis_fetch/child.py` in the grep; and no diff at all for the tab document and `CACHE_VERSION`.

- [ ] **Step 4: Optionally, the live check**

With Deno 2.3 or later installed: `make smoke-url`. Expected: `3 passed`, printing the lookup, a download of format 140, ffprobe's 37.06 s, and YouTube's messages for a private and a removed video. Compare those with `packages/fetch/tests/fixtures/youtube-messages.json`; if YouTube's wording has changed, update the fixture, re-run `uv run pytest packages/fetch/tests/test_classify.py`, and commit both. This is never a substitute for Step 2, nor gated by it.

- [ ] **Step 5: Tick this plan's checkboxes and commit**

```bash
git add docs/specs/012-url-ingestion/plan.md
git commit -m "docs: tick 012's plan checkboxes for Tasks 1–19

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

`acceptance.md` is filled in by a person, against real services and a browser, before the PR is merged.

---

## Coverage: the failure catalog, row by row

Every row of the spec's failure catalog, and the tests that pin it. Parametrized tests are named with the case that covers the row. A row's "Test" column in the spec (links, classify, fetcher, catalog, route, worker, store) maps to `test_links.py`, `test_classify.py` and `test_child.py`, `test_fetcher.py`, `test_catalog.py`, `test_links_route.py`, `test_link_jobs.py` and `test_job_store.py` / `test_migrations.py`. Every row is also pinned, reason, status, level and retry, by `test_each_kind_is_its_catalog_row` (Task 5), and every message by `test_no_message_carries_ytdlp_text` (Task 5).

| Row | Failure | Test | Task |
|---|---|---|---|
| R1 | Links switched off | `test_links_switched_off_are_refused_before_anything_is_read`; `test_switching_links_off_in_settings_alone_turns_the_route_off`; `test_features_says_whether_links_are_on[False]` | 10 |
| R1 | (client) | `UploadPage › the link field › is hidden when the api says links are off`; `… removes itself when the api says links were turned off` | 14 |
| R2 | Body not JSON; `url` missing, wrong type, over 2,048 | `test_a_body_that_is_not_a_link_in_json_is_refused[not-json, a-form, empty, no-url, misnamed, not-a-string, a-list, over-2048]` | 10 |
| R3 | Body over 16 KB | `test_a_body_over_16_kb_is_refused_before_it_is_read`; `test_the_upload_limit_still_guards_uploads_only` | 10 |
| R4 | Not a link | `test_each_refusal_has_its_kind` (the `NOT_A_LINK` cases); `test_a_link_at_the_limit_is_read_and_one_over_is_not` | 4 |
| R4 | (api) | `test_a_link_we_cannot_use_is_refused_without_a_lookup` (row `R4`) | 10 |
| R5 | Scheme not http(s) | `test_each_refusal_has_its_kind` (`BAD_SCHEME`: `javascript:`, `file:`, `ftp:`, `mailto:`, `data:`) | 4 |
| R5 | (api) | `test_a_link_we_cannot_use_is_refused_without_a_lookup` (row `R5`) | 10 |
| R6 | Not a supported site | `test_each_refusal_has_its_kind` (`UNSUPPORTED_SITE`: lookalike host, user info, port, IP literals, Cyrillic and `xn--` hosts) | 4 |
| R6 | (api) | `test_a_link_we_cannot_use_is_refused_without_a_lookup` (row `R6`) | 10 |
| R7 | Not one video | `test_each_refusal_has_its_kind` (`NOT_A_VIDEO`: playlist, channel, handle, search, clip, bad ids, two `v=`) | 4 |
| R7 | (api, and its log line) | `test_a_link_we_cannot_use_is_refused_without_a_lookup` (row `R7`); `test_a_refused_link_is_logged_by_its_kind_host_and_first_segment_only` | 10 |
| Q1 | Live job for this video | `test_the_same_video_in_any_form_is_the_same_job_without_a_lookup`; `test_a_link_whose_job_the_queue_lost_starts_a_fresh_one`; `test_the_dedupe_key_is_the_videos_identity` (Task 4); `test_a_link_job_end_to_end` (Task 12) | 10 |
| Q2 | Address at its limit | `test_an_address_at_its_limit_is_refused_without_a_lookup` | 10 |
| Q3 | Four lookups running | `test_a_fifth_lookup_at_once_is_turned_away_without_waiting`; `test_four_lookups_run_at_once_and_a_fifth_is_refused`; `test_a_lookup_slot_is_given_back_whatever_the_outcome` | 10 |
| L1 | Private | `test_each_recorded_message_classifies_as_its_kind[private-0]` (Task 7); `test_check_info_refuses_what_we_cannot_use` (`availability=private`, Task 6); `test_a_failed_lookup_answers_with_its_catalog_row` (row `L1`) | 7, 6, 10 |
| L2 | Removed | `test_each_recorded_message_classifies_as_its_kind[unavailable-*]` (Task 7); `test_a_failed_lookup_answers_with_its_catalog_row` (row `L2`) | 7, 10 |
| L3 | Region-locked | `test_ytdlp_exception_types_classify` (`GeoRestrictedError`); `…[geo_restricted-*]` fixture (Task 7); route row `L3` | 7, 10 |
| L4 | Age-restricted | `…[age_restricted-1]` fixture (Task 7); `test_check_info_refuses_what_we_cannot_use` (`needs_auth`, Task 6); route row `L4` | 7, 6, 10 |
| L5 | Members-only or paid | `…[members_only-*]` fixtures and `test_a_trailer_in_place_of_a_paid_video_is_members_only` (Task 7); `check_info` (`subscriber_only`, `premium_only`, Task 6); route row `L5` | 7, 6, 10 |
| L6 | Live now | `test_check_info_refuses_what_we_cannot_use` (`is_live`, Task 6); `test_a_live_stream_is_refused_before_formats_are_chosen` (Task 7); `test_metadata_we_cannot_use_is_refused_before_queueing` (row `L6`) | 6, 7, 10 |
| L7 | Upcoming | `…[upcoming-*]` fixtures (Task 7); `check_info` (`is_upcoming`, Task 6); `test_metadata_we_cannot_use_is_refused_before_queueing` (row `L7`) | 7, 6, 10 |
| L8 | Just ended | `check_info` (`post_live`, Task 6); `test_metadata_we_cannot_use_is_refused_before_queueing` (row `L8`) | 6, 10 |
| L9 | No duration | `check_info` (`None`, `0`, `NaN`, Task 6); `test_metadata_we_cannot_use_is_refused_before_queueing` (row `L9`) | 6, 10 |
| L10 | Over ten minutes | `check_info` (721 s) and `test_too_long_carries_the_length_for_its_message` (Task 6); `test_too_long_names_the_videos_length_and_the_limit` (Task 5); route row `L10` | 6, 5, 10 |
| L11 | No audio-only format | `test_a_format_error_is_no_audio_unless_challenges_failed`; `…[no_audio-*]`; `test_a_format_error_is_left_for_the_classifier` (Task 7); route row `L11` | 7, 10 |
| L12 | Rate-limited, 429, bot check | `test_ytdlp_exception_types_classify` (HTTP 429); `…[rate_limited-*]` (soft limit, IP blocked, captcha, bot check both apostrophes) (Task 7); route row `L12` | 7, 10 |
| L13 | Network | `test_ytdlp_exception_types_classify` (503, 500, DNS, refused, TLS, certificate, proxy, timeout) (Task 7); route row `L13` | 7, 10 |
| L14 | Lookup deadline | `test_a_lookup_past_its_deadline_is_killed_with_its_process_group` (Task 6); route row `L14` | 6, 10 |
| L15 | Extractor broken | `test_a_format_error_is_no_audio_unless_challenges_failed`; `…[extractor_broken-*]` (Unable to extract, Unsupported URL, No suitable extractor, Failed to extract any player response, format error with challenge warnings) (Task 7); route row `L15` | 7, 10 |
| L16 | Misconfigured | `test_without_a_javascript_runtime_the_child_says_misconfigured`; `test_when_yt_dlp_will_not_import_the_child_says_misconfigured` (Task 7); `test_find_deno_*` (Task 6); route row `L16` | 7, 6, 10 |
| L17 | Unrecognised error | `test_ytdlp_exception_types_classify` (404, `RuntimeError`); `…[unknown-*]` (Task 7); `test_a_kind_this_build_does_not_know_is_unknown` (Task 6); route row `L17` | 7, 6, 10 |
| L18 | Child crashed, silent, garbage | `test_garbage_on_stdout_is_a_crash_at_once`; `test_a_child_that_crashes_is_a_crash_with_its_exit_code_and_tail`; `test_a_child_that_exits_without_an_answer_is_a_crash`; `test_a_result_missing_a_field_is_a_crash` (Task 6); route row `L18`; `test_an_internal_lookup_failure_says_what_every_internal_failure_says` | 6, 10 |
| E1 | Same video at the same moment | `test_the_same_video_again_is_the_same_job` (both stores, Task 8); `test_the_same_video_created_at_the_same_moment_returns_the_winner` | 8, 10 |
| E2 | Limit passed in a race | `test_an_address_that_races_past_the_count_is_refused_when_created` | 10 |
| E3 | Enqueue raises | `test_a_queue_that_refuses_the_job_fails_the_row` | 10 |
| E4 | Postgres unreachable | `test_a_store_that_cannot_be_reached_is_our_failure` (and 005's `test_an_unexpected_error_uses_the_error_body_and_hides_the_detail`) | 10 |
| W1 | Links off, audio not stored | `test_a_link_job_with_no_stored_audio_fails_when_nothing_fetches` (Task 8); `test_links_off_fails_a_link_job_with_no_stored_audio`; `test_links_off_still_runs_a_link_job_whose_download_is_stored` | 8, 11 |
| W2 | The video changed in the queue | `test_a_video_that_changed_in_the_queue_fails_with_its_own_reason[L1…L11]` (Task 11); `test_a_video_that_changed_in_the_queue_is_refused_before_downloading` (Task 7) | 11, 7 |
| D1 | Network | `test_a_download_that_may_pass_is_retried` and `test_the_last_attempt_keeps_the_downloads_own_reason` (row `D1`) | 11 |
| D2 | Download deadline | the same two (row `D2`); `test_a_download_past_its_deadline_is_a_download_timeout` (Task 6) | 11, 6 |
| D3 | Rate-limited | `test_a_download_that_will_not_pass_soon_is_not_retried` (row `D3`) | 11 |
| D4 | Extractor broken or misconfigured | `test_a_download_that_will_not_pass_soon_is_not_retried` (both `D4` rows) | 11 |
| D5 | Media URL refused | `test_a_download_that_will_not_pass_soon_is_not_retried` (row `D5`); `test_a_media_url_we_did_not_expect_is_refused_before_connecting` (http, HLS, other hosts, lookalike, private, loopback, metadata and ULA addresses, two formats) (Task 7) | 11, 7 |
| D6 | Over the size cap | `test_a_download_that_will_not_pass_soon_is_not_retried` (row `D6`); `test_a_format_larger_than_the_cap_is_refused_before_downloading`, `test_a_file_larger_than_the_cap_on_disk_is_refused`, `test_yt_dlps_quiet_size_cap_is_too_large_not_empty`, `test_the_hook_stops_a_download_past_the_cap_with_no_length` (Task 7) | 11, 7 |
| D7 | No file, or empty | `test_a_download_that_will_not_pass_soon_is_not_retried` (row `D7`); `test_a_download_that_leaves_no_file_or_an_empty_one_is_unusable` (Task 7) | 11, 7 |
| D8 | Disk full, local I/O | the retried pair (row `D8`); `test_ytdlp_exception_types_classify` (`UnavailableVideoError`, `OSError`) (Task 7) | 11, 7 |
| D9 | Child crashed | the retried pair (row `D9`); the L18 tests (Task 6) | 11, 6 |
| D10 | Unrecognised error | the retried pair (row `D10`); `test_ytdlp_text_reaches_the_log_and_never_the_row` | 11 |
| P1 | ffprobe cannot read it | `test_audio_ffprobe_cannot_read_is_unusable`; `test_audio_with_no_length_is_unusable` | 11 |
| P2 | ffprobe says over ten minutes | `test_audio_over_ten_minutes_by_ffprobe_is_too_long` | 11 |
| P3 | ffprobe not installed | `test_a_missing_ffprobe_after_a_download_is_retried_then_internal` | 11 |
| S1 | Storing the download fails | `test_a_failed_store_of_the_download_is_retried_and_downloads_again` | 11 |
| S2 | Recording the key fails | `test_a_failed_attach_is_retried_then_internal` | 11 |
| S3 | Row no longer running | `test_a_download_for_a_row_failed_meanwhile_is_dropped` (Task 11); `test_attach_upload_changes_nothing_once_the_row_is_not_running` (both stores, Task 8) | 11, 8 |
| G1 | Mix before the audio is stored | `test_the_mix_of_a_link_job_is_not_ready_until_its_download_is_stored` (Task 8); `test_a_link_jobs_mix_is_not_ready_until_the_worker_stores_it` (Task 10); `test_a_link_job_end_to_end` (Task 12) | 8, 10, 12 |

The rule across rows — yt-dlp's text in the log, never in a response or a row — is pinned by `test_a_fetch_errors_message_is_the_catalogs_never_its_detail` (Task 6), `test_ytdlp_text_reaches_the_log_and_never_the_body` (Task 10) and `test_ytdlp_text_reaches_the_log_and_never_the_row` (Task 11). The log line's shape and level by `test_a_failure_is_one_line_at_its_catalog_level`, `test_an_error_level_failure_adds_the_childs_stderr` and `test_a_success_is_logged_with_its_format` (Task 6), `test_a_successful_lookup_is_logged` (Task 10) and `test_a_successful_download_is_logged_with_its_format` (Task 11).
