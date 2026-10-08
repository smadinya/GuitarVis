# API and Job Queue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the pipeline in a service: a client uploads audio to `POST /jobs`, polls `GET /jobs/{id}` for stage and a percent that moves during separation, and fetches the finished tab document and presigned audio. Retries resume from cached stages.

**Architecture:** A new workspace member, `packages/jobs` (`guitarvis_jobs`), holds what the api and the worker share: the job record and its `JobStore` (Postgres via SQLAlchemy Core, plus an in-memory twin), a `BlobStore` (S3 via boto3, plus an in-memory twin), a `JobQueue` (RQ, plus an in-memory twin) and `Settings`. Postgres is the record; Redis carries only job ids. The api (`apps/api`) validates and dedupes uploads and enqueues by dotted path, so it never imports the worker. The worker (`apps/worker`) runs `process_job` under RQ, with each expensive stage wrapped in a content-hash cache decorator.

**Tech Stack:** Python 3.12, uv workspace, FastAPI 0.142 / Starlette 1.7, SQLAlchemy 2.1 Core + psycopg 3, Alembic 1.20, RQ 2.12 + redis-py, boto3, pytest, mypy, ruff. Local services through `compose.yaml`: `postgres:16`, `redis:7`, `rustfs/rustfs:1.0.1`.

**Spec:** [spec.md](spec.md) · **Parent:** [001-guitarvis-design](../001-guitarvis-design/spec.md) · **Carried findings:** [003 review notes](../003-pipeline-skeleton/review-notes.md) · **ADR added here:** 0007 (Task 13)

**Checked while writing:** the code in Tasks 1–12 was assembled from this plan, following its own instructions, in a scratch copy of the repo and run. That covered 295 tests, including the store contract suites and the end-to-end test against real Postgres 16, Redis 7 and RustFS 1.0.1, with mypy and ruff clean. Not run: the Makefile targets, the CI workflow on GitHub, and Task 13's docs. A snippet that fails as written most likely has a transcription slip, so check the copy against the plan before doubting the design.

## Global Constraints

Repo-wide rules from `CLAUDE.md` and `docs/CONVENTIONS.md`, plus the values this spec fixes. Every task inherits them.

- **Never commit to `main`.** All work happens on branch `005-api-job-queue`. `.githooks/pre-commit` enforces it.
- **`make check` is the gate.** Run it before claiming any task is done: ruff, mypy, pytest, ESLint, `tsc`, `make schema-check`.
- **`apps/api` must not import** torch, demucs, basic_pitch, librosa, numpy — **or `guitarvis_worker`**. The api enqueues by the string `"guitarvis_worker.runner.run_job"` and never imports the function. Task 12 makes the boundary test enforce the worker half; respect it from Task 10 on.
- **`guitarvis_jobs` imports nothing** from the ML stack, `guitarvis_worker` or `guitarvis_api`. It depends on `guitarvis_core` only, among workspace members.
- **Stage modules must not import** torch, demucs, basic_pitch, librosa or numpy at module level. `caching.py` and `runner.py` are not stage modules, but they follow the same rule.
- **Evaluation never gates CI.** Not touched here.
- **No `tabdoc.py` change**, so no `make schema` run. `source.audio_url` is already a string; the worker puts a relative path in it.
- **Seconds are authoritative.** Not touched here.
- **Degrade, never fail.** Only a `PipelineError` fails a job without retry. Every other exception is retried (three attempts in all), then fails as `internal`.
- **Test file basenames are unique across the repo** (the Makefile's mypy caveat). **Do not add any `conftest.py`.** Shared test helpers live in `guitarvis_jobs.testing`, or in a helper module beside the tests that need it, imported by bare name. `apps/eval/tests/guitarset_fixture.py` is the precedent.
- **Integration tests touch only** the `guitarvis_test` database, Redis database 15 and the `guitarvis-test` bucket, and clean up after each test. Never the dev database, Redis db 0 or the `guitarvis` bucket.
- **RustFS replaces MinIO.** The user decided this on 2026-10-08: MinIO's community edition is archived, and `docker pull minio/minio` and `quay.io/minio/minio` both fail. The code talks plain S3 through boto3. Only `compose.yaml` and documentation name the server. The bucket is created by `make migrate` through boto3, not by a one-shot `mc` container. Task 6 amends the spec to match.
- **Exact values from the spec:**
  - `GUITARVIS_MAX_UPLOAD_MB` = 150
  - `GUITARVIS_MAX_ACTIVE_JOBS_PER_IP` = 2
  - `GUITARVIS_JOB_TIMEOUT_SEC` = 1800
  - `Retry(max=2, interval=[10, 60])`
  - presigned URLs live 15 minutes
  - reconciliation: queued grace 60 s; a running row is stale after the job timeout plus 5 min
  - stage start percents: separation 0, transcription 40, structure 65, fretboard 80; `fretboard 100` at the end
  - separation progress: the 6-stem pass maps to 0–0.75, the fallback to 0.75–1
  - Demucs failure message: the last 500 characters of output
  - upload extension: a lowercased suffix of 1–5 alphanumerics, otherwise none
  - `CACHE_VERSION` starts at 1
  - internal failure message: "Something went wrong on our side. Try again later."
- Install changes with `uv lock && uv sync`. CI runs `make install UV_SYNC_FLAGS=--locked`, so commit `uv.lock` with any dependency change.
- Run `uv run ruff format . && uv run ruff check --fix .` before each commit. Import order in these snippets is best-effort; ruff is authoritative.
- End every commit message with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

Inputs the spec implies but never names, most likely first. Each is pinned by a test in the task that owns the code.

1. **Filenames as browsers and curl actually send them**: none at all, no extension, a Windows path (`C:\Users\me\Song.MP3`), a 300-character name. Expected: the title is the basename minus its last extension, capped at 200 characters, and `Untitled` when empty. The key suffix is kept only when it is 1–5 alphanumerics. Never a crash. → Task 11, `test_title_and_extension_from_awkward_filenames` and `test_a_windows_path_filename_is_reduced_to_its_basename`.
2. **Object storage failing while a stage's result is being cached.** Expected: transcription and structure output still reach the document. A cache read or write error counts as a miss, never as a stage failure, so the cache can never cause a "Transcription failed" warning. → Task 8, `test_a_storage_failure_while_caching_notes_does_not_cost_the_notes` and `test_an_unreadable_cache_is_a_miss`.
3. **Redis down while a client polls** a `queued` row past its 60-second grace. Expected: `GET /jobs/{id}` answers 200 from Postgres. Not a 500, and not a job wrongly failed because the queue could not be asked. → Task 10, `test_redis_down_while_polling_answers_from_postgres`.
4. **A worker killed outright, then redelivered.** RQ retries a job whose row still says `running`, because no `except` ever ran. Expected: the retry runs and succeeds with `attempts` 2. It must not be dropped as "finished elsewhere". → Task 9, `test_a_row_left_running_by_a_killed_worker_is_resumed`.
5. **Re-uploading a file whose job the queue lost.** The upload's dedupe lookup (the spec's step 3) finds a `queued` row whose RQ job is gone. Expected: the lookup reconciles the row (a lookup is a read) and starts a fresh job with 202, rather than handing back a dead job with 200. → Task 11, `test_reupload_of_a_lost_job_starts_a_fresh_one`.

## File map

| Path | Responsibility | Task |
|---|---|---|
| `packages/core/src/guitarvis_core/audio.py` | `probe_duration`, `check_duration`, `MAX_DURATION_SEC` — stdlib only | 1 |
| `packages/core/src/guitarvis_core/contracts.py` | `SeparationProgress`; `Separator.isolate(..., *, progress=None)` | 2 |
| `apps/worker/src/guitarvis_worker/pipeline.py` | stage-start progress, monotonic separation progress, `audio_url` | 2 |
| `apps/worker/src/guitarvis_worker/stages/separation.py` | `Popen` streaming, `TqdmPercent`, required `work_dir`, no `stems/` subdirectory | 2, 3 |
| `apps/worker/src/guitarvis_worker/cli.py` | output guard; `serve` subcommand | 3, 9 |
| `packages/jobs/` | new workspace member `guitarvis_jobs` | 4–7 |
| `…/guitarvis_jobs/settings.py` | `Settings.from_env()` | 4 |
| `…/guitarvis_jobs/models.py` | `JobStatus`, `Job`, `NewJob`, `canonical_id`, `INTERNAL_FAILURE_MESSAGE` | 4 |
| `…/guitarvis_jobs/store.py` | `JobStore` Protocol, `InMemoryJobStore`, `Clock`, `utc_now` | 4 |
| `…/guitarvis_jobs/blobs.py` | `BlobStore` Protocol, `InMemoryBlobStore`, `S3BlobStore`, `s3_client` | 5, 7 |
| `…/guitarvis_jobs/queue.py` | `JobQueue` Protocol, `InMemoryJobQueue`, `RQJobQueue`, `RUN_JOB` | 5, 7 |
| `…/guitarvis_jobs/postgres.py` | `jobs` table, `PostgresJobStore` | 6 |
| `…/guitarvis_jobs/migrations/` | Alembic `env.py` and `versions/r0001_create_jobs.py` | 6 |
| `…/guitarvis_jobs/migrate.py` | `python -m guitarvis_jobs.migrate`: upgrade, then create the bucket | 6, 7 |
| `…/guitarvis_jobs/testing.py` | `FakeClock`, `sample_new_job`, `require`, integration store/blob/redis helpers | 4, 6, 7 |
| `compose.yaml`, `deploy/postgres-init/01-test-database.sql` | Postgres, Redis, RustFS | 6 |
| `apps/worker/src/guitarvis_worker/caching.py` | `CACHE_VERSION`, `CacheKeys`, three cache decorators | 8 |
| `apps/worker/src/guitarvis_worker/runner.py` | `run_job`, `process_job`, `build_stages`, `serve` | 9 |
| `apps/api/src/guitarvis_api/services.py` | `Services` bundle, `build_services` | 10 |
| `apps/api/src/guitarvis_api/errors.py` | `ApiError`, `HttpReason`, error body and handlers | 10 |
| `apps/api/src/guitarvis_api/schemas.py` | `JobView`, `FailureView` | 10 |
| `apps/api/src/guitarvis_api/reconcile.py` | repair lost jobs on read | 10 |
| `apps/api/src/guitarvis_api/routes.py` | every route | 10, 11 |
| `apps/api/src/guitarvis_api/uploads.py` | `UploadSizeLimit`, `receive`, `title_of`, `upload_key` | 11 |
| `apps/api/src/guitarvis_api/app.py` | `create_app(services)`, module-level `app` | 10, 11 |
| `.github/workflows/ci.yml` | services in CI, `GUITARVIS_REQUIRE_SERVICES=1` | 7 |
| `docs/decisions/0007-postgres-is-the-record.md` | ADR | 13 |

---

### Task 1: `guitarvis_core.audio`

The api has to probe uploads too, and it may not import the worker. Probing moves to core, which both sides already depend on. The worker's `UploadSource` keeps calling it, because the worker must not trust its caller.

**Files:**
- Create: `packages/core/src/guitarvis_core/audio.py`
- Create: `packages/core/tests/test_audio.py`
- Modify: `apps/worker/src/guitarvis_worker/ingest.py` (whole file below)
- Modify: `apps/worker/src/guitarvis_worker/cli.py:18` (one import)
- Modify: `apps/worker/tests/test_ingest.py` (drop the moved probe test)

**Interfaces:**
- Consumes: `guitarvis_core.contracts.FailureReason`, `PipelineError`.
- Produces: `guitarvis_core.audio.MAX_DURATION_SEC: float = 600.0`; `probe_duration(path: Path) -> float` (raises `PipelineError` `unsupported_format` for unreadable input, `internal` when ffprobe is missing); `check_duration(duration_sec: float, max_duration_sec: float = MAX_DURATION_SEC) -> None` (raises `PipelineError` `too_long` when `duration_sec > max_duration_sec`, with a message containing "single song").

- [ ] **Step 1: Write the failing tests**

Create `packages/core/tests/test_audio.py`:

```python
"""Duration probing and the length limit, shared by the api and the worker."""

import shutil
import subprocess
import wave
from pathlib import Path

import pytest
from guitarvis_core.audio import MAX_DURATION_SEC, check_duration, probe_duration
from guitarvis_core.contracts import FailureReason, PipelineError

requires_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None,
    reason="ffprobe not installed; install ffmpeg",
)


def write_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> Path:
    """A silent wav, written with the stdlib so the test needs no ml extra."""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


@requires_ffprobe
def test_probe_duration_reads_length(tmp_path: Path) -> None:
    assert probe_duration(write_wav(tmp_path / "a.wav", seconds=2.0)) == pytest.approx(
        2.0, abs=0.05
    )


@requires_ffprobe
def test_probe_rejects_a_file_that_is_not_audio(tmp_path: Path) -> None:
    path = tmp_path / "not-audio.wav"
    path.write_bytes(b"this is not audio")

    with pytest.raises(PipelineError) as excinfo:
        probe_duration(path)

    assert excinfo.value.reason is FailureReason.UNSUPPORTED_FORMAT


def test_missing_ffprobe_is_internal_not_the_users_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_ffprobe(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(subprocess, "run", no_ffprobe)

    with pytest.raises(PipelineError) as excinfo:
        probe_duration(tmp_path / "a.wav")

    assert excinfo.value.reason is FailureReason.INTERNAL
    assert "ffmpeg" in str(excinfo.value)


def test_the_limit_is_ten_minutes() -> None:
    assert MAX_DURATION_SEC == 600.0


def test_check_duration_accepts_exactly_the_limit() -> None:
    check_duration(MAX_DURATION_SEC)


def test_check_duration_rejects_past_the_limit() -> None:
    with pytest.raises(PipelineError, match="single song") as excinfo:
        check_duration(MAX_DURATION_SEC + 0.1)
    assert excinfo.value.reason is FailureReason.TOO_LONG


def test_check_duration_honours_a_custom_limit() -> None:
    with pytest.raises(PipelineError) as excinfo:
        check_duration(2.0, max_duration_sec=1.0)
    assert excinfo.value.reason is FailureReason.TOO_LONG
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/core/tests/test_audio.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'guitarvis_core.audio'`.

- [ ] **Step 3: Create `guitarvis_core/audio.py`**

```python
"""Audio facts the api and the worker both need, from the standard library.

The api probes an upload before queueing it, so a user with a bad file learns
in a second rather than after a queue wait. The worker probes again, because
it must not trust its caller. Both go through these functions so the two
checks cannot drift apart.

ffprobe rather than a Python audio library: it decodes every container a user
might supply, and core must stay free of heavy dependencies.
"""

import json
import subprocess
from pathlib import Path

from guitarvis_core.contracts import FailureReason, PipelineError

MAX_DURATION_SEC = 600.0  # ten minutes

_UNREADABLE = "That file could not be read as audio. Try an mp3, wav, or m4a file."


def probe_duration(path: Path) -> float:
    """Read a file's duration in seconds with ffprobe."""
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise PipelineError(
            FailureReason.INTERNAL,
            "ffprobe is not installed. Install ffmpeg to process audio.",
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise PipelineError(FailureReason.UNSUPPORTED_FORMAT, _UNREADABLE) from exc

    try:
        return float(json.loads(completed.stdout)["format"]["duration"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PipelineError(FailureReason.UNSUPPORTED_FORMAT, _UNREADABLE) from exc


def check_duration(
    duration_sec: float, max_duration_sec: float = MAX_DURATION_SEC
) -> None:
    """Refuse a recording longer than the limit, before any expensive work."""
    if duration_sec > max_duration_sec:
        raise PipelineError(
            FailureReason.TOO_LONG,
            f"That recording is longer than {max_duration_sec / 60:.0f} "
            "minutes. Try a single song rather than a full set.",
        )
```

- [ ] **Step 4: Run the new tests**

Run: `uv run pytest packages/core/tests/test_audio.py -v`
Expected: 7 PASS (the two `requires_ffprobe` tests skip if ffmpeg is missing; it is installed on this machine and in CI).

- [ ] **Step 5: Point the worker at core**

Replace `apps/worker/src/guitarvis_worker/ingest.py` with:

```python
"""Getting audio into the pipeline.

UploadSource is one implementation of AudioSource; URL fetching will be
another, and nothing downstream will change when it lands. Guards run here, at
the front door, because rejecting a three-hour DJ set after separation has
already run is the expensive way to find out. The probe itself lives in
guitarvis_core.audio, because the api runs the same check before queueing.
"""

from pathlib import Path

from guitarvis_core.audio import MAX_DURATION_SEC, check_duration, probe_duration
from guitarvis_core.contracts import FailureReason, IngestedAudio, PipelineError


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
```

In `apps/worker/src/guitarvis_worker/cli.py`, replace line 18:

```python
from guitarvis_worker.ingest import MAX_DURATION_SEC, UploadSource
```

with:

```python
from guitarvis_core.audio import MAX_DURATION_SEC

from guitarvis_worker.ingest import UploadSource
```

(ruff will move the core import up into the `guitarvis_core` group.)

In `apps/worker/tests/test_ingest.py`, change the import to `from guitarvis_worker.ingest import UploadSource` and delete `test_probe_duration_reads_length`, which now lives in `test_audio.py`.

- [ ] **Step 6: Run the affected suites**

Run: `uv run pytest packages/core apps/worker/tests/test_ingest.py apps/worker/tests/test_cli.py -v`
Expected: all PASS. `test_too_long_message_tells_the_user_what_to_do` still passes: the message is unchanged.

- [ ] **Step 7: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add packages/core/src/guitarvis_core/audio.py packages/core/tests/test_audio.py apps/worker/src/guitarvis_worker/ingest.py apps/worker/src/guitarvis_worker/cli.py apps/worker/tests/test_ingest.py
git commit -m "refactor(core): move duration probing to guitarvis_core.audio

The api must probe uploads before queueing them and may not import the
worker, so the probe and the length limit move to core.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Progress names the running stage, and separation reports as it goes

Today `StageProgress` fires after each stage finishes. After this task it fires when each stage *starts*. Separation reports fractions while it runs, through a new keyword on the `Separator` protocol, and the pipeline keeps the percent monotonic whatever a separator reports. Every separator test double changes in this same commit, because a double without the keyword fails with `TypeError` once the pipeline passes it. `DemucsSeparator` gains the keyword and the pass scaling here. Its subprocess starts producing the numbers in Task 3.

**Files:**
- Modify: `packages/core/src/guitarvis_core/contracts.py` (imports; `SeparationProgress`; `Separator`)
- Modify: `packages/core/tests/test_contracts.py` (two separator doubles; one new test)
- Modify: `apps/worker/src/guitarvis_worker/pipeline.py` (whole file below)
- Modify: `apps/worker/src/guitarvis_worker/stages/separation.py` (`isolate`, `_demucs` signature, `FIRST_PASS_SHARE`, `_span`)
- Modify: `apps/worker/tests/test_pipeline.py`, `apps/worker/tests/test_cli.py`, `apps/worker/tests/test_separation.py` (separator doubles; new tests)
- Modify: `.claude/skills/pipeline-stage/SKILL.md:13-18` (interface table)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `guitarvis_core.contracts.SeparationProgress = Callable[[float], None]`.
  - `Separator.isolate(self, audio_path: Path, *, progress: SeparationProgress | None = None) -> SeparationResult`.
  - `guitarvis_worker.pipeline.STAGE_START_PERCENT = {"separation": 0, "transcription": 40, "structure": 65, "fretboard": 80}`.
  - `run_pipeline(..., progress: ProgressCallback | None = None, audio_url: str | None = None)`. The events are `separation 0`, any `separation N` with 0 < N ≤ 40, `transcription 40`, `structure 65`, `fretboard 80`, then `fretboard 100`. The last one comes only after every note passes the invariant check.
  - `guitarvis_worker.stages.separation.FIRST_PASS_SHARE = 0.75`; `DemucsSeparator._demucs(self, model: str, audio_path: Path, stem_name: str, progress: SeparationProgress | None = None) -> Path`.

- [ ] **Step 1: Write the failing contract test**

In `packages/core/tests/test_contracts.py`, add `import inspect` to the stdlib imports and `SeparationProgress` to the `guitarvis_core.contracts` import list. Change both separator doubles — `FakeSeparator` inside the protocol-conformance test (around line 66) and `Stub` in `test_separator_protocol_returns_separation_result` (around line 133) — to:

```python
        def isolate(
            self, audio_path: Path, *, progress: SeparationProgress | None = None
        ) -> SeparationResult:
            return SeparationResult(stem_path=audio_path)
```

and append:

```python
def test_separator_takes_an_optional_keyword_only_progress_hook() -> None:
    """Separation dominates job time; the hook is what keeps percent moving."""
    parameter = inspect.signature(Separator.isolate).parameters["progress"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/core/tests/test_contracts.py -v`
Expected: collection error, `ImportError: cannot import name 'SeparationProgress'`.

- [ ] **Step 3: Change the protocol**

In `contracts.py`, change `from collections.abc import Sequence` to `from collections.abc import Callable, Sequence`. Directly after the `SeparationResult` class, add:

```python
SeparationProgress = Callable[[float], None]
"""Stage 1's progress hook: the fraction of separation done, 0.0 to 1.0."""
```

and replace the `Separator` protocol with:

```python
@runtime_checkable
class Separator(Protocol):
    """Stage 1: isolate the guitar from a mix.

    `progress`, when given, receives the fraction of separation done while it
    runs. Separation dominates job time, so this is what keeps a job's percent
    moving. A separator may report nothing at all, and the pipeline tolerates
    any sequence, including one that runs backwards.
    """

    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult: ...
```

Run: `uv run pytest packages/core/tests/test_contracts.py -v`
Expected: all PASS.

- [ ] **Step 4: Write the failing pipeline tests**

In `apps/worker/tests/test_pipeline.py`, add `import math` to the stdlib imports and `SeparationProgress` to the `guitarvis_core.contracts` import list. Replace `StubSeparator` and `FailingSeparator` with:

```python
class StubSeparator:
    def __init__(
        self, warnings: list[str] | None = None, fractions: Sequence[float] = ()
    ) -> None:
        self.warnings = warnings or []
        self.fractions = list(fractions)

    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        if progress is not None:
            for fraction in self.fractions:
                progress(fraction)
        return SeparationResult(stem_path=audio_path, warnings=list(self.warnings))


class FailingSeparator:
    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        raise PipelineError(FailureReason.NO_GUITAR_DETECTED, "No clear guitar part")
```

Replace `test_reports_progress_for_every_stage` and `test_progress_still_reports_when_stages_degrade` with:

```python
EVERY_STAGE_STARTS = [
    ("separation", 0),
    ("transcription", 40),
    ("structure", 65),
    ("fretboard", 80),
    ("fretboard", 100),
]


def test_reports_each_stage_as_it_starts_then_100(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    run(tmp_path, progress=seen.append)

    assert [(p.stage, p.percent) for p in seen] == EVERY_STAGE_STARTS


def test_progress_still_reports_when_stages_degrade(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    run(
        tmp_path,
        analyzer=FailingAnalyzer(),
        mapper=FailingMapper(),
        progress=seen.append,
    )

    assert [(p.stage, p.percent) for p in seen] == EVERY_STAGE_STARTS


def test_separation_progress_moves_within_its_band(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    run(
        tmp_path,
        separator=StubSeparator(fractions=[0.25, 0.5, 1.0]),
        progress=seen.append,
    )

    assert [(p.stage, p.percent) for p in seen if p.stage == "separation"] == [
        ("separation", 0),
        ("separation", 10),
        ("separation", 20),
        ("separation", 40),
    ]
    assert seen[-1] == StageProgress(stage="fretboard", percent=100)


def test_progress_is_monotonic_whatever_the_separator_reports(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    run(
        tmp_path,
        separator=StubSeparator(fractions=[0.5, 0.2, 0.5, 1.7, math.nan, -1.0, 0.9]),
        progress=seen.append,
    )

    percents = [p.percent for p in seen]
    assert percents == sorted(percents)
    # 0.2 and the second 0.5 would not raise the percent; 1.7 is clamped to
    # the band's top; NaN and -1 are ignored; 0.9 arrives after 40 already has.
    assert [p.percent for p in seen if p.stage == "separation"] == [0, 20, 40]


def test_a_separator_that_reports_nothing_still_reaches_100(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    run(tmp_path, separator=StubSeparator(fractions=[]), progress=seen.append)

    assert seen[-1].percent == 100


def test_audio_url_replaces_the_file_uri(tmp_path: Path) -> None:
    result = run_pipeline(
        audio(tmp_path),
        separator=StubSeparator(),
        transcriber=StubTranscriber(),
        analyzer=StubAnalyzer(),
        mapper=StubMapper(),
        audio_url="/jobs/abc/audio/mix",
    )

    assert result.document.source.audio_url == "/jobs/abc/audio/mix"


def test_an_invariant_failure_never_reports_100(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    with pytest.raises(PipelineError):
        run(
            tmp_path,
            transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 53, 0.8)]),
            mapper=StubMapper([TabNote(1.0, 0.5, 53, 2, 2, 0.8)]),
            progress=seen.append,
        )

    assert seen[-1] == StageProgress(stage="fretboard", percent=80)
```

In `apps/worker/tests/test_cli.py`, add `SeparationProgress` to the `guitarvis_core.contracts` import list and change both `StubSeparator.isolate` and `ExplodingSeparator.isolate` to take `self, audio_path: Path, *, progress: SeparationProgress | None = None`.

- [ ] **Step 5: Run them to verify they fail**

Run: `uv run pytest apps/worker/tests/test_pipeline.py -v`
Expected: the new and replaced tests FAIL. For example, `test_reports_each_stage_as_it_starts_then_100` sees `[("separation", 40), ...]`, and `test_audio_url_replaces_the_file_uri` fails with `TypeError: run_pipeline() got an unexpected keyword argument 'audio_url'`.

- [ ] **Step 6: Rewrite `pipeline.py`**

Replace `apps/worker/src/guitarvis_worker/pipeline.py` with:

```python
"""Runs the stages in order and assembles a tab document.

The degradation ladder lives here. Every stage after separation is optional to
the core promise, so a failure downstream costs the user a feature rather than
the whole job. Only "no usable guitar audio" fails outright.

Stages arrive by injection: the worker decides what to run, and the stages stay
ignorant of each other.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from guitarvis_core.contracts import (
    FailureReason,
    FretboardMapper,
    IngestedAudio,
    NoteEvent,
    PipelineError,
    Separator,
    StructureAnalyzer,
    StructureResult,
    TabNote,
    Transcriber,
)
from guitarvis_core.fretboard import InvariantViolation, check_invariant
from guitarvis_core.tabdoc import (
    STANDARD_TUNING,
    Instrument,
    Note,
    Source,
    TabDocument,
    Timing,
)

# The whole job's percent when each stage starts. Separation fills the band
# up to transcription's start as it reports; `fretboard 100` marks the end.
STAGE_START_PERCENT = {
    "separation": 0,
    "transcription": 40,
    "structure": 65,
    "fretboard": 80,
}
_SEPARATION_BAND = STAGE_START_PERCENT["transcription"]


@dataclass(frozen=True)
class StageProgress:
    """The stage now running, and the whole job's percent. 100 means done."""

    stage: str
    percent: int


ProgressCallback = Callable[[StageProgress], None]


@dataclass(frozen=True)
class PipelineResult:
    """What `run_pipeline` hands back: the document plus what stage 2 saw.

    `transcribed_note_count` is how many note events transcription produced,
    before stage 4 dropped any it could not place. Comparing it with
    `len(document.notes)` shows how much the fretboard stage lost. Returned
    as data rather than folded into a warning string so a caller gets it
    without parsing prose.
    """

    document: TabDocument
    transcribed_note_count: int


class _Reporter:
    """Turns stage starts and separation fractions into monotonic progress.

    A separator's fractions are not trusted: anything that would not raise
    the whole-number percent is dropped, values past 1 are clamped and NaN or
    negative values are ignored. That is what lets the worker write the row
    only when something changed — at most about a hundred writes a job.
    """

    def __init__(self, callback: ProgressCallback | None) -> None:
        self._callback = callback
        self._percent = -1

    def start(self, stage: str) -> None:
        self._emit(stage, max(STAGE_START_PERCENT[stage], self._percent))

    def separation(self, fraction: float) -> None:
        if not fraction >= 0.0:  # also False for NaN
            return
        percent = int(min(fraction, 1.0) * _SEPARATION_BAND)
        if percent > self._percent:
            self._emit("separation", percent)

    def finish(self) -> None:
        self._emit("fretboard", 100)

    def _emit(self, stage: str, percent: int) -> None:
        self._percent = percent
        if self._callback is not None:
            self._callback(StageProgress(stage=stage, percent=percent))


def run_pipeline(
    audio: IngestedAudio,
    *,
    separator: Separator,
    transcriber: Transcriber,
    analyzer: StructureAnalyzer,
    mapper: FretboardMapper,
    tuning: Sequence[str] = STANDARD_TUNING,
    progress: ProgressCallback | None = None,
    audio_url: str | None = None,
) -> PipelineResult:
    """Turn ingested audio into a tab document.

    `audio_url` becomes the document's `source.audio_url`. The CLI leaves it
    unset and gets a file:// URI of the input; the job runner passes the api
    path a client fetches the mix from.
    """
    report = _Reporter(progress)
    warnings: list[str] = []

    # Stage 1. The only stage whose failure is fatal: with no guitar audio
    # there is nothing to transcribe and nothing honest to show.
    report.start("separation")
    separation = separator.isolate(audio.path, progress=report.separation)
    warnings.extend(separation.warnings)

    # Stage 2. Optional like stages 3 and 4: a raised exception costs notes,
    # not the whole job. A genuinely empty result (no exception, no notes)
    # gets its own, more specific warning, so a caller can tell "found
    # nothing" apart from "blew up".
    report.start("transcription")
    events: list[NoteEvent] = []
    try:
        events = transcriber.transcribe(separation.stem_path)
    except Exception as exc:  # every transcriber failure degrades alike
        warnings.append(
            f"Transcription failed ({exc.__class__.__name__}), so no notes "
            "could be detected."
        )
    else:
        if not events:
            warnings.append("No notes were detected in the isolated guitar part.")

    # Stage 3. Optional: notes carry their own onsets, so losing the beat grid
    # costs bar lines and chord symbols, never synchronisation. Beats and
    # chords each fail independently inside `analyze` now, and each failure
    # produces its own warning on `structure.warnings`. This except is a
    # backstop for an analyzer implementation that does not catch its own
    # halves (or that dies before returning a StructureResult at all) — the
    # shipped LibrosaStructureAnalyzer never takes this path, since both of
    # its halves already degrade internally.
    report.start("structure")
    structure = StructureResult(timing=Timing(), chords=[], sections=[])
    try:
        structure = analyzer.analyze(separation.stem_path, audio.path)
    except Exception as exc:  # the analyzer itself raised, not just a half
        warnings.append(
            f"Structure analysis failed entirely ({exc.__class__.__name__}), "
            "so bar lines and chord symbols are unavailable."
        )
    warnings.extend(structure.warnings)

    # Stage 4. Optional like stages 2 and 3: a mapper that raises costs the
    # notes track, not the job — including NotImplementedError, which a real
    # mapper may raise for a genuinely unsupported case. Notes the mapper
    # could not place arrive as warnings on its result. A wrong fret is a
    # different matter: the invariant check below fails the job instead.
    report.start("fretboard")
    tab_notes: list[TabNote] = []
    try:
        fretboard = mapper.assign(events, tuning)
    except Exception as exc:  # every mapper failure degrades alike
        warnings.append(
            f"Fretboard assignment failed ({exc.__class__.__name__}), so this "
            "document carries no notes."
        )
    else:
        tab_notes = fretboard.notes
        warnings.extend(fretboard.warnings)

    # A tab that renders the wrong fret is worse than no tab: a beginner cannot
    # tell it from a hard passage. Refuse to emit one. A string or fret that
    # does not exist on the neck is the same failure, not a crash: pitch_of
    # raises IndexError and Note's validation raises ValueError.
    notes: list[Note] = []
    for index, tab in enumerate(tab_notes):
        try:
            note = Note(
                id=f"n_{index:04d}",
                t=tab.onset,
                dur=tab.duration,
                midi=tab.midi,
                string=tab.string,
                fret=tab.fret,
                confidence=tab.confidence,
            )
            check_invariant(note, tuning)
        except (InvariantViolation, IndexError, ValueError) as exc:
            raise PipelineError(
                FailureReason.INTERNAL, f"Fretboard assignment is inconsistent: {exc}"
            ) from exc
        notes.append(note)

    # 100 only once every note has passed the invariant: a job must never
    # read 100% and then fail.
    report.finish()

    document = TabDocument(
        source=Source(
            title=audio.title,
            duration_sec=audio.duration_sec,
            audio_url=(
                audio_url if audio_url is not None else audio.path.resolve().as_uri()
            ),
        ),
        instrument=Instrument(tuning=list(tuning), string_count=len(tuning)),
        timing=structure.timing,
        notes=notes,
        chords=structure.chords,
        sections=structure.sections,
        warnings=warnings,
    )
    return PipelineResult(document=document, transcribed_note_count=len(events))
```

