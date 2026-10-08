# API and Job Queue — Design

**Date:** 2026-10-08
**Status:** Approved design, pre-implementation
**Amended:** 2026-10-08 — RustFS replaces MinIO, whose community edition is archived and no longer published as an image. The bucket is created by `make migrate` through boto3 rather than by a one-shot `mc` container.
**Parent spec:** [001-guitarvis-design](../001-guitarvis-design/spec.md)
**Builds on:** [004-fretboard-mapper](../004-fretboard-mapper/spec.md), and the
two findings in [003's review notes](../003-pipeline-skeleton/review-notes.md)
that name this phase

## Purpose

Build phase 3: wrap the pipeline in a service. A client uploads audio, gets a
job id back at once, polls for stage and percent, and fetches the finished tab
document and the audio to play it against.

After 004 the pipeline is complete but reachable only from a CLI on the machine
that holds the file. Phase 4's web client needs an HTTP surface, and the parent
spec's architecture — a thin `api`, a `worker` reachable only through the
queue, Postgres, Redis and S3-compatible storage — is what this phase stands
up. Every later client, web or native, talks to what is built here.

The success conditions:

1. With `make services`, `make migrate`, `make api` and `make worker` running,
   `curl -F file=@song.mp3 localhost:8000/jobs` returns a job id, `GET
   /jobs/{id}` advances through the four stages with a percent that moves
   during separation, and `GET /jobs/{id}/document` returns a tab document that
   validates as `TabDocument`.
2. Uploading the same file again returns the same job without new work.
3. A job whose worker crashes after separation, then succeeds on retry, does
   not run separation twice.
4. `make check` runs the integration suite against real Postgres, Redis and
   RustFS in CI, and cannot pass by skipping it.

## Scope

**In:** a shared `guitarvis_jobs` package (job store, blob store, queue,
settings); the `jobs` table and its first Alembic migration; the HTTP routes
below; the worker's RQ entry point and `guitarvis-worker serve`; content-hash
dedupe; per-stage caching so a retry resumes; per-IP active-job limits; live
progress during separation; read-time reconciliation of jobs the queue lost;
`compose.yaml` for the three services; CI running the integration suite; ADR
0007. Two 003 findings close here because their files change anyway:
`DemucsSeparator.work_dir` becomes required, and progress stops looking frozen
during separation. Two smaller ones ride along for the same reason: the CLI's
output write is guarded against any exception, and `--stems-dir X` writes to
`X` rather than `X/stems`.

**Out:** Dockerfiles for the api and worker, and any hosting (open decision
12); a retention policy for stored audio (open decision 13 — see
*Consequences*); auth and accounts (open decision 11); URL ingestion (phase 6);
publishing OpenAPI-derived types to `web/` (phase 4 decides); choosing a tuning
per job — the API processes standard tuning only; cancelling a job;
WebSockets. No `tabdoc.py` change, so no schema regeneration.

## Approach

### Components

```
           ┌──────────── guitarvis_jobs ────────────┐
  api ───▶ │ JobStore   BlobStore   JobQueue  Settings│ ◀─── worker
           └──┬────────────┬───────────┬─────────────┘
          Postgres      RustFS       Redis (RQ)
```

**`packages/jobs` (`guitarvis_jobs`)** is a new workspace member that both the
api and the worker depend on. It cannot live in `core`, which would drag
SQLAlchemy and boto3 into the eval package and every client-facing type; and
the api cannot import the worker, which the parent spec says is reachable only
through the queue. It imports nothing from the ML stack.

- **`JobStore`** — a Protocol with two implementations: `PostgresJobStore`
  (SQLAlchemy Core over psycopg 3, schema owned by Alembic) and
  `InMemoryJobStore`. One contract test suite runs against both, so the fake
  cannot quietly drift from the database the system actually runs on.
- **`BlobStore`** — a Protocol: put and get a file or bytes, check existence,
  presign a GET. `S3BlobStore` (boto3; RustFS locally, any S3 later) and
  `InMemoryBlobStore`, under the same shared contract suite.
- **`JobQueue`** — a thin wrapper over RQ. It enqueues by dotted path,
  `"guitarvis_worker.runner.run_job"`, so the api never imports the function
  it schedules. The RQ job id *is* the GuitarVis job id. Every job carries
  `Retry(max=2, interval=[10, 60])` — three attempts in all, as the parent
  spec asks — and a timeout of `GUITARVIS_JOB_TIMEOUT_SEC` (default 1800). A
  worker test imports the dotted path, so renaming `run_job` fails CI rather
  than every job.
- **`Settings`** — a frozen stdlib dataclass built from `GUITARVIS_*`
  environment variables. Defaults match `compose.yaml`, so local development
  needs no env file.

### Postgres is the record; Redis carries ids

ADR 0007 records this. The job's state lives in one `jobs` table; RQ is told
only "run job `<uuid>`". A client never reads Redis, and losing Redis loses
pending work, not history.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key, public, unguessable |
| `content_hash` | text | sha256 of the uploaded bytes |
| `status` | text | `queued` · `running` · `succeeded` · `failed` |
| `stage` | text, null | stage currently running |
| `percent` | int | 0–100, overall |
| `attempts` | int | attempts started |
| `failure_reason` | text, null | a `FailureReason` value |
| `failure_message` | text, null | user-facing text |
| `failed_stage` | text, null | where it broke |
| `title` | text | upload's filename without extension |
| `duration_sec` | float | from the upload-time probe |
| `upload_key` | text | blob key of the original audio |
| `stem_key` | text, null | blob key of the stem the tab came from |
| `client_ip` | text | for the active-job limit |
| `document` | jsonb, null | the tab document, once succeeded |
| `created_at`, `updated_at` | timestamptz | `updated_at` doubles as heartbeat |

Indexes: a partial unique index on `content_hash WHERE status <> 'failed'`,
which is the dedupe rule; and one on `(client_ip, status)` for the limit.

Tab documents live in Postgres, as the parent spec places them, not in object
storage: they are small, they are what every client fetches, and `jsonb` keeps
them queryable later.

### Object storage layout

```
uploads/{hash}{ext}                                original audio
cache/v{N}/{hash}/separation/stem.wav              stage 1 output
cache/v{N}/{hash}/separation/result.json           which stem, warnings
cache/v{N}/{hash}/transcription.json               stage 2 output
cache/v{N}/{hash}/structure.json                   stage 3 output
```

`{ext}` is the upload's lowercased suffix when it is one to five alphanumeric
characters, else nothing; ffprobe and Demucs sniff content, so it is a
courtesy to a human browsing the bucket. `N` is `CACHE_VERSION`, one constant
in the worker, bumped by hand whenever a stage's output for the same input
would change. Stage 4 is fast and deterministic and is not cached.

### Upload: `POST /jobs`

Multipart, one field, `file`. In order, cheapest check first:

1. Stream the body to a temporary file, hashing and counting as it goes. Past
   `GUITARVIS_MAX_UPLOAD_MB` (default 150 — a ten-minute 16-bit stereo WAV is
   about 106 MB) the upload is abandoned: **413 `too_large`**.
2. Probe with ffprobe. Unreadable → **422 `unsupported_format`**; longer than
   `MAX_DURATION_SEC` → **422 `too_long`**. Doing this in the api, not only
   the worker, means a user learns their file is wrong in a second rather than
   after their job waits out a queue. `probe_duration` and `MAX_DURATION_SEC`
   therefore move from `guitarvis_worker.ingest` to a new stdlib-only
   `guitarvis_core.audio`, and the worker's `UploadSource` keeps calling them
   — a second check is cheap and the worker must not trust its caller.
3. Look up the hash. A `queued`, `running` or `succeeded` job with this hash
   is returned with **200**. It does not count against the limit below: it
   starts no work.
4. Count this IP's `queued` and `running` jobs. At
   `GUITARVIS_MAX_ACTIVE_JOBS_PER_IP` (default 2): **429 `too_many_jobs`**.
   The IP is `request.client.host`. Behind a proxy, uvicorn's
   `--forwarded-allow-ips` rewrites it from `X-Forwarded-For`; the api parses
   no proxy headers itself.
5. Put the upload blob unless it exists, insert the row as `queued` — `ON
   CONFLICT` on the dedupe index returns the winner of a same-file race with
   **200** — and enqueue. If enqueueing raises, the row is marked
   `failed/internal` and the response is **503**. Otherwise **202**, with a
   `Location` header.

### The worker: `run_job(job_id)`

`guitarvis_worker.runner.run_job` is a thin RQ adapter: it reads
`retries_left` from RQ's current job and calls `process_job(job_id, deps,
retries_left)`, which tests call directly with in-memory stores and stub
stages.

1. Load the row. If it is already `succeeded` or `failed`, return: RQ
   delivers at least once, and a second delivery must be harmless.
2. Mark it `running`, increment `attempts`.
3. Download the upload into a temporary directory; run `UploadSource.fetch()`
   on it; replace the title with the row's.
4. Build the stages, each wrapped by its cache decorator (below).
   `DemucsSeparator` gets the temporary directory as its `work_dir`, which is
   now a required argument — the 003 finding warned that this second caller
   would otherwise leave stems beside every downloaded file.
5. `run_pipeline(..., progress=..., audio_url="/jobs/{id}/audio/mix")`.
   `run_pipeline` gains the `audio_url` keyword; the CLI keeps its `file://`
   URI by not passing it.
