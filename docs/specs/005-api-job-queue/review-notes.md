# API and Job Queue: Carried Findings

These findings come from the per-task reviews and the whole-branch review of 005.
None of them blocks the merge. Each one was deferred on purpose, not forgotten.
They are kept here because the review's own ledger lives in `.superpowers/`,
which is gitignored and will not survive the branch. Phase 4 (web client) should
read this file before it starts.

## Behaviour worth fixing

- **Lost jobs can lock an IP out.** `count_active` counts `queued` rows whose RQ
  job is lost or terminal until something reconciles them. Only reads reconcile,
  and only the row being read. A user can therefore get 429 until those exact
  jobs are polled or their files re-uploaded. The 429 path reads the rows it
  counts, so it could reconcile them first. That is still a read, not a reaper.
  **Resolved in 006:** at the limit, POST /jobs reconciles every row it counted
  (JobStore.active_jobs) and counts again.
- **Hung storage stalls the api.** The S3 client uses a 60 s read timeout and
  standard retries. Storage that accepts connections and then hangs can hold
  `/health`, and any blob call, for minutes. Give `ping` its own short,
  single-attempt client.
- **`UploadSizeLimit` breaks under a root path.** It matches
  `scope["path"] == "/jobs"` exactly. Under `uvicorn --root-path` the route
  still matches but the middleware does not, so Starlette spools the whole body
  before the route refuses it. Compare against the path minus `root_path`. This
  matters once there is hosting.
- **Dedupe ignores `CACHE_VERSION`.** `find_live` returns any succeeded job
  for the hash, so a bump never reaches audio that already succeeded: a
  re-upload gets the old document. A fix needs the version on the row, a
  dedupe index that includes it, and the api knowing the current version
  without importing the worker. That is a design decision for a later spec,
  and it matters from the first bump after launch.
- **A row can say running while RQ's retry waits.** When RQ kills a horse it
  schedules the retry itself, so the row keeps its last stage and percent
  until the retry starts. Phase 4 should not read a stalled percent as a hang.
  **Handled in 006:** the song page never decides a job has hung; it keeps
  polling, and shows what the api reports.
- **The worker runs on after its row is finished.** `_ProgressWriter` only
  logs when `set_progress` returns False. Reconciliation cannot cause this
  today: the job timeout (30 min) ends a run before its row is stale enough
  to fail (35 min). Only clock skew between hosts, or a duplicate delivery,
  could. Revisit if either turns up.
- **A job timeout during a file-error `fail` leaves the row running.** The
  `except PipelineError` branch's write is not covered by the `JobTimedOut`
  handler. The window is one UPDATE at the thirtieth minute; RQ retries, or
  on the last attempt reconciliation fails the row later.
- **Postgres timestamps are not pinned to UTC.** `PostgresJobStore` returns
  `timestamptz` in the session time zone. `JobView` normalises to UTC, so
  clients are unaffected. Pinning `-c timezone=UTC` in `from_url` would restore
  parity with the in-memory twin.

## Twin and real-store divergences (no live effect today)

- `InMemoryJobStore.find_live()` and the dedupe path of `create()` return the
  stored `Job`, so its `document` dict is shared with the store. `get()`
  copies.
- `S3BlobStore.get_file` creates the parent directory before it discovers a
  missing key. The twin creates nothing.
- `NoSuchBucket` counts as a missing key in `exists`/`get_*`. A misconfigured
  bucket therefore reads as `BlobNotFound`; it still surfaces through
  `/health`.
- `set_progress(percent=101)` violates a Postgres CHECK but is accepted in
  memory. The pipeline's reporter clamps, so it never happens.

## Test gaps

- `compare_metadata` cannot see drift in the partial-index predicate or the
  CHECK constraints between `postgres.py` and the migration.
- No test covers any of these:
  - the Demucs child *not* being killed on a normal run;
  - the CLI's new `separation 0` / `fretboard 80` progress lines;
  - `CachedAnalyzer` with a corrupt entry or a failing store;
  - `CachedSeparator` with a non-not-found `get_file` error;
  - `run_job` with a current job whose `retries_left` is `None`/0;
  - the route-level same-file race branch in `POST /jobs`;
  - `ping`/`enqueue` against an unreachable S3 or Redis;
  - the 405 → `not_found` mapping.
- The contract suite does not check `find_live` against running or succeeded
  rows, or `mark_running` against a failed row.
- Some tests are weaker than they look:
  - `test_simultaneous_uploads_of_one_file_make_one_job` overlaps only by luck;
    a `threading.Barrier` would make the race reliable.
  - The e2e dedupe step proves "no new work" only indirectly. Assert the queue
    count.
  - The CI gate test is a text match over the workflow. Parsing the YAML would
    be stricter.

## Hygiene

- RQ's `SimpleWorker.work()` installs SIGINT/SIGTERM handlers that it never
  restores. The e2e test and the real-worker timeout test leave them installed
  in the pytest process. Save and restore them in the fixtures.
- `separation._demucs` never closes `process.stdout`. On the exception path one
  pipe fd stays open while the traceback is retained (`ResourceWarning`).
- In `caching.py`, serialisation runs before `_store`'s guard, so a
  serialisation error would fail the stage rather than count as a miss.
- The runner ignores `False` from its conditional `fail`/`requeue`. The spec
  says the worker logs and drops a late result.
- Some log output is noisy:
  - every unexpected 500 is logged twice, by the handler and by uvicorn;
  - a client disconnecting mid-upload logs an ERROR traceback.
- Some small inconsistencies:
  - real timestamps carry microseconds, while the spec's example shows whole
    seconds;
  - `api_fixture.make_api(store=...)` keeps the store's own clock;
  - `migrate.py`'s `%`-escaping is untested;
  - under `GUITARVIS_REQUIRE_SERVICES=1` a missing service shows as a fixture
    ERROR with SQLAlchemy's long text;
  - `.gitignore` still lists `.minio/`.
- Some wording is out of date:
  - `pipeline-stage` SKILL.md says a cache error is "never a stage failure",
    but the separation stem is the exception;
  - the `_Reporter` docstring doesn't say that stage-start events bypass the
    "must raise the percent" rule;
  - `timeouts.py`'s docstring is wrong about callbacks, which none are
    registered for;
  - CLAUDE.md's "Only `compose.yaml` names the server" is narrower than the
    global constraint (compose and docs).
- Two cosmetic items:
  - `check_duration` formats a sub-minute limit as "0 minutes";
  - `tail[-_TAIL_CHARS:]` is a redundant slice.

Test-helper duplication grew in this phase. It is tracked in
[003's review notes](../003-pipeline-skeleton/review-notes.md).