- [ ] **Step 7: Give `DemucsSeparator` the keyword and the pass scaling (failing test first)**

In `apps/worker/tests/test_separation.py`, import `SeparationProgress` from `guitarvis_core.contracts` and `FIRST_PASS_SHARE` from `guitarvis_worker.stages.separation`. Replace `FakeSeparator` with:

```python
class FakeSeparator(DemucsSeparator):
    """Replaces the Demucs subprocess with prepared files.

    Each fake pass reports half-way, then done, so the scaling of the two
    passes onto one stage is visible to a test.
    """

    def __init__(self, stems: dict[str, Path]) -> None:
        super().__init__()
        self.stems = stems
        self.calls: list[tuple[str, str]] = []

    def _demucs(
        self,
        model: str,
        audio_path: Path,
        stem_name: str,
        progress: SeparationProgress | None = None,
    ) -> Path:
        self.calls.append((model, stem_name))
        if progress is not None:
            progress(0.5)
            progress(1.0)
        return self.stems[model]
```

and append:

```python
def test_the_first_pass_fills_three_quarters_of_the_stage(tmp_path: Path) -> None:
    separator = FakeSeparator({"htdemucs_6s": write_wav(tmp_path / "g.wav")})
    seen: list[float] = []

    separator.isolate(tmp_path / "song.wav", progress=seen.append)

    assert seen == [0.375, FIRST_PASS_SHARE]


def test_the_fallback_pass_fills_the_rest_without_running_backwards(
    tmp_path: Path,
) -> None:
    separator = FakeSeparator(
        {
            "htdemucs_6s": write_wav(tmp_path / "guitar.wav", amplitude=0),
            "htdemucs": write_wav(tmp_path / "other.wav", amplitude=8000),
        }
    )
    seen: list[float] = []

    separator.isolate(tmp_path / "song.wav", progress=seen.append)

    assert seen == [0.375, 0.75, 0.875, 1.0]
    assert seen == sorted(seen)
```

Run: `uv run pytest apps/worker/tests/test_separation.py -v`
Expected: the two new tests FAIL with `TypeError: DemucsSeparator.isolate() got an unexpected keyword argument 'progress'` (or `ImportError` on `FIRST_PASS_SHARE`).

In `apps/worker/src/guitarvis_worker/stages/separation.py`: add `SeparationProgress` to the `guitarvis_core.contracts` import, and add below `_RMS_STRIDE`:

```python
# The 6-stem pass fills this share of the stage's progress; the 4-stem
# fallback, when it runs, fills the rest, so progress never runs backwards.
FIRST_PASS_SHARE = 0.75


def _span(
    progress: SeparationProgress | None, start: float, end: float
) -> SeparationProgress | None:
    """Map one Demucs pass's 0..1 onto [start, end] of the whole stage."""
    if progress is None:
        return None
    report = progress

    def scaled(fraction: float) -> None:
        report(start + (end - start) * fraction)

    return scaled
```

Replace `isolate` and the `_demucs` signature with:

```python
    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        guitar = self._demucs(
            self.model, audio_path, "guitar", _span(progress, 0.0, FIRST_PASS_SHARE)
        )
        if measure_rms(guitar) >= SILENCE_RMS:
            return SeparationResult(stem_path=guitar)

        # A heavily distorted guitar is often attributed elsewhere by the
        # 6-stem model. The 4-stem `other` track is the next best thing, and
        # saying so is better than returning silence.
        other = self._demucs(
            self.fallback_model,
            audio_path,
            "other",
            _span(progress, FIRST_PASS_SHARE, 1.0),
        )
        if measure_rms(other) < SILENCE_RMS:
            raise PipelineError(
                FailureReason.NO_GUITAR_DETECTED,
                "No clear guitar part was found in this recording.",
            )

        return SeparationResult(
            stem_path=other,
            warnings=[
                "The 6-stem model found no guitar, so this tab comes from the "
                "4-stem 'other' track and may include other instruments."
            ],
        )

    def _demucs(
        self,
        model: str,
        audio_path: Path,
        stem_name: str,
        progress: SeparationProgress | None = None,
    ) -> Path:
```

Leave the body of `_demucs` alone; Task 3 replaces it.

- [ ] **Step 8: Update the stage skill's interface table**

In `.claude/skills/pipeline-stage/SKILL.md`, replace the table at lines 13–18 with:

```markdown
| Stage | Interface | Progress |
|---|---|---|
| 1 Separation | `Separator.isolate(audio_path, *, progress=None) -> SeparationResult` | 0–40%, live: `progress(fraction)` while it runs |
| 2 Transcription | `Transcriber.transcribe(stem_path) -> list[NoteEvent]` | starts at 40% |
| 3 Structure | `StructureAnalyzer.analyze(stem, mix) -> StructureResult` | starts at 65% |
| 4 Fretboard | `FretboardMapper.assign(notes, tuning) -> FretboardResult` | starts at 80%; 100% when the document is built |

Progress names the stage **running**. The pipeline reports each stage's start
and keeps the percent monotonic whatever a separator reports, so a separator
may report nothing, or nonsense, without breaking a client.
```

- [ ] **Step 9: Run every worker and core test**

Run: `uv run pytest packages/core apps/worker -v`
Expected: all PASS. `test_cli.py::test_writes_a_valid_document_and_exits_zero` still sees `100%` on stderr.

Run: `uv run mypy packages/core/src apps/worker/src packages/core/tests apps/worker/tests`
Expected: `Success`. A separator double you missed shows up here as an incompatible-type error on the Protocol.

- [ ] **Step 10: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add packages/core apps/worker .claude/skills/pipeline-stage/SKILL.md
git commit -m "feat(pipeline): progress names the running stage; separation reports live

Separator.isolate gains a keyword-only progress hook. The pipeline reports
each stage's start, maps separation's fractions onto 0-40%, and drops any
update that would not raise the percent. run_pipeline gains audio_url.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Demucs streams its progress; close 003's separation and CLI findings

`DemucsSeparator` switches from `subprocess.run` to `Popen`, reading merged stdout/stderr as it arrives and turning tqdm's `NN%|` into progress. If anything raises while it reads (a job timeout, a failing progress write), the Demucs child is killed rather than orphaned. Three of 003's findings close here: `work_dir` becomes required; stems land directly in `work_dir`, so `--stems-dir X` writes to `X`; and the CLI's output write is guarded against any exception.

**Files:**
- Modify: `apps/worker/src/guitarvis_worker/stages/separation.py`
- Modify: `apps/worker/src/guitarvis_worker/cli.py` (the output-write `except`)
- Modify: `apps/worker/tests/test_separation.py` (rewrite the subprocess tests)
- Modify: `apps/worker/tests/test_stages.py` (two construction sites)
- Modify: `apps/worker/tests/test_cli.py` (one new test)

**Interfaces:**
- Consumes: `SeparationProgress`, `FIRST_PASS_SHARE` and `_span` from Task 2.
- Produces: `DemucsSeparator(*, work_dir: Path, model: str = "htdemucs_6s", fallback_model: str = "htdemucs", device: str | None = None)`. `work_dir` is required and keyword-only. A stem is written at `work_dir / model / audio_path.stem / f"{stem_name}.wav"`. `TqdmPercent().feed(chunk: str) -> list[int]` returns the percentages completed in that chunk.

- [ ] **Step 1: Write the failing tests**

In `apps/worker/tests/test_separation.py`, replace everything from the comment `# The tests above replace _demucs entirely` to the end of the file with:

```python
# The tests above replace _demucs entirely, so nothing above exercises the
# subprocess it wraps. These call _demucs directly on a real DemucsSeparator,
# with subprocess.Popen monkeypatched, to cover its output parsing, its
# failure paths and its command construction without installing Demucs.

# Captured from tqdm 4.70.1 driven with the arguments Demucs 4.1.0 passes it
# (demucs/apply.py: unit_scale=..., ncols=120, unit="seconds"); the bars are
# shortened. tqdm redraws one line with \r, so there are no newlines to split
# on, and its block characters are multi-byte UTF-8.
DEMUCS_OUTPUT = (
    "Separated tracks will be stored in /tmp/w/htdemucs_6s\n"
    "Separating track /tmp/w/upload.wav\n"
    "\r  0%|          | 0.0/29.25 [00:00<?, ?seconds/s]"
    "\r 20%|██▌       | 5.85/29.25 [00:03<00:14,  1.62seconds/s]"
    "\r 40%|████▏     | 11.7/29.25 [00:07<00:10,  1.62seconds/s]"
    "\r 60%|██████▍   | 17.549999999999997/29.25 [00:10<00:07,  1.62seconds/s]"
    "\r 80%|████████▍ | 23.4/29.25 [00:14<00:03,  1.62seconds/s]"
    "\r100%|██████████| 29.25/29.25 [00:18<00:00,  1.62seconds/s]"
    "\r100%|██████████| 29.25/29.25 [00:18<00:00,  1.61seconds/s]\n"
)
DEMUCS_PERCENTS = [0, 20, 40, 60, 80, 100, 100]


class TrickleReader:
    """A pipe that hands back a few bytes per read, so bars and multi-byte
    characters split across reads the way a real pipe splits them."""

    def __init__(
        self, data: bytes, size: int = 7, error: BaseException | None = None
    ) -> None:
        self._data = data
        self._size = size
        self._error = error
        self._position = 0

    def read1(self, size: int = -1) -> bytes:
        if self._position >= len(self._data):
            if self._error is not None:
                raise self._error
            return b""
        chunk = self._data[self._position : self._position + self._size]
        self._position += len(chunk)
        return chunk


class FakeProcess:
    def __init__(self, stdout: TrickleReader, exit_code: int) -> None:
        self.stdout = stdout
        self._exit_code = exit_code
        self.returncode: int | None = None
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self) -> int:
        self.returncode = -9 if self.killed else self._exit_code
        return self.returncode

    def kill(self) -> None:
        self.killed = True


class FakeDemucs:
    """Stands in for subprocess.Popen: records the command, writes the stem
    Demucs would have written, and replays canned output."""

    def __init__(
        self,
        output: str = DEMUCS_OUTPUT,
        exit_code: int = 0,
        write_stem: bool = True,
        read_error: BaseException | None = None,
    ) -> None:
        self.output = output.encode()
        self.exit_code = exit_code
        self.write_stem = write_stem
        self.read_error = read_error
        self.commands: list[list[str]] = []
        self.processes: list[FakeProcess] = []

    def __call__(self, command: list[str], **kwargs: object) -> FakeProcess:
        assert kwargs["stderr"] is subprocess.STDOUT  # tqdm draws on stderr
        self.commands.append(command)
        if self.write_stem:
            out_dir = Path(command[command.index("-o") + 1])
            audio = Path(command[command.index("-o") + 2])
            stem = out_dir / command[command.index("-n") + 1] / audio.stem
            stem.mkdir(parents=True, exist_ok=True)
            (stem / "guitar.wav").write_bytes(b"")
        process = FakeProcess(
            TrickleReader(self.output, error=self.read_error), self.exit_code
        )
        self.processes.append(process)
        return process


def test_tqdm_percentages_are_read_from_a_recorded_bar() -> None:
    assert TqdmPercent().feed(DEMUCS_OUTPUT) == DEMUCS_PERCENTS


def test_tqdm_percentages_survive_a_bar_split_across_reads() -> None:
    parser = TqdmPercent()
    found: list[int] = []
    for start in range(0, len(DEMUCS_OUTPUT), 3):
        found += parser.feed(DEMUCS_OUTPUT[start : start + 3])

    assert found == DEMUCS_PERCENTS


def test_output_without_a_bar_yields_nothing() -> None:
    # Demucs's output is not an API. If the format changes, progress jumps
    # 0 -> 40% as it did before this parser existed; it never fails a job.
    assert TqdmPercent().feed("Separating track song.wav\nDone.\n") == []


def test_a_number_past_100_is_not_a_percentage() -> None:
    assert TqdmPercent().feed("\r142%|") == []


def test_demucs_reports_progress_as_its_bar_advances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "Popen", FakeDemucs())
    seen: list[float] = []

    DemucsSeparator(work_dir=tmp_path)._demucs(
        "htdemucs_6s", tmp_path / "song.wav", "guitar", seen.append
    )

    assert seen == [p / 100 for p in DEMUCS_PERCENTS]


def test_demucs_missing_binary_raises_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_python(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "Popen", no_python)

    with pytest.raises(PipelineError) as excinfo:
        DemucsSeparator(work_dir=tmp_path)._demucs(
            "htdemucs_6s", tmp_path / "song.wav", "guitar"
        )

    assert excinfo.value.reason is FailureReason.INTERNAL
    assert "--extra ml" in str(excinfo.value)


def test_demucs_nonzero_exit_raises_internal_error_with_output_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    noise = "x" * 2000
    monkeypatch.setattr(
        subprocess,
        "Popen",
        FakeDemucs(output=noise + "boom: model crashed", exit_code=1),
    )

    with pytest.raises(PipelineError) as excinfo:
        DemucsSeparator(work_dir=tmp_path)._demucs(
            "htdemucs_6s", tmp_path / "song.wav", "guitar"
        )

    message = str(excinfo.value)
    assert excinfo.value.reason is FailureReason.INTERNAL
    assert message.endswith("boom: model crashed")
    assert len(message) <= len("Separation failed: ") + 500


def test_demucs_missing_output_stem_raises_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "Popen", FakeDemucs(write_stem=False))

    with pytest.raises(PipelineError) as excinfo:
        DemucsSeparator(work_dir=tmp_path)._demucs(
            "htdemucs_6s", tmp_path / "song.wav", "guitar"
        )

    assert excinfo.value.reason is FailureReason.INTERNAL
    expected_stem = tmp_path / "htdemucs_6s" / "song" / "guitar.wav"
    assert str(expected_stem) in str(excinfo.value)


def test_demucs_builds_command_with_device_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeDemucs()
    monkeypatch.setattr(subprocess, "Popen", fake)

    DemucsSeparator(work_dir=tmp_path, device="cuda")._demucs(
        "htdemucs_6s", tmp_path / "song.wav", "guitar"
    )

    assert fake.commands == [
        [
            sys.executable,
            "-m",
            "demucs",
            "-n",
            "htdemucs_6s",
            "-o",
            str(tmp_path),
            str(tmp_path / "song.wav"),
            "-d",
            "cuda",
        ]
    ]


def test_demucs_omits_device_flag_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeDemucs()
    monkeypatch.setattr(subprocess, "Popen", fake)

    DemucsSeparator(work_dir=tmp_path)._demucs(
        "htdemucs_6s", tmp_path / "song.wav", "guitar"
    )

    assert "-d" not in fake.commands[0]


def test_stems_land_directly_in_work_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 003's finding: `--stems-dir X` used to write to X/stems/.
    monkeypatch.setattr(subprocess, "Popen", FakeDemucs())
    work_dir = tmp_path / "kept"
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()

    stem = DemucsSeparator(work_dir=work_dir)._demucs(
        "htdemucs_6s", audio_dir / "song.wav", "guitar"
    )

    assert stem == work_dir / "htdemucs_6s" / "song" / "guitar.wav"
    assert not (work_dir / "stems").exists()
    assert not (audio_dir / "stems").exists()


def test_an_exception_while_streaming_kills_the_demucs_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A job timeout raises inside the read loop; Demucs must not outlive it."""

    class JobTimeout(Exception):
        pass

    fake = FakeDemucs(output="\r 10%|", read_error=JobTimeout())
    monkeypatch.setattr(subprocess, "Popen", fake)

    with pytest.raises(JobTimeout):
        DemucsSeparator(work_dir=tmp_path)._demucs(
            "htdemucs_6s", tmp_path / "song.wav", "guitar"
        )

    assert fake.processes[0].killed


def test_a_failing_progress_hook_also_kills_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeDemucs()
    monkeypatch.setattr(subprocess, "Popen", fake)

    def unreachable_database(fraction: float) -> None:
        raise ConnectionError("postgres went away")

    with pytest.raises(ConnectionError):
        DemucsSeparator(work_dir=tmp_path)._demucs(
            "htdemucs_6s", tmp_path / "song.wav", "guitar", unreachable_database
        )

    assert fake.processes[0].killed
```

Add `TqdmPercent` to the `guitarvis_worker.stages.separation` import at the top of the file, and change `FakeSeparator.__init__`'s `super().__init__()` to `super().__init__(work_dir=Path("unused"))`.

In `apps/worker/tests/test_stages.py`, change both `DemucsSeparator()` calls (the `_separator` assignment and the `isinstance` assertion) to `DemucsSeparator(work_dir=Path("unused"))`.

In `apps/worker/tests/test_cli.py`, append:

```python
def test_any_failure_writing_the_output_reports_its_reason(
    tmp_path: Path,
    stub_stages: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 003's finding: only OSError was caught here, so anything else raised
    # while serialising or writing surfaced as a traceback.
    monkeypatch.setattr(cli, "UploadSource", StubAudioSource)

    def explode(self: Path, *args: object, **kwargs: object) -> int:
        raise ValueError("cannot serialise that")

    monkeypatch.setattr(Path, "write_text", explode)

    code = cli.main(
        ["process", str(tmp_path / "song.wav"), "-o", str(tmp_path / "o.json")]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "internal" in err
    assert "cannot serialise that" in err
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest apps/worker/tests/test_separation.py apps/worker/tests/test_stages.py apps/worker/tests/test_cli.py -v`
Expected: collection error, `ImportError: cannot import name 'TqdmPercent'`. Once that exists, the `_demucs` tests fail because it still calls `subprocess.run`. The CLI test fails with a `ValueError` traceback.

- [ ] **Step 3: Rewrite the subprocess half of `separation.py`**

In `apps/worker/src/guitarvis_worker/stages/separation.py`, add `import codecs`, `import io` and `import re` to the imports, and change `from typing import TYPE_CHECKING` to `from typing import TYPE_CHECKING, cast`. Add below `_span`:

```python
_TAIL_CHARS = 500  # of Demucs's output, kept for the failure message
_READ_SIZE = 4096


class TqdmPercent:
    """Pull the percentages out of a tqdm bar as it streams.

    Demucs draws its progress with tqdm, which redraws one line with `\\r`, so
    the output has no newlines to split on and a read can end mid-number.
    This keeps the unmatched tail of each chunk and prepends it to the next.
    Demucs's output is not an API: if its format changes, this finds nothing
    and progress jumps from 0 to 40% exactly as it did before.
    """

    _PATTERN = re.compile(r"(\d{1,3})%\|")
    _CARRY = 8  # longer than any partial "100%|"

    def __init__(self) -> None:
        self._carry = ""

    def feed(self, chunk: str) -> list[int]:
        text = self._carry + chunk
        found: list[int] = []
        consumed = 0
        for match in self._PATTERN.finditer(text):
            value = int(match.group(1))
            if value <= 100:
                found.append(value)
            consumed = match.end()
        self._carry = text[consumed:][-self._CARRY :]
        return found
```

Replace the constructor with:

```python
    def __init__(
        self,
        *,
        work_dir: Path,
        model: str = "htdemucs_6s",
        fallback_model: str = "htdemucs",
        device: str | None = None,
    ) -> None:
        self.model = model
        self.fallback_model = fallback_model
        self.device = device
        # Required: a default of "next to the audio" left stems beside every
        # downloaded job file in a long-lived worker (003's review notes).
        # Stems land directly in it, so `--stems-dir X` writes to X.
        self.work_dir = work_dir
```

Replace the body of `_demucs` (keep the signature from Task 2) with:

```python
"""Run Demucs as a subprocess and return the requested stem.

A subprocess rather than the Python API: the CLI is stable across
releases, and a model that dies cannot take the worker down with it.
stderr is merged into stdout and read as it arrives, because that is
where tqdm draws the bar that progress is parsed from.
"""

command = [
    sys.executable,
    "-m",
    "demucs",
    "-n",
    model,
    "-o",
    str(self.work_dir),
    str(audio_path),
]
if self.device:
    command += ["-d", self.device]

try:
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
except FileNotFoundError as exc:
    raise PipelineError(
        FailureReason.INTERNAL,
        "demucs is not installed. Run `uv sync --extra ml`.",
    ) from exc

try:
    tail = _stream(process, progress)
    exit_code = process.wait()
finally:
    # A job timeout, or a progress write that fails, raises in here.
    # The Demucs child must not outlive the job that started it.
    if process.poll() is None:
        process.kill()
        process.wait()

if exit_code != 0:
    raise PipelineError(
        FailureReason.INTERNAL, f"Separation failed: {tail[-_TAIL_CHARS:]}"
    )

stem = self.work_dir / model / audio_path.stem / f"{stem_name}.wav"
if not stem.exists():
    raise PipelineError(
        FailureReason.INTERNAL, f"Separation produced no stem at {stem}"
    )
return stem
```

Add this module-level function after the class (before the `TYPE_CHECKING` block):

```python
def _stream(
    process: "subprocess.Popen[bytes]", progress: SeparationProgress | None
) -> str:
    """Read the child's output as it arrives, report progress, return the tail.

    `read1` returns whatever the pipe holds rather than waiting to fill a
    buffer, so progress is reported as Demucs draws it. The incremental
    decoder keeps a multi-byte bar character split across reads intact.
    """
    stdout = cast(io.BufferedIOBase, process.stdout)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    percents = TqdmPercent()
    tail = ""
    while chunk := stdout.read1(_READ_SIZE):
        text = decoder.decode(chunk)
        tail = (tail + text)[-_TAIL_CHARS:]
        for percent in percents.feed(text):
            if progress is not None:
                progress(percent / 100)
    return tail
```

Change the `TYPE_CHECKING` conformance assignment to `_conforms: Separator = DemucsSeparator(work_dir=Path())`.

- [ ] **Step 4: Guard the CLI's output write**

In `apps/worker/src/guitarvis_worker/cli.py`, change `except OSError as error:` (the one around `Path(args.output).write_text(...)`) to:

```python
    except Exception as error:  # OSError, or anything serialising raised
```

- [ ] **Step 5: Run the worker suite**

Run: `uv run pytest apps/worker -v`
Expected: all PASS. `test_stems_dir_option_keeps_the_directory_in_place` still passes: the CLI hands `--stems-dir` straight through as `work_dir`, and the separator now writes into it directly.

Run: `uv run mypy apps/worker/src apps/worker/tests`
Expected: `Success`.

- [ ] **Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add apps/worker
git commit -m "feat(separation): stream Demucs output and report its progress

Popen with merged output, read as it arrives; tqdm's NN%| becomes progress.
The child is killed if anything raises while it runs. work_dir is required
and stems land directly in it, so --stems-dir X writes to X. The CLI's output
write is guarded against any exception.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `guitarvis_jobs`: the package, `Settings`, the job record and `JobStore`

A new workspace member both apps will depend on. This task gives it the settings, the job record, the `JobStore` protocol and its in-memory twin, plus a contract suite that Task 6 runs against Postgres too. The package depends on `guitarvis_core` alone for now; each later task adds the third-party libraries it needs.

**Files:**
- Create: `packages/jobs/pyproject.toml`
- Create: `packages/jobs/src/guitarvis_jobs/__init__.py`, `py.typed` (empty), `settings.py`, `models.py`, `store.py`, `testing.py`
- Create: `packages/jobs/tests/test_settings.py`, `test_job_store.py`, `test_jobs_package.py`
- Modify: `pyproject.toml` (root: dependency, workspace member, source)
- Modify: `Makefile` (`PY_SOURCES`)
- Modify: `packages/core/tests/test_py_typed_markers.py` (`WORKSPACE_PACKAGES`)