6. Store the document and `stem_key`; mark `succeeded`, `stage` null, percent
   100.

**Failure.**

- **`PipelineError`** — `no_guitar_detected`, `unsupported_format`,
  `too_long`, or `internal` from the fretboard invariant — is deterministic;
  running it again gives the same answer. Mark `failed` with its reason,
  message and current stage, and return normally so RQ does not retry.
- **Any other exception** — object storage or Postgres unreachable,
  `JobTimeoutException`, a bug — with retries left: set the row back to
  `queued` with `stage` null and `percent` 0, keeping `attempts`, and re-raise
  so RQ schedules the retry. The cache means the retry resumes after the last
  finished stage.
- **The same on the final attempt**: mark `failed/internal`, message "Something
  went wrong on our side. Try again later.", `failed_stage` recorded; re-raise
  so RQ files it in its `FailedJobRegistry` with the traceback. That registry
  is the dead-letter queue; the row is what the user sees.

Every write the worker makes after step 2 is conditional on the row still
being `running`. If reconciliation (below) has already failed it, the write
changes nothing and the worker logs and drops its result: a second row for the
same hash may exist by then, and a late `succeeded` would collide with it on
the dedupe index.

`guitarvis-worker serve` runs an RQ `Worker` on the `jobs` queue with its
scheduler enabled (retry intervals need it).