**Interfaces:**
- Consumes: `guitarvis_core.contracts.FailureReason`.
- Produces:
  - `guitarvis_jobs.settings.Settings`, a frozen dataclass. Fields: `database_url`, `redis_url`, `s3_endpoint`, `s3_public_endpoint`, `s3_access_key`, `s3_secret_key`, `s3_bucket`, `s3_region` (all `str`); `max_upload_mb`, `max_active_jobs_per_ip`, `job_timeout_sec` (`int`); `device: str | None`. Also `max_upload_bytes -> int` and `Settings.from_env(environ: Mapping[str, str] | None = None) -> Settings`, which reads `GUITARVIS_<FIELD_NAME_UPPER>`.
  - `guitarvis_jobs.models`: `JobStatus` (StrEnum: `queued`, `running`, `succeeded`, `failed`), `ACTIVE_STATUSES`, `FINISHED_STATUSES` (frozensets), `NewJob(content_hash, title, duration_sec, upload_key, client_ip)`, `Job` (every column in the spec's table; `status: JobStatus`; `failure_reason: FailureReason | None`; `document: dict[str, Any] | None`; tz-aware `created_at`/`updated_at`), `canonical_id(raw: str) -> str | None`, `INTERNAL_FAILURE_MESSAGE`.
  - `guitarvis_jobs.store`: `Clock = Callable[[], datetime]`, `utc_now()`, the `JobStore` Protocol (methods below), and `InMemoryJobStore(clock: Clock = utc_now)`.
    - `create(new) -> tuple[Job, bool]`
    - `get(job_id) -> Job | None`
    - `find_live(content_hash) -> Job | None`
    - `count_active(client_ip) -> int`
    - `mark_running(job_id) -> Job | None`
    - `set_progress(job_id, stage, percent) -> bool`
    - `succeed(job_id, *, document, stem_key) -> bool`
    - `fail(job_id, *, reason, message, stage, expect, expect_updated_at=None) -> bool`
    - `requeue(job_id) -> bool`
    - `ping() -> None`
  - `guitarvis_jobs.testing`: `FakeClock` (callable; `.now`; `.advance(**timedelta_kwargs)`) and `sample_new_job(*, content_hash="a"*64, title="song", duration_sec=30.0, upload_key=None, client_ip="203.0.113.7") -> NewJob`.

- [ ] **Step 1: Create the package skeleton**

`packages/jobs/pyproject.toml`:

```toml
[project]
name = "guitarvis-jobs"
version = "0.1.0"
description = "Job state the api and the worker share: store, blobs, queue, settings."
requires-python = ">=3.12"
dependencies = ["guitarvis-core"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/guitarvis_jobs"]
```

`packages/jobs/src/guitarvis_jobs/__init__.py`:

```python
"""Job state shared by the api and the worker.

The api and the worker never import each other — the worker is reachable only
through the queue — so what both must agree on lives here: the job record and
its store, the blob store, the queue, and the settings that point at all
three. Nothing here imports the ML stack. apps/api/tests/test_boundaries.py
proves it, because importing the api imports this.
"""

__version__ = "0.1.0"
```

Create an empty `packages/jobs/src/guitarvis_jobs/py.typed`.

In the root `pyproject.toml`, add `"guitarvis-jobs",` to `[project].dependencies` after `"guitarvis-core",`; add `"packages/jobs"` to `[tool.uv.workspace].members` after `"packages/core"`; and add `guitarvis-jobs = { workspace = true }` to `[tool.uv.sources]`.

In `Makefile`, change `PY_SOURCES` to:

```make
PY_SOURCES := packages/core/src packages/jobs/src apps/api/src apps/worker/src apps/eval/src \
              packages/core/tests packages/jobs/tests apps/api/tests apps/worker/tests apps/eval/tests
```

In `packages/core/tests/test_py_typed_markers.py`, add to `WORKSPACE_PACKAGES`:

```python
    "guitarvis_jobs": REPO_ROOT / "packages" / "jobs" / "src" / "guitarvis_jobs",
```

Run: `uv lock && uv sync`
Expected: `guitarvis-jobs` resolves as a workspace member.

- [ ] **Step 2: Write the failing settings tests**

`packages/jobs/tests/test_settings.py`:

```python
"""Settings come from GUITARVIS_* variables; the defaults match compose.yaml."""

import pytest
from guitarvis_jobs.settings import Settings


def test_defaults_match_compose_and_the_spec() -> None:
    settings = Settings()

    assert settings.database_url == (
        "postgresql+psycopg://guitarvis:guitarvis@localhost:5432/guitarvis"
    )
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.s3_endpoint == "http://localhost:9000"
    assert settings.s3_public_endpoint == "http://localhost:9000"
    assert settings.s3_bucket == "guitarvis"
    assert settings.max_upload_mb == 150
    assert settings.max_active_jobs_per_ip == 2
    assert settings.job_timeout_sec == 1800
    assert settings.device is None


def test_from_env_reads_prefixed_variables() -> None:
    settings = Settings.from_env(
        {
            "GUITARVIS_REDIS_URL": "redis://elsewhere:6380/2",
            "GUITARVIS_MAX_UPLOAD_MB": "20",
            "GUITARVIS_DEVICE": "cuda",
        }
    )

    assert settings.redis_url == "redis://elsewhere:6380/2"
    assert settings.max_upload_mb == 20
    assert settings.device == "cuda"


def test_an_empty_variable_means_the_default() -> None:
    assert Settings.from_env({"GUITARVIS_MAX_UPLOAD_MB": ""}).max_upload_mb == 150


def test_unrelated_variables_are_ignored() -> None:
    assert Settings.from_env({"DATABASE_URL": "x", "GUITARVIS_NOPE": "y"}) == Settings()


def test_a_malformed_number_names_the_variable() -> None:
    with pytest.raises(ValueError, match="GUITARVIS_JOB_TIMEOUT_SEC"):
        Settings.from_env({"GUITARVIS_JOB_TIMEOUT_SEC": "half an hour"})


def test_a_limit_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        Settings.from_env({"GUITARVIS_MAX_ACTIVE_JOBS_PER_IP": "0"})


def test_from_env_defaults_to_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GUITARVIS_S3_BUCKET", "other")

    assert Settings.from_env().s3_bucket == "other"


def test_max_upload_bytes_is_mebibytes() -> None:
    assert Settings(max_upload_mb=2).max_upload_bytes == 2 * 1024 * 1024
```

Run: `uv run pytest packages/jobs/tests/test_settings.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'guitarvis_jobs.settings'`.

- [ ] **Step 3: Implement `settings.py`**

```python
"""Where the services are, and the limits the api enforces.

A frozen stdlib dataclass read from GUITARVIS_* environment variables — one
per field, named after it. The defaults match compose.yaml, so local
development needs no env file.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

_PREFIX = "GUITARVIS_"


@dataclass(frozen=True)
class Settings:
    database_url: str = (
        "postgresql+psycopg://guitarvis:guitarvis@localhost:5432/guitarvis"
    )
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    # Presigned URLs are signed for this host, because a browser has to reach
    # it. It differs from s3_endpoint once the api runs somewhere a browser
    # cannot address by the same name.
    s3_public_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "guitarvis"
    s3_secret_key: str = "guitarvis-secret"
    s3_bucket: str = "guitarvis"
    s3_region: str = "us-east-1"
    max_upload_mb: int = 150  # a ten-minute 16-bit stereo WAV is about 106 MB
    max_active_jobs_per_ip: int = 2
    job_timeout_sec: int = 1800
    device: str | None = None  # worker only: the torch device, e.g. "cuda"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        values: dict[str, Any] = {}
        for field in fields(cls):
            name = _PREFIX + field.name.upper()
            raw = env.get(name, "")
            if raw == "":
                continue
            values[field.name] = _parse_int(name, raw) if field.type is int else raw
        return cls(**values)


def _parse_int(name: str, raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got {value}")
    return value
```

Run: `uv run pytest packages/jobs/tests/test_settings.py -v`
Expected: 8 PASS.

- [ ] **Step 4: Write the failing store contract suite**

`packages/jobs/tests/test_job_store.py`:

```python
"""The JobStore contract. Task 6 adds a "postgres" param, so these same
tests run against the database the system actually uses, and the in-memory
twin cannot quietly drift from it."""

from collections.abc import Iterator

import pytest
from guitarvis_core.contracts import FailureReason
from guitarvis_jobs.models import JobStatus
from guitarvis_jobs.store import InMemoryJobStore, JobStore
from guitarvis_jobs.testing import FakeClock, sample_new_job

HASH_B = "b" * 64


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture(params=["memory"])
def store(request: pytest.FixtureRequest, clock: FakeClock) -> Iterator[JobStore]:
    yield InMemoryJobStore(clock=clock)


def running(store: JobStore, content_hash: str = "a" * 64) -> str:
    job, _ = store.create(sample_new_job(content_hash=content_hash))
    assert store.mark_running(job.id) is not None
    return job.id


def test_create_returns_a_queued_job(store: JobStore, clock: FakeClock) -> None:
    job, created = store.create(sample_new_job())

    assert created
    assert job.status is JobStatus.QUEUED
    assert (job.stage, job.percent, job.attempts) == (None, 0, 0)
    assert (job.title, job.duration_sec, job.client_ip) == ("song", 30.0, "203.0.113.7")
    assert job.failure_reason is None and job.document is None
    assert job.created_at == job.updated_at == clock.now
    assert store.get(job.id) == job


def test_create_dedupes_a_live_job_with_the_same_hash(store: JobStore) -> None:
    first, _ = store.create(sample_new_job())
    second, created = store.create(sample_new_job(client_ip="198.51.100.1"))

    assert not created
    assert second.id == first.id


def test_a_failed_job_does_not_block_a_new_one(store: JobStore) -> None:
    first, _ = store.create(sample_new_job())
    store.fail(
        first.id,
        reason=FailureReason.INTERNAL,
        message="m",
        stage=None,
        expect=JobStatus.QUEUED,
    )

    second, created = store.create(sample_new_job())

    assert created
    assert second.id != first.id


def test_a_succeeded_job_is_returned_rather_than_redone(store: JobStore) -> None:
    job_id = running(store)
    store.succeed(job_id, document={"notes": []}, stem_key="cache/stem.wav")

    again, created = store.create(sample_new_job())

    assert not created
    assert again.id == job_id
    assert again.status is JobStatus.SUCCEEDED


def test_get_returns_none_for_unknown_and_malformed_ids(store: JobStore) -> None:
    assert store.get("5f0c6c2e-0000-4000-8000-000000000000") is None
    assert store.get("not-a-uuid") is None
    assert store.get("") is None


def test_get_accepts_an_uppercase_id(store: JobStore) -> None:
    job, _ = store.create(sample_new_job())

    found = store.get(job.id.upper())

    assert found is not None and found.id == job.id


def test_find_live_ignores_failed_jobs(store: JobStore) -> None:
    job, _ = store.create(sample_new_job())
    assert store.find_live(job.content_hash) == job

    store.fail(
        job.id,
        reason=FailureReason.INTERNAL,
        message="m",
        stage=None,
        expect=JobStatus.QUEUED,
    )

    assert store.find_live(job.content_hash) is None


def test_count_active_counts_queued_and_running_for_one_ip(store: JobStore) -> None:
    store.create(sample_new_job())
    running(store, content_hash=HASH_B)
    done = running(store, content_hash="c" * 64)
    store.succeed(done, document={}, stem_key="k")
    store.create(sample_new_job(content_hash="d" * 64, client_ip="198.51.100.1"))

    assert store.count_active("203.0.113.7") == 2
    assert store.count_active("198.51.100.1") == 1
    assert store.count_active("192.0.2.1") == 0


def test_mark_running_starts_an_attempt(store: JobStore, clock: FakeClock) -> None:
    job, _ = store.create(sample_new_job())
    clock.advance(seconds=5)

    started = store.mark_running(job.id)

    assert started is not None
    assert started.status is JobStatus.RUNNING
    assert started.attempts == 1
    assert started.updated_at == clock.now


def test_mark_running_accepts_a_row_already_running(store: JobStore) -> None:
    # A worker killed outright never ran its except; RQ's retry finds the
    # row still running and must be allowed to start again.
    job_id = running(store)

    again = store.mark_running(job_id)

    assert again is not None and again.attempts == 2


def test_mark_running_refuses_a_finished_row(store: JobStore) -> None:
    job_id = running(store)
    store.succeed(job_id, document={}, stem_key="k")

    assert store.mark_running(job_id) is None
    assert store.mark_running("not-a-uuid") is None


def test_set_progress_only_while_running(store: JobStore) -> None:
    job, _ = store.create(sample_new_job())
    assert not store.set_progress(job.id, "separation", 5)

    store.mark_running(job.id)
    assert store.set_progress(job.id, "separation", 12)

    row = store.get(job.id)
    assert row is not None and (row.stage, row.percent) == ("separation", 12)


def test_succeed_stores_the_document_and_stem(store: JobStore) -> None:
    job_id = running(store)
    store.set_progress(job_id, "fretboard", 80)
    document = {"notes": [{"id": "n_0000", "t": 1.5}], "warnings": ["w"]}

    assert store.succeed(job_id, document=document, stem_key="cache/v1/x/stem.wav")

    row = store.get(job_id)
    assert row is not None
    assert row.status is JobStatus.SUCCEEDED
    assert (row.stage, row.percent) == (None, 100)
    assert row.document == document
    assert row.stem_key == "cache/v1/x/stem.wav"


def test_the_stored_document_is_a_copy(store: JobStore) -> None:
    job_id = running(store)
    document: dict[str, object] = {"warnings": []}
    store.succeed(job_id, document=document, stem_key="k")

    document["warnings"] = ["changed after the fact"]

    row = store.get(job_id)
    assert row is not None and row.document == {"warnings": []}


def test_a_late_success_after_the_row_was_failed_changes_nothing(
    store: JobStore,
) -> None:
    job_id = running(store)
    store.fail(
        job_id,
        reason=FailureReason.INTERNAL,
        message="lost",
        stage="separation",
        expect=JobStatus.RUNNING,
    )

    assert not store.succeed(job_id, document={}, stem_key="k")
    row = store.get(job_id)
    assert row is not None and row.status is JobStatus.FAILED


def test_fail_records_reason_message_and_stage(store: JobStore) -> None:
    job_id = running(store)
    store.set_progress(job_id, "separation", 20)

    assert store.fail(
        job_id,
        reason=FailureReason.NO_GUITAR_DETECTED,
        message="No clear guitar part was found in this recording.",
        stage="separation",
        expect=JobStatus.RUNNING,
    )

    row = store.get(job_id)
    assert row is not None
    assert row.status is JobStatus.FAILED
    assert row.failure_reason is FailureReason.NO_GUITAR_DETECTED
    assert row.failure_message == "No clear guitar part was found in this recording."
    assert row.failed_stage == "separation"
    assert row.stage is None


def test_fail_with_the_wrong_expected_status_changes_nothing(store: JobStore) -> None:
    job, _ = store.create(sample_new_job())

    assert not store.fail(
        job.id,
        reason=FailureReason.INTERNAL,
        message="m",
        stage=None,
        expect=JobStatus.RUNNING,
    )
    assert store.get(job.id) == job


def test_fail_with_a_stale_updated_at_changes_nothing(
    store: JobStore, clock: FakeClock
) -> None:
    job_id = running(store)
    seen = store.get(job_id)
    assert seen is not None
    clock.advance(seconds=1)
    store.set_progress(job_id, "separation", 3)  # the worker wrote first

    assert not store.fail(
        job_id,
        reason=FailureReason.INTERNAL,
        message="m",
        stage=None,
        expect=JobStatus.RUNNING,
        expect_updated_at=seen.updated_at,
    )
    row = store.get(job_id)
    assert row is not None and row.status is JobStatus.RUNNING


def test_requeue_resets_stage_and_percent_but_keeps_attempts(store: JobStore) -> None:
    job_id = running(store)
    store.set_progress(job_id, "transcription", 40)

    assert store.requeue(job_id)

    row = store.get(job_id)
    assert row is not None
    assert row.status is JobStatus.QUEUED
    assert (row.stage, row.percent, row.attempts) == (None, 0, 1)
    assert not store.requeue(job_id)  # only a running row goes back


def test_ping_answers(store: JobStore) -> None:
    store.ping()
```

`packages/jobs/tests/test_jobs_package.py`:

```python
"""guitarvis_jobs sits between the api and the worker, so it must pull in
neither of them, and nothing from the ML stack."""

import subprocess
import sys

FORBIDDEN_ROOTS = {
    "torch",
    "demucs",
    "basic_pitch",
    "librosa",
    "numpy",
    "guitarvis_worker",
    "guitarvis_api",
}


def test_jobs_exposes_a_version() -> None:
    import guitarvis_jobs

    assert guitarvis_jobs.__version__ == "0.1.0"


def test_importing_every_jobs_module_loads_nothing_forbidden() -> None:
    probe = (
        "import importlib, pkgutil, sys, guitarvis_jobs as package;"
        "[importlib.import_module(m.name) for m in "
        "pkgutil.walk_packages(package.__path__, 'guitarvis_jobs.') "
        "if m.name != 'guitarvis_jobs.testing'];"
        "leaked = {name.split('.')[0] for name in sys.modules}"
        f" & {FORBIDDEN_ROOTS!r};"
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "", (
        f"importing guitarvis_jobs pulled in: {result.stdout.strip()}"
    )
```

Run: `uv run pytest packages/jobs/tests -v`
Expected: `test_job_store.py` fails to collect (`No module named 'guitarvis_jobs.models'`), and the package tests pass.

- [ ] **Step 5: Implement `models.py`**

```python
"""The job record, as the api and the worker both see it."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from guitarvis_core.contracts import FailureReason

# What a user is told when the failure is ours, not their file's.
INTERNAL_FAILURE_MESSAGE = "Something went wrong on our side. Try again later."


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


ACTIVE_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})
FINISHED_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED})


def canonical_id(raw: str) -> str | None:
    """A job id in canonical form, or None when `raw` is not a UUID.

    Ids are UUIDs because they are public and must be unguessable. A
    malformed id is simply a job that does not exist.
    """
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError, TypeError):
        return None


@dataclass(frozen=True)
class NewJob:
    """What an upload contributes to a fresh row."""

    content_hash: str
    title: str
    duration_sec: float
    upload_key: str
    client_ip: str


@dataclass(frozen=True)
class Job:
    """One row of the jobs table; spec 005 describes each column."""

    id: str
    content_hash: str
    status: JobStatus
    stage: str | None
    percent: int
    attempts: int
    failure_reason: FailureReason | None
    failure_message: str | None
    failed_stage: str | None
    title: str
    duration_sec: float
    upload_key: str
    stem_key: str | None
    client_ip: str
    document: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 6: Implement `store.py`**

```python
"""The jobs table's contract, and an in-memory twin of it.

Every write after creation is conditional: it names the status it expects to
find and changes nothing when the row has moved on. That is what lets the
worker, the api's reconciliation and a duplicate RQ delivery race without
corrupting a row. One contract suite (packages/jobs/tests/test_job_store.py)
runs against this and against PostgresJobStore.
"""

import copy
import threading
import uuid
from collections.abc import Callable, Collection
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from guitarvis_core.contracts import FailureReason

from guitarvis_jobs.models import ACTIVE_STATUSES, Job, JobStatus, NewJob, canonical_id

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class JobStore(Protocol):
    def create(self, new: NewJob) -> tuple[Job, bool]:
        """Insert a queued row, or return the live row for this hash.

        Returns the job and whether this call created it. "Live" is any
        status but failed: a failed job never blocks a fresh attempt.
        """
        ...

    def get(self, job_id: str) -> Job | None: ...

    def find_live(self, content_hash: str) -> Job | None: ...

    def count_active(self, client_ip: str) -> int:
        """Jobs from this address that are queued or running."""
        ...

    def mark_running(self, job_id: str) -> Job | None:
        """Start an attempt: running, attempts + 1, stage and percent reset.

        Accepts a row already running: a worker killed outright never ran its
        except, and RQ's retry finds the row as that worker left it. Returns
        None, changing nothing, for a finished or missing row.
        """
        ...

    def set_progress(self, job_id: str, stage: str, percent: int) -> bool: ...

    def succeed(
        self, job_id: str, *, document: dict[str, Any], stem_key: str
    ) -> bool: ...

    def fail(
        self,
        job_id: str,
        *,
        reason: FailureReason,
        message: str,
        stage: str | None,
        expect: JobStatus,
        expect_updated_at: datetime | None = None,
    ) -> bool:
        """Fail the row if it is still `expect` — and, when given, still
        carries `expect_updated_at`, so a writer that got there first wins."""
        ...

    def requeue(self, job_id: str) -> bool:
        """Running back to queued for RQ's retry; attempts are kept."""
        ...

    def ping(self) -> None:
        """Raise if the store cannot be reached."""
        ...


class InMemoryJobStore:
    """Implements JobStore in a dict.

    Locked, because TestClient runs plain-def routes in a threadpool.
    """

    def __init__(self, clock: Clock = utc_now) -> None:
        self._clock = clock
        self._rows: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, new: NewJob) -> tuple[Job, bool]:
        with self._lock:
            live = self._find_live(new.content_hash)
            if live is not None:
                return live, False
            now = self._clock()
            job = Job(
                id=str(uuid.uuid4()),
                content_hash=new.content_hash,
                status=JobStatus.QUEUED,
                stage=None,
                percent=0,
                attempts=0,
                failure_reason=None,
                failure_message=None,
                failed_stage=None,
                title=new.title,
                duration_sec=new.duration_sec,
                upload_key=new.upload_key,
                stem_key=None,
                client_ip=new.client_ip,
                document=None,
                created_at=now,
                updated_at=now,
            )
            self._rows[job.id] = job
            return job, True

    def get(self, job_id: str) -> Job | None:
        key = canonical_id(job_id)
        with self._lock:
            row = None if key is None else self._rows.get(key)
            # A copy, as a database read would be.
            return (
                None
                if row is None
                else replace(row, document=copy.deepcopy(row.document))
            )

    def find_live(self, content_hash: str) -> Job | None:
        with self._lock:
            return self._find_live(content_hash)

    def count_active(self, client_ip: str) -> int:
        with self._lock:
            return sum(
                1
                for row in self._rows.values()
                if row.client_ip == client_ip and row.status in ACTIVE_STATUSES
            )

    def mark_running(self, job_id: str) -> Job | None:
        return self._transition(
            job_id,
            ACTIVE_STATUSES,
            lambda row: replace(
                row,
                status=JobStatus.RUNNING,
                attempts=row.attempts + 1,
                stage=None,
                percent=0,
            ),
        )

    def set_progress(self, job_id: str, stage: str, percent: int) -> bool:
        changed = self._transition(
            job_id,
            {JobStatus.RUNNING},
            lambda row: replace(row, stage=stage, percent=percent),
        )
        return changed is not None

    def succeed(self, job_id: str, *, document: dict[str, Any], stem_key: str) -> bool:
        stored = copy.deepcopy(document)
        changed = self._transition(
            job_id,
            {JobStatus.RUNNING},
            lambda row: replace(
                row,
                status=JobStatus.SUCCEEDED,
                stage=None,
                percent=100,
                document=stored,
                stem_key=stem_key,
            ),
        )
        return changed is not None

    def fail(
        self,
        job_id: str,
        *,
        reason: FailureReason,
        message: str,
        stage: str | None,
        expect: JobStatus,
        expect_updated_at: datetime | None = None,
    ) -> bool:
        changed = self._transition(
            job_id,
            {expect},
            lambda row: replace(
                row,
                status=JobStatus.FAILED,
                stage=None,
                failure_reason=reason,
                failure_message=message,
                failed_stage=stage,
            ),
            expect_updated_at=expect_updated_at,
        )
        return changed is not None

    def requeue(self, job_id: str) -> bool:
        changed = self._transition(
            job_id,
            {JobStatus.RUNNING},
            lambda row: replace(row, status=JobStatus.QUEUED, stage=None, percent=0),
        )
        return changed is not None

    def ping(self) -> None:
        return None

    def _find_live(self, content_hash: str) -> Job | None:
        """Caller holds the lock."""
        return next(
            (
                row
                for row in self._rows.values()
                if row.content_hash == content_hash
                and row.status is not JobStatus.FAILED
            ),
            None,
        )

    def _transition(
        self,
        job_id: str,
        allowed: Collection[JobStatus],
        change: Callable[[Job], Job],
        *,
        expect_updated_at: datetime | None = None,
    ) -> Job | None:
        key = canonical_id(job_id)
        with self._lock:
            row = None if key is None else self._rows.get(key)
            if row is None or row.status not in allowed:
                return None
            if expect_updated_at is not None and row.updated_at != expect_updated_at:
                return None
            updated = replace(change(row), updated_at=self._clock())
            self._rows[row.id] = updated
            return updated


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    _conforms: JobStore = InMemoryJobStore()
```

- [ ] **Step 7: Implement `testing.py`**

```python
"""Test support shared by every package's tests.

Imported by tests only — never by the api or the worker. It lives in the
package rather than in a conftest.py because a second conftest.py anywhere in
PY_SOURCES collides in mypy (see the Makefile).
"""

from datetime import UTC, datetime, timedelta

from guitarvis_jobs.models import NewJob


class FakeClock:
    """A clock a test moves by hand.

    It never ticks on its own, so two writes in one test carry the same
    `updated_at` unless the test advances it between them. Postgres keeps
    microseconds; advance by at least that much.
    """

    def __init__(
        self, start: datetime = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    ) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def sample_new_job(
    *,
    content_hash: str = "a" * 64,
    title: str = "song",
    duration_sec: float = 30.0,
    upload_key: str | None = None,
    client_ip: str = "203.0.113.7",
) -> NewJob:
    return NewJob(
        content_hash=content_hash,
        title=title,
        duration_sec=duration_sec,
        upload_key=upload_key or f"uploads/{content_hash}.mp3",
        client_ip=client_ip,
    )
```

- [ ] **Step 8: Run the jobs suite and the type check**

Run: `uv run pytest packages/jobs packages/core/tests/test_py_typed_markers.py -v`
Expected: all PASS.

Run: `uv run mypy packages/jobs/src packages/jobs/tests`
Expected: `Success`.

- [ ] **Step 9: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add packages/jobs pyproject.toml uv.lock Makefile packages/core/tests/test_py_typed_markers.py
git commit -m "feat(jobs): guitarvis_jobs package with Settings and JobStore

A workspace member the api and worker will share. The JobStore contract
suite runs against an in-memory twin; Postgres joins it next.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `BlobStore` and `JobQueue` contracts, with in-memory twins

The api and worker tests run on these twins. Task 7 adds the S3 and RQ implementations under the same contract suites.

**Files:**
- Create: `packages/jobs/src/guitarvis_jobs/blobs.py`, `packages/jobs/src/guitarvis_jobs/queue.py`
- Create: `packages/jobs/tests/test_blob_store.py`, `packages/jobs/tests/test_job_queue.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `guitarvis_jobs.blobs`: `BlobNotFound(KeyError)`, `PRESIGN_EXPIRES_SEC = 900`, the `BlobStore` Protocol (methods below), and `InMemoryBlobStore`, whose `presign_get` returns `f"memory://{key}?expires={expires_sec}"`.
    - `put_file(key, path)`
    - `put_bytes(key, data)`
    - `get_file(key, path)` (creates parent directories; raises `BlobNotFound` and writes nothing for a missing key)
    - `get_bytes(key) -> bytes` (raises `BlobNotFound`)
    - `exists(key) -> bool`
    - `presign_get(key, *, expires_sec) -> str` (no existence check)
    - `ping()`
  - `guitarvis_jobs.queue`: `RUN_JOB = "guitarvis_worker.runner.run_job"`, `QUEUE_NAME = "jobs"`, `MAX_RETRIES = 2`, `RETRY_INTERVALS_SEC = (10, 60)`, the `JobQueue` Protocol (`enqueue(job_id) -> None`, `exists(job_id) -> bool`, `ping() -> None`), and `InMemoryJobQueue`. The twin has `.enqueued: list[str]`, `.fail_next: bool` (the next `enqueue` raises `ConnectionError`), `.down: bool` (`exists` and `ping` raise `ConnectionError`) and `.lose(job_id)` (forget it, as a flushed Redis would).

- [ ] **Step 1: Write the failing contract suites**

`packages/jobs/tests/test_blob_store.py`:

```python
"""The BlobStore contract. Task 7 adds an "s3" param against RustFS."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from guitarvis_jobs.blobs import (
    PRESIGN_EXPIRES_SEC,
    BlobNotFound,
    BlobStore,
    InMemoryBlobStore,
)


@pytest.fixture(params=["memory"])
def blobs(request: pytest.FixtureRequest) -> Iterator[BlobStore]:
    yield InMemoryBlobStore()


def test_bytes_round_trip(blobs: BlobStore) -> None:
    blobs.put_bytes("cache/v1/h/transcription.json", b'[{"midi": 52}]')

    assert blobs.get_bytes("cache/v1/h/transcription.json") == b'[{"midi": 52}]'


def test_a_file_round_trips_into_a_directory_that_does_not_exist_yet(
    blobs: BlobStore, tmp_path: Path
) -> None:
    source = tmp_path / "stem.wav"
    source.write_bytes(b"RIFF....WAVE")
    blobs.put_file("cache/v1/h/separation/stem.wav", source)

    target = tmp_path / "restored" / "deeper" / "stem.wav"
    blobs.get_file("cache/v1/h/separation/stem.wav", target)

    assert target.read_bytes() == b"RIFF....WAVE"


def test_exists(blobs: BlobStore) -> None:
    assert not blobs.exists("uploads/nothing.mp3")
    blobs.put_bytes("uploads/something.mp3", b"x")
    assert blobs.exists("uploads/something.mp3")


def test_a_put_replaces_what_was_there(blobs: BlobStore) -> None:
    blobs.put_bytes("k", b"old")
    blobs.put_bytes("k", b"new")

    assert blobs.get_bytes("k") == b"new"


def test_a_missing_key_raises_blob_not_found(blobs: BlobStore, tmp_path: Path) -> None:
    with pytest.raises(BlobNotFound):
        blobs.get_bytes("cache/v1/none.json")

    target = tmp_path / "out.wav"
    with pytest.raises(BlobNotFound):
        blobs.get_file("cache/v1/none.wav", target)
    assert not target.exists()


def test_presign_names_the_key(blobs: BlobStore) -> None:
    blobs.put_bytes("uploads/abc.mp3", b"x")

    url = blobs.presign_get("uploads/abc.mp3", expires_sec=PRESIGN_EXPIRES_SEC)

    assert "uploads/abc.mp3" in url


def test_presign_lifetime_is_fifteen_minutes() -> None:
    assert PRESIGN_EXPIRES_SEC == 15 * 60


def test_ping_answers(blobs: BlobStore) -> None:
    blobs.ping()
```

`packages/jobs/tests/test_job_queue.py`:

```python
"""The JobQueue contract. Task 7 adds an "rq" param against Redis."""

from collections.abc import Iterator

import pytest
from guitarvis_jobs.queue import (
    MAX_RETRIES,
    RETRY_INTERVALS_SEC,
    RUN_JOB,
    InMemoryJobQueue,
    JobQueue,
)

JOB_ID = "5f0c6c2e-0000-4000-8000-000000000001"


@pytest.fixture(params=["memory"])
def queue(request: pytest.FixtureRequest) -> Iterator[JobQueue]:
    yield InMemoryJobQueue()


def test_an_enqueued_job_exists(queue: JobQueue) -> None:
    queue.enqueue(JOB_ID)

    assert queue.exists(JOB_ID)


def test_an_unknown_job_does_not_exist(queue: JobQueue) -> None:
    assert not queue.exists("5f0c6c2e-0000-4000-8000-0000000000ff")


def test_ping_answers(queue: JobQueue) -> None:
    queue.ping()


def test_the_job_function_is_named_not_imported() -> None:
    # The api enqueues by this string and never imports the worker. A worker
    # test (Task 9) imports it, so renaming run_job fails CI, not every job.
    assert RUN_JOB == "guitarvis_worker.runner.run_job"


def test_three_attempts_in_all() -> None:
    assert MAX_RETRIES == 2
    assert RETRY_INTERVALS_SEC == (10, 60)


def test_the_twin_can_fail_lose_and_go_down() -> None:
    queue = InMemoryJobQueue()

    queue.fail_next = True
    with pytest.raises(ConnectionError):
        queue.enqueue(JOB_ID)
    queue.enqueue(JOB_ID)  # only the next one failed
    assert queue.enqueued == [JOB_ID]

    queue.lose(JOB_ID)
    assert not queue.exists(JOB_ID)

    queue.down = True
    with pytest.raises(ConnectionError):
        queue.exists(JOB_ID)
    with pytest.raises(ConnectionError):
        queue.ping()
```

Run: `uv run pytest packages/jobs/tests/test_blob_store.py packages/jobs/tests/test_job_queue.py -v`
Expected: collection errors, `No module named 'guitarvis_jobs.blobs'` / `'guitarvis_jobs.queue'`.

- [ ] **Step 2: Implement `blobs.py` (protocol and twin)**