### Stage caching

Three decorators — `CachedSeparator`, `CachedTranscriber`, `CachedAnalyzer` —
each wrap a real stage and implement that stage's own Protocol, so
`run_pipeline` and the stages change not at all for caching. Each is given the
blob store and the content hash.

- **Hit:** restore the output (for separation, download the stem into the
  work directory) and return it without calling the inner stage.
- **Miss:** call the inner stage. If it returns, store the output, then return
  it. If it raises, store nothing and let the exception through — the
  pipeline degrades exactly as it does today, and the next attempt tries the
  stage again rather than replaying a failure.

Serialization is JSON: `NoteEvent` lists as arrays of objects;
`StructureResult` through the pydantic models it already holds; separation as
`{"stem": "guitar" | "other", "warnings": [...]}` beside the WAV.

### Progress

Today `StageProgress` fires once per stage, *after* it finishes. A job status
needs to say what is running now, and separation — minutes on CPU — needs to
move while it runs.

- `StageProgress(stage, percent)` now names the stage **running**. The
  pipeline emits each stage's start — separation 0, transcription 40,
  structure 65, fretboard 80 — and `fretboard 100` when stage 4 returns. The
  CLI prints the same events.
- `Separator.isolate` gains an optional keyword, `progress:
  Callable[[float], None] | None = None`, reporting the fraction of separation
  done. This changes a stage Protocol, so every separator test double changes
  with it and the `pipeline-stage` skill's interface table is updated.
- `DemucsSeparator` replaces `subprocess.run` with `Popen`, merging stderr
  into stdout and reading it as it arrives. Demucs draws a tqdm bar; each
  `NN%|` it prints is a progress point. The 6-stem pass maps to 0–0.75 of the
  stage and the fallback pass, when it runs, to 0.75–1, so progress never
  runs backwards. The last 500 characters are kept for the failure message, as
  now.
- The pipeline maps the fraction onto 0–40%, drops any update that would not
  raise the whole-number percent, and so guarantees monotonic progress
  whatever a separator reports. The worker writes the row only on those
  updates — at most about a hundred writes per job, and each refreshes
  `updated_at`.

### Reconciliation on read

Two stores can disagree, and `GET /jobs/{id}` repairs the two ways they can:

- A row `queued` for more than 60 seconds whose RQ job does not exist — the
  api died between insert and enqueue, or Redis lost its data. The grace
  period covers the gap between those two steps in a live request.
- A row `running` whose `updated_at` is older than the job timeout plus five
  minutes — the worker was killed outright (out of memory, `SIGKILL`) and
  never ran its `except`. RQ's own timeout raises inside the job, so the
  ordinary failure path handles every timeout it can see.

Either is marked `failed/internal` with a conditional `UPDATE ... WHERE
status = <what was read> AND updated_at = <what was read>`, so a worker that
was merely slow and writes first wins. No background reaper is needed; a job
nobody looks at can stay wrong until somebody does.

### HTTP surface

| Route | Answer |
|---|---|
| `POST /jobs` | 202 new · 200 existing · 413 · 422 · 429 · 503 |
| `GET /jobs/{id}` | the job (below) · 404 |
| `GET /jobs/{id}/document` | the tab document · 404 · 409 `not_ready` |
| `GET /jobs/{id}/audio/mix` | 307 to a presigned URL of the upload · 404 |
| `GET /jobs/{id}/audio/guitar` | 307 to a presigned URL of the stem · 404 · 409 `not_ready` |
| `GET /health` | 200, or 503 naming which of Postgres, Redis, object storage did not answer |

A job:

```jsonc
{
  "id": "5f0c…",
  "status": "running",            // queued | running | succeeded | failed
  "stage": "separation",          // null unless running
  "percent": 23,
  "attempts": 1,
  "title": "song",
  "duration_sec": 214.3,
  "failure": null,                // { "reason", "message", "stage" } when failed
  "created_at": "2026-10-08T12:00:00Z",
  "updated_at": "2026-10-08T12:00:41Z"
}
```

Every error body is `{"error": {"reason": "...", "message": "..."}}`.
`reason` uses the five `FailureReason` values plus four the HTTP layer alone
can produce — `too_large`, `too_many_jobs`, `not_found`, `not_ready` — so a
client maps one vocabulary to text. A malformed job id is `not_found`, not a
validation error.

Audio is a redirect to a presigned object-storage URL rather than bytes
streamed through the api: S3 storage already answers `Range` requests, which
seeking needs, and the api stays thin. URLs are signed against
`GUITARVIS_S3_PUBLIC_ENDPOINT` so a browser can reach them, and live fifteen
minutes.

`source.audio_url` in a document the api produced is the relative path
`/jobs/{id}/audio/mix`, resolved against the api's base URL. The field is
already a string, so nothing in `tabdoc.py` changes.

All routes are plain `def`: their work is blocking I/O, which FastAPI runs in
its threadpool. `create_app(...)` takes the store, blob store and queue; the
module-level `app` builds real ones from `Settings` in its lifespan, so
importing `guitarvis_api.app` opens no connection and the boundary test keeps
working.

### Boundaries

`apps/api/tests/test_boundaries.py` adds `guitarvis_worker` to the forbidden
roots, in both the AST scan and the `sys.modules` probe. The probe imports the
api app, and the app imports `guitarvis_jobs`, so the probe also proves the
shared package pulls in nothing from the ML stack.

### Running it

`compose.yaml` at the root runs `postgres:16`, `redis:7` and RustFS
(`rustfs/rustfs:1.0.1`), with a Postgres init script that also creates
`guitarvis_test`; `make migrate` creates the bucket. Healthchecks on each, so
`docker compose up --wait` returns when they are ready. New Make targets:
`services` (`docker compose up -d --wait`), `migrate` (Alembic upgrade plus
bucket creation), `api` (uvicorn, reload on), `worker` (`guitarvis-worker
serve`). The api and worker run on the host, which is what makes `--extra ml`
and `--device cuda` work as they do for the CLI.

### Testing

**Always run, no services:**

- api routes through `TestClient` with in-memory stores and a recording fake
  queue: each status code above, dedupe, the IP limit, reconciliation, the
  error body shape.