```python
"""Object storage for uploads, stems and cached stage output.

Keys are plain strings laid out as spec 005 describes: `uploads/{hash}{ext}`
for originals, `cache/v{N}/{hash}/...` for stage output.
"""

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

PRESIGN_EXPIRES_SEC = 15 * 60


class BlobNotFound(KeyError):
    """Nothing is stored at that key."""


class BlobStore(Protocol):
    def put_file(self, key: str, path: Path) -> None: ...

    def put_bytes(self, key: str, data: bytes) -> None: ...

    def get_file(self, key: str, path: Path) -> None:
        """Download to `path`, creating its directory. Raises BlobNotFound,
        writing nothing, when the key is missing."""
        ...

    def get_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def presign_get(self, key: str, *, expires_sec: int) -> str:
        """A URL a browser can GET without credentials. Does not check that
        the key exists; S3 presigning cannot either."""
        ...

    def ping(self) -> None:
        """Raise if the store cannot be reached."""
        ...


class InMemoryBlobStore:
    """Implements BlobStore in a dict."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def put_file(self, key: str, path: Path) -> None:
        self.put_bytes(key, path.read_bytes())

    def put_bytes(self, key: str, data: bytes) -> None:
        with self._lock:
            self._objects[key] = bytes(data)

    def get_file(self, key: str, path: Path) -> None:
        data = self.get_bytes(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        with self._lock:
            try:
                return self._objects[key]
            except KeyError:
                raise BlobNotFound(key) from None

    def exists(self, key: str) -> bool:
        with self._lock:
            return key in self._objects

    def presign_get(self, key: str, *, expires_sec: int) -> str:
        return f"memory://{key}?expires={expires_sec}"

    def ping(self) -> None:
        return None


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    _conforms: BlobStore = InMemoryBlobStore()
```

- [ ] **Step 3: Implement `queue.py` (protocol and twin)**

```python
"""The queue. Postgres is the record (ADR 0007); Redis carries job ids only.

The api enqueues the worker's entry point by its dotted path, so it never
imports the function it schedules — the worker is reachable only through the
queue. The RQ job id is the GuitarVis job id.
"""

import threading
from typing import TYPE_CHECKING, Protocol

RUN_JOB = "guitarvis_worker.runner.run_job"
QUEUE_NAME = "jobs"
MAX_RETRIES = 2  # three attempts in all, as spec 001 asks
RETRY_INTERVALS_SEC = (10, 60)


class JobQueue(Protocol):
    def enqueue(self, job_id: str) -> None: ...

    def exists(self, job_id: str) -> bool:
        """Whether the queue still knows this job, in any state."""
        ...

    def ping(self) -> None:
        """Raise if the queue cannot be reached."""
        ...


class InMemoryJobQueue:
    """Implements JobQueue by recording what was enqueued.

    `fail_next` makes the next enqueue raise; `down` makes `exists` and
    `ping` raise; `lose` forgets a job, as a flushed Redis would.
    """

    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.fail_next = False
        self.down = False
        self._known: set[str] = set()
        self._lock = threading.Lock()

    def enqueue(self, job_id: str) -> None:
        with self._lock:
            if self.fail_next:
                self.fail_next = False
                raise ConnectionError("queue unavailable")
            self.enqueued.append(job_id)
            self._known.add(job_id)

    def exists(self, job_id: str) -> bool:
        self.ping()
        with self._lock:
            return job_id in self._known

    def lose(self, job_id: str) -> None:
        with self._lock:
            self._known.discard(job_id)

    def ping(self) -> None:
        if self.down:
            raise ConnectionError("queue unavailable")


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    _conforms: JobQueue = InMemoryJobQueue()
```

- [ ] **Step 4: Run the suites**

Run: `uv run pytest packages/jobs -v && uv run mypy packages/jobs/src packages/jobs/tests`
Expected: all PASS; mypy `Success`.

- [ ] **Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add packages/jobs
git commit -m "feat(jobs): BlobStore and JobQueue contracts with in-memory twins

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Local services, the Postgres store and its migration

`compose.yaml` brings up all three services; this task uses Postgres, and Task 7 uses the other two. The `JobStore` contract suite gains a `postgres` param. Tests reach the services through `guitarvis_jobs.testing.require`. It skips when a service is down, unless `GUITARVIS_REQUIRE_SERVICES=1`, in which case it fails. The spec is amended here to name RustFS.

**Files:**
- Create: `compose.yaml`, `deploy/postgres-init/01-test-database.sql`
- Create: `packages/jobs/src/guitarvis_jobs/postgres.py`, `migrate.py`
- Create: `packages/jobs/src/guitarvis_jobs/migrations/env.py`, `packages/jobs/src/guitarvis_jobs/migrations/versions/r0001_create_jobs.py`
- Create: `packages/jobs/tests/test_migrations.py`
- Modify: `packages/jobs/pyproject.toml` (dependencies)
- Modify: `packages/jobs/src/guitarvis_jobs/testing.py` (append)
- Modify: `packages/jobs/tests/test_job_store.py` (fixture param; one new test)
- Modify: `Makefile` (`services`, `migrate`)
- Modify: `docs/specs/005-api-job-queue/spec.md`, `docs/specs/001-guitarvis-design/spec.md:74` (RustFS)

**Interfaces:**
- Consumes: `JobStore`, `Clock`, `utc_now`, `Job`, `NewJob`, `JobStatus`, `ACTIVE_STATUSES`, `canonical_id`, `Settings` (Task 4).
- Produces:
  - `guitarvis_jobs.postgres.metadata` and `.jobs` (a `sa.Table`); `PostgresJobStore(engine: sa.Engine, clock: Clock = utc_now)` implementing `JobStore`, with `.engine` and `PostgresJobStore.from_url(url: str, clock: Clock = utc_now)`.
  - `guitarvis_jobs.migrate.MIGRATIONS: Path`, `alembic_config(database_url) -> Config`, `upgrade(database_url) -> None`, `main() -> int`.
  - `guitarvis_jobs.testing.REQUIRE_SERVICES_ENV = "GUITARVIS_REQUIRE_SERVICES"`, `TEST_DATABASE`, `TEST_REDIS_DB`, `TEST_BUCKET`, `integration_settings() -> Settings`, `require(service: str) -> None` (services: `"postgres"`; Task 7 adds `"redis"` and `"storage"`), and the context manager `postgres_store(clock: Clock = utc_now) -> Iterator[PostgresJobStore]`, which yields an empty, migrated test database.

- [ ] **Step 1: Add the services**

`compose.yaml`:

```yaml
# Postgres, Redis and S3-compatible object storage for `make api` and
# `make worker`, which run on the host. `make services` starts them and
# returns once every healthcheck passes; `docker compose down` stops them
# (add -v to delete their data).
#
# RustFS rather than MinIO: MinIO's community edition is archived and its
# images are no longer published. The code speaks plain S3 through boto3, so
# this is the only file that names the server.

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: guitarvis
      POSTGRES_PASSWORD: guitarvis
      POSTGRES_DB: guitarvis
    ports:
      - "5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
      # Runs once, on a fresh volume: creates guitarvis_test beside guitarvis.
      - ./deploy/postgres-init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      # Over TCP on purpose: during first-run initialisation Postgres listens
      # on its socket only, and a socket check would pass before it is ready.
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U guitarvis -d guitarvis"]
      interval: 2s
      timeout: 3s
      retries: 30

  redis:
    image: redis:7
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      timeout: 3s
      retries: 30

  storage:
    image: rustfs/rustfs:1.0.1
    environment:
      RUSTFS_ACCESS_KEY: guitarvis
      RUSTFS_SECRET_KEY: guitarvis-secret
    ports:
      - "9000:9000"
      - "9001:9001"  # web console
    volumes:
      - storage-data:/data
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:9000/health"]
      interval: 2s
      timeout: 3s
      retries: 30

volumes:
  postgres-data:
  storage-data:
```

`deploy/postgres-init/01-test-database.sql`:

```sql
-- The integration suite's database. It never shares one with `make api`.
CREATE DATABASE guitarvis_test;
```

In `Makefile`, add `services migrate` to `.PHONY` and add after the `eval-data` target:

```make
services: ## Start Postgres, Redis and object storage (docker compose)
	docker compose up -d --wait

migrate: ## Bring the database schema up to date
	$(UV) run python -m guitarvis_jobs.migrate
```

Run: `make services`
Expected: three containers `Healthy`, and the command returns. If a port is already taken (a local Postgres on 5432, say), stop that service, or change the left-hand side of the port mapping and the matching `GUITARVIS_*` URL.

- [ ] **Step 2: Add the database dependencies**

In `packages/jobs/pyproject.toml`, set:

```toml
dependencies = [
    "guitarvis-core",
    "sqlalchemy>=2.0",
    "psycopg[binary]>=3.2",
    "alembic>=1.13",
]
```

Run: `uv lock && uv sync`
Expected: SQLAlchemy 2.1, psycopg 3.3 and Alembic 1.20 (or newer) are installed.

- [ ] **Step 3: Write the failing tests**

In `packages/jobs/tests/test_job_store.py`, add `from guitarvis_jobs.testing import postgres_store` (beside the existing `guitarvis_jobs.testing` import) and `from concurrent.futures import ThreadPoolExecutor`. Replace the `store` fixture with:

```python
@pytest.fixture(params=["memory", "postgres"])
def store(request: pytest.FixtureRequest, clock: FakeClock) -> Iterator[JobStore]:
    if request.param == "memory":
        yield InMemoryJobStore(clock=clock)
        return
    with postgres_store(clock=clock) as postgres:
        yield postgres
```

and append:

```python
def test_simultaneous_uploads_of_one_file_make_one_job(store: JobStore) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.create(sample_new_job()), range(8)))

    assert sum(created for _, created in results) == 1
    assert len({job.id for job, _ in results}) == 1
```

Create `packages/jobs/tests/test_migrations.py`:

```python
"""The Alembic migration and the table the code queries must agree."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from guitarvis_jobs.migrate import MIGRATIONS, upgrade
from guitarvis_jobs.postgres import metadata
from guitarvis_jobs.testing import integration_settings, postgres_store


def test_the_migrations_build_exactly_the_table_the_code_queries() -> None:
    with postgres_store() as store, store.engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), metadata)

    assert diff == [], f"migrations and postgres.py disagree: {diff}"


def test_upgrading_twice_is_harmless() -> None:
    with postgres_store():
        upgrade(integration_settings().database_url)


def test_migration_files_have_importable_names() -> None:
    # mypy scans packages/jobs/src and derives a module name from each file;
    # Alembic's usual "0001_x.py" is not a valid one.
    versions = sorted((MIGRATIONS / "versions").glob("*.py"))

    assert versions, "no migrations found"
    assert all(path.stem.isidentifier() for path in versions)
```

Run: `uv run pytest packages/jobs/tests/test_job_store.py packages/jobs/tests/test_migrations.py -v`
Expected: collection errors, `cannot import name 'postgres_store'` and `No module named 'guitarvis_jobs.migrate'`.

- [ ] **Step 4: Implement `postgres.py`**

```python
"""The jobs table in Postgres, through SQLAlchemy Core and psycopg 3.

Alembic owns the schema (guitarvis_jobs/migrations). The table below
describes it for queries, and test_migrations.py fails if the two disagree.
Status and reason values go in as plain strings: psycopg would write an
Enum's *name*, not its value.
"""

import uuid
from collections.abc import Collection
from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from guitarvis_core.contracts import FailureReason
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert

from guitarvis_jobs.models import ACTIVE_STATUSES, Job, JobStatus, NewJob, canonical_id
from guitarvis_jobs.store import Clock, utc_now

metadata = sa.MetaData()

jobs = sa.Table(
    "jobs",
    metadata,
    sa.Column("id", UUID(as_uuid=False), primary_key=True),
    sa.Column("content_hash", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("stage", sa.Text(), nullable=True),
    sa.Column("percent", sa.Integer(), nullable=False),
    sa.Column("attempts", sa.Integer(), nullable=False),
    sa.Column("failure_reason", sa.Text(), nullable=True),
    sa.Column("failure_message", sa.Text(), nullable=True),
    sa.Column("failed_stage", sa.Text(), nullable=True),
    sa.Column("title", sa.Text(), nullable=False),
    sa.Column("duration_sec", sa.Float(), nullable=False),
    sa.Column("upload_key", sa.Text(), nullable=False),
    sa.Column("stem_key", sa.Text(), nullable=True),
    sa.Column("client_ip", sa.Text(), nullable=False),
    sa.Column("document", JSONB(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "status IN ('queued', 'running', 'succeeded', 'failed')",
        name="jobs_status_valid",
    ),
    sa.CheckConstraint("percent BETWEEN 0 AND 100", name="jobs_percent_range"),
    # The dedupe rule: one live job per upload; a failed one never blocks.
    sa.Index(
        "jobs_content_hash_live",
        "content_hash",
        unique=True,
        postgresql_where=sa.text("status <> 'failed'"),
    ),
    sa.Index("jobs_client_ip_status", "client_ip", "status"),
)

_LIVE = jobs.c.status != JobStatus.FAILED.value


class PostgresJobStore:
    """Implements JobStore."""

    def __init__(self, engine: sa.Engine, clock: Clock = utc_now) -> None:
        self.engine = engine
        self._clock = clock

    @classmethod
    def from_url(cls, url: str, clock: Clock = utc_now) -> "PostgresJobStore":
        engine = sa.create_engine(
            url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
        )
        return cls(engine, clock)

    def create(self, new: NewJob) -> tuple[Job, bool]:
        # Retried because the live row this insert collided with can fail
        # between the insert and the read; the next insert then succeeds.
        for _ in range(3):
            now = self._clock()
            insert = (
                pg_insert(jobs)
                .values(
                    id=str(uuid.uuid4()),
                    content_hash=new.content_hash,
                    status=JobStatus.QUEUED.value,
                    stage=None,
                    percent=0,
                    attempts=0,
                    title=new.title,
                    duration_sec=new.duration_sec,
                    upload_key=new.upload_key,
                    client_ip=new.client_ip,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=[jobs.c.content_hash], index_where=_LIVE
                )
                .returning(*jobs.c)
            )
            with self.engine.begin() as connection:
                row = connection.execute(insert).mappings().one_or_none()
                if row is not None:
                    return _to_job(row), True
                live = (
                    connection.execute(
                        sa.select(jobs).where(
                            jobs.c.content_hash == new.content_hash, _LIVE
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            if live is not None:
                return _to_job(live), False
        raise RuntimeError(
            f"could neither create nor find a live job for {new.content_hash}"
        )

    def get(self, job_id: str) -> Job | None:
        key = canonical_id(job_id)
        if key is None:
            return None
        return self._one(sa.select(jobs).where(jobs.c.id == key))

    def find_live(self, content_hash: str) -> Job | None:
        return self._one(
            sa.select(jobs).where(jobs.c.content_hash == content_hash, _LIVE)
        )

    def count_active(self, client_ip: str) -> int:
        statement = (
            sa.select(sa.func.count())
            .select_from(jobs)
            .where(
                jobs.c.client_ip == client_ip,
                jobs.c.status.in_([status.value for status in ACTIVE_STATUSES]),
            )
        )
        with self.engine.connect() as connection:
            return int(connection.execute(statement).scalar_one())

    def mark_running(self, job_id: str) -> Job | None:
        return self._update(
            job_id,
            ACTIVE_STATUSES,
            {
                "status": JobStatus.RUNNING.value,
                "attempts": jobs.c.attempts + 1,
                "stage": None,
                "percent": 0,
            },
        )

    def set_progress(self, job_id: str, stage: str, percent: int) -> bool:
        changed = self._update(
            job_id, {JobStatus.RUNNING}, {"stage": stage, "percent": percent}
        )
        return changed is not None

    def succeed(self, job_id: str, *, document: dict[str, Any], stem_key: str) -> bool:
        changed = self._update(
            job_id,
            {JobStatus.RUNNING},
            {
                "status": JobStatus.SUCCEEDED.value,
                "stage": None,
                "percent": 100,
                "document": document,
                "stem_key": stem_key,
            },
        )
        return changed is not None

    def fail(
        self,
        job_id: str,
        *,
        reason: FailureReason,
        message: str,
        stage: str | None,
        expect: JobStatus,
        expect_updated_at: datetime | None = None,
    ) -> bool:
        changed = self._update(
            job_id,
            {expect},
            {
                "status": JobStatus.FAILED.value,
                "stage": None,
                "failure_reason": reason.value,
                "failure_message": message,
                "failed_stage": stage,
            },
            expect_updated_at=expect_updated_at,
        )
        return changed is not None

    def requeue(self, job_id: str) -> bool:
        changed = self._update(
            job_id,
            {JobStatus.RUNNING},
            {"status": JobStatus.QUEUED.value, "stage": None, "percent": 0},
        )
        return changed is not None

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))

    def _one(self, statement: sa.Select[Any]) -> Job | None:
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else _to_job(row)

    def _update(
        self,
        job_id: str,
        allowed: Collection[JobStatus],
        values: dict[str, Any],
        *,
        expect_updated_at: datetime | None = None,
    ) -> Job | None:
        key = canonical_id(job_id)
        if key is None:
            return None
        conditions = [
            jobs.c.id == key,
            jobs.c.status.in_([status.value for status in allowed]),
        ]
        if expect_updated_at is not None:
            conditions.append(jobs.c.updated_at == expect_updated_at)
        statement = (
            sa.update(jobs)
            .where(*conditions)
            .values(updated_at=self._clock(), **values)
            .returning(*jobs.c)
        )
        with self.engine.begin() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else _to_job(row)


def _to_job(row: sa.RowMapping) -> Job:
    reason = row["failure_reason"]
    return Job(
        id=str(row["id"]),
        content_hash=row["content_hash"],
        status=JobStatus(row["status"]),
        stage=row["stage"],
        percent=row["percent"],
        attempts=row["attempts"],
        failure_reason=None if reason is None else FailureReason(reason),
        failure_message=row["failure_message"],
        failed_stage=row["failed_stage"],
        title=row["title"],
        duration_sec=row["duration_sec"],
        upload_key=row["upload_key"],
        stem_key=row["stem_key"],
        client_ip=row["client_ip"],
        document=row["document"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    from guitarvis_jobs.store import JobStore

    _conforms: JobStore = PostgresJobStore(sa.create_engine("postgresql://"))
```

- [ ] **Step 5: Add the migration**

`packages/jobs/src/guitarvis_jobs/migrations/env.py`:

```python
"""Alembic's entry point, run by `python -m guitarvis_jobs.migrate`.

There is no alembic.ini: migrate.py supplies the script location and the
database URL. To add a migration, copy versions/r0001_create_jobs.py to the
next number, set `revision` and `down_revision`, and keep the file name a
valid identifier (test_migrations.py checks).
"""

from alembic import context
from sqlalchemy import create_engine

from guitarvis_jobs.postgres import metadata


def run_migrations() -> None:
    url = context.config.get_main_option("sqlalchemy.url")
    if url is None:
        raise RuntimeError("no database URL; run `python -m guitarvis_jobs.migrate`")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported.")
run_migrations()
```

`packages/jobs/src/guitarvis_jobs/migrations/versions/r0001_create_jobs.py`:

```python
"""Create the jobs table.

Revision ID: 0001
Revises: (none)
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("percent", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("failed_stage", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("duration_sec", sa.Float(), nullable=False),
        sa.Column("upload_key", sa.Text(), nullable=False),
        sa.Column("stem_key", sa.Text(), nullable=True),
        sa.Column("client_ip", sa.Text(), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="jobs_status_valid",
        ),
        sa.CheckConstraint("percent BETWEEN 0 AND 100", name="jobs_percent_range"),
    )
    op.create_index(
        "jobs_content_hash_live",
        "jobs",
        ["content_hash"],
        unique=True,
        postgresql_where=sa.text("status <> 'failed'"),
    )
    op.create_index("jobs_client_ip_status", "jobs", ["client_ip", "status"])


def downgrade() -> None:
    op.drop_table("jobs")
```

`packages/jobs/src/guitarvis_jobs/migrate.py`:

```python
"""`make migrate`: bring the database up to date.

There is no alembic.ini. The database URL comes from Settings like every
other address, and the migrations ship inside the package.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from guitarvis_jobs.settings import Settings

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    # ConfigParser interpolates %, which a URL-encoded password can contain.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")


def main() -> int:
    settings = Settings.from_env()
    upgrade(settings.database_url)
    shown = make_url(settings.database_url).render_as_string(hide_password=True)
    print(f"database up to date: {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Add the integration helpers to `testing.py`**

Replace the imports at the top of `packages/jobs/src/guitarvis_jobs/testing.py` with:

```python
import functools
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from guitarvis_jobs.migrate import upgrade
from guitarvis_jobs.models import NewJob
from guitarvis_jobs.postgres import PostgresJobStore
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.store import Clock, utc_now
```

and append:

```python
REQUIRE_SERVICES_ENV = "GUITARVIS_REQUIRE_SERVICES"
TEST_DATABASE = "guitarvis_test"
TEST_REDIS_DB = 15
TEST_BUCKET = "guitarvis-test"


def integration_settings() -> Settings:
    """The environment's settings, pointed at the test database, Redis db 15
    and the test bucket — never at the stores `make api` uses."""
    base = Settings.from_env()
    return replace(
        base,
        database_url=make_url(base.database_url)
        .set(database=TEST_DATABASE)
        .render_as_string(hide_password=False),
        redis_url=urlunsplit(
            urlsplit(base.redis_url)._replace(path=f"/{TEST_REDIS_DB}")
        ),
        s3_bucket=TEST_BUCKET,
    )


def require(service: str) -> None:
    """Skip the calling test when `service` is down — or fail it, when
    GUITARVIS_REQUIRE_SERVICES=1 says every service must be up, as in CI."""
    problem = _probe(service)
    if problem is None:
        return
    message = f"{service} is not reachable ({problem}). Run `make services`."
    if os.environ.get(REQUIRE_SERVICES_ENV) == "1":
        pytest.fail(message, pytrace=False)
    pytest.skip(message)


def _ping_postgres(settings: Settings) -> None:
    engine = sa.create_engine(
        settings.database_url, connect_args={"connect_timeout": 2}
    )
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    finally:
        engine.dispose()


_PINGS: dict[str, Callable[[Settings], None]] = {"postgres": _ping_postgres}


@functools.cache
def _probe(service: str) -> str | None:
    """None when `service` answers, else why not. Asked once per process."""
    ping = _PINGS[service]  # a typo is a KeyError, never a silent skip
    try:
        ping(integration_settings())
    except Exception as exc:
        return f"{exc.__class__.__name__}: {exc}"
    return None


@contextmanager
def postgres_store(clock: Clock = utc_now) -> Iterator[PostgresJobStore]:
    """A PostgresJobStore on the migrated test database, empty before and after."""
    require("postgres")
    url = integration_settings().database_url
    _migrate_once(url)
    store = PostgresJobStore.from_url(url, clock=clock)
    _truncate(store)
    try:
        yield store
    finally:
        _truncate(store)
        store.engine.dispose()


@functools.cache
def _migrate_once(database_url: str) -> None:
    upgrade(database_url)


def _truncate(store: PostgresJobStore) -> None:
    with store.engine.begin() as connection:
        connection.execute(sa.text("TRUNCATE jobs"))
```

- [ ] **Step 7: Run the suites against real Postgres**

Run: `uv run pytest packages/jobs -v`
Expected: every `test_job_store.py` test runs twice (`[memory]` and `[postgres]`) and passes, and the three migration tests pass.

Run: `docker compose stop postgres && uv run pytest packages/jobs/tests/test_job_store.py -q; GUITARVIS_REQUIRE_SERVICES=1 uv run pytest packages/jobs/tests/test_job_store.py -q; make services`
Expected: the first run reports the `[postgres]` tests as skipped ("postgres is not reachable … Run `make services`"). The second reports them as failed with the same message. `make services` brings Postgres back and waits until it is healthy.

Run: `make migrate`
Expected: `database up to date: postgresql+psycopg://guitarvis:***@localhost:5432/guitarvis`.

Run: `uv run mypy packages/jobs/src packages/jobs/tests`
Expected: `Success`.

- [ ] **Step 8: Amend the spec to name RustFS**

In `docs/specs/005-api-job-queue/spec.md`:

- After the `**Status:**` line, add: `**Amended:** 2026-10-08 — RustFS replaces MinIO, whose community edition is archived and no longer published as an image. The bucket is created by `make migrate` through boto3 rather than by a one-shot `mc` container.`
- Success condition 4: `against real Postgres, Redis and MinIO` → `against real Postgres, Redis and RustFS`.
- The components diagram: `Postgres       MinIO       Redis (RQ)` → `Postgres      RustFS       Redis (RQ)`.
- `S3BlobStore` (boto3; MinIO locally, any S3 later) → (boto3; RustFS locally, any S3 later).
- Failure paragraph: `MinIO or Postgres unreachable` → `Object storage or Postgres unreachable`.
- HTTP table: `naming which of Postgres, Redis, MinIO did not answer` → `naming which of Postgres, Redis, object storage did not answer`.
- `a presigned MinIO URL` → `a presigned object-storage URL`; `MinIO already answers` → `S3 storage already answers`.
- Replace the first sentence of *Running it* with: `` `compose.yaml` at the root runs `postgres:16`, `redis:7` and RustFS (`rustfs/rustfs:1.0.1`), with a Postgres init script that also creates `guitarvis_test`; `make migrate` creates the bucket. ``
- Testing: `against Postgres and MinIO` → `against Postgres and RustFS`.
- Consequences: `Uploads and stems stay in MinIO indefinitely` → `Uploads and stems stay in object storage indefinitely`.

In `docs/specs/001-guitarvis-design/spec.md:74`, `MinIO locally` → `RustFS locally`.

Run: `grep -n -i minio docs/specs/005-api-job-queue/spec.md docs/specs/001-guitarvis-design/spec.md`
Expected: only the new *Amended* line.

- [ ] **Step 9: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add compose.yaml deploy Makefile packages/jobs uv.lock docs/specs/005-api-job-queue/spec.md docs/specs/001-guitarvis-design/spec.md
git commit -m "feat(jobs): Postgres job store, first migration, local services

compose.yaml runs Postgres, Redis and RustFS (MinIO's community images are
gone). The JobStore contract suite now runs against Postgres too; it skips
when services are down unless GUITARVIS_REQUIRE_SERVICES=1.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: S3 blobs and the RQ queue, under the same contracts; CI runs them

`S3BlobStore` and `RQJobQueue` join their contract suites against RustFS and Redis, and `make migrate` now creates the bucket. CI starts the same `compose.yaml` and sets `GUITARVIS_REQUIRE_SERVICES=1`, and a test pins that, so `make check` in CI cannot pass by skipping the integration suite.

**Files:**
- Modify: `packages/jobs/pyproject.toml` (dependencies)
- Modify: `packages/jobs/src/guitarvis_jobs/blobs.py` (append `s3_client`, `S3BlobStore`)
- Modify: `packages/jobs/src/guitarvis_jobs/queue.py` (append `RQJobQueue`)
- Modify: `packages/jobs/src/guitarvis_jobs/migrate.py` (`main` creates the bucket)
- Modify: `packages/jobs/src/guitarvis_jobs/testing.py` (redis and storage probes and helpers)
- Modify: `packages/jobs/tests/test_blob_store.py`, `packages/jobs/tests/test_job_queue.py` (params and S3/RQ-specific tests)
- Create: `packages/jobs/tests/test_services_gate_ci.py`
- Modify: `.github/workflows/ci.yml` (whole file below)
- Modify: `mypy.ini` (boto3 and botocore have no type information)

**Interfaces:**
- Consumes: `BlobStore`, `BlobNotFound`, `JobQueue`, `RUN_JOB`, `QUEUE_NAME`, `MAX_RETRIES`, `RETRY_INTERVALS_SEC` (Task 5); `Settings`, `integration_settings`, `require` (Tasks 4, 6).
- Produces:
  - `guitarvis_jobs.blobs.s3_client(settings, endpoint, *, connect_timeout=5, max_attempts=3)`, returning a boto3 client.
  - `S3BlobStore(client, public_client, bucket, region="us-east-1")` implementing `BlobStore`, with `.bucket`, `S3BlobStore.from_settings(settings)` and `ensure_bucket()`.
  - `guitarvis_jobs.queue.RQJobQueue(connection: Redis, *, job_timeout_sec: int)` implementing `JobQueue`, with `.connection` and `RQJobQueue.from_settings(settings)`. Each enqueue carries `retry=Retry(max=2, interval=[10, 60])`, `job_timeout=job_timeout_sec` and the RQ job id equal to the GuitarVis id.
  - `guitarvis_jobs.testing`: `require` now also accepts `"redis"` and `"storage"`. New context managers: `redis_connection() -> Iterator[Redis]` (db 15, flushed before and after) and `s3_blob_store() -> Iterator[S3BlobStore]` (the `guitarvis-test` bucket, emptied before and after).

- [ ] **Step 1: Add the storage and queue dependencies**

In `packages/jobs/pyproject.toml`, set:

```toml
dependencies = [
    "guitarvis-core",
    "sqlalchemy>=2.0",
    "psycopg[binary]>=3.2",
    "alembic>=1.13",
    "boto3>=1.35",
    "redis>=5.0",
    "rq>=2.0",
]
```