- `process_job` with in-memory stores and stub stages: success; each
  `PipelineError`; another exception with retries left, then on the final
  attempt; a second delivery of a finished job; a retry that finds separation
  cached and never calls the separator.
- Each cache decorator: hit, miss, and a raising inner stage that leaves
  nothing cached.
- Demucs progress parsing, fed recorded tqdm output, including a bar split
  across reads.
- Pipeline progress: stage starts in order, monotonic whatever the separator
  reports.
- The store and blob contract suites, against the in-memory implementations.

**Integration, `@requires_services`:** the same contract suites against
Postgres and RustFS; RQ enqueue and fetch against Redis; and one end-to-end
path — `POST /jobs` through `TestClient` on real stores, an in-process RQ
`SimpleWorker` in burst mode with the stage factory patched to stubs, then
`GET` the job, the document, and the audio redirect. They use the
`guitarvis_test` database, Redis database 15 and a `guitarvis-test` bucket,
and clean up after each test.

Locally these skip when the services are down, as ingest tests skip without
ffprobe. With `GUITARVIS_REQUIRE_SERVICES=1` a missing service is a failure,
not a skip. CI runs `docker compose up -d --wait` from the same
`compose.yaml`, then `make migrate`, then `make check` with that variable set.
`make check` remains the only gate.

No test loads a model. ffprobe-dependent tests keep their existing skip.

## Rejected alternatives

**Postgres as the queue** (`SELECT ... FOR UPDATE SKIP LOCKED`). One service
fewer, and creating a job and queueing it would be one transaction, so the
reconciliation above would be unnecessary. Rejected in favour of the
architecture the parent spec approved; the dual-write it costs is contained by
keeping Redis to ids and repairing on read. Worth revisiting if
reconciliation turns out to fire in practice.

**SQLite and a filesystem.** Nothing to run but `make`. Leaves the system
unproven on the stores it is designed for, and SQLite's write locking caps
concurrent workers.

**Celery.** Routing, scheduling and many brokers, none of which one job type
needs, at a real cost in configuration. **arq.** Async-native, but the
pipeline is blocking CPU work, so every job would run in an executor anyway.

**Streaming audio through the api.** Full control, but `Range` support done by
hand, and every byte of playback through a process meant to stay thin.

**Checking duration only in the worker.** Keeps ffprobe out of the api, but a
user with a bad file waits for a queue slot to be told so.

**Storing documents in object storage.** Cheaper bytes, but a second fetch for
the one thing every client wants, and against the parent spec.

**A background reaper for lost jobs.** Fixes jobs nobody is looking at, but is
another process to run and monitor. Repairing on read fixes every job anyone
asks about, which is every job that matters to a user.

## Consequences

The pipeline is reachable over HTTP, and phase 4 can build against a real
surface rather than a fixture.

**Audio now persists.** Uploads and stems stay in object storage indefinitely.
That is fine for a local demo and is exactly the takedown surface open decision 13
describes; a retention policy is needed before public users, and this spec
does not supply one.

**CI needs Docker.** `make check` in CI depends on three containers starting.
Locally, `make check` without `make services` skips the integration suite and
can pass where CI fails; running `make services` first closes that gap.

Changing `Separator.isolate` touches the protocol, `DemucsSeparator`, the
orchestrator, and every separator test double — done once, while there is one
implementation.

`apps/api` gains a runtime dependency on `ffprobe`, as the worker already has.

## Risks

**Two stores disagreeing** is the most fragile part of this design.
Reconciliation covers the two failure modes identified; a third — say, a row
`queued` while RQ holds the job in a registry nobody drains — would show up as
a job that never moves. The end-to-end test and `attempts` in the job body are
how it would be noticed.

**Demucs's progress output is not an API.** If a release changes the bar
format, parsing finds nothing and progress jumps 0 → 40% as it does today. It
never fails a job.

**Stale cache entries.** A stage change that alters output without a
`CACHE_VERSION` bump serves old results for audio processed before it. The
constant sits next to the decorators with a comment saying when to bump it;
nothing enforces it.

**Stem size.** About 40 MB per four-minute song, uncompressed. Disk, not
correctness, but it compounds the retention question.

**The IP limit is approximate.** Two simultaneous uploads from one address can
both pass the count and land one job over the limit. Accepted: it guards
against abuse, not accounting.