In `mypy.ini`, append (following the file's own convention of naming untyped dependencies rather than ignoring all of them):

```ini
; boto3 and botocore ship no type information (stubs exist as boto3-stubs,
; not worth a dependency for the handful of calls in guitarvis_jobs.blobs).
[mypy-boto3]
ignore_missing_imports = True

[mypy-boto3.*]
ignore_missing_imports = True

[mypy-botocore]
ignore_missing_imports = True

[mypy-botocore.*]
ignore_missing_imports = True
```

Run: `uv lock && uv sync`

- [ ] **Step 2: Write the failing tests**

In `packages/jobs/tests/test_blob_store.py`, add these imports:

```python
import urllib.request
from dataclasses import replace

from guitarvis_jobs.blobs import S3BlobStore, s3_client
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.testing import integration_settings, require, s3_blob_store
```

Replace the fixture with:

```python
@pytest.fixture(params=["memory", "s3"])
def blobs(request: pytest.FixtureRequest) -> Iterator[BlobStore]:
    if request.param == "memory":
        yield InMemoryBlobStore()
        return
    with s3_blob_store() as store:
        yield store
```

and append:

```python
def test_a_presigned_url_is_signed_for_the_public_endpoint() -> None:
    # No network: presigning is local. The browser, not the api, fetches it.
    store = S3BlobStore.from_settings(
        Settings(s3_public_endpoint="http://public.example:9000")
    )

    url = store.presign_get("uploads/k.mp3", expires_sec=60)

    assert url.startswith("http://public.example:9000/guitarvis/uploads/k.mp3?")


def test_a_presigned_s3_url_serves_byte_ranges() -> None:
    """Seeking needs Range, which is why the api redirects rather than proxies."""
    with s3_blob_store() as store:
        store.put_bytes("uploads/range.wav", b"0123456789")
        url = store.presign_get("uploads/range.wav", expires_sec=PRESIGN_EXPIRES_SEC)

        request = urllib.request.Request(url, headers={"Range": "bytes=2-5"})
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 206
            assert response.read() == b"2345"


def test_ensure_bucket_creates_a_missing_bucket_and_is_repeatable() -> None:
    require("storage")
    settings = replace(integration_settings(), s3_bucket="guitarvis-test-ensure")
    store = S3BlobStore.from_settings(settings)
    try:
        store.ensure_bucket()
        store.ensure_bucket()
        store.ping()
    finally:
        s3_client(settings, settings.s3_endpoint).delete_bucket(
            Bucket=settings.s3_bucket
        )
```

In `packages/jobs/tests/test_job_queue.py`, add `from guitarvis_jobs.queue import QUEUE_NAME, RQJobQueue`, `from guitarvis_jobs.testing import redis_connection` and `from rq.job import Job as RQJob`. Replace the fixture with:

```python
@pytest.fixture(params=["memory", "rq"])
def queue(request: pytest.FixtureRequest) -> Iterator[JobQueue]:
    if request.param == "memory":
        yield InMemoryJobQueue()
        return
    with redis_connection() as connection:
        yield RQJobQueue(connection, job_timeout_sec=1800)
```

and append:

```python
def test_an_rq_job_carries_the_retry_policy_and_the_timeout() -> None:
    with redis_connection() as connection:
        RQJobQueue(connection, job_timeout_sec=1800).enqueue(JOB_ID)
        job = RQJob.fetch(JOB_ID, connection=connection)

        assert job.func_name == RUN_JOB
        assert job.args == (JOB_ID,)
        assert job.origin == QUEUE_NAME
        assert job.retries_left == MAX_RETRIES
        assert job.retry_intervals == list(RETRY_INTERVALS_SEC)
        assert job.timeout == 1800
```

Create `packages/jobs/tests/test_services_gate_ci.py`:

```python
"""`make check` in CI must run the integration suite, never skip it.

Locally, a test that needs Postgres, Redis or object storage skips when they
are down, as ingest tests skip without ffprobe. In CI the same skip would let
the build pass with the integration suite unrun, so CI sets
GUITARVIS_REQUIRE_SERVICES=1, which turns the skip into a failure. These
tests keep that true.
"""

import re
from pathlib import Path

import pytest
from guitarvis_jobs import testing

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"


def test_ci_starts_the_services_migrates_and_forbids_skipping() -> None:
    workflow = WORKFLOW.read_text()

    start = workflow.index("docker compose up -d --wait")
    migrate = workflow.index("make migrate")
    check = workflow.index("run: make check")
    assert start < migrate < check
    assert re.search(r'GUITARVIS_REQUIRE_SERVICES:\s*"1"', workflow[migrate:]), (
        "the check step must set GUITARVIS_REQUIRE_SERVICES=1, or the "
        "integration suite skips in CI and make check passes without it"
    )


def test_a_missing_service_fails_when_services_are_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(testing.REQUIRE_SERVICES_ENV, "1")
    monkeypatch.setattr(testing, "_probe", lambda service: "ConnectionRefusedError")

    with pytest.raises(pytest.fail.Exception, match="make services"):
        testing.require("postgres")


def test_a_missing_service_skips_otherwise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(testing.REQUIRE_SERVICES_ENV, raising=False)
    monkeypatch.setattr(testing, "_probe", lambda service: "ConnectionRefusedError")

    with pytest.raises(pytest.skip.Exception):
        testing.require("postgres")
```

Run: `uv run pytest packages/jobs -v`
Expected: collection errors (`cannot import name 'S3BlobStore'`, `'RQJobQueue'`, `'redis_connection'`), and the CI gate test fails at `workflow.index("docker compose up -d --wait")` with `ValueError: substring not found`.

- [ ] **Step 3: Implement `S3BlobStore`**

In `packages/jobs/src/guitarvis_jobs/blobs.py`, extend the imports:

```python
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from guitarvis_jobs.settings import Settings
```

and insert before the `if TYPE_CHECKING:` block:

```python
_MISSING_CODES = {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}


def s3_client(
    settings: Settings,
    endpoint: str,
    *,
    connect_timeout: float = 5,
    max_attempts: int = 3,
) -> Any:
    """A boto3 client for any S3-compatible server.

    Path-style addressing, because a local server has no per-bucket DNS
    names. Signature v4, which presigned URLs need.
    """
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=connect_timeout,
            read_timeout=60,
            retries={"max_attempts": max_attempts, "mode": "standard"},
        ),
    )


class S3BlobStore:
    """Implements BlobStore on any S3-compatible server: RustFS locally."""

    def __init__(
        self, client: Any, public_client: Any, bucket: str, region: str = "us-east-1"
    ) -> None:
        self._client = client
        # Signs URLs for the host a browser reaches; never sends a request.
        self._public = public_client
        self.bucket = bucket
        self._region = region

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3BlobStore":
        return cls(
            s3_client(settings, settings.s3_endpoint),
            s3_client(settings, settings.s3_public_endpoint),
            settings.s3_bucket,
            settings.s3_region,
        )

    def put_file(self, key: str, path: Path) -> None:
        self._client.upload_file(str(path), self.bucket, key)

    def put_bytes(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get_file(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client.download_file(self.bucket, key, str(path))
        except ClientError as exc:
            if _is_missing(exc):
                raise BlobNotFound(key) from exc
            raise

    def get_bytes(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if _is_missing(exc):
                raise BlobNotFound(key) from exc
            raise
        return bytes(response["Body"].read())

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if _is_missing(exc):
                return False
            raise
        return True

    def presign_get(self, key: str, *, expires_sec: int) -> str:
        return str(
            self._public.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_sec,
            )
        )

    def ping(self) -> None:
        self._client.head_bucket(Bucket=self.bucket)

    def ensure_bucket(self) -> None:
        """Create the bucket unless it exists. `make migrate` calls this."""
        try:
            self._client.head_bucket(Bucket=self.bucket)
            return
        except ClientError as exc:
            if not _is_missing(exc):
                raise
        if self._region == "us-east-1":
            self._client.create_bucket(Bucket=self.bucket)
        else:
            self._client.create_bucket(
                Bucket=self.bucket,
                CreateBucketConfiguration={"LocationConstraint": self._region},
            )


def _is_missing(exc: Any) -> bool:
    return str(exc.response.get("Error", {}).get("Code")) in _MISSING_CODES
```

Add `_s3: BlobStore = S3BlobStore(None, None, "bucket")` inside the existing `if TYPE_CHECKING:` block.

- [ ] **Step 4: Implement `RQJobQueue`**

In `packages/jobs/src/guitarvis_jobs/queue.py`, extend the imports:

```python
import threading
from typing import TYPE_CHECKING, Protocol

from redis import Redis
from rq import Queue, Retry
from rq.job import Job as RQJob

from guitarvis_jobs.settings import Settings
```

and insert before the `if TYPE_CHECKING:` block:

```python
class RQJobQueue:
    """Implements JobQueue on RQ."""

    def __init__(self, connection: Redis, *, job_timeout_sec: int) -> None:
        self.connection = connection
        self.job_timeout_sec = job_timeout_sec
        self._queue = Queue(QUEUE_NAME, connection=connection)

    @classmethod
    def from_settings(cls, settings: Settings) -> "RQJobQueue":
        # No socket timeout: a worker blocks on this connection for minutes
        # while it waits for work, and RQ manages that wait itself.
        connection = Redis.from_url(settings.redis_url, socket_connect_timeout=5)
        return cls(connection, job_timeout_sec=settings.job_timeout_sec)

    def enqueue(self, job_id: str) -> None:
        self._queue.enqueue(
            RUN_JOB,
            job_id,
            job_id=job_id,
            retry=Retry(max=MAX_RETRIES, interval=list(RETRY_INTERVALS_SEC)),
            job_timeout=self.job_timeout_sec,
            description=f"guitarvis job {job_id}",
        )

    def exists(self, job_id: str) -> bool:
        return RQJob.exists(job_id, connection=self.connection)

    def ping(self) -> None:
        self.connection.ping()
```

Add `_rq: JobQueue = RQJobQueue(Redis(), job_timeout_sec=1)` inside the existing `if TYPE_CHECKING:` block.

- [ ] **Step 5: Teach `testing.py` about Redis and storage**

Add to the imports of `packages/jobs/src/guitarvis_jobs/testing.py`:

```python
from redis import Redis

from guitarvis_jobs.blobs import S3BlobStore, s3_client
```

Replace the `_PINGS` line with:

```python
def _ping_redis(settings: Settings) -> None:
    connection = Redis.from_url(settings.redis_url, socket_connect_timeout=1)
    try:
        connection.ping()
    finally:
        connection.close()


def _ping_storage(settings: Settings) -> None:
    client = s3_client(
        settings, settings.s3_endpoint, connect_timeout=1, max_attempts=1
    )
    client.list_buckets()


_PINGS: dict[str, Callable[[Settings], None]] = {
    "postgres": _ping_postgres,
    "redis": _ping_redis,
    "storage": _ping_storage,
}
```

and append:

```python
@contextmanager
def redis_connection() -> Iterator[Redis]:
    """Redis database 15, flushed before and after."""
    require("redis")
    connection = Redis.from_url(integration_settings().redis_url)
    connection.flushdb()
    try:
        yield connection
    finally:
        connection.flushdb()
        connection.close()


@contextmanager
def s3_blob_store() -> Iterator[S3BlobStore]:
    """The test bucket, created if missing, emptied before and after."""
    require("storage")
    settings = integration_settings()
    store = S3BlobStore.from_settings(settings)
    store.ensure_bucket()
    _empty_bucket(settings)
    try:
        yield store
    finally:
        _empty_bucket(settings)


def _empty_bucket(settings: Settings) -> None:
    client = s3_client(settings, settings.s3_endpoint)
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=settings.s3_bucket
    ):
        for item in page.get("Contents", []):
            client.delete_object(Bucket=settings.s3_bucket, Key=item["Key"])
```

- [ ] **Step 6: `make migrate` creates the bucket**

In `packages/jobs/src/guitarvis_jobs/migrate.py`, add `from guitarvis_jobs.blobs import S3BlobStore` and replace `main` with:

```python
def main() -> int:
    settings = Settings.from_env()
    upgrade(settings.database_url)
    shown = make_url(settings.database_url).render_as_string(hide_password=True)
    print(f"database up to date: {shown}")
    S3BlobStore.from_settings(settings).ensure_bucket()
    print(f"bucket ready: {settings.s3_bucket} at {settings.s3_endpoint}")
    return 0
```

- [ ] **Step 7: Run the services in CI**

Replace `.github/workflows/ci.yml` with:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 20

    steps:
      - uses: actions/checkout@v4

      # Postgres, Redis and RustFS from the same compose.yaml developers run.
      # --wait returns once every healthcheck passes.
      - name: Start services
        run: docker compose up -d --wait

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install Node
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: web/package-lock.json

      # ffprobe (from ffmpeg) is what ingestion uses to probe uploaded audio.
      # Installed explicitly so CI never depends on the runner image happening
      # to ship it.
      - name: Install ffmpeg
        run: sudo apt-get update && sudo apt-get install -y ffmpeg

      # --locked makes `uv sync` fail loudly if pyproject.toml and uv.lock
      # disagree, matching `npm ci`'s existing enforcement of package-lock.json.
      - name: Install dependencies
        run: make install UV_SYNC_FLAGS=--locked

      - name: Migrate
        run: make migrate

      # CPU only. The worker's ml extra is never installed here, so no model
      # weights are downloaded and no GPU is required.
      #
      # Locally the integration suite skips when services are down. Here a
      # missing service fails the build instead, so `make check` cannot pass
      # by skipping it (packages/jobs/tests/test_services_gate_ci.py).
      - name: Check
        env:
          GUITARVIS_REQUIRE_SERVICES: "1"
        run: make check
```

- [ ] **Step 8: Run everything with the services up**

Run: `make services && GUITARVIS_REQUIRE_SERVICES=1 uv run pytest packages/jobs -v`
Expected: all PASS, nothing skipped. The blob tests run `[memory]` and `[s3]`; the queue tests run `[memory]` and `[rq]`.

Run: `make migrate`
Expected: `database up to date: …` and then `bucket ready: guitarvis at http://localhost:9000`.

Run: `make check`
Expected: exit 0.

- [ ] **Step 9: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add packages/jobs uv.lock mypy.ini .github/workflows/ci.yml
git commit -m "feat(jobs): S3 blob store and RQ queue; CI runs the integration suite

S3BlobStore and RQJobQueue run under the same contract suites as their
in-memory twins. make migrate creates the bucket. CI starts compose.yaml and
sets GUITARVIS_REQUIRE_SERVICES=1, which a test pins.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Stage caching

Three decorators wrap the real stages and implement each stage's own Protocol, so `run_pipeline` and the stages do not change. A hit returns the stored output without calling the stage. A miss calls the stage and stores what it returns. A stage that raises stores nothing. For transcription and structure the cache is only an optimisation, so a storage error there is a miss and is never re-raised. Re-raising would show up as a degraded document (Review Focus 2). Separation is different: its stem is what the api serves as the guitar track, so failing to store it fails the attempt, and RQ retries.

**Files:**
- Modify: `apps/worker/pyproject.toml` (depend on `guitarvis-jobs`)
- Create: `apps/worker/src/guitarvis_worker/caching.py`
- Create: `apps/worker/tests/test_caching.py`
- Modify: `.claude/skills/pipeline-stage/SKILL.md` (the caching rule)

**Interfaces:**
- Consumes: `BlobStore`, `BlobNotFound`, `InMemoryBlobStore` (Task 5); `SeparationProgress` and the stage Protocols (Task 2).
- Produces:
  - `guitarvis_worker.caching.CACHE_VERSION = 1`.
  - `CacheKeys(content_hash: str, version: int = CACHE_VERSION)` with properties `prefix` (`cache/v{N}/{hash}`), `stem` (`…/separation/stem.wav`), `separation` (`…/separation/result.json`), `transcription` (`…/transcription.json`) and `structure` (`…/structure.json`).
  - The decorators: `CachedSeparator(inner: Separator, blobs: BlobStore, keys: CacheKeys, work_dir: Path)`, `CachedTranscriber(inner: Transcriber, blobs: BlobStore, keys: CacheKeys)` and `CachedAnalyzer(inner: StructureAnalyzer, blobs: BlobStore, keys: CacheKeys)`. A separation hit restores the stem to `work_dir / "cached-separation" / "stem.wav"`.

- [ ] **Step 1: Depend on the shared package**

In `apps/worker/pyproject.toml`, change `dependencies = ["guitarvis-core"]` to `dependencies = ["guitarvis-core", "guitarvis-jobs"]`. Run: `uv lock && uv sync`.

- [ ] **Step 2: Write the failing tests**

`apps/worker/tests/test_caching.py`:

```python
"""Stage caching: a retried job resumes after the last stage that finished."""

import json
import logging
from collections.abc import Sequence
from pathlib import Path

import pytest
from guitarvis_core.contracts import (
    FailureReason,
    IngestedAudio,
    NoteEvent,
    PipelineError,
    SeparationProgress,
    SeparationResult,
    Separator,
    StructureAnalyzer,
    StructureResult,
    Transcriber,
)
from guitarvis_core.tabdoc import Beat, Chord, Section, Timing
from guitarvis_jobs.blobs import InMemoryBlobStore
from guitarvis_worker.caching import (
    CACHE_VERSION,
    CachedAnalyzer,
    CachedSeparator,
    CachedTranscriber,
    CacheKeys,
)
from guitarvis_worker.pipeline import run_pipeline
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper

KEYS = CacheKeys("f" * 64)
EVENTS = [NoteEvent(onset=1.0, duration=0.5, midi=52, confidence=0.8)]
STRUCTURE = StructureResult(
    timing=Timing(beats=[Beat(t=0.5, bar=1, beat=1)], tempo_bpm_avg=96.0),
    chords=[Chord(t=0.0, dur=2.0, symbol="Am", confidence=0.7)],
    sections=[Section(t=0.0, dur=8.0, label="verse")],
    warnings=["Chord detection was unsure in places."],
)


class CountingSeparator:
    def __init__(
        self,
        stem: Path,
        warnings: Sequence[str] = (),
        error: Exception | None = None,
    ) -> None:
        self.stem = stem
        self.warnings = list(warnings)
        self.error = error
        self.calls = 0

    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if progress is not None:
            progress(0.5)
        return SeparationResult(stem_path=self.stem, warnings=list(self.warnings))


class CountingTranscriber:
    def __init__(
        self, events: Sequence[NoteEvent] = EVENTS, error: Exception | None = None
    ) -> None:
        self.events = list(events)
        self.error = error
        self.calls = 0

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.events)


class CountingAnalyzer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return STRUCTURE


class FlakyBlobStore(InMemoryBlobStore):
    """Storage that cannot be read, or cannot be written."""

    def __init__(self, *, reads_fail: bool = False, writes_fail: bool = False) -> None:
        super().__init__()
        self.reads_fail = reads_fail
        self.writes_fail = writes_fail

    def exists(self, key: str) -> bool:
        if self.reads_fail:
            raise ConnectionError("storage went away")
        return super().exists(key)

    def put_bytes(self, key: str, data: bytes) -> None:
        if self.writes_fail:
            raise ConnectionError("storage went away")
        super().put_bytes(key, data)


def stem_file(tmp_path: Path) -> Path:
    path = tmp_path / "guitar.wav"
    path.write_bytes(b"stem-bytes")
    return path


def test_keys_are_versioned_and_per_upload() -> None:
    assert CACHE_VERSION == 1
    assert KEYS.prefix == f"cache/v1/{'f' * 64}"
    assert KEYS.stem == f"{KEYS.prefix}/separation/stem.wav"
    assert KEYS.separation == f"{KEYS.prefix}/separation/result.json"
    assert KEYS.transcription == f"{KEYS.prefix}/transcription.json"
    assert KEYS.structure == f"{KEYS.prefix}/structure.json"
    assert CacheKeys("e" * 64).prefix != KEYS.prefix
    assert CacheKeys("f" * 64, version=2).prefix != KEYS.prefix


def test_the_decorators_implement_the_stage_protocols(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    assert isinstance(
        CachedSeparator(CountingSeparator(tmp_path), blobs, KEYS, tmp_path), Separator
    )
    assert isinstance(
        CachedTranscriber(CountingTranscriber(), blobs, KEYS), Transcriber
    )
    assert isinstance(
        CachedAnalyzer(CountingAnalyzer(), blobs, KEYS), StructureAnalyzer
    )


def test_a_separation_miss_runs_the_stage_and_stores_its_output(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    inner = CountingSeparator(stem_file(tmp_path), warnings=["used the 4-stem track"])
    seen: list[float] = []

    result = CachedSeparator(inner, blobs, KEYS, tmp_path).isolate(
        tmp_path / "upload.mp3", progress=seen.append
    )

    assert inner.calls == 1
    assert seen == [0.5]  # progress passes straight through on a miss
    assert result.warnings == ["used the 4-stem track"]
    assert blobs.get_bytes(KEYS.stem) == b"stem-bytes"
    assert json.loads(blobs.get_bytes(KEYS.separation)) == {
        "stem": "guitar",
        "warnings": ["used the 4-stem track"],
    }


def test_a_separation_hit_restores_the_stem_without_running_the_stage(
    tmp_path: Path,
) -> None:
    blobs = InMemoryBlobStore()
    first = CountingSeparator(stem_file(tmp_path), warnings=["w"])
    CachedSeparator(first, blobs, KEYS, tmp_path).isolate(tmp_path / "upload.mp3")

    retry_dir = tmp_path / "retry"
    second = CountingSeparator(tmp_path / "unused.wav")
    result = CachedSeparator(second, blobs, KEYS, retry_dir).isolate(
        retry_dir / "upload.mp3"
    )

    assert second.calls == 0
    assert result.stem_path == retry_dir / "cached-separation" / "stem.wav"
    assert result.stem_path.read_bytes() == b"stem-bytes"
    assert result.warnings == ["w"]


def test_a_failed_separation_stores_nothing(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    inner = CountingSeparator(
        tmp_path,
        error=PipelineError(FailureReason.NO_GUITAR_DETECTED, "No clear guitar part"),
    )

    with pytest.raises(PipelineError):
        CachedSeparator(inner, blobs, KEYS, tmp_path).isolate(tmp_path / "a.mp3")

    assert not blobs.exists(KEYS.separation)
    assert not blobs.exists(KEYS.stem)


def test_a_result_without_its_stem_is_a_miss(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    blobs.put_bytes(KEYS.separation, b'{"stem": "guitar", "warnings": []}')
    inner = CountingSeparator(stem_file(tmp_path))

    CachedSeparator(inner, blobs, KEYS, tmp_path).isolate(tmp_path / "a.mp3")

    assert inner.calls == 1


def test_failing_to_store_the_stem_fails_the_attempt(tmp_path: Path) -> None:
    # The api serves this stem as the guitar track, so it must be stored;
    # the exception reaches the runner, which hands the job back to RQ.
    inner = CountingSeparator(stem_file(tmp_path))

    with pytest.raises(ConnectionError):
        CachedSeparator(
            inner, FlakyBlobStore(writes_fail=True), KEYS, tmp_path
        ).isolate(tmp_path / "a.mp3")


def test_a_transcription_miss_then_hit(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    first = CountingTranscriber()
    assert CachedTranscriber(first, blobs, KEYS).transcribe(tmp_path) == EVENTS

    second = CountingTranscriber(events=[])
    assert CachedTranscriber(second, blobs, KEYS).transcribe(tmp_path) == EVENTS
    assert (first.calls, second.calls) == (1, 0)


def test_an_empty_transcription_is_cached_too(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    CachedTranscriber(CountingTranscriber(events=[]), blobs, KEYS).transcribe(tmp_path)

    again = CountingTranscriber()
    assert CachedTranscriber(again, blobs, KEYS).transcribe(tmp_path) == []
    assert again.calls == 0


def test_a_failed_transcription_stores_nothing(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    inner = CountingTranscriber(error=RuntimeError("model failed to load"))

    with pytest.raises(RuntimeError):
        CachedTranscriber(inner, blobs, KEYS).transcribe(tmp_path)

    assert not blobs.exists(KEYS.transcription)


def test_a_storage_failure_while_caching_notes_does_not_cost_the_notes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Review Focus 2: through the real pipeline, the notes still land."""
    blobs = FlakyBlobStore(writes_fail=True)
    audio_path = tmp_path / "upload.wav"
    audio_path.write_bytes(b"")

    with caplog.at_level(logging.WARNING, logger="guitarvis_worker.caching"):
        result = run_pipeline(
            IngestedAudio(path=audio_path, title="song", duration_sec=10.0),
            separator=CountingSeparator(audio_path),
            transcriber=CachedTranscriber(CountingTranscriber(), blobs, KEYS),
            analyzer=CountingAnalyzer(),
            mapper=ViterbiFretboardMapper(),
        )

    assert len(result.document.notes) == 1
    assert not any("Transcription failed" in w for w in result.document.warnings)
    assert "cache write failed" in caplog.text


def test_an_unreadable_cache_is_a_miss(tmp_path: Path) -> None:
    inner = CountingTranscriber()

    events = CachedTranscriber(inner, FlakyBlobStore(reads_fail=True), KEYS).transcribe(
        tmp_path
    )

    assert events == EVENTS
    assert inner.calls == 1


def test_a_corrupt_cache_entry_is_a_miss(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    blobs.put_bytes(KEYS.transcription, b"not json at all")
    inner = CountingTranscriber()

    assert CachedTranscriber(inner, blobs, KEYS).transcribe(tmp_path) == EVENTS
    assert inner.calls == 1


def test_structure_round_trips_through_the_cache(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    first = CountingAnalyzer()
    CachedAnalyzer(first, blobs, KEYS).analyze(tmp_path / "stem", tmp_path / "mix")

    second = CountingAnalyzer()
    restored = CachedAnalyzer(second, blobs, KEYS).analyze(
        tmp_path / "stem", tmp_path / "mix"
    )

    assert restored == STRUCTURE
    assert second.calls == 0


def test_a_failed_analysis_stores_nothing(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()

    with pytest.raises(RuntimeError):
        CachedAnalyzer(CountingAnalyzer(error=RuntimeError("x")), blobs, KEYS).analyze(
            tmp_path, tmp_path
        )

    assert not blobs.exists(KEYS.structure)
```

Run: `uv run pytest apps/worker/tests/test_caching.py -v`
Expected: collection error, `No module named 'guitarvis_worker.caching'`.

- [ ] **Step 3: Implement `caching.py`**

```python
"""Per-stage caching, so a retried job resumes after the last stage that finished.

Each decorator wraps a real stage and implements that stage's own Protocol, so
run_pipeline and the stages know nothing about it. Entries are keyed by the
upload's content hash, under `cache/v{CACHE_VERSION}/{hash}/`.

A stage that raises stores nothing: the pipeline degrades exactly as it would
without a cache, and the next attempt runs the stage again rather than
replaying its failure. Stage 4 is fast and deterministic and is not cached.

For transcription and structure the cache is only an optimisation, so a
storage error reading or writing it is logged and treated as a miss. It must
never surface as the stage failing, which the pipeline would turn into a
degraded document. Separation's stem is different: the api serves it as the
guitar track, so failing to store it fails the attempt, and RQ retries.
"""

import dataclasses
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from guitarvis_core.contracts import (
    NoteEvent,
    SeparationProgress,
    SeparationResult,
    Separator,
    StructureAnalyzer,
    StructureResult,
    Transcriber,
)
from guitarvis_core.tabdoc import Chord, Section, Timing
from guitarvis_jobs.blobs import BlobNotFound, BlobStore

log = logging.getLogger(__name__)

# Bump by hand whenever a stage's output for the same input would change: a
# new model, a changed threshold, a fixed bug. Nothing enforces it. Forget,
# and audio processed before the change keeps being served the old result.
CACHE_VERSION = 1


@dataclass(frozen=True)
class CacheKeys:
    content_hash: str
    version: int = CACHE_VERSION

    @property
    def prefix(self) -> str:
        return f"cache/v{self.version}/{self.content_hash}"

    @property
    def stem(self) -> str:
        return f"{self.prefix}/separation/stem.wav"

    @property
    def separation(self) -> str:
        return f"{self.prefix}/separation/result.json"

    @property
    def transcription(self) -> str:
        return f"{self.prefix}/transcription.json"

    @property
    def structure(self) -> str:
        return f"{self.prefix}/structure.json"


def _load[T](blobs: BlobStore, key: str, decode: Callable[[Any], T]) -> T | None:
    """The cached value at `key`, or None on a miss.

    A store that cannot be read, or an entry that cannot be decoded, is a
    miss too: logged, never raised.
    """
    try:
        if not blobs.exists(key):
            return None
        return decode(json.loads(blobs.get_bytes(key)))
    except Exception:
        log.warning("cache read failed for %s; running the stage", key, exc_info=True)
        return None


def _store(blobs: BlobStore, key: str, value: Any) -> None:
    """Cache `value`. A failure is logged, never raised: the result stands."""
    try:
        blobs.put_bytes(key, json.dumps(value).encode())
    except Exception:
        log.warning(
            "cache write failed for %s; using the result anyway", key, exc_info=True
        )


class CachedSeparator:
    """Implements Separator around another Separator."""

    def __init__(
        self, inner: Separator, blobs: BlobStore, keys: CacheKeys, work_dir: Path
    ) -> None:
        self._inner = inner
        self._blobs = blobs
        self._keys = keys
        self._work_dir = work_dir

    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        cached = self._restore()
        if cached is not None:
            return cached

        result = self._inner.isolate(audio_path, progress=progress)
        # The stem first, then result.json, whose presence is what marks the
        # entry complete. Not _store: a failure here must fail the attempt.
        self._blobs.put_file(self._keys.stem, result.stem_path)
        self._blobs.put_bytes(
            self._keys.separation,
            json.dumps(
                {"stem": result.stem_path.stem, "warnings": list(result.warnings)}
            ).encode(),
        )
        return result

    def _restore(self) -> SeparationResult | None:
        warnings = _load(
            self._blobs, self._keys.separation, lambda meta: list(meta["warnings"])
        )
        if warnings is None:
            return None
        stem_path = self._work_dir / "cached-separation" / "stem.wav"
        try:
            self._blobs.get_file(self._keys.stem, stem_path)
        except BlobNotFound:
            log.warning(
                "%s has no stem beside it; separating again", self._keys.separation
            )
            return None
        return SeparationResult(stem_path=stem_path, warnings=warnings)


class CachedTranscriber:
    """Implements Transcriber around another Transcriber."""

    def __init__(self, inner: Transcriber, blobs: BlobStore, keys: CacheKeys) -> None:
        self._inner = inner
        self._blobs = blobs
        self._keys = keys

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        cached = _load(
            self._blobs,
            self._keys.transcription,
            lambda items: [NoteEvent(**item) for item in items],
        )
        if cached is not None:
            return cached
        events = self._inner.transcribe(stem_path)
        _store(
            self._blobs,
            self._keys.transcription,
            [dataclasses.asdict(event) for event in events],
        )
        return events


class CachedAnalyzer:
    """Implements StructureAnalyzer around another StructureAnalyzer."""

    def __init__(
        self, inner: StructureAnalyzer, blobs: BlobStore, keys: CacheKeys
    ) -> None:
        self._inner = inner
        self._blobs = blobs
        self._keys = keys

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        cached = _load(self._blobs, self._keys.structure, _structure_from_json)
        if cached is not None:
            return cached
        result = self._inner.analyze(stem_path, mix_path)
        _store(self._blobs, self._keys.structure, _structure_to_json(result))
        return result


def _structure_to_json(result: StructureResult) -> dict[str, Any]:
    return {
        "timing": result.timing.model_dump(mode="json"),
        "chords": [chord.model_dump(mode="json") for chord in result.chords],
        "sections": [section.model_dump(mode="json") for section in result.sections],
        "warnings": list(result.warnings),
    }


def _structure_from_json(data: dict[str, Any]) -> StructureResult:
    return StructureResult(
        timing=Timing.model_validate(data["timing"]),
        chords=[Chord.model_validate(chord) for chord in data["chords"]],
        sections=[Section.model_validate(section) for section in data["sections"]],
        warnings=list(data["warnings"]),
    )


if TYPE_CHECKING:  # Static conformance: the typed assignments are what mypy checks.
    from typing import cast

    from guitarvis_jobs.blobs import InMemoryBlobStore

    _blobs = InMemoryBlobStore()
    _s: Separator = CachedSeparator(
        cast(Separator, None), _blobs, CacheKeys(""), Path()
    )
    _t: Transcriber = CachedTranscriber(cast(Transcriber, None), _blobs, CacheKeys(""))
    _a: StructureAnalyzer = CachedAnalyzer(
        cast(StructureAnalyzer, None), _blobs, CacheKeys("")
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest apps/worker/tests/test_caching.py -v && uv run mypy apps/worker/src apps/worker/tests`
Expected: 15 PASS; mypy `Success`.

- [ ] **Step 5: Record the caching rule in the stage skill**

In `.claude/skills/pipeline-stage/SKILL.md`, replace the paragraph starting `**Stages are idempotent and intermediates are cached by content hash.**` with:

```markdown
**Stages are idempotent and intermediates are cached by content hash.** A
stage-3 failure must not force re-running separation on retry. The cache lives
in `apps/worker/src/guitarvis_worker/caching.py`: one decorator per cached
stage, each implementing that stage's Protocol. **Bump `CACHE_VERSION`
whenever a stage's output for the same input would change** (a new model, a
changed threshold, a fixed bug). Nothing enforces it, and forgetting serves
old results for audio processed before the change. A cache read or write error
is a miss, never a stage failure; only the separation stem must be stored,
because the api serves it.
```

- [ ] **Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add apps/worker uv.lock .claude/skills/pipeline-stage/SKILL.md
git commit -m "feat(worker): cache separation, transcription and structure by content hash

Decorators implement each stage's Protocol, so run_pipeline is unchanged. A
raising stage stores nothing; a cache I/O error is a miss, never a stage
failure. Only the separation stem must be stored, since the api serves it.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The job runner and `guitarvis-worker serve`

`process_job` is the whole of one delivery: it loads the row, ignores a repeat delivery, marks the row running, downloads the upload, runs the cached pipeline and stores the result. `run_job` is the thin RQ adapter. `serve` runs an RQ `Worker` with its scheduler on, which retry intervals need.

**Files:**
- Create: `apps/worker/src/guitarvis_worker/runner.py`
- Create: `apps/worker/tests/test_runner.py`
- Modify: `apps/worker/src/guitarvis_worker/cli.py` (`serve` subcommand; `main` split into `_process` and `_serve`)
- Modify: `apps/worker/tests/test_cli.py` (one new test)
- Modify: `Makefile` (`worker` target)

**Interfaces:**
- Consumes: `JobStore`, `Job`, `JobStatus`, `FINISHED_STATUSES`, `INTERNAL_FAILURE_MESSAGE` (Task 4); `BlobStore`, `S3BlobStore` (Tasks 5, 7); `PostgresJobStore` (Task 6); `QUEUE_NAME`, `RUN_JOB` (Task 5); `CacheKeys` and the decorators (Task 8); `run_pipeline(..., audio_url=...)` and `StageProgress` (Task 2); `UploadSource` (Task 1).
- Produces:
  - `guitarvis_worker.runner.Stages(separator, transcriber, analyzer, mapper)` and `build_stages(work_dir: Path, device: str | None = None) -> Stages`. Tests patch `build_stages`.
  - `WorkerDeps(store: JobStore, blobs: BlobStore, stages: Callable[[Path], Stages])`.
  - `process_job(job_id: str, deps: WorkerDeps, *, retries_left: int) -> None`.
  - `run_job(job_id: str) -> None` (RQ's entry point), `open_deps(settings: Settings)` (a context manager yielding `WorkerDeps`) and `serve(settings: Settings, *, burst: bool = False) -> None`.
  - CLI `guitarvis-worker serve [--device DEV] [--burst]`.

- [ ] **Step 1: Write the failing tests**

`apps/worker/tests/test_runner.py`:

```python
"""One delivery of one job: the runner's contract with RQ and the job row.

process_job is driven directly, with in-memory stores and stub stages; the
end-to-end test (test_end_to_end.py) runs it under a real RQ worker.
"""

import importlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

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
from guitarvis_jobs.blobs import InMemoryBlobStore
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, Job, JobStatus
from guitarvis_jobs.queue import RUN_JOB
from guitarvis_jobs.store import InMemoryJobStore
from guitarvis_jobs.testing import sample_new_job
from guitarvis_worker import runner
from guitarvis_worker.caching import CacheKeys
from guitarvis_worker.runner import Stages, WorkerDeps, process_job
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper


class StubSeparator:
    def __init__(self) -> None:
        self.calls = 0
        self.error: Exception | None = None

    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if progress is not None:
            progress(0.5)
        return SeparationResult(stem_path=audio_path)


class StubTranscriber:
    def __init__(self) -> None:
        self.during: Callable[[], None] | None = None

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        if self.during is not None:
            self.during()
        return [NoteEvent(onset=1.0, duration=0.5, midi=52, confidence=0.8)]


class StubAnalyzer:
    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        return StructureResult(timing=Timing(), chords=[], sections=[])


class StubAudioSource:
    """Stands in for UploadSource, so these tests need no ffprobe."""

    def __init__(self, path: Path | str, **kwargs: object) -> None:
        self._path = Path(path)

    def fetch(self) -> IngestedAudio:
        return IngestedAudio(path=self._path, title=self._path.stem, duration_sec=30.0)


@dataclass
class Harness:
    store: InMemoryJobStore
    blobs: InMemoryBlobStore
    separator: StubSeparator
    transcriber: StubTranscriber
    job_id: str

    def deps(self) -> WorkerDeps:
        return WorkerDeps(
            store=self.store,
            blobs=self.blobs,
            stages=lambda work_dir: Stages(
                separator=self.separator,
                transcriber=self.transcriber,
                analyzer=StubAnalyzer(),
                mapper=ViterbiFretboardMapper(),
            ),
        )

    def run(self, retries_left: int = 2) -> None:
        process_job(self.job_id, self.deps(), retries_left=retries_left)

    def row(self) -> Job:
        row = self.store.get(self.job_id)
        assert row is not None
        return row


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    monkeypatch.setattr(runner, "UploadSource", StubAudioSource)
    store = InMemoryJobStore()
    blobs = InMemoryBlobStore()
    job, _ = store.create(sample_new_job(title="My Song"))
    blobs.put_bytes(job.upload_key, b"pretend mp3 bytes")
    return Harness(store, blobs, StubSeparator(), StubTranscriber(), job.id)


def test_a_job_runs_to_a_stored_document(harness: Harness) -> None:
    harness.run()

    row = harness.row()
    assert row.status is JobStatus.SUCCEEDED
    assert (row.stage, row.percent, row.attempts) == (None, 100, 1)
    document = TabDocument.model_validate(row.document)
    assert document.source.title == "My Song"  # the row's, not the temp file's
    assert document.source.audio_url == f"/jobs/{row.id}/audio/mix"
    assert len(document.notes) == 1
    assert row.stem_key == CacheKeys(row.content_hash).stem
    assert harness.blobs.get_bytes(row.stem_key) == b"pretend mp3 bytes"


def test_progress_reaches_the_row_while_the_job_runs(
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
        ("separation", 0),
        ("separation", 20),
        ("transcription", 40),
        ("structure", 65),
        ("fretboard", 80),
        ("fretboard", 100),
    ]


def test_a_pipeline_error_fails_the_job_without_a_retry(harness: Harness) -> None:
    harness.separator.error = PipelineError(
        FailureReason.NO_GUITAR_DETECTED,
        "No clear guitar part was found in this recording.",
    )

    harness.run()  # returns normally, which tells RQ not to retry

    row = harness.row()
    assert row.status is JobStatus.FAILED
    assert row.failure_reason is FailureReason.NO_GUITAR_DETECTED
    assert row.failure_message == "No clear guitar part was found in this recording."
    assert row.failed_stage == "separation"
    assert row.stage is None


def test_a_file_the_worker_rejects_fails_before_any_stage(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TooLong(StubAudioSource):
        def fetch(self) -> IngestedAudio:
            raise PipelineError(FailureReason.TOO_LONG, "Try a single song.")

    monkeypatch.setattr(runner, "UploadSource", TooLong)

    harness.run()

    row = harness.row()
    assert row.failure_reason is FailureReason.TOO_LONG
    assert row.failed_stage is None
    assert harness.separator.calls == 0


def test_another_exception_with_retries_left_requeues_and_reraises(
    harness: Harness,
) -> None:
    harness.separator.error = RuntimeError("storage blinked")

    with pytest.raises(RuntimeError):
        harness.run(retries_left=1)

    row = harness.row()
    assert row.status is JobStatus.QUEUED
    assert (row.stage, row.percent, row.attempts) == (None, 0, 1)


def test_the_last_attempt_fails_internal_and_reraises(harness: Harness) -> None:
    harness.separator.error = RuntimeError("still broken")

    with pytest.raises(RuntimeError):  # RQ files it in FailedJobRegistry
        harness.run(retries_left=0)

    row = harness.row()
    assert row.status is JobStatus.FAILED
    assert row.failure_reason is FailureReason.INTERNAL
    assert row.failure_message == INTERNAL_FAILURE_MESSAGE
    assert row.failed_stage == "separation"


def test_a_finished_job_delivered_again_is_left_alone(harness: Harness) -> None:
    harness.run()
    before = harness.row()

    harness.run()

    assert harness.row() == before
    assert harness.separator.calls == 1


def test_a_retry_resumes_from_the_cached_separation(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec success condition 3: a worker that crashes after separation, then
    succeeds on retry, does not run separation twice."""
    write = harness.store.set_progress
    crashed: list[bool] = []

    def crash_once_when_transcription_starts(
        job_id: str, stage: str, percent: int
    ) -> bool:
        if stage == "transcription" and not crashed:
            crashed.append(True)
            raise ConnectionError("postgres went away")
        return write(job_id, stage, percent)

    monkeypatch.setattr(
        harness.store, "set_progress", crash_once_when_transcription_starts
    )

    with pytest.raises(ConnectionError):
        harness.run(retries_left=2)
    assert harness.row().status is JobStatus.QUEUED

    harness.run(retries_left=1)

    row = harness.row()
    assert row.status is JobStatus.SUCCEEDED
    assert row.attempts == 2
    assert harness.separator.calls == 1


def test_a_row_left_running_by_a_killed_worker_is_resumed(harness: Harness) -> None:
    """Review Focus 4: SIGKILL means no except ran; RQ redelivers anyway."""
    harness.store.mark_running(harness.job_id)

    harness.run(retries_left=1)

    row = harness.row()
    assert row.status is JobStatus.SUCCEEDED
    assert row.attempts == 2


def test_a_result_after_the_row_was_failed_is_dropped(harness: Harness) -> None:
    def reconciled_behind_our_back() -> None:
        harness.store.fail(
            harness.job_id,
            reason=FailureReason.INTERNAL,
            message="lost",
            stage="transcription",
            expect=JobStatus.RUNNING,
        )

    harness.transcriber.during = reconciled_behind_our_back

    harness.run()  # no exception: the late result is logged and dropped

    row = harness.row()
    assert row.status is JobStatus.FAILED
    assert row.failure_message == "lost"
    assert row.document is None


def test_an_unknown_job_is_dropped(harness: Harness) -> None:
    process_job("5f0c6c2e-0000-4000-8000-0000000000ff", harness.deps(), retries_left=2)

    assert harness.separator.calls == 0


def test_the_dotted_path_the_api_enqueues_is_run_job() -> None:
    # Renaming or moving run_job must fail here, not in every queued job.
    module_name, _, function_name = RUN_JOB.rpartition(".")

    assert (
        getattr(importlib.import_module(module_name), function_name) is runner.run_job
    )


@pytest.mark.parametrize(
    ("current", "expected"), [(SimpleNamespace(retries_left=1), 1), (None, 0)]
)
def test_run_job_hands_rq_retries_left_to_process_job(
    monkeypatch: pytest.MonkeyPatch, current: object, expected: int
) -> None:
    seen: dict[str, object] = {}

    @contextmanager
    def fake_deps(settings: object) -> Iterator[str]:
        yield "deps"

    def fake_process(job_id: str, deps: object, *, retries_left: int) -> None:
        seen.update(job_id=job_id, deps=deps, retries_left=retries_left)

    monkeypatch.setattr(runner, "get_current_job", lambda: current)
    monkeypatch.setattr(runner, "open_deps", fake_deps)
    monkeypatch.setattr(runner, "process_job", fake_process)

    runner.run_job("abc")

    # Outside RQ (no current job) the attempt is treated as the last one.
    assert seen == {"job_id": "abc", "deps": "deps", "retries_left": expected}
```

In `apps/worker/tests/test_cli.py`, add `import os`, `from guitarvis_jobs.settings import Settings` and `from guitarvis_worker import runner`, and append:

```python
def test_serve_runs_the_queue_worker_with_the_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Recorded so monkeypatch restores it, although serve sets it directly.
    monkeypatch.setenv("GUITARVIS_DEVICE", "")
    seen: dict[str, object] = {}

    def fake_serve(settings: Settings, *, burst: bool) -> None:
        seen.update(device=settings.device, burst=burst)

    monkeypatch.setattr(runner, "serve", fake_serve)

    assert cli.main(["serve", "--device", "cuda", "--burst"]) == 0
    assert seen == {"device": "cuda", "burst": True}
    # Each job runs in a forked work horse that reads the environment.
    assert os.environ["GUITARVIS_DEVICE"] == "cuda"
```

Run: `uv run pytest apps/worker/tests/test_runner.py apps/worker/tests/test_cli.py -v`
Expected: collection error, `cannot import name 'runner'`.

- [ ] **Step 2: Implement `runner.py`**

```python
"""The queue's entry point: one job, end to end, against the shared stores.

`run_job` is what RQ calls, found by the dotted path in
guitarvis_jobs.queue.RUN_JOB. It is a thin adapter: it reads how many
retries RQ has left and hands off to `process_job`, which tests drive
directly with in-memory stores and stub stages.

RQ delivers at least once, so a second delivery of a finished job must be
harmless. The api's reconciliation can fail a row behind the worker's back,
so every write after the job starts is conditional on the row still being
running; when one changes nothing, the worker logs and drops its result.
"""

import logging
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

from guitarvis_core.contracts import (
    FailureReason,
    FretboardMapper,
    PipelineError,
    Separator,
    StructureAnalyzer,
    Transcriber,
)
from guitarvis_jobs.blobs import BlobStore, S3BlobStore
from guitarvis_jobs.models import (
    FINISHED_STATUSES,
    INTERNAL_FAILURE_MESSAGE,
    Job,
    JobStatus,
)
from guitarvis_jobs.postgres import PostgresJobStore
from guitarvis_jobs.queue import QUEUE_NAME
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.store import JobStore
from redis import Redis
from rq import Worker, get_current_job

from guitarvis_worker.caching import (
    CachedAnalyzer,
    CachedSeparator,
    CachedTranscriber,
    CacheKeys,
)
from guitarvis_worker.ingest import UploadSource
from guitarvis_worker.pipeline import StageProgress, run_pipeline
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper
from guitarvis_worker.stages.separation import DemucsSeparator
from guitarvis_worker.stages.structure import LibrosaStructureAnalyzer
from guitarvis_worker.stages.transcription import BasicPitchTranscriber

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Stages:
    separator: Separator
    transcriber: Transcriber
    analyzer: StructureAnalyzer
    mapper: FretboardMapper


def build_stages(work_dir: Path, device: str | None = None) -> Stages:
    """The real stages. Tests patch this name, as test_cli patches cli's."""
    return Stages(
        separator=DemucsSeparator(work_dir=work_dir, device=device),
        transcriber=BasicPitchTranscriber(),
        analyzer=LibrosaStructureAnalyzer(),
        mapper=ViterbiFretboardMapper(),
    )


@dataclass(frozen=True)
class WorkerDeps:
    store: JobStore
    blobs: BlobStore
    stages: Callable[[Path], Stages]


class _ProgressWriter:
    """Writes each progress update to the row and remembers the stage running."""

    def __init__(self, store: JobStore, job_id: str) -> None:
        self._store = store
        self._job_id = job_id
        self._warned = False
        self.stage: str | None = None

    def __call__(self, update: StageProgress) -> None:
        self.stage = update.stage
        if self._store.set_progress(self._job_id, update.stage, update.percent):
            return
        if not self._warned:
            self._warned = True
            log.warning(
                "job %s is no longer running; its progress is not recorded",
                self._job_id,
            )


def process_job(job_id: str, deps: WorkerDeps, *, retries_left: int) -> None:
    """Run one delivery of a job. `retries_left` is RQ's count; 0 means last."""
    job = deps.store.get(job_id)
    if job is None:
        log.warning("job %s does not exist; dropping it", job_id)
        return
    if job.status in FINISHED_STATUSES:
        log.info("job %s is already %s; ignoring a repeat delivery", job_id, job.status)
        return
    if deps.store.mark_running(job_id) is None:
        log.info("job %s finished elsewhere before it could start", job_id)
        return

    progress = _ProgressWriter(deps.store, job_id)
    try:
        document, stem_key = _run(job, deps, progress)
    except PipelineError as error:
        # Deterministic: another attempt gives the same answer. Returning
        # normally tells RQ not to retry.
        deps.store.fail(
            job_id,
            reason=error.reason,
            message=str(error),
            stage=progress.stage,
            expect=JobStatus.RUNNING,
        )
        return
    except Exception:
        if retries_left > 0:
            deps.store.requeue(job_id)
        else:
            deps.store.fail(
                job_id,
                reason=FailureReason.INTERNAL,
                message=INTERNAL_FAILURE_MESSAGE,
                stage=progress.stage,
                expect=JobStatus.RUNNING,
            )
        # Re-raised so RQ schedules the retry, or on the last attempt files
        # the job in its FailedJobRegistry — the dead-letter queue — with
        # the traceback. The row is what the user sees.
        raise

    if not deps.store.succeed(job_id, document=document, stem_key=stem_key):
        log.warning("job %s was failed while it ran; dropping its result", job_id)


def _run(
    job: Job, deps: WorkerDeps, progress: _ProgressWriter
) -> tuple[dict[str, Any], str]:
    keys = CacheKeys(job.content_hash)
    with tempfile.TemporaryDirectory(prefix="guitarvis-job-") as tmp:
        work_dir = Path(tmp)
        upload = work_dir / f"upload{PurePosixPath(job.upload_key).suffix}"
        deps.blobs.get_file(job.upload_key, upload)
        # Probed again here: the worker must not trust its caller.
        audio = replace(UploadSource(upload).fetch(), title=job.title)
        stages = deps.stages(work_dir)
        result = run_pipeline(
            audio,
            separator=CachedSeparator(stages.separator, deps.blobs, keys, work_dir),
            transcriber=CachedTranscriber(stages.transcriber, deps.blobs, keys),
            analyzer=CachedAnalyzer(stages.analyzer, deps.blobs, keys),
            mapper=stages.mapper,
            progress=progress,
            audio_url=f"/jobs/{job.id}/audio/mix",
        )
    return result.document.model_dump(mode="json"), keys.stem


def run_job(job_id: str) -> None:
    """RQ's entry point, enqueued by name (guitarvis_jobs.queue.RUN_JOB)."""
    current = get_current_job()
    retries_left = (
        current.retries_left
        if current is not None and current.retries_left is not None
        else 0
    )
    with open_deps(Settings.from_env()) as deps:
        process_job(job_id, deps, retries_left=retries_left)


@contextmanager
def open_deps(settings: Settings) -> Iterator[WorkerDeps]:
    """Real stores for one job.

    Built per job: each job runs in a forked work horse, and a database
    engine must not cross a fork with connections in its pool.
    """
    store = PostgresJobStore.from_url(settings.database_url)
    try:
        yield WorkerDeps(
            store=store,
            blobs=S3BlobStore.from_settings(settings),
            stages=lambda work_dir: build_stages(work_dir, settings.device),
        )
    finally:
        store.engine.dispose()


def serve(settings: Settings, *, burst: bool = False) -> None:
    """Run jobs from the queue until stopped (or, with `burst`, until empty).

    The scheduler is on because RQ needs it to run retries after their
    intervals.
    """
    connection = Redis.from_url(settings.redis_url)
    Worker([QUEUE_NAME], connection=connection).work(with_scheduler=True, burst=burst)
```

- [ ] **Step 3: Add `serve` to the CLI**

In `apps/worker/src/guitarvis_worker/cli.py`, add `import os`, `from guitarvis_jobs.settings import Settings` and `from guitarvis_worker import runner`. In `_build_parser`, before `return parser`, add:

```python
serve = subparsers.add_parser("serve", help="run jobs from the queue until stopped")
serve.add_argument(
    "--device", default=None, help="torch device for every job, e.g. cuda"
)
serve.add_argument("--burst", action="store_true", help="exit once the queue is empty")
```

Rename the existing `def main(argv: list[str] | None = None) -> int:` to `def _process(args: argparse.Namespace) -> int:`, delete its first line (`args = _build_parser().parse_args(argv)`), and add above it:

```python
def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    return _process(args)


def _serve(args: argparse.Namespace) -> int:
    if args.device:
        # Each job runs in a forked work horse that reads its settings from
        # the environment, so this is how the flag reaches every job.
        os.environ["GUITARVIS_DEVICE"] = args.device
    runner.serve(Settings.from_env(), burst=args.burst)
    return 0
```

Update the module docstring's last sentence from `It is also the seam the future job worker replaces.` to `` `serve` hands the same stages to the queue worker in runner.py. ``

In `Makefile`, add `worker` to `.PHONY` and, after `migrate`:

```make
worker: ## Run jobs from the queue (ARGS="--device cuda"; needs `uv sync --extra ml`)
	$(UV) run guitarvis-worker serve $(ARGS)
```

- [ ] **Step 4: Run the worker suite**

Run: `uv run pytest apps/worker -v && uv run mypy apps/worker/src apps/worker/tests`
Expected: all PASS; mypy `Success`.

- [ ] **Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add apps/worker Makefile
git commit -m "feat(worker): process_job, the RQ entry point, and guitarvis-worker serve

A PipelineError fails the job without a retry; any other exception requeues
and re-raises, or fails internal on the last attempt. Writes are conditional
on the row still running, so a late result after reconciliation is dropped.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The api's read side: job status, document, audio, health, reconciliation

`create_app(services)` takes the stores, so tests hand in the in-memory twins. The module-level `app` builds the real ones in its lifespan, so importing it opens no connection. This task covers every route except `POST /jobs` (Task 11): the error vocabulary and its handlers, the `JobView` body, and read-time reconciliation.

**Files:**
- Modify: `apps/api/pyproject.toml` (dependencies)
- Modify: `pyproject.toml` (root dev group: `httpx2`)
- Create: `apps/api/src/guitarvis_api/services.py`, `errors.py`, `schemas.py`, `reconcile.py`, `routes.py`
- Modify: `apps/api/src/guitarvis_api/app.py` (whole file below)
- Create: `apps/api/tests/api_fixture.py`, `apps/api/tests/test_job_routes.py`, `apps/api/tests/test_health.py`
- Modify: `Makefile` (`api` target)

**Interfaces:**
- Consumes: everything in `guitarvis_jobs` from Tasks 4–7; `guitarvis_core.audio.probe_duration` (Task 1).
- Produces:
  - `guitarvis_api.services.Services(store, blobs, queue, settings, probe: Callable[[Path], float] = probe_duration, clock: Clock = utc_now)` and `build_services(settings) -> Services`.
  - `guitarvis_api.errors.HttpReason` (StrEnum: `too_large`, `too_many_jobs`, `not_found`, `not_ready`), `Reason = FailureReason | HttpReason`, `ApiError(status_code, reason, message)` (a Starlette `HTTPException`), `error_body(reason, message) -> dict` and `install_error_handlers(app)`.
  - `guitarvis_api.schemas.JobView` (`.of(job)`) and `FailureView`.
  - `guitarvis_api.reconcile.QUEUED_GRACE = timedelta(seconds=60)`, `RUNNING_GRACE = timedelta(minutes=5)` and `reconcile(job, services) -> Job`.
  - `guitarvis_api.routes.router` and `services_of(request) -> Services`.
  - `guitarvis_api.app.create_app(services: Services | None = None) -> FastAPI` and the module-level `app`.
  - Test helper `api_fixture.make_api(*, probe=…, store=None, blobs=None, raise_server_exceptions=True, **settings) -> Api`. `Api` has `.client`, `.store`, `.blobs`, `.queue`, `.clock`, `.settings`, `.services`, `.job(id)` and `.client_from(ip)`. Requests come from `CLIENT_IP = "203.0.113.7"`.

- [ ] **Step 1: Dependencies and the `api` target**

`apps/api/pyproject.toml`:

```toml
dependencies = [
    "guitarvis-core",
    "guitarvis-jobs",
    "fastapi>=0.115",
    "uvicorn>=0.30",
]
```

In the root `pyproject.toml`, add `"httpx2>=2.13",` to `[dependency-groups].dev`. Starlette 1.7's `TestClient` warns that plain `httpx` is deprecated in its favour.

In `Makefile`, add `api` to `.PHONY` and, after `migrate`:

```make
api: ## Serve the api on localhost:8000, reloading on change
	$(UV) run uvicorn guitarvis_api.app:app --reload
```

Run: `uv lock && uv sync`

- [ ] **Step 2: Write the test helper and the failing tests**

`apps/api/tests/api_fixture.py`:

```python
"""The api on in-memory twins, for route tests.

Imported by bare name, as apps/eval/tests imports guitarset_fixture; there is
no conftest.py anywhere in this repo (see the Makefile's mypy note).
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from guitarvis_api.app import create_app
from guitarvis_api.services import Services
from guitarvis_jobs.blobs import InMemoryBlobStore
from guitarvis_jobs.models import Job
from guitarvis_jobs.queue import InMemoryJobQueue
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.store import InMemoryJobStore
from guitarvis_jobs.testing import FakeClock

CLIENT_IP = "203.0.113.7"


def thirty_seconds(path: Path) -> float:
    return 30.0


@dataclass
class Api:
    client: TestClient
    store: InMemoryJobStore
    blobs: InMemoryBlobStore
    queue: InMemoryJobQueue
    clock: FakeClock
    settings: Settings
    services: Services

    def job(self, job_id: str) -> Job:
        job = self.store.get(job_id)
        assert job is not None, f"no job {job_id}"
        return job

    def client_from(self, ip: str) -> TestClient:
        """Another client of the same app, from another address."""
        return TestClient(self.client.app, client=(ip, 50000))


def make_api(
    *,
    probe: Callable[[Path], float] = thirty_seconds,
    store: InMemoryJobStore | None = None,
    blobs: InMemoryBlobStore | None = None,
    raise_server_exceptions: bool = True,
    **settings: Any,  # Settings fields to override, e.g. max_upload_mb=1
) -> Api:
    clock = FakeClock()
    store = store if store is not None else InMemoryJobStore(clock=clock)
    blobs = blobs if blobs is not None else InMemoryBlobStore()
    queue = InMemoryJobQueue()
    resolved = replace(Settings(), **settings)
    services = Services(
        store=store,
        blobs=blobs,
        queue=queue,
        settings=resolved,
        probe=probe,
        clock=clock,
    )
    client = TestClient(
        create_app(services),
        client=(CLIENT_IP, 50000),
        raise_server_exceptions=raise_server_exceptions,
    )
    return Api(client, store, blobs, queue, clock, resolved, services)
```

`apps/api/tests/test_job_routes.py`:

```python
"""Reading jobs: status, document, audio redirects, errors and reconciliation."""

from collections.abc import Callable

import pytest
from api_fixture import Api, make_api
from fastapi.testclient import TestClient
from guitarvis_api import app as app_module
from guitarvis_api.errors import HttpReason
from guitarvis_api.reconcile import reconcile
from guitarvis_core.contracts import FailureReason
from guitarvis_core.tabdoc import Instrument, Source, TabDocument, Timing
from guitarvis_jobs.blobs import PRESIGN_EXPIRES_SEC
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, JobStatus
from guitarvis_jobs.store import InMemoryJobStore
from guitarvis_jobs.testing import sample_new_job

MISSING_ID = "5f0c6c2e-0000-4000-8000-0000000000ff"
STEM_KEY = "cache/v1/" + "a" * 64 + "/separation/stem.wav"
DOCUMENT = TabDocument(
    source=Source(title="song", duration_sec=30.0, audio_url="/jobs/x/audio/mix"),
    instrument=Instrument(),
    timing=Timing(),
).model_dump(mode="json")


def queued(api: Api) -> str:
    job, _ = api.store.create(sample_new_job())
    return job.id


def running(api: Api) -> str:
    job_id = queued(api)
    api.store.mark_running(job_id)
    return job_id


def succeeded(api: Api) -> str:
    job_id = running(api)
    api.store.succeed(job_id, document=DOCUMENT, stem_key=STEM_KEY)
    return job_id


def failed(api: Api) -> str:
    job_id = running(api)
    api.store.set_progress(job_id, "separation", 12)
    api.store.fail(
        job_id,
        reason=FailureReason.NO_GUITAR_DETECTED,
        message="No clear guitar part was found in this recording.",
        stage="separation",
        expect=JobStatus.RUNNING,
    )
    return job_id


def test_an_unknown_job_is_not_found() -> None:
    response = make_api().client.get(f"/jobs/{MISSING_ID}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"reason": "not_found", "message": "There is no job with that id."}
    }


@pytest.mark.parametrize(
    "path", ["/jobs/not-a-uuid", "/jobs/not-a-uuid/document", "/jobs/x/audio/mix"]
)
def test_a_malformed_id_is_not_found_rather_than_invalid(path: str) -> None:
    response = make_api().client.get(path)

    assert response.status_code == 404
    assert response.json()["error"]["reason"] == "not_found"


def test_a_queued_job() -> None:
    api = make_api()
    job_id = queued(api)

    assert api.client.get(f"/jobs/{job_id}").json() == {
        "id": job_id,
        "status": "queued",
        "stage": None,
        "percent": 0,
        "attempts": 0,
        "title": "song",
        "duration_sec": 30.0,
        "failure": None,
        "created_at": "2026-10-08T12:00:00Z",
        "updated_at": "2026-10-08T12:00:00Z",
    }


def test_a_running_job_reports_its_stage_and_percent() -> None:
    api = make_api()
    job_id = running(api)
    api.store.set_progress(job_id, "separation", 23)

    body = api.client.get(f"/jobs/{job_id}").json()

    assert (body["status"], body["stage"], body["percent"], body["attempts"]) == (
        "running",
        "separation",
        23,
        1,
    )


def test_a_failed_job_says_why_and_where() -> None:
    api = make_api()
    job_id = failed(api)

    body = api.client.get(f"/jobs/{job_id}").json()

    assert body["status"] == "failed"
    assert body["stage"] is None
    assert body["failure"] == {
        "reason": "no_guitar_detected",
        "message": "No clear guitar part was found in this recording.",
        "stage": "separation",
    }


def test_the_document_of_a_finished_job_is_a_tab_document() -> None:
    api = make_api()
    job_id = succeeded(api)

    response = api.client.get(f"/jobs/{job_id}/document")

    assert response.status_code == 200
    assert (
        TabDocument.model_validate(response.json()).model_dump(mode="json") == DOCUMENT
    )


@pytest.mark.parametrize(
    ("make", "says"),
    [(queued, "not ready"), (running, "not ready"), (failed, "failed")],
)
def test_a_document_that_is_not_ready(make: Callable[[Api], str], says: str) -> None:
    api = make_api()
    job_id = make(api)

    response = api.client.get(f"/jobs/{job_id}/document")

    assert response.status_code == 409
    assert response.json()["error"]["reason"] == "not_ready"
    assert says in response.json()["error"]["message"]


def test_the_mix_redirects_to_a_presigned_url() -> None:
    api = make_api()
    job_id = queued(api)

    response = api.client.get(f"/jobs/{job_id}/audio/mix", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == api.blobs.presign_get(
        api.job(job_id).upload_key, expires_sec=PRESIGN_EXPIRES_SEC
    )


def test_the_guitar_redirects_once_the_stem_exists() -> None:
    api = make_api()
    job_id = succeeded(api)

    response = api.client.get(f"/jobs/{job_id}/audio/guitar", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == api.blobs.presign_get(
        STEM_KEY, expires_sec=PRESIGN_EXPIRES_SEC
    )


def test_the_guitar_is_not_ready_before_separation_finishes() -> None:
    api = make_api()
    job_id = running(api)

    response = api.client.get(f"/jobs/{job_id}/audio/guitar", follow_redirects=False)

    assert response.status_code == 409
    assert response.json()["error"]["reason"] == "not_ready"


def test_an_unknown_route_uses_the_error_body() -> None:
    response = make_api().client.get("/nope")

    assert response.status_code == 404
    assert response.json()["error"]["reason"] == "not_found"


def test_an_unexpected_error_uses_the_error_body_and_hides_the_detail() -> None:
    class OnFire(InMemoryJobStore):
        def get(self, job_id: str) -> None:
            raise RuntimeError("the database is on fire")

    api = make_api(store=OnFire(), raise_server_exceptions=False)

    response = api.client.get(f"/jobs/{MISSING_ID}")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"reason": "internal", "message": INTERNAL_FAILURE_MESSAGE}
    }


def test_the_http_layer_adds_exactly_four_reasons() -> None:
    http = {reason.value for reason in HttpReason}

    assert http == {"too_large", "too_many_jobs", "not_found", "not_ready"}
    assert not http & {reason.value for reason in FailureReason}


def test_the_module_app_connects_to_nothing_until_it_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not hasattr(app_module.app.state, "services")
    built: list[object] = []

    def fake_build(settings: object) -> object:
        built.append(settings)
        return make_api().services

    monkeypatch.setattr(app_module, "build_services", fake_build)

    with TestClient(app_module.create_app()) as client:
        assert client.get("/health").status_code == 200
    assert len(built) == 1


# Reconciliation: the two ways Postgres and Redis can disagree, repaired on read.


def test_a_queued_job_the_queue_lost_is_failed_on_read() -> None:
    api = make_api()
    job_id = queued(api)  # never enqueued: as if the api died in between
    api.clock.advance(seconds=61)

    body = api.client.get(f"/jobs/{job_id}").json()

    assert body["status"] == "failed"
    assert body["failure"] == {
        "reason": "internal",
        "message": INTERNAL_FAILURE_MESSAGE,
        "stage": None,
    }


def test_a_queued_job_inside_its_grace_period_is_left_alone() -> None:
    api = make_api()
    job_id = queued(api)
    api.clock.advance(seconds=60)

    assert api.client.get(f"/jobs/{job_id}").json()["status"] == "queued"


def test_a_queued_job_the_queue_still_holds_is_left_alone() -> None:
    api = make_api()
    job_id = queued(api)
    api.queue.enqueue(job_id)
    api.clock.advance(hours=1)

    assert api.client.get(f"/jobs/{job_id}").json()["status"] == "queued"


def test_redis_down_while_polling_answers_from_postgres() -> None:
    """Review Focus 3: a queue that cannot be asked is not a lost job."""
    api = make_api()
    job_id = queued(api)
    api.queue.down = True
    api.clock.advance(seconds=61)

    response = api.client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_a_running_job_long_past_its_timeout_is_failed_on_read() -> None:
    api = make_api(job_timeout_sec=60)
    job_id = running(api)
    api.store.set_progress(job_id, "separation", 12)
    api.clock.advance(seconds=60 + 5 * 60 + 1)

    body = api.client.get(f"/jobs/{job_id}").json()

    assert body["status"] == "failed"
    assert body["failure"]["stage"] == "separation"


def test_a_running_job_inside_timeout_plus_grace_is_left_alone() -> None:
    api = make_api(job_timeout_sec=60)
    job_id = running(api)
    api.clock.advance(seconds=60 + 5 * 60)

    assert api.client.get(f"/jobs/{job_id}").json()["status"] == "running"


def test_a_worker_that_writes_first_wins() -> None:
    api = make_api(job_timeout_sec=60)
    job_id = running(api)
    api.clock.advance(seconds=400)
    stale = api.job(job_id)  # what a slow GET read...
    api.store.set_progress(job_id, "transcription", 40)  # ...before the worker wrote

    assert reconcile(stale, api.services).status is JobStatus.RUNNING
```

`apps/api/tests/test_health.py`:

```python
"""GET /health names whichever store did not answer."""

from api_fixture import make_api
from guitarvis_jobs.blobs import InMemoryBlobStore
from guitarvis_jobs.store import InMemoryJobStore


class DownStore(InMemoryJobStore):
    def ping(self) -> None:
        raise ConnectionError("postgres is down")


class DownBlobs(InMemoryBlobStore):
    def ping(self) -> None:
        raise ConnectionError("storage is down")


def test_everything_answers() -> None:
    response = make_api().client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "services": {"postgres": "ok", "redis": "ok", "storage": "ok"},
    }


def test_the_queue_does_not_answer() -> None:
    api = make_api()
    api.queue.down = True

    response = api.client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["services"] == {
        "postgres": "ok",
        "redis": "unreachable",
        "storage": "ok",
    }
    assert body["error"] == {"reason": "internal", "message": "Not answering: redis."}


def test_the_database_and_storage_do_not_answer() -> None:
    response = make_api(store=DownStore(), blobs=DownBlobs()).client.get("/health")

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Not answering: postgres, storage."
```

Run: `uv run pytest apps/api -v`
Expected: collection errors (`No module named 'guitarvis_api.services'` and similar).

- [ ] **Step 3: Implement `services.py`**

```python
"""What a request handler needs, bundled so tests can hand in the twins."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from guitarvis_core.audio import probe_duration
from guitarvis_jobs.blobs import BlobStore, S3BlobStore
from guitarvis_jobs.postgres import PostgresJobStore
from guitarvis_jobs.queue import JobQueue, RQJobQueue
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.store import Clock, JobStore, utc_now


@dataclass(frozen=True)
class Services:
    store: JobStore
    blobs: BlobStore
    queue: JobQueue
    settings: Settings
    probe: Callable[[Path], float] = probe_duration
    clock: Clock = utc_now


def build_services(settings: Settings) -> Services:
    """The real stores. Nothing here connects until first use."""
    return Services(
        store=PostgresJobStore.from_url(settings.database_url),
        blobs=S3BlobStore.from_settings(settings),
        queue=RQJobQueue.from_settings(settings),
        settings=settings,
    )
```

- [ ] **Step 4: Implement `errors.py`**

```python
"""One error vocabulary for every client.

Every error body is {"error": {"reason": ..., "message": ...}}. `reason` is a
FailureReason value or one of the four HttpReason values only the HTTP layer
produces, so a client maps one vocabulary to text.
"""

import logging
from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from guitarvis_core.contracts import FailureReason
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class HttpReason(StrEnum):
    TOO_LARGE = "too_large"
    TOO_MANY_JOBS = "too_many_jobs"
    NOT_FOUND = "not_found"
    NOT_READY = "not_ready"


Reason = FailureReason | HttpReason


class ApiError(StarletteHTTPException):
    """An HTTP error carrying a reason a client can map to text.

    A Starlette HTTPException on purpose: FastAPI re-raises those untouched
    from inside request-body parsing, which is what lets the upload limit
    abandon a request mid-stream with its own status and body.
    """

    def __init__(self, status_code: int, reason: Reason, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.reason = reason
        self.message = message


def error_body(reason: Reason, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"reason": reason.value, "message": message}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if isinstance(exc, ApiError):
            reason: Reason = exc.reason
            message = exc.message
        else:  # Starlette's own: an unknown route, a wrong method
            reason = (
                HttpReason.NOT_FOUND
                if exc.status_code in (404, 405)
                else FailureReason.INTERNAL
            )
            message = str(exc.detail)
        return JSONResponse(
            error_body(reason, message),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # The only validated input is POST /jobs's multipart body.
        return JSONResponse(
            error_body(
                FailureReason.UNSUPPORTED_FORMAT,
                "Send the audio as a multipart form field named `file`.",
            ),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error(
            "unhandled error on %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return JSONResponse(
            error_body(FailureReason.INTERNAL, INTERNAL_FAILURE_MESSAGE),
            status_code=500,
        )
```

- [ ] **Step 5: Implement `schemas.py`**

```python
"""The job as clients see it."""

from datetime import datetime

from guitarvis_core.contracts import FailureReason
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, Job, JobStatus
from pydantic import BaseModel


class FailureView(BaseModel):
    reason: str
    message: str
    stage: str | None


class JobView(BaseModel):
    """`failure` is set only when `status` is failed; `stage` only while running."""

    id: str
    status: JobStatus
    stage: str | None
    percent: int
    attempts: int
    title: str
    duration_sec: float
    failure: FailureView | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, job: Job) -> "JobView":
        failure = None
        if job.status is JobStatus.FAILED:
            failure = FailureView(
                reason=(job.failure_reason or FailureReason.INTERNAL).value,
                message=job.failure_message or INTERNAL_FAILURE_MESSAGE,
                stage=job.failed_stage,
            )
        return cls(
            id=job.id,
            status=job.status,
            stage=job.stage,
            percent=job.percent,
            attempts=job.attempts,
            title=job.title,
            duration_sec=job.duration_sec,
            failure=failure,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
```

- [ ] **Step 6: Implement `reconcile.py`**

```python
"""Repair, on read, the two ways Postgres and Redis can disagree (ADR 0007).

A row queued for over a minute whose RQ job is gone: the api died between
insert and enqueue, or Redis lost its data. The grace period covers the gap
between those two steps in a live request. A row running long past the job
timeout: the worker was killed outright and never ran its except. RQ's own
timeout raises inside the job, so the worker handles every timeout it can see.

Either is failed as internal, conditionally on the row being exactly as read,
so a worker that was merely slow and writes first wins. Nothing runs in the
background; a job nobody asks about can stay wrong until somebody does.
"""

import logging
from datetime import timedelta

from guitarvis_core.contracts import FailureReason
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, Job, JobStatus

from guitarvis_api.services import Services

log = logging.getLogger(__name__)

QUEUED_GRACE = timedelta(seconds=60)
RUNNING_GRACE = timedelta(minutes=5)


def reconcile(job: Job, services: Services) -> Job:
    """The job as it now stands — failed first, if the queue lost it."""
    if not _is_lost(job, services):
        return job
    services.store.fail(
        job.id,
        reason=FailureReason.INTERNAL,
        message=INTERNAL_FAILURE_MESSAGE,
        stage=job.stage,
        expect=job.status,
        expect_updated_at=job.updated_at,
    )
    return services.store.get(job.id) or job


def _is_lost(job: Job, services: Services) -> bool:
    age = services.clock() - job.updated_at
    if job.status is JobStatus.RUNNING:
        timeout = timedelta(seconds=services.settings.job_timeout_sec)
        return age > timeout + RUNNING_GRACE
    if job.status is not JobStatus.QUEUED or age <= QUEUED_GRACE:
        return False
    try:
        return not services.queue.exists(job.id)
    except Exception:
        # Redis is down: answer from Postgres now, and repair on a later read.
        log.warning("could not ask the queue about job %s", job.id, exc_info=True)
        return False
```

- [ ] **Step 7: Implement `routes.py` (everything but the upload)**

```python
"""Every route. Plain `def`: the work is blocking I/O, which FastAPI runs in
its threadpool."""

import logging
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from guitarvis_core.contracts import FailureReason
from guitarvis_jobs.blobs import PRESIGN_EXPIRES_SEC
from guitarvis_jobs.models import Job, JobStatus

from guitarvis_api.errors import ApiError, HttpReason, error_body
from guitarvis_api.reconcile import reconcile
from guitarvis_api.schemas import JobView
from guitarvis_api.services import Services

log = logging.getLogger(__name__)

router = APIRouter()


def services_of(request: Request) -> Services:
    return cast(Services, request.app.state.services)


def _load(services: Services, job_id: str) -> Job:
    job = services.store.get(job_id)
    if job is None:
        raise ApiError(404, HttpReason.NOT_FOUND, "There is no job with that id.")
    return job


def _not_ready(job: Job, what: str) -> ApiError:
    if job.status is JobStatus.FAILED:
        return ApiError(
            409, HttpReason.NOT_READY, f"That job failed, so it has no {what}."
        )
    return ApiError(
        409,
        HttpReason.NOT_READY,
        f"The {what} is not ready yet. Poll the job until it succeeds.",
    )


@router.get("/jobs/{job_id}", response_model=JobView)
def get_job(job_id: str, request: Request) -> JobView:
    services = services_of(request)
    return JobView.of(reconcile(_load(services, job_id), services))


@router.get("/jobs/{job_id}/document")
def get_document(job_id: str, request: Request) -> JSONResponse:
    job = _load(services_of(request), job_id)
    if job.status is not JobStatus.SUCCEEDED or job.document is None:
        raise _not_ready(job, "tab document")
    return JSONResponse(job.document)


@router.get("/jobs/{job_id}/audio/mix")
def get_mix(job_id: str, request: Request) -> RedirectResponse:
    # A redirect, not bytes through the api: storage answers Range requests,
    # which seeking needs, and the api stays thin.
    services = services_of(request)
    job = _load(services, job_id)
    url = services.blobs.presign_get(job.upload_key, expires_sec=PRESIGN_EXPIRES_SEC)
    return RedirectResponse(url, status_code=307)


@router.get("/jobs/{job_id}/audio/guitar")
def get_guitar(job_id: str, request: Request) -> RedirectResponse:
    services = services_of(request)
    job = _load(services, job_id)
    if job.stem_key is None:
        raise _not_ready(job, "isolated guitar")
    url = services.blobs.presign_get(job.stem_key, expires_sec=PRESIGN_EXPIRES_SEC)
    return RedirectResponse(url, status_code=307)


@router.get("/health")
def health(request: Request) -> JSONResponse:
    services = services_of(request)
    checks = {
        "postgres": services.store.ping,
        "redis": services.queue.ping,
        "storage": services.blobs.ping,
    }
    answers: dict[str, str] = {}
    for name, ping in checks.items():
        try:
            ping()
        except Exception:
            log.warning("health: %s did not answer", name, exc_info=True)
            answers[name] = "unreachable"
        else:
            answers[name] = "ok"

    down = [name for name, answer in answers.items() if answer != "ok"]
    if not down:
        return JSONResponse({"status": "ok", "services": answers})
    body = error_body(FailureReason.INTERNAL, f"Not answering: {', '.join(down)}.")
    return JSONResponse({**body, "services": answers}, status_code=503)
```

- [ ] **Step 8: Rewrite `app.py`**

```python
"""The FastAPI application.

`create_app(services)` is what tests use, with in-memory twins. The
module-level `app` — what `make api` serves — builds the real stores from
Settings when it starts, not when it is imported, so importing this module
opens no connection and the boundary test can import it freely.

Behind a proxy, run uvicorn with --forwarded-allow-ips so request.client is
the user's address; the api parses no proxy headers itself.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from guitarvis_jobs.settings import Settings

from guitarvis_api import __version__
from guitarvis_api.errors import install_error_handlers
from guitarvis_api.routes import router
from guitarvis_api.services import Services, build_services


def create_app(services: Services | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if services is None:
            app.state.services = build_services(Settings.from_env())
        yield

    app = FastAPI(
        title="GuitarVis API",
        version=__version__,
        description="Audio in, tab documents out.",
        lifespan=lifespan,
    )
    if services is not None:
        app.state.services = services
    install_error_handlers(app)
    app.include_router(router)
    return app


app = create_app()
```

- [ ] **Step 9: Run the api suite**

Run: `uv run pytest apps/api -v`
Expected: all PASS, including both `test_boundaries.py` tests: importing the app still loads nothing from the ML stack.

Run: `uv run mypy apps/api/src apps/api/tests`
Expected: `Success`.

- [ ] **Step 10: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add apps/api pyproject.toml uv.lock Makefile
git commit -m "feat(api): job status, document and audio routes; health; reconciliation

create_app takes the stores; the module-level app builds real ones on start.
Every error body is {error: {reason, message}}. A job the queue lost is
failed on read, conditionally, so a slow worker that writes first wins.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: `POST /jobs`

The upload route, cheapest check first: size, then ffprobe, then dedupe, then the per-IP limit, then storage and the queue. Starlette writes a whole multipart body to disk before a route runs, so the size limit has two layers. A small ASGI middleware refuses an oversized body as it arrives: by its declared `Content-Length` before a byte is read, or by counting a chunked body. The route then counts the file's own bytes exactly while hashing them.

**Files:**
- Modify: `apps/api/pyproject.toml` (`python-multipart`)
- Create: `apps/api/src/guitarvis_api/uploads.py`
- Modify: `apps/api/src/guitarvis_api/routes.py` (the route and its helpers)
- Modify: `apps/api/src/guitarvis_api/app.py` (install the middleware)
- Create: `apps/api/tests/test_upload.py`

**Interfaces:**
- Consumes: `Services`, `ApiError`, `HttpReason`, `error_body`, `reconcile`, `JobView`, `services_of` (Task 10); `NewJob`, `JobStatus`, `INTERNAL_FAILURE_MESSAGE` (Task 4); `check_duration` (Task 1).
- Produces:
  - `guitarvis_api.uploads.UploadSizeLimit` (ASGI middleware).
  - `receive(source: BinaryIO, destination: Path, *, max_bytes: int) -> ReceivedUpload(path, content_hash, size)`.
  - `title_of(filename: str | None) -> str`, `extension_of(filename: str | None) -> str`, `upload_key(content_hash: str, filename: str | None) -> str`.
  - Constants: `MAX_TITLE_CHARS = 200`, `MULTIPART_ALLOWANCE = 64 * 1024`.
  - Route `POST /jobs`. Its answers: 202 with `Location` for a new job; 200 for an existing live job; 413 `too_large`; 422 `unsupported_format` (unreadable, empty or missing file) or `too_long`; 429 `too_many_jobs`; 503 `internal` (ffprobe missing, or the queue refused).

- [ ] **Step 1: Add the multipart dependency**

In `apps/api/pyproject.toml`, add `"python-multipart>=0.0.18",` to `dependencies` (FastAPI requires it for `UploadFile`). Run: `uv lock && uv sync`.

- [ ] **Step 2: Write the failing tests**

`apps/api/tests/test_upload.py`:

```python
"""POST /jobs: validate, dedupe, limit, store, enqueue — cheapest check first."""

import hashlib
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx2
import pytest
from api_fixture import CLIENT_IP, make_api
from fastapi.testclient import TestClient
from guitarvis_api.uploads import MAX_TITLE_CHARS, extension_of, title_of
from guitarvis_core.audio import probe_duration
from guitarvis_core.contracts import FailureReason, PipelineError
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, Job, JobStatus, NewJob

SONG = b"ID3 pretend these are mp3 bytes"
SONG_HASH = hashlib.sha256(SONG).hexdigest()
MIB = 1024 * 1024

requires_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None,
    reason="ffprobe not installed; install ffmpeg",
)


def post(
    client: TestClient, data: bytes = SONG, filename: str = "song.mp3"
) -> httpx2.Response:
    return client.post("/jobs", files={"file": (filename, data, "audio/mpeg")})


def refuse(error: PipelineError) -> Callable[[Path], float]:
    """A probe that rejects every file the way ffprobe would."""

    def probe(path: Path) -> float:
        raise error

    return probe


def test_a_new_upload_is_stored_queued_and_accepted() -> None:
    api = make_api()

    response = post(api.client)

    assert response.status_code == 202
    body = response.json()
    assert response.headers["location"] == f"/jobs/{body['id']}"
    assert (body["status"], body["percent"], body["title"], body["duration_sec"]) == (
        "queued",
        0,
        "song",
        30.0,
    )
    assert api.queue.enqueued == [body["id"]]
    job = api.job(body["id"])
    assert job.content_hash == SONG_HASH
    assert job.upload_key == f"uploads/{SONG_HASH}.mp3"
    assert job.client_ip == CLIENT_IP
    assert api.blobs.get_bytes(job.upload_key) == SONG


def test_the_same_file_again_is_the_same_job_and_no_new_work() -> None:
    api = make_api()
    first = post(api.client).json()

    again = post(api.client, filename="renamed.wav")

    assert again.status_code == 200
    assert again.json()["id"] == first["id"]
    assert api.queue.enqueued == [first["id"]]


def test_the_same_file_after_success_returns_the_finished_job() -> None:
    api = make_api()
    job_id = post(api.client).json()["id"]
    api.store.mark_running(job_id)
    api.store.succeed(job_id, document={}, stem_key="k")

    again = post(api.client)

    assert again.status_code == 200
    assert again.json()["status"] == "succeeded"


def test_the_same_file_after_a_failure_starts_over() -> None:
    api = make_api()
    first = post(api.client).json()["id"]
    api.store.mark_running(first)
    api.store.fail(
        first,
        reason=FailureReason.INTERNAL,
        message="m",
        stage=None,
        expect=JobStatus.RUNNING,
    )

    again = post(api.client)

    assert again.status_code == 202
    assert again.json()["id"] != first


def test_reupload_of_a_lost_job_starts_a_fresh_one() -> None:
    """Review Focus 5: the dedupe lookup is a read, so it reconciles."""
    api = make_api()
    first = post(api.client).json()["id"]
    api.queue.lose(first)
    api.clock.advance(seconds=61)

    again = post(api.client)

    assert again.status_code == 202
    assert again.json()["id"] != first
    assert api.job(first).status is JobStatus.FAILED


def test_a_duplicate_does_not_count_against_the_limit() -> None:
    api = make_api(max_active_jobs_per_ip=1)
    post(api.client)

    assert post(api.client).status_code == 200


def test_too_many_active_jobs_from_one_address() -> None:
    api = make_api(max_active_jobs_per_ip=2)
    assert post(api.client, b"one").status_code == 202
    assert post(api.client, b"two").status_code == 202

    third = post(api.client, b"three")

    assert third.status_code == 429
    assert third.json()["error"]["reason"] == "too_many_jobs"
    assert post(api.client_from("198.51.100.9"), b"three").status_code == 202
    assert len(api.queue.enqueued) == 3


def test_a_finished_job_frees_its_slot() -> None:
    api = make_api(max_active_jobs_per_ip=1)
    job_id = post(api.client, b"one").json()["id"]
    api.store.mark_running(job_id)
    api.store.succeed(job_id, document={}, stem_key="k")

    assert post(api.client, b"two").status_code == 202


def test_a_file_exactly_at_the_limit_is_accepted() -> None:
    api = make_api(max_upload_mb=1)

    assert post(api.client, b"x" * MIB).status_code == 202


def test_a_file_one_byte_over_the_limit_is_refused() -> None:
    api = make_api(max_upload_mb=1)

    response = post(api.client, b"x" * (MIB + 1))

    assert response.status_code == 413
    assert response.json()["error"]["reason"] == "too_large"
    assert "1 MB" in response.json()["error"]["message"]
    assert api.queue.enqueued == []


def test_a_body_far_over_the_limit_is_refused_by_its_declared_length() -> None:
    api = make_api(max_upload_mb=1)

    response = post(api.client, b"x" * (MIB + 100 * 1024))

    assert response.status_code == 413
    assert response.json()["error"]["reason"] == "too_large"


def test_an_oversized_body_with_no_declared_length_is_abandoned() -> None:
    api = make_api(max_upload_mb=1)

    def chunked() -> Iterator[bytes]:
        yield (
            b'--zzz\r\nContent-Disposition: form-data; name="file"; '
            b'filename="big.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n'
        )
        for _ in range(20):
            yield b"x" * (64 * 1024)
        yield b"\r\n--zzz--\r\n"

    response = api.client.post(
        "/jobs",
        content=chunked(),
        headers={"content-type": "multipart/form-data; boundary=zzz"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["reason"] == "too_large"


def test_an_empty_file_is_refused() -> None:
    response = post(make_api().client, b"")

    assert response.status_code == 422
    assert response.json()["error"]["reason"] == "unsupported_format"


def test_a_file_that_is_not_audio_is_refused_before_it_is_stored() -> None:
    api = make_api(
        probe=refuse(
            PipelineError(
                FailureReason.UNSUPPORTED_FORMAT, "That file could not be read."
            )
        )
    )

    response = post(api.client)

    assert response.status_code == 422
    assert response.json()["error"] == {
        "reason": "unsupported_format",
        "message": "That file could not be read.",
    }
    assert not api.blobs.exists(f"uploads/{SONG_HASH}.mp3")
    assert api.queue.enqueued == []


def test_a_recording_over_ten_minutes_is_refused() -> None:
    response = post(make_api(probe=lambda path: 600.5).client)

    assert response.status_code == 422
    assert response.json()["error"]["reason"] == "too_long"
    assert "single song" in response.json()["error"]["message"]


def test_missing_ffprobe_is_our_problem_not_the_files() -> None:
    api = make_api(
        probe=refuse(PipelineError(FailureReason.INTERNAL, "ffprobe is not installed."))
    )

    response = post(api.client)

    assert response.status_code == 503
    assert response.json()["error"]["reason"] == "internal"


def test_a_request_without_a_file_field() -> None:
    response = make_api().client.post("/jobs", data={"song": "x"})

    assert response.status_code == 422
    assert response.json()["error"]["reason"] == "unsupported_format"
    assert "`file`" in response.json()["error"]["message"]


def test_a_queue_that_refuses_the_job() -> None:
    api = make_api()
    api.queue.fail_next = True

    response = post(api.client)

    assert response.status_code == 503
    assert response.json()["error"]["reason"] == "internal"
    assert api.store.find_live(SONG_HASH) is None  # the row was failed, not left queued
    retried = post(api.client)
    assert retried.status_code == 202


def test_a_failed_enqueue_leaves_the_generic_message_on_the_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = make_api()
    api.queue.fail_next = True
    created: list[str] = []
    create = api.store.create

    def recording(new: NewJob) -> tuple[Job, bool]:
        job, was_created = create(new)
        created.append(job.id)
        return job, was_created

    monkeypatch.setattr(api.store, "create", recording)

    post(api.client)

    row = api.job(created[0])
    assert row.status is JobStatus.FAILED
    assert row.failure_reason is FailureReason.INTERNAL
    assert row.failure_message == INTERNAL_FAILURE_MESSAGE


@requires_ffprobe
def test_the_real_probe_refuses_bytes_that_are_not_audio() -> None:
    response = post(make_api(probe=probe_duration).client, b"this is not audio")

    assert response.status_code == 422
    assert response.json()["error"]["reason"] == "unsupported_format"


@pytest.mark.parametrize(
    ("filename", "title", "extension"),
    [
        ("song.mp3", "song", ".mp3"),
        ("Song.MP3", "Song", ".mp3"),
        ("C:\\Users\\me\\Song.MP3", "Song", ".mp3"),
        ("/home/me/riff.wav", "riff", ".wav"),
        ("live.at.wembley.flac", "live.at.wembley", ".flac"),
        ("no-extension", "no-extension", ""),
        ("odd.extension-too-long", "odd", ""),
        ("spaced.m p3", "spaced", ""),
        ("", "Untitled", ""),
        (None, "Untitled", ""),
        ("x" * 300 + ".mp3", "x" * MAX_TITLE_CHARS, ".mp3"),
    ],
)
def test_title_and_extension_from_awkward_filenames(
    filename: str | None, title: str, extension: str
) -> None:
    """Review Focus 1: whatever a browser or curl sends, never a crash."""
    assert title_of(filename) == title
    assert extension_of(filename) == extension


def test_a_windows_path_filename_is_reduced_to_its_basename() -> None:
    api = make_api()

    body = post(api.client, filename="C:\\Users\\me\\Song.MP3").json()

    assert body["title"] == "Song"
    assert api.job(body["id"]).upload_key == f"uploads/{SONG_HASH}.mp3"
```

Run: `uv run pytest apps/api/tests/test_upload.py -v`
Expected: collection error, `No module named 'guitarvis_api.uploads'`.

- [ ] **Step 3: Implement `uploads.py`**

```python
"""Receiving an upload: the size limit, the hash, the title and the key.

Starlette writes a whole multipart body to disk before a route sees it, so a
limit checked only in the route would accept 2 GB first and refuse it after.
UploadSizeLimit sits in front of the app and abandons an oversized body as it
arrives; `receive` then counts the file's own bytes exactly while hashing.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from fastapi.responses import JSONResponse
from guitarvis_core.contracts import FailureReason
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from guitarvis_api.errors import ApiError, HttpReason, error_body

CHUNK_BYTES = 1024 * 1024
# Boundary lines and part headers around the file. The route enforces the
# limit on the file itself; this only keeps the framing from tripping it.
MULTIPART_ALLOWANCE = 64 * 1024
MAX_TITLE_CHARS = 200
_EXTENSION = re.compile(r"\.[a-z0-9]{1,5}")


def too_large(max_bytes: int) -> ApiError:
    return ApiError(
        413,
        HttpReason.TOO_LARGE,
        f"That file is larger than the {max_bytes // (1024 * 1024)} MB limit.",
    )


class UploadSizeLimit:
    """ASGI middleware: refuse an oversized POST /jobs before it lands.

    A declared Content-Length over the limit is refused before a byte is
    read. A body that declares none (chunked) is counted as it streams and
    abandoned the moment it passes the limit: the ApiError raised here comes
    out of FastAPI's body parsing untouched, as the 413 itself.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] != "/jobs"
        ):
            await self.app(scope, receive, send)
            return

        max_bytes: int = scope["app"].state.services.settings.max_upload_bytes
        limit = max_bytes + MULTIPART_ALLOWANCE
        declared = _content_length(scope)
        if declared is not None and declared > limit:
            error = too_large(max_bytes)
            response = JSONResponse(
                error_body(error.reason, error.message), status_code=413
            )
            await response(scope, receive, send)
            return

        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise too_large(max_bytes)
            return message

        await self.app(scope, counted, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


@dataclass(frozen=True)
class ReceivedUpload:
    path: Path
    content_hash: str
    size: int


def receive(source: BinaryIO, destination: Path, *, max_bytes: int) -> ReceivedUpload:
    """Copy the upload to `destination`, hashing and counting as it goes."""
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as out:
        while chunk := source.read(CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                raise too_large(max_bytes)
            digest.update(chunk)
            out.write(chunk)
    if size == 0:
        raise ApiError(422, FailureReason.UNSUPPORTED_FORMAT, "That file is empty.")
    return ReceivedUpload(path=destination, content_hash=digest.hexdigest(), size=size)


def _basename(filename: str | None) -> str:
    """The last path component, whichever separator the client's OS used."""
    return (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()


def title_of(filename: str | None) -> str:
    """The upload's filename without its last extension: the job's title."""
    return (
        PurePosixPath(_basename(filename)).stem.strip()[:MAX_TITLE_CHARS] or "Untitled"
    )


def extension_of(filename: str | None) -> str:
    """The lowercased suffix, kept only when it is 1 to 5 alphanumerics.

    ffprobe and Demucs sniff content, so this is a courtesy to a human
    browsing the bucket, never something the pipeline relies on.
    """
    suffix = PurePosixPath(_basename(filename)).suffix.lower()
    return suffix if _EXTENSION.fullmatch(suffix) else ""


def upload_key(content_hash: str, filename: str | None) -> str:
    return f"uploads/{content_hash}{extension_of(filename)}"
```

- [ ] **Step 4: Add the route**

In `apps/api/src/guitarvis_api/routes.py`, extend the imports:

```python
import logging
import tempfile
from pathlib import Path
from typing import cast

from fastapi import APIRouter, Request, Response, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from guitarvis_core.audio import check_duration
from guitarvis_core.contracts import FailureReason, PipelineError
from guitarvis_jobs.blobs import PRESIGN_EXPIRES_SEC
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, Job, JobStatus, NewJob

from guitarvis_api.errors import ApiError, HttpReason, error_body
from guitarvis_api.reconcile import reconcile
from guitarvis_api.schemas import JobView
from guitarvis_api.services import Services
from guitarvis_api.uploads import receive, title_of, upload_key
```

and add after `_not_ready`:

```python
@router.post("/jobs", status_code=202, response_model=JobView)
def create_job(file: UploadFile, request: Request, response: Response) -> JobView:
    """Validate, dedupe, limit, store and enqueue — cheapest check first."""
    services = services_of(request)
    settings = services.settings
    client_ip = request.client.host if request.client is not None else "unknown"

    with tempfile.TemporaryDirectory(prefix="guitarvis-upload-") as tmp:
        upload = receive(
            file.file, Path(tmp) / "upload", max_bytes=settings.max_upload_bytes
        )
        duration = _probe(services, upload.path)

        live = _live_job(services, upload.content_hash)
        if live is not None:  # starts no work, so it is not counted below
            response.status_code = 200
            return JobView.of(live)

        active = services.store.count_active(client_ip)
        if active >= settings.max_active_jobs_per_ip:
            songs = "song" if active == 1 else "songs"
            raise ApiError(
                429,
                HttpReason.TOO_MANY_JOBS,
                f"You already have {active} {songs} processing. Wait for one to "
                "finish, then try again.",
            )

        key = upload_key(upload.content_hash, file.filename)
        if not services.blobs.exists(key):
            services.blobs.put_file(key, upload.path)

    job, created = services.store.create(
        NewJob(
            content_hash=upload.content_hash,
            title=title_of(file.filename),
            duration_sec=duration,
            upload_key=key,
            client_ip=client_ip,
        )
    )
    if not created:  # the same file, uploaded at the same moment, got there first
        response.status_code = 200
        return JobView.of(job)

    try:
        services.queue.enqueue(job.id)
    except Exception as exc:
        log.exception("could not enqueue job %s", job.id)
        services.store.fail(
            job.id,
            reason=FailureReason.INTERNAL,
            message=INTERNAL_FAILURE_MESSAGE,
            stage=None,
            expect=JobStatus.QUEUED,
        )
        raise ApiError(
            503,
            FailureReason.INTERNAL,
            "We could not queue that song. Try again in a minute.",
        ) from exc

    response.headers["Location"] = f"/jobs/{job.id}"
    return JobView.of(job)


def _probe(services: Services, path: Path) -> float:
    """ffprobe now, so a bad file is refused in a second, not after a queue wait."""
    try:
        duration = services.probe(path)
        check_duration(duration)
    except PipelineError as error:
        if error.reason is FailureReason.INTERNAL:  # ffprobe missing: ours, not theirs
            raise ApiError(503, error.reason, str(error)) from error
        raise ApiError(422, error.reason, str(error)) from error
    return duration


def _live_job(services: Services, content_hash: str) -> Job | None:
    """The live job for this upload, repaired first if the queue lost it.

    A lookup is a read like any other, so it reconciles: a dead job must not
    be handed back as though it were still coming.
    """
    job = services.store.find_live(content_hash)
    if job is None:
        return None
    job = reconcile(job, services)
    return None if job.status is JobStatus.FAILED else job
```

- [ ] **Step 5: Install the middleware**

In `apps/api/src/guitarvis_api/app.py`, add `from guitarvis_api.uploads import UploadSizeLimit`, and in `create_app` add this line directly after `install_error_handlers(app)`:

```python
    app.add_middleware(UploadSizeLimit)
```

- [ ] **Step 6: Run the api suite**

Run: `uv run pytest apps/api -v`
Expected: all PASS. `test_the_real_probe_refuses_bytes_that_are_not_audio` runs because ffmpeg is installed.

Run: `uv run mypy apps/api/src apps/api/tests`
Expected: `Success`.

- [ ] **Step 7: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add apps/api uv.lock
git commit -m "feat(api): POST /jobs with size limit, early probe, dedupe and IP limit

An oversized body is refused as it arrives, before Starlette spools it. The
upload is probed before it is queued. A duplicate returns its live job, after
reconciling it. A failed enqueue fails the row and answers 503.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: The api never imports the worker; the whole path, end to end

The boundary test gains `guitarvis_worker`. Then one test runs the real thing: `POST /jobs` through `TestClient` on real Postgres, Redis and RustFS, an in-process RQ `SimpleWorker` in burst mode with the stages stubbed, then `GET` the job, the document and both audio redirects. It covers success conditions 1, 2 and 4 except the live progress, which Tasks 2, 3 and 9 cover.

**Files:**
- Modify: `apps/api/tests/test_boundaries.py`
- Modify: `packages/jobs/src/guitarvis_jobs/testing.py` (`settings_env`)
- Modify: `packages/jobs/tests/test_settings.py` (round trip)
- Create: `apps/worker/tests/test_end_to_end.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `guitarvis_jobs.testing.settings_env(settings) -> dict[str, str]`, the `GUITARVIS_*` variables that `Settings.from_env` reads back as `settings`.

- [ ] **Step 1: Forbid the worker in the api**

In `apps/api/tests/test_boundaries.py`, replace `FORBIDDEN_ROOTS = {...}` with:

```python
# The ML stack, and the worker itself: the api reaches the worker only
# through the queue, by the dotted path in guitarvis_jobs.queue.RUN_JOB.
FORBIDDEN_ROOTS = {
    "torch",
    "demucs",
    "basic_pitch",
    "librosa",
    "numpy",
    "guitarvis_worker",
}
```

Change the AST test's failure message from `"api must stay free of the ML stack, but found: {offenders}. That code belongs in apps/worker."` to:

```python
        f"api must stay free of the ML stack and of the worker, but found: "
        f"{offenders}. ML code belongs in apps/worker; the api reaches the "
        "worker only through the queue."
```

Add this paragraph to the end of the module docstring:

```
The sys.modules probe imports guitarvis_api.app, which imports
guitarvis_jobs, so it also proves the shared package pulls in nothing
forbidden.
```

Prove the guard bites: add `import guitarvis_worker  # noqa: F401` to the top of `apps/api/src/guitarvis_api/routes.py` and run `uv run pytest apps/api/tests/test_boundaries.py -v`.
Expected: both tests FAIL, naming `guitarvis_worker`. Remove the line again and re-run. Expected: both PASS.

- [ ] **Step 2: Write `settings_env` and its test**

Append to `packages/jobs/tests/test_settings.py`:

```python
def test_settings_env_round_trips_through_from_env() -> None:
    from guitarvis_jobs.testing import settings_env

    settings = Settings(
        redis_url="redis://elsewhere:6380/15", max_upload_mb=3, device="cuda"
    )

    assert Settings.from_env(settings_env(settings)) == settings
```

Run: `uv run pytest packages/jobs/tests/test_settings.py -v`
Expected: FAIL, `cannot import name 'settings_env'`.

Add `from dataclasses import fields, replace` (replacing the bare `replace` import) to `testing.py` and append:

```python
def settings_env(settings: Settings) -> dict[str, str]:
    """`settings` as the GUITARVIS_* variables Settings.from_env reads back.

    The end-to-end test sets these, because run_job builds its own stores
    from the environment exactly as it does under a real worker.
    """
    values = {field.name: getattr(settings, field.name) for field in fields(settings)}
    return {
        f"GUITARVIS_{name.upper()}": str(value)
        for name, value in values.items()
        if value is not None
    }
```

Run: `uv run pytest packages/jobs/tests/test_settings.py -v`
Expected: all PASS.

- [ ] **Step 3: Write the end-to-end test**

`apps/worker/tests/test_end_to_end.py`:

```python
"""The whole service, on real Postgres, Redis and RustFS.

Upload through the api, process under a real RQ worker, fetch the results.
The stages are stubbed, so no model loads; ffprobe, the stores, the queue and
the job runner are all real. It lives with the worker because it drives
run_job; the api's own tests never import the worker.
"""

import shutil
import urllib.request
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from guitarvis_api.app import create_app
from guitarvis_api.services import Services
from guitarvis_core.contracts import (
    NoteEvent,
    SeparationProgress,
    SeparationResult,
    StructureResult,
)
from guitarvis_core.tabdoc import TabDocument, Timing
from guitarvis_jobs.queue import QUEUE_NAME, RQJobQueue
from guitarvis_jobs.testing import (
    integration_settings,
    postgres_store,
    redis_connection,
    s3_blob_store,
    settings_env,
)
from guitarvis_worker import runner
from guitarvis_worker.runner import Stages
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper
from redis import Redis
from rq import Queue, SimpleWorker

requires_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None,
    reason="ffprobe not installed; install ffmpeg",
)


class StubSeparator:
    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        if progress is not None:
            progress(1.0)
        return SeparationResult(stem_path=audio_path)


class StubTranscriber:
    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        return [NoteEvent(onset=0.25, duration=0.5, midi=52, confidence=0.8)]


class StubAnalyzer:
    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        return StructureResult(timing=Timing(), chords=[], sections=[])


def stub_stages(work_dir: Path, device: str | None = None) -> Stages:
    return Stages(
        separator=StubSeparator(),
        transcriber=StubTranscriber(),
        analyzer=StubAnalyzer(),
        mapper=ViterbiFretboardMapper(),
    )


def write_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x01\x00" * int(rate * seconds))
    return path


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Redis]]:
    with (
        postgres_store() as store,
        s3_blob_store() as blobs,
        redis_connection() as redis,
    ):
        settings = integration_settings()
        # run_job builds its stores from the environment, in this process.
        for name, value in settings_env(settings).items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(runner, "build_stages", stub_stages)
        services = Services(
            store=store,
            blobs=blobs,
            queue=RQJobQueue(redis, job_timeout_sec=settings.job_timeout_sec),
            settings=settings,
        )
        yield TestClient(create_app(services)), redis


@requires_ffprobe
def test_upload_process_and_fetch(
    service: tuple[TestClient, Redis], tmp_path: Path
) -> None:
    client, redis = service
    song = write_wav(tmp_path / "song.wav").read_bytes()

    created = client.post("/jobs", files={"file": ("song.wav", song, "audio/wav")})
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]

    again = client.post("/jobs", files={"file": ("again.wav", song, "audio/wav")})
    assert (again.status_code, again.json()["id"]) == (200, job_id)

    SimpleWorker([Queue(QUEUE_NAME, connection=redis)], connection=redis).work(
        burst=True
    )

    job = client.get(f"/jobs/{job_id}").json()
    assert (job["status"], job["percent"], job["attempts"]) == ("succeeded", 100, 1), (
        job
    )

    document = TabDocument.model_validate(client.get(f"/jobs/{job_id}/document").json())
    assert document.source.title == "song"
    assert document.source.audio_url == f"/jobs/{job_id}/audio/mix"
    assert len(document.notes) == 1

    mix = client.get(f"/jobs/{job_id}/audio/mix", follow_redirects=False)
    assert mix.status_code == 307
    request = urllib.request.Request(
        mix.headers["location"], headers={"Range": "bytes=0-3"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 206
        assert response.read() == song[:4]

    guitar = client.get(f"/jobs/{job_id}/audio/guitar", follow_redirects=False)
    assert guitar.status_code == 307
```

- [ ] **Step 4: Run it against the services**

Run: `make services && GUITARVIS_REQUIRE_SERVICES=1 uv run pytest apps/worker/tests/test_end_to_end.py -v`
Expected: PASS. If the job is not `succeeded`, the assertion prints the job body. RQ's `FailedJobRegistry` on Redis db 15 holds the traceback until the fixture flushes it, so rerun with `-s` to see the worker's log.

Run: `docker compose stop redis && uv run pytest apps/worker/tests/test_end_to_end.py -q; make services`
Expected: `1 skipped` ("redis is not reachable … Run `make services`").

- [ ] **Step 5: Run everything, the way CI does**

Run: `GUITARVIS_REQUIRE_SERVICES=1 make check`
Expected: exit 0, with nothing skipped except tests that are legitimately conditional (none on this machine, since ffmpeg is installed).

- [ ] **Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add apps/api/tests/test_boundaries.py apps/worker/tests/test_end_to_end.py packages/jobs
git commit -m "test: api never imports the worker; upload-to-document end to end

The boundary test forbids guitarvis_worker. One test runs POST /jobs, a real
RQ worker and the job runner against Postgres, Redis and RustFS, then fetches
the document and the audio redirects.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: ADR 0007, the docs, and 003's findings

No code. The ADR records the one structural decision; the docs give the new commands and the new things that bite. The 003 findings this branch closed get marked resolved.

**Files:**
- Create: `docs/decisions/0007-postgres-is-the-record.md`
- Modify: `docs/decisions/README.md`, `CLAUDE.md`, `README.md`, `CONTRIBUTING.md`, `docs/CONVENTIONS.md`, `docs/specs/003-pipeline-skeleton/review-notes.md`

**Interfaces:** none.

- [ ] **Step 1: Write ADR 0007**

`docs/decisions/0007-postgres-is-the-record.md`:

```markdown
# 0007. Postgres is the record; Redis carries job ids

**Status:** Accepted
**Date:** 2026-10-08
**Spec:** [005-api-job-queue](../specs/005-api-job-queue/spec.md#postgres-is-the-record-redis-carries-ids)

## Context

Phase 3 puts a queue between the api and the worker, on the stores the parent
spec chose: Postgres, Redis and S3-compatible object storage. Two of them now
hold facts about a job — the row a client reads and the RQ job a worker pulls —
and they can disagree. The api can die between inserting the row and
enqueueing it; Redis can lose its data; a worker can be killed outright and
never record that it stopped.

## Decision

The `jobs` table in Postgres is the only record of a job's state. RQ is told
only "run job `<uuid>`", and its job id is the GuitarVis job id. Clients never
read Redis. The two known ways the stores disagree are repaired when a job is
read — by `GET /jobs/{id}`, and by the upload's dedupe lookup — with an update
conditional on the row being exactly as read, so a worker that writes first
wins.

## Consequences

Losing Redis loses pending work, not history: every job stays answerable, and a
lost one is failed honestly on its next read. There is no background reaper to
run or watch; a job nobody asks about can stay wrong until somebody does.

The cost is a dual write. Creating a job and queueing it are two steps against
two stores and cannot share a transaction; reconciliation exists to contain
what that allows. A third disagreement it does not cover — a row `queued`
while RQ holds the job in a registry nobody drains — would show as a job that
never moves. `attempts` in the job body, and the end-to-end test, are how it
would be noticed.

Revisit with Postgres as the queue (`SELECT … FOR UPDATE SKIP LOCKED`) if
reconciliation turns out to fire in practice: one service fewer, and creating
and queueing a job become one transaction.
```

In `docs/decisions/README.md`, add a row to the *Accepted* table:

```markdown
| [0007](0007-postgres-is-the-record.md) | Postgres is the record of a job; Redis carries only its id |
```

- [ ] **Step 2: Update `CLAUDE.md`**

- Replace the *Commands* line with: `` `make install` · `make check` · `make test` · `make schema` · `make eval-data` · `make eval` · `make services` · `make migrate` · `make api` · `make worker` · `make help` ``
- Invariant 3 becomes: `` `apps/api` must not import torch, demucs, basic_pitch, librosa, or numpy — nor `guitarvis_worker`, which it reaches only through the queue. ``
- In *Build phases*, remove ` ← **next**` from line 3 and append it to line 4: `4. Web client: tab view and sync ← **next**`.
- Append to *Things that will bite you*:

```markdown
- Integration tests need `make services` (Postgres, Redis and RustFS, via
  Docker). Without them those tests skip locally; CI sets
  `GUITARVIS_REQUIRE_SERVICES=1`, which turns the skip into a failure. So
  `make check` can pass locally and fail in CI — run `make services` first.
- Object storage is RustFS, not MinIO: MinIO's community images are gone.
  Only `compose.yaml` names the server; the code speaks plain S3.
- Bump `CACHE_VERSION` in `apps/worker/src/guitarvis_worker/caching.py`
  whenever a stage's output for the same input changes. Nothing enforces it.
- `make worker` runs the real stages, so it needs `uv sync --extra ml`.
```

- [ ] **Step 3: Update `README.md`**

Replace the *Status* paragraph with:

```markdown
**Status: phase 3 of 6 done.** The pipeline runs end to end and emits real
tablature, and it now runs as a service: upload audio to the api, poll the
job, fetch the tab document and the audio to play it against. The web client
(phase 4) is next.
```

Add after the *Running the pipeline* section:

````markdown
## Running the service

Postgres, Redis and S3-compatible storage run in Docker; the api and the
worker run on your machine, so `--device cuda` works as it does for the CLI.

```bash
make services      # docker compose up -d --wait
make migrate       # create the jobs table and the bucket
make api           # localhost:8000
make worker        # in another terminal; needs `uv sync --extra ml`
```

```bash
curl -F file=@song.mp3 localhost:8000/jobs        # → 202 and a job id
curl localhost:8000/jobs/<id>                      # stage and percent
curl localhost:8000/jobs/<id>/document             # the tab document
curl -L localhost:8000/jobs/<id>/audio/mix -o mix  # a redirect to storage
```

Uploading the same file again returns the same job. Uploads and stems stay in
storage until you run `docker compose down -v`.
````

- [ ] **Step 4: Update `CONTRIBUTING.md`**

After the *Setup* requirements sentence, add: `` The integration tests and `make api`/`make worker` also need Docker, for `make services`. ``

Add these rows to the *Commands* table, after `make eval`:

```markdown
| `make services` | Start Postgres, Redis and RustFS in Docker |
| `make migrate` | Create or upgrade the jobs table, and create the bucket |
| `make api` | Serve the api on `localhost:8000`, reloading on change |
| `make worker` | Run jobs from the queue (`ARGS="--device cuda"`; needs the `ml` extra) |
```

After the paragraph about the `ml` extra, add:

```markdown
Tests that need Postgres, Redis or object storage skip when `make services`
has not been run, the way ingest tests skip without ffprobe. CI runs them with
`GUITARVIS_REQUIRE_SERVICES=1`, which makes a missing service a failure;
set it locally to check you are not skipping anything. They use the
`guitarvis_test` database, Redis database 15 and the `guitarvis-test` bucket,
never the ones `make api` uses.

Behind a reverse proxy, start uvicorn with `--forwarded-allow-ips` so the
per-address job limit sees the user's address, not the proxy's.
```

- [ ] **Step 5: Update `docs/CONVENTIONS.md`**

Replace the Python bullet `` `apps/api` imports nothing from the ML stack. This is enforced by `apps/api/tests/test_boundaries.py`, not by good intentions. `` with:

```markdown
- `apps/api` imports nothing from the ML stack, and never `guitarvis_worker`:
  it enqueues the worker's entry point by name. This is enforced by
  `apps/api/tests/test_boundaries.py`, not by good intentions.
- **Postgres is the record of a job; Redis carries its id** (ADR 0007). Every
  write after a job starts is conditional on the status it expects.
```

In *Testing*, add to the *Tested, and gating CI* bullet: `the job lifecycle, stage caching and the HTTP surface — with the store contract suites and one end-to-end test running against real Postgres, Redis and RustFS.`

Add rows to the *Mechanisms over notes* table:

```markdown
| api never imports the worker | `apps/api/tests/test_boundaries.py` |
| In-memory store twins behave like the real stores | shared contract suites in `packages/jobs/tests` |
| The migration matches the table the code queries | `packages/jobs/tests/test_migrations.py` |
| CI cannot pass by skipping the integration suite | `packages/jobs/tests/test_services_gate_ci.py` |
```

- [ ] **Step 6: Mark 003's findings resolved**

In `docs/specs/003-pipeline-skeleton/review-notes.md`, append a line to each of these four findings:

- *Progress looks frozen during separation*: `**Resolved in 005:** progress names the running stage, and Demucs's tqdm output drives separation from 0 to 40% (pipeline.py, stages/separation.py).`
- *`--stems-dir X` writes to `X/stems/`*: `**Resolved in 005:** stems land directly in work_dir.`
- *`DemucsSeparator(work_dir=None)` …*: `**Resolved in 005:** work_dir is a required keyword; the job runner passes its temporary directory.`
- *The CLI's output write is guarded only by `OSError`*: `**Resolved in 005:** it catches any exception and reports it as internal.`

- [ ] **Step 7: Optional — the real pipeline through the service**

Only if the ML stack is available. The first run downloads model weights and takes minutes on CPU. Run `uv sync --extra ml`, then `make services && make migrate`, then `make api` and `make worker` in two terminals. Then `curl -F file=@<a short song> localhost:8000/jobs` and poll `GET /jobs/<id>`.
Expected: `stage` goes `separation`, `transcription`, `structure`, `fretboard`; `percent` moves during separation; the document validates.
If you run it, paste the polled `stage`/`percent` pairs into the PR description. If you do not run it, say so in the PR description rather than implying it was run. Then run `uv sync` to drop the extra again.

- [ ] **Step 8: Verify and commit**

Run: `GUITARVIS_REQUIRE_SERVICES=1 make check`
Expected: exit 0.

```bash
git add docs CLAUDE.md README.md CONTRIBUTING.md
git commit -m "docs: ADR 0007, service commands, phase 3 status, 003 findings resolved

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Then open the PR with `.github/pull_request_template.md` (`**Spec:** docs/specs/005-api-job-queue/spec.md`), copying the section below into *Deviations from the spec*.

---

## Deviations from the spec

Known while writing this plan; append any found during implementation.

- **RustFS, not MinIO** (user decision, 2026-10-08). MinIO's community edition is archived, and its images no longer pull from Docker Hub or Quay. `make migrate` creates the bucket through boto3, in place of a one-shot `mc` container. The spec is amended in Task 6.
- **The dedupe lookup reconciles the job it finds.** The spec's step 3 only says "look up". But a lookup is a read, and without reconciling, re-uploading a file whose job the queue lost would hand back the dead job with a 200 (Review Focus 5).
- **`fretboard 100` comes after the invariant check**, not the moment stage 4 returns, so a job never reads 100% and then fails.
- **`/health`'s 503 carries the standard `error` object plus a `services` map.** This keeps "every error body is `{"error": …}`" true while still naming what did not answer. The map says `storage`, not a server name.
- **Two layers enforce the upload limit:** an ASGI middleware (declared length, or a counted chunked body) and an exact count in the route. Starlette spools a whole body before a route runs, so "abandoned past the limit" needs the first layer.
- **An empty upload is refused** with 422 `unsupported_format` before it is probed.
- **For transcription and structure, a cache read or write error is a miss, not a stage failure.** The spec is silent here. Without this, a storage blip would come out as a degraded document. The separation stem must still be stored, because the api serves it.
- **The Demucs child is killed** if anything raises while it runs (a job timeout, a failing progress write), so it cannot outlive the job.
- **`POST /jobs` answers 503 `internal` when ffprobe is missing in the api.** The spec gives 422 for probe failures and 503 only for a failed enqueue. A missing ffprobe is our fault, not the file's.
- **`create_app` takes a `Services` bundle** (store, blobs, queue, settings, probe, clock), not just the store, blob store and queue. Tests hand in the twins, a stub probe and a fake clock through the one argument.
- **There is no `@requires_services` marker.** Integration fixtures call `guitarvis_jobs.testing.require(service)`, which skips, or fails under `GUITARVIS_REQUIRE_SERVICES=1`. The behaviour is the same.
- **One integration test creates and deletes a throwaway bucket**, `guitarvis-test-ensure`, beside `guitarvis-test`. It is how `ensure_bucket` is tested against a bucket that does not exist yet.
- **The api-side Redis connection has a 5 s socket timeout** (`RQJobQueue.from_settings`), so a dead Redis raises quickly and reads answer from Postgres. The worker builds its own connection, which waits for work without one.
- **`JobView` serialises `created_at` and `updated_at` as UTC with a `Z` suffix**, whatever offset the store returns.
- **A body that cannot be parsed as multipart answers 422 `unsupported_format`.** A failure while reading the body on our side, such as a full disk while spooling, answers 500 `internal` and is logged. A NUL byte in a filename is dropped.
- **The worker declares `redis` and `rq` directly**, because `runner.py` imports them.
- **Job timeouts are not catchable as `Exception`.** The worker's death penalty raises a `BaseException` subclass (`guitarvis_worker.timeouts.JobTimedOut`), so a stage's degrade handler cannot swallow it, and it reaches the runner's requeue/fail path.
- **Reconciliation treats a terminal RQ job as lost.** A row `queued` past its grace whose RQ job is FINISHED, FAILED, STOPPED or CANCELED is repaired like one whose RQ job is gone. This covers the third disagreement the spec's Risks section named.
- **Stored objects carry an explicit Content-Type** from an allow-list keyed on the extension, `application/octet-stream` otherwise. The key keeps the spec's extension rule.
- **Compose binds every service port to 127.0.0.1.**
