# Tab View and Sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build phase 4's browser client. A user uploads a song, watches its four stages, then plays it with a scrolling tab strip that stays in sync with the audio. They can slow it down, loop a passage, and switch between the mix and the isolated guitar.

**Architecture:** In `web/`, a plain-TypeScript `PlaybackEngine` owns a single `<audio>` element and a `MediaClock`. Views draw from `engine.onFrame(t)`, and the controls read `engine.getState()` through `useSyncExternalStore`. The tab strip is a pure `layout()` that returns a draw list, which a thin canvas component paints. The api's response models get a generated JSON Schema and generated TypeScript, through the same pipeline as `tabDocument.ts`, so `tsc` refuses a failure reason that has no text. On the server side, `POST /jobs` reconciles the rows it counts before it answers 429. `make eval ARGS=--full` gains a confidence-band tally, and the shared `confidence.ts` takes its thresholds from that measurement.

**Tech Stack:** React 18.3, TypeScript 6.0, Vite 8.3, Vitest 5.0 with jsdom 29 and Testing Library 16, canvas 2D. Python 3.12, FastAPI, Pydantic 2.13, pytest, mypy, ruff, and mir_eval for the band tally.

**Spec:** [spec.md](spec.md) · **Parent:** [001-guitarvis-design](../001-guitarvis-design/spec.md) · **Carried findings:** [005 review notes](../005-api-job-queue/review-notes.md) · **ADR added here:** 0008 (Task 14)

**Checked while writing:** this plan's code was assembled, following its own instructions, in a scratch worktree and run. That covers Tasks 1–3 and 5–13, with stand-in thresholds of 0.4 and 0.7. The run was `make check` with the services up: exit 0, 528 Python tests including the Postgres contract suite, and 132 web tests. Also run: `vite build`, and a smoke test of the dev server, which confirmed its SPA fallback for `/songs/…` and its proxying of `/health` to a running api. Not run: Task 4's calibration, which needs the GuitarSet audio and a clean commit; Task 14's docs; Task 15's manual acceptance. A snippet that fails as written most likely has a transcription slip, so compare it with the plan before doubting the design.

## Global Constraints

Repo-wide rules from `CLAUDE.md` and `docs/CONVENTIONS.md`, plus the values the spec fixes. Every task inherits them.

- **Never commit to `main`.** Work on branch `006-tab-view-sync`, which already holds the spec. `.githooks/pre-commit` enforces this.
- **`make check` is the gate.** Run `make services` first: without the services the integration tests skip locally, and CI turns that skip into a failure.
- **`apps/api` must not import** torch, demucs, basic_pitch, librosa or numpy, nor `guitarvis_worker`. The new `guitarvis_api.schema_export` imports only pydantic and the api's own modules.
- **Evaluation never gates CI.** The band tally is measured and printed, never asserted against a threshold. No test may contain the literal path `eval/results`: `apps/eval/tests/test_eval_never_gates_ci.py` is a tripwire for exactly that.
- **No `tabdoc.py` change.** `make schema` must regenerate `web/src/types/tabDocument.ts` byte for byte.
- **Generated files are never hand-edited:** `schema/tab-document.schema.json`, `schema/api.schema.json`, `web/src/types/tabDocument.ts`, `web/src/types/api.ts`.
- **Seconds are authoritative.** The strip's x position is linear in song seconds. Beats move only the bar lines.
- **Python test basenames are unique across the repo, and there is no `conftest.py`.** Web tests sit beside their modules. A test that needs the DOM opts into jsdom with `// @vitest-environment jsdom` on its first line; everything else runs on the default `node` environment.
- **Same origin.** Client code uses relative paths. In development the Vite proxy forwards `/jobs` and `/health` to `http://localhost:8000`. Client routes live under `/songs/…`, never `/jobs/…`.
- **Node.** CI installs the latest Node 22. jsdom is pinned to `^29.1.1`, because jsdom 30 needs Node 22.22 or later and the dev machine runs 22.20. `web/scripts/confidence-report.ts` runs through Node's type stripping, which needs 22.18 or later.
- **Exact values from the spec:**
  - polling every 1.5 s; after a failed poll, double the interval up to 10 s; the first good answer restores 1.5 s
  - speeds 0.5, 0.75 and 1; ← and → seek 5 s; loop points less than 0.5 s apart are refused
  - the clock snaps to media time when extrapolation drifts more than 50 ms
  - 150 px per song second; the playhead at 20% of the width
  - `emphasis` is 0.35 at or below HIDE, 1.0 at or above FULL, and linear in between
  - a hidden passage is at least 3 consecutive notes (in onset order, across strings) below HIDE, with no onset gap over 1 s
  - confidence bands are 0.1 wide; a band counts only with at least 50 notes; HIDE needs precision ≥ 0.5 and FULL ≥ 0.8
  - the engine gives up after 3 consecutive media errors; a job has 3 attempts in all
  - stage words: separation "Isolating the guitar", transcription "Transcribing notes", structure "Finding the beat and chords", fretboard "Working out fingerings"; anything else "Working"
  - a document whose `schema_version` is not 1 reads: "This song was processed by a newer version of GuitarVis. Reload the page."
- **Running web tests:** `npm --prefix web test -- <path>` runs `tsc --noEmit`, then `vitest run <path>`, inside `web/`. Paths after `--` are relative to `web/`. Both halves matter. While a module does not exist yet, `tsc` is what fails.
- **Style.** There is no TypeScript formatter. Match the existing code (double quotes, semicolons, two-space indent); ESLint is authoritative. For Python, run `uv run ruff format . && uv run ruff check --fix .` before each commit.
- End every commit message with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

These are inputs the spec implies but never names, most likely first. Each one is pinned by a test in the task that owns the code.

1. **Space pressed after clicking a control with the mouse.** Chrome leaves focus on a clicked button, so Space would click "0.5×" again rather than pause. Expected: Space plays and pauses. Space still activates a button the user reached with Tab. → Task 12: `keeps a mouse click from leaving focus on a control` and `leaves Space to a button that has keyboard focus`.
2. **Toggling mix ↔ guitar twice, or seeking, before the new file has loaded.** The media element reports time 0 until metadata arrives. Expected: the second toggle and the seek both keep the intended position and play state, and the strip never jumps to 0. → Task 8: `survives a second toggle before the first file has loaded`, `seeks within a file that is still loading`, and `holds the strip still while the other file loads`.
3. **A file over the upload limit.** The api refuses it by declared length and closes the connection mid-upload, which some browsers report as a network error rather than a 413. Expected: "That file is too large", not "We couldn't reach GuitarVis". → Task 10: `refuses a file over the limit without sending it` and `reads a bare 413 from a proxy as too large`.
4. **The api down while the Vite proxy is up.** The proxy answers 500 or 502 with a body that is not the api's error body. Expected: the client treats it as no answer. The song page shows "Reconnecting…" and keeps polling, rather than "Something went wrong on our side." → Task 10: `treats an answer without the api's error body as no answer`. Task 13: `keeps polling, slower, through a lost connection, and recovers`.
5. **A loop whose B is the very end of the song.** Playback ends rather than crossing B. Expected: it jumps back to A and keeps playing. → Task 8: `keeps looping when B is the very end of the song`.

## File map

| Path | Responsibility | Task |
|---|---|---|
| `apps/api/src/guitarvis_api/schemas.py` | `FailureView.reason: Reason`; `ErrorDetail`, `ErrorBody` | 1 |
| `apps/api/src/guitarvis_api/schema_export.py` | writes `schema/api.schema.json` | 1 |
| `packages/core/src/guitarvis_core/schema_export.py` | `strip_property_titles` made public | 1 |
| `web/scripts/generate-types.mjs`, `Makefile`, `web/eslint.config.js` | two contracts generated, checked, and left unlinted | 1 |
| `schema/api.schema.json`, `web/src/types/api.ts` | generated | 1 |
| `packages/jobs/src/guitarvis_jobs/store.py`, `postgres.py` | `JobStore.active_jobs` | 2 |
| `apps/api/src/guitarvis_api/routes.py` | reconcile the counted rows before a 429 | 2 |
| `apps/eval/src/guitarvis_eval/calibration.py` | `ConfidenceBands`, `confidence_bands`, `threshold` | 3 |
| `apps/eval/src/guitarvis_eval/runner.py`, `__main__.py` | the bands in the summary, the table and the thresholds printed | 3 |
| `eval/results/*-full-test.json`, `docs/specs/006-tab-view-sync/calibration.md` | the measurement and the chosen values | 4, 5 |
| `web/src/confidence.ts` | `emphasis`, `hiddenPassages`, `HIDE`, `FULL` | 5 |
| `web/scripts/confidence-report.ts` | what the thresholds do to real documents | 5 |
| `web/src/test/fixtures/first-song.tabdoc.json` | the first real song through the api | 5 |
| `web/src/playback/cursor.ts` | `NoteCursor` | 6 |
| `web/src/song.ts` | `Song`, `buildSong`, `canRead` | 6 |
| `web/src/playback/clock.ts` | `MediaLike`, `Clock`, `MediaClock`, `FakeClock` | 7 |
| `web/src/test/fakeMedia.ts` | `FakeMedia`, `FakeFrames` | 7 |
| `web/src/playback/engine.ts` | `PlaybackEngine` | 8 |
| `web/src/tab/layout.ts` | `layout`, `rowsOf`, `stringLabels` | 9 |
| `web/src/api/messages.ts` | `MESSAGES: Record<Reason, Message>` | 10 |
| `web/src/api/client.ts` | `getJob`, `getDocument`, `createJob`, `ApiError`, `errorFrom` | 10 |
| `web/src/test/fakeXhr.ts`, `web/src/test/jobs.ts` | test doubles | 10 |
| `web/src/routing.ts` | `routeOf`, `navigate`, `followLink`, `useRoute` | 11 |
| `web/src/pages/Failure.tsx`, `UploadPage.tsx` | mapped failure text; the upload page | 11 |
| `web/src/player/` | `Player`, `Controls`, `Warnings`, `useTransportKeys` | 12 |
| `web/src/tab/TabStrip.tsx` | the canvas painter | 12 |
| `web/src/pages/SongPage.tsx`, `progress.ts` | polling, progress, failure, the player | 13 |
| `web/src/App.tsx`, `main.tsx`, `styles.css`, `vite-env.d.ts`, `web/vite.config.ts`, `Makefile` | routes, styling, the dev proxy, `make web` | 13 |
| `docs/decisions/0008-native-time-stretch.md` and the docs | ADR, conventions, commands | 14 |
| `docs/specs/006-tab-view-sync/acceptance.md` | the manual checks | 15 |

---

### Task 1: The api's response schema, generated for the web

Today `FailureView.reason` is a bare `str`, and nothing ties the reason vocabulary to the client. This task types the reason, models the error body, and exports both response shapes as JSON Schema. `make schema` then turns the schema into `web/src/types/api.ts`, as it already does for the tab document. The bytes on the wire do not change.

**Files:**
- Modify: `apps/api/src/guitarvis_api/schemas.py`
- Create: `apps/api/src/guitarvis_api/schema_export.py`
- Modify: `packages/core/src/guitarvis_core/schema_export.py` (rename one function)
- Create: `apps/api/tests/test_api_schema.py`
- Modify: `web/scripts/generate-types.mjs` (whole file below), `web/eslint.config.js:5`, `Makefile` (`schema`, `schema-check`, and one comment)
- Generated: `schema/api.schema.json`, `web/src/types/api.ts`

**Interfaces:**
- Consumes: `guitarvis_api.errors.Reason` (`FailureReason | HttpReason`, already defined), `guitarvis_api.errors.HttpReason`.
- Produces:
  - `guitarvis_api.schemas.ErrorDetail(reason: Reason, message: str)` and `guitarvis_api.schemas.ErrorBody(error: ErrorDetail)`.
  - `FailureView.reason: Reason`.
  - `guitarvis_api.schema_export.api_schema() -> dict[str, Any]`, and `python -m guitarvis_api.schema_export <path>`.
  - `guitarvis_core.schema_export.strip_property_titles(node: Any) -> None`, which is public now.
  - The generated TypeScript in `web/src/types/api.ts` exports `ApiResponse = JobView | ErrorBody`, `JobView`, `FailureView`, `ErrorBody`, `ErrorDetail`, `JobStatus`, `FailureReason` and `HttpReason`. `ErrorDetail["reason"]` is `FailureReason | HttpReason`, and Task 10 builds `Reason` from it.

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_api_schema.py`:

```python
"""The api's response schema: generated, committed, and true to what the
routes send. The web client's types are generated from it."""

import subprocess
import sys
from pathlib import Path

from api_fixture import make_api
from guitarvis_api.errors import HttpReason
from guitarvis_api.schema_export import api_schema
from guitarvis_api.schemas import ErrorBody, JobView
from guitarvis_core.contracts import FailureReason
from guitarvis_jobs.models import JobStatus
from guitarvis_jobs.store import InMemoryJobStore
from guitarvis_jobs.testing import sample_new_job

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED = REPO_ROOT / "schema" / "api.schema.json"
MISSING_ID = "5f0c6c2e-0000-4000-8000-0000000000ff"
MIB = 1024 * 1024


def upload(data: bytes) -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("song.mp3", data, "audio/mpeg")}


def test_the_export_writes_exactly_the_committed_file(tmp_path: Path) -> None:
    """Byte for byte, since schema-check compares bytes through git."""
    fresh = tmp_path / "api.schema.json"
    subprocess.run(
        [sys.executable, "-m", "guitarvis_api.schema_export", str(fresh)],
        check=True,
    )

    assert COMMITTED.exists(), "run `make schema` and commit the output"
    assert fresh.read_text() == COMMITTED.read_text(), (
        "schema/api.schema.json is stale; run `make schema`"
    )


def test_the_schema_names_all_nine_reasons() -> None:
    definitions = api_schema()["$defs"]
    named = set(definitions["FailureReason"]["enum"]) | set(
        definitions["HttpReason"]["enum"]
    )

    assert named == {r.value for r in FailureReason} | {r.value for r in HttpReason}
    assert len(named) == 9


def test_the_errors_the_routes_send_are_error_bodies() -> None:
    api = make_api(max_active_jobs_per_ip=1, max_upload_mb=1)
    job_id = api.client.post("/jobs", files=upload(b"one")).json()["id"]

    responses = [
        api.client.get(f"/jobs/{MISSING_ID}"),
        api.client.get("/nowhere"),
        api.client.get(f"/jobs/{job_id}/document"),
        api.client.post("/jobs", files=upload(b"two")),
        api.client.post("/jobs", files=upload(b"x" * (MIB + 1))),
        api.client.post("/jobs", data={"nothing": "here"}),
    ]

    assert [r.status_code for r in responses] == [404, 404, 409, 429, 413, 422]
    for response in responses:
        ErrorBody.model_validate(response.json())


def test_an_internal_error_is_an_error_body() -> None:
    class OnFire(InMemoryJobStore):
        def get(self, job_id: str) -> None:
            raise RuntimeError("the database is on fire")

    api = make_api(store=OnFire(), raise_server_exceptions=False)

    response = api.client.get(f"/jobs/{MISSING_ID}")

    assert response.status_code == 500
    ErrorBody.model_validate(response.json())


def test_a_failed_job_is_a_job_view_with_a_typed_reason() -> None:
    api = make_api()
    job, _ = api.store.create(sample_new_job())
    api.store.fail(
        job.id,
        reason=FailureReason.TOO_LONG,
        message="m",
        stage=None,
        expect=JobStatus.QUEUED,
    )

    view = JobView.model_validate(api.client.get(f"/jobs/{job.id}").json())

    assert view.failure is not None
    assert view.failure.reason is FailureReason.TOO_LONG
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest apps/api/tests/test_api_schema.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'guitarvis_api.schema_export'`.

- [ ] **Step 3: Make `strip_property_titles` public**

In `packages/core/src/guitarvis_core/schema_export.py`, rename `_strip_property_titles` to `strip_property_titles`. That is the definition and its three call sites, two recursive and one in `main`. The api's export reuses it in the next step. Nothing else in the repo calls it: `grep -rn _strip_property_titles packages apps` must print nothing afterwards.

- [ ] **Step 4: Type the reason and model the error body**

In `apps/api/src/guitarvis_api/schemas.py`, add the import after the existing ones:

```python
from guitarvis_api.errors import Reason
```

Change `FailureView`:

```python
class FailureView(BaseModel):
    reason: Reason
    message: str
    stage: str | None
```

In `JobView.of`, pass the enum rather than its value:

```python
            failure = FailureView(
                reason=job.failure_reason or FailureReason.INTERNAL,
                message=job.failure_message or INTERNAL_FAILURE_MESSAGE,
                stage=job.failed_stage,
            )
```

Append:

```python
class ErrorDetail(BaseModel):
    reason: Reason
    message: str


class ErrorBody(BaseModel):
    """Every error the api answers with. `errors.error_body` builds it; this
    model describes it, for the generated client types and the tests."""

    error: ErrorDetail
```

`errors.py` imports nothing from `schemas.py`, so this adds no cycle.

- [ ] **Step 5: Write the export**

Create `apps/api/src/guitarvis_api/schema_export.py`:

```python
"""Emit the JSON Schema of the api's response bodies.

`make schema` writes schema/api.schema.json from these models and turns it
into web/src/types/api.ts, as it does for the tab document. The reason
vocabulary is the point: a reason added on the server regenerates the web
types, and the client's `Record<Reason, ...>` stops compiling until the new
reason has text.

Run via `make schema`.
"""

import json
import sys
from pathlib import Path
from typing import Any

from guitarvis_core.schema_export import strip_property_titles
from pydantic.json_schema import models_json_schema

from guitarvis_api.schemas import ErrorBody, JobView

DEFAULT_OUTPUT = Path("schema/api.schema.json")


def api_schema() -> dict[str, Any]:
    """Every body the api answers with: a job, or an error.

    The root is the union of the two, so the generator emits a type for each
    model without needing a list of unreachable definitions.
    """
    _, definitions = models_json_schema(
        [(JobView, "serialization"), (ErrorBody, "serialization")],
        ref_template="#/$defs/{model}",
    )
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ApiResponse",
        "anyOf": [{"$ref": "#/$defs/JobView"}, {"$ref": "#/$defs/ErrorBody"}],
        **definitions,
    }
    strip_property_titles(schema)
    return schema


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    output = Path(args[0]) if args else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys makes regeneration byte-stable, so a diff means a real change.
    output.write_text(json.dumps(api_schema(), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Generate both contracts from one script**

Replace `web/scripts/generate-types.mjs` with:

```javascript
/**
 * Generate the web types from the committed JSON Schemas.
 *
 * Each schema and its generated file are both committed, so a contract change
 * shows up as a diff in review. Run via `make schema`, never by hand.
 */
import { mkdirSync, writeFileSync } from "node:fs";

import { compileFromFile } from "json-schema-to-typescript";

const CONTRACTS = [
  {
    schema: "../schema/tab-document.schema.json",
    from: "packages/core tabdoc.py",
    output: "src/types/tabDocument.ts",
  },
  {
    schema: "../schema/api.schema.json",
    from: "apps/api schemas.py",
    output: "src/types/api.ts",
  },
];

mkdirSync("src/types", { recursive: true });

for (const { schema, from, output } of CONTRACTS) {
  const ts = await compileFromFile(schema, {
    bannerComment:
      "/* GENERATED FILE — do not edit.\n" +
      ` * Source: ${schema.replace("../", "")} (from ${from}).\n` +
      " * Regenerate with `make schema`.\n" +
      " */",
    additionalProperties: false,
    style: { singleQuote: false },
  });
  writeFileSync(output, ts);
  console.log(`wrote ${output}`);
}
```

The tab document's banner comes out exactly as before, so `tabDocument.ts` does not change.

In `web/eslint.config.js`, line 5, ignore the new generated file too:

```javascript
  { ignores: ["dist", "src/types/tabDocument.ts", "src/types/api.ts"] },
```

- [ ] **Step 7: Widen `make schema` and `make schema-check`**

In `Makefile`, change the first line of the comment above `.NOTPARALLEL:` from `` # `schema-check` rewrites schema/ and web/src/types/tabDocument.ts as a side `` to:

```make
# `schema-check` rewrites schema/ and the generated files in web/src/types/ as a side
```

Replace the `schema` target:

```make
schema: ## Regenerate the contract schemas and the web types
	$(UV) run python -m guitarvis_core.schema_export schema/tab-document.schema.json
	$(UV) run python -m guitarvis_api.schema_export schema/api.schema.json
	$(NPM) run generate-types
```

Replace the comment above `schema-check`, and the target itself:

```make
# Scoped to every generated file in web/src/types, which is all of it but
# the hand-written *.test.ts files beside them: editing a test must not look
# like a stale artifact.
#
# `git status --porcelain`, not `git diff --exit-code`: diff only sees
# changes to tracked files, so a generator that starts emitting a brand-new
# (untracked) file would pass `git diff` silently. status also reports
# untracked paths under the scoped directories.
schema-check: schema ## Fail if the committed contract artifacts are stale
	@changes="$$(git status --porcelain -- schema web/src/types ':(exclude)web/src/types/*.test.ts')"; \
	if [ -n "$$changes" ]; then \
	  echo "$$changes"; \
	  echo ""; \
	  echo "✗ Contract artifacts are stale."; \
	  echo "  tabdoc.py or the api's schemas.py changed without regenerating,"; \
	  echo "  or the regenerated output was never committed. Commit the"; \
	  echo "  changes listed above."; \
	  exit 1; \
	fi
```

Recipe lines start with a tab.

- [ ] **Step 8: Generate, and check what came out**

Run: `make schema`
Expected: `wrote src/types/tabDocument.ts` and `wrote src/types/api.ts`. Then `git status --porcelain` lists only the files this task touched, the two new artifacts, and the untracked `tab.json` that Task 4 deals with. `web/src/types/tabDocument.ts` and `schema/tab-document.schema.json` must not appear.

`web/src/types/api.ts` starts like this. Check the names, which later tasks rely on:

```typescript
/* GENERATED FILE — do not edit.
 * Source: schema/api.schema.json (from apps/api schemas.py).
 * Regenerate with `make schema`.
 */

export type ApiResponse = JobView | ErrorBody;
```

It must also contain `export type FailureReason = "unsupported_format" | "no_guitar_detected" | "too_long" | "fetch_failed" | "internal";`, `export type HttpReason = "too_large" | "too_many_jobs" | "not_found" | "not_ready";`, and `export interface ErrorDetail { message: string; reason: FailureReason | HttpReason; }`.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest apps/api/tests packages/core/tests -q`
Expected: all pass, including the five new tests and `packages/core/tests/test_schema_export.py`.

Run: `npm --prefix web run typecheck && npm --prefix web run lint`
Expected: no errors. Nothing imports `api.ts` yet, but it must compile, and ESLint must skip it.

`make check` waits for the commit. Its `schema-check` reports the two new artifacts as stale until they are tracked.

- [ ] **Step 10: Commit, then run the gate**

```bash
uv run ruff format . && uv run ruff check --fix .
git add apps/api/src/guitarvis_api/schemas.py apps/api/src/guitarvis_api/schema_export.py \
  apps/api/tests/test_api_schema.py packages/core/src/guitarvis_core/schema_export.py \
  web/scripts/generate-types.mjs web/eslint.config.js Makefile \
  schema/api.schema.json web/src/types/api.ts
git commit -m "feat(api): generate the response types the web client reads

FailureView.reason becomes the Reason enum and ErrorBody models the
error shape the handlers already send. make schema exports both as
schema/api.schema.json and web/src/types/api.ts, and schema-check now
guards every generated file in web/src/types.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
make check
```

Expected: `make check` exits 0, with `schema-check` finding nothing stale.

---

### Task 2: A lost job no longer holds an upload slot

This fixes a finding carried from 005. `count_active` counts `queued` rows whose RQ job is lost, and only a read of that exact row repairs it. So a user can be refused with "you already have 2 songs processing" while nothing is processing. At the limit, `POST /jobs` now reads the rows it counted, reconciles each one, and counts again. It is still a repair on read, as ADR 0007 has it, not a reaper.

**Files:**
- Modify: `packages/jobs/src/guitarvis_jobs/store.py` (Protocol and `InMemoryJobStore`)
- Modify: `packages/jobs/src/guitarvis_jobs/postgres.py`
- Modify: `apps/api/src/guitarvis_api/routes.py`
- Test: `packages/jobs/tests/test_job_store.py`, `apps/api/tests/test_upload.py`

**Interfaces:**
- Consumes: `guitarvis_api.reconcile.reconcile(job, services) -> Job`; `guitarvis_jobs.models.ACTIVE_STATUSES`.
- Produces: `JobStore.active_jobs(client_ip: str) -> list[Job]`, which returns queued and running jobs from that address, oldest first, as copies.

- [ ] **Step 1: Write the failing contract test**

In `packages/jobs/tests/test_job_store.py`, insert this directly above `def test_create_refuses_a_new_job_at_the_limit`:

```python
def test_active_jobs_are_the_counted_rows_oldest_first(
    store: JobStore, clock: FakeClock
) -> None:
    queued, _ = store.create(sample_new_job())
    clock.advance(seconds=1)
    started = running(store, content_hash=HASH_B)
    clock.advance(seconds=1)
    done = running(store, content_hash="c" * 64)
    store.succeed(done, document={}, stem_key="k")
    store.create(sample_new_job(content_hash="d" * 64, client_ip="198.51.100.1"))

    active = store.active_jobs("203.0.113.7")

    assert [job.id for job in active] == [queued.id, started]
    assert [job.status for job in active] == [JobStatus.QUEUED, JobStatus.RUNNING]
    assert len(active) == store.count_active("203.0.113.7")
    assert store.active_jobs("192.0.2.1") == []
```

- [ ] **Step 2: Write the failing route tests**

In `apps/api/tests/test_upload.py`, insert these directly above `def test_uploads_that_race_past_the_count_are_refused_when_created(`:

```python
def test_a_lost_job_at_the_limit_is_repaired_rather_than_refused() -> None:
    api = make_api(max_active_jobs_per_ip=2)
    lost = post(api.client, b"one").json()["id"]
    assert post(api.client, b"two").status_code == 202
    api.queue.lose(lost)
    api.clock.advance(seconds=61)

    third = post(api.client, b"three")

    assert third.status_code == 202
    assert api.job(lost).status is JobStatus.FAILED
    assert api.job(lost).failure_reason is FailureReason.INTERNAL


def test_jobs_the_queue_still_holds_keep_their_slots() -> None:
    api = make_api(max_active_jobs_per_ip=2)
    assert post(api.client, b"one").status_code == 202
    assert post(api.client, b"two").status_code == 202
    api.clock.advance(seconds=61)

    third = post(api.client, b"three")

    assert third.status_code == 429
    assert "2 songs" in third.json()["error"]["message"]
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest packages/jobs/tests/test_job_store.py -k active_jobs -v`
Expected: FAIL with `AttributeError: 'InMemoryJobStore' object has no attribute 'active_jobs'`.

Run: `uv run pytest apps/api/tests/test_upload.py -k "lost_job_at_the_limit or still_holds" -v`
Expected: `test_a_lost_job_at_the_limit_is_repaired_rather_than_refused` fails with `assert 429 == 202`. The "still holds" test already passes: it guards against a fix that over-reaches.

- [ ] **Step 4: Add `active_jobs` to the contract and the twin**

In `packages/jobs/src/guitarvis_jobs/store.py`, add this to the `JobStore` Protocol, right after `count_active`:

```python
    def active_jobs(self, client_ip: str) -> list[Job]:
        """The jobs count_active counts, oldest first, so a caller at the
        limit can repair the ones the queue lost before refusing."""
        ...
```

Add this to `InMemoryJobStore`, right after its `count_active`:

```python
    def active_jobs(self, client_ip: str) -> list[Job]:
        with self._lock:
            rows = [
                row
                for row in self._rows.values()
                if row.client_ip == client_ip and row.status in ACTIVE_STATUSES
            ]
        rows.sort(key=lambda row: row.created_at)
        # Copies, as a database read would be.
        return [replace(row, document=copy.deepcopy(row.document)) for row in rows]
```

- [ ] **Step 5: Add it to the Postgres store**

In `packages/jobs/src/guitarvis_jobs/postgres.py`, add this to `PostgresJobStore`, right after its `count_active`:

```python
    def active_jobs(self, client_ip: str) -> list[Job]:
        statement = (
            sa.select(jobs)
            .where(*_is_active_from(client_ip))
            .order_by(jobs.c.created_at, jobs.c.id)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [_to_job(row) for row in rows]
```

Replace the module-level `_active_from` with the shared condition and a count over it:

```python
def _is_active_from(client_ip: str) -> tuple[sa.ColumnElement[bool], ...]:
    return (
        jobs.c.client_ip == client_ip,
        jobs.c.status.in_([status.value for status in ACTIVE_STATUSES]),
    )


def _active_from(client_ip: str) -> sa.Select[Any]:
    return (
        sa.select(sa.func.count()).select_from(jobs).where(*_is_active_from(client_ip))
    )
```

- [ ] **Step 6: Reconcile the counted rows before refusing**

In `apps/api/src/guitarvis_api/routes.py`, inside `create_job`, replace:

```python
        active = services.store.count_active(client_ip)
        if active >= settings.max_active_jobs_per_ip:
            raise _too_many_jobs(active)
```

with:

```python
        active = services.store.count_active(client_ip)
        if active >= settings.max_active_jobs_per_ip:
            active = _active_after_repair(services, client_ip)
        if active >= settings.max_active_jobs_per_ip:
            raise _too_many_jobs(active)
```

Add this function directly above `_too_many_jobs`:

```python
def _active_after_repair(services: Services, client_ip: str) -> int:
    """The count again, once the rows it counted have been reconciled.

    A queued row whose RQ job is lost holds its slot until something reads
    it, so a user could be refused with nothing processing. At the limit,
    read them all, then count again. Still repair on read (ADR 0007), not a
    reaper.
    """
    for job in services.store.active_jobs(client_ip):
        reconcile(job, services)
    return services.store.count_active(client_ip)
```

`reconcile` is already imported in `routes.py`. When Redis is down, `reconcile` answers from Postgres and changes nothing, so the 429 stands. That matches what a poll does in the same state.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest packages/jobs apps/api -q`
Expected: all pass. With `make services` running, the contract test runs twice, against the twin and against Postgres. Check that with `-v -k active_jobs`, which should show both params passing rather than one skipped.

- [ ] **Step 8: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add packages/jobs/src/guitarvis_jobs/store.py packages/jobs/src/guitarvis_jobs/postgres.py \
  packages/jobs/tests/test_job_store.py apps/api/src/guitarvis_api/routes.py \
  apps/api/tests/test_upload.py
git commit -m "fix(api): repair lost jobs before refusing an upload at the limit

A queued row whose RQ job was lost held an upload slot until that exact
row was read. At the limit, POST /jobs now reconciles every row it
counted, via the new JobStore.active_jobs, and counts again. This was
carried from 005's review findings.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Precision by confidence, in full-mode evaluation

The client's thresholds have to come from a measurement. `score_full` already pairs transcribed notes with the truth. This task tallies each transcribed note's confidence band and whether it was paired, adds `precision_by_confidence` to the results summary, and prints the bands. It also prints the HIDE and FULL that the spec's rule picks. Like everything in `make eval`, this is measured and never gated.

**Files:**
- Create: `apps/eval/src/guitarvis_eval/calibration.py`
- Modify: `apps/eval/src/guitarvis_eval/runner.py`, `apps/eval/src/guitarvis_eval/__main__.py`
- Create: `apps/eval/tests/test_calibration.py`
- Modify: `apps/eval/tests/test_full.py` (add `import json` and two tests)

**Interfaces:**
- Consumes: `guitarvis_core.contracts.NoteEvent` (with `.confidence`); `match_notes` pairs, which are `(truth index, estimate index)`.
- Produces:
  - `guitarvis_eval.calibration` exports `BANDS = 10`, `MIN_BAND_NOTES = 50`, `HIDE_PRECISION = 0.5` and `FULL_PRECISION = 0.8`.
  - `ConfidenceBands(estimated: tuple[int, ...], matched: tuple[int, ...])`, with `+` and `.precision(band) -> float | None`.
  - `band_of(confidence) -> int`, `confidence_bands(estimated, matched_indices) -> ConfidenceBands`, and `threshold(bands, min_precision, min_notes=50) -> float | None`.
  - `ExcerptScore.confidence: ConfidenceBands | None`.
  - Each group in the summary gains `precision_by_confidence: {"0.0": {"estimated", "matched", "precision"}, …, "0.9": {…}}`. Per-excerpt dicts do not.

- [ ] **Step 1: Write the failing tests**

Create `apps/eval/tests/test_calibration.py`:

```python
"""Confidence bands and the threshold rule, from hand-built tallies: no
audio, no mir_eval."""

import pytest
from guitarvis_core.contracts import NoteEvent
from guitarvis_eval.calibration import (
    BANDS,
    ConfidenceBands,
    band_of,
    confidence_bands,
    threshold,
)
from guitarvis_eval.metrics import Tally
from guitarvis_eval.runner import ExcerptScore, score_to_dict, summarize


def bands(*rows: tuple[int, int]) -> ConfidenceBands:
    """(estimated, matched) for bands 0, 1, 2, ...; the rest are empty."""
    padded = list(rows) + [(0, 0)] * (BANDS - len(rows))
    return ConfidenceBands(tuple(e for e, _ in padded), tuple(m for _, m in padded))


def note(confidence: float) -> NoteEvent:
    return NoteEvent(onset=0.0, duration=0.5, midi=60, confidence=confidence)


@pytest.mark.parametrize(
    ("confidence", "band"),
    [(0.0, 0), (0.09, 0), (0.1, 1), (0.3, 3), (0.45, 4), (0.99, 9), (1.0, 9)],
)
def test_band_of(confidence: float, band: int) -> None:
    assert band_of(confidence) == band


def test_confidence_bands_tally_estimates_and_matches() -> None:
    estimated = [note(0.31), note(0.35), note(0.72), note(0.95)]

    tally = confidence_bands(estimated, matched={1, 3})

    assert tally.estimated == (0, 0, 0, 2, 0, 0, 0, 1, 0, 1)
    assert tally.matched == (0, 0, 0, 1, 0, 0, 0, 0, 0, 1)
    assert tally.precision(3) == 0.5
    assert tally.precision(0) is None


def test_bands_add_up() -> None:
    total = bands((2, 1)) + bands((4, 3), (1, 1))

    assert total.estimated[:2] == (6, 1)
    assert total.matched[:2] == (4, 1)


def test_threshold_is_the_lowest_edge_with_everything_above_it_precise() -> None:
    # Precision by band: 0.2, 0.3, 0.45, 0.55, 0.6, 0.7, 0.85, 0.9, 0.95.
    tally = bands(
        (100, 20), (100, 30), (100, 45), (100, 55), (100, 60),
        (100, 70), (100, 85), (100, 90), (100, 95),
    )  # fmt: skip

    assert threshold(tally, 0.5) == 0.3
    assert threshold(tally, 0.8) == 0.6


def test_a_dip_above_a_good_band_raises_the_threshold() -> None:
    tally = bands((100, 10), (100, 60), (100, 40), (100, 70))

    assert threshold(tally, 0.5) == 0.3


def test_bands_with_too_few_notes_are_ignored() -> None:
    # Band 1 is bad but holds only 10 notes; band 2 holds 49.
    tally = bands((100, 10), (10, 0), (49, 0), (100, 60))

    assert threshold(tally, 0.5) == 0.1


def test_every_band_precise_means_nothing_is_below_the_threshold() -> None:
    assert threshold(bands((100, 90), (100, 95)), 0.5) == 0.0


def test_no_supporting_measurement_gives_no_threshold() -> None:
    assert threshold(bands((100, 10), (100, 40)), 0.5) is None
    assert threshold(bands((10, 10)), 0.5) is None
    assert threshold(ConfidenceBands(), 0.5) is None


def test_the_summary_carries_bands_and_each_excerpt_does_not() -> None:
    score = ExcerptScore(
        name="05_a_comp",
        style="comp",
        strings=Tally(),
        confidence=bands((0, 0), (0, 0), (0, 0), (4, 1)),
    )

    summary = summarize([score])["all"]
    excerpt = score_to_dict(score)

    assert isinstance(summary, dict)
    by_band = summary["precision_by_confidence"]
    assert list(by_band) == [f"0.{n}" for n in range(10)]
    assert by_band["0.3"] == {"estimated": 4, "matched": 1, "precision": 0.25}
    assert by_band["0.0"] == {"estimated": 0, "matched": 0, "precision": None}
    assert "precision_by_confidence" not in excerpt
```

In `apps/eval/tests/test_full.py`, add `import json` as the first import, above `from pathlib import Path`, and append:

```python
def test_score_full_tallies_the_transcriber_s_confidence(tmp_path: Path) -> None:
    pytest.importorskip("mir_eval")
    excerpt = read_jams(
        write_jams(tmp_path, "05_a_comp", notes=[(0.0, 0.5, 40.0, 0)], duration=1.0)
    )

    score = score_full(
        excerpt,
        tmp_path / "05_a_comp_mic.wav",
        transcriber=EchoTranscriber(
            [NoteEvent(0.01, 0.5, 40, 0.92), NoteEvent(0.5, 0.5, 70, 0.34)]
        ),
        analyzer=FixedAnalyzer([]),
        mapper=ViterbiFretboardMapper(),
    )

    assert score.confidence is not None
    assert (score.confidence.estimated[9], score.confidence.matched[9]) == (1, 1)
    assert (score.confidence.estimated[3], score.confidence.matched[3]) == (1, 0)


def test_full_mode_prints_and_records_precision_by_confidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("mir_eval")
    import guitarvis_worker.stages.structure as structure
    import guitarvis_worker.stages.transcription as transcription
    from guitarvis_eval.__main__ import main

    echo = EchoTranscriber([NoteEvent(0.0, 0.5, 40, 0.95)])
    monkeypatch.setattr(transcription, "BasicPitchTranscriber", lambda: echo)
    monkeypatch.setattr(
        structure, "LibrosaStructureAnalyzer", lambda: FixedAnalyzer([])
    )
    write_jams(tmp_path / "annotation", "05_a_comp", notes=[(0.0, 0.5, 40.0, 0)])
    (tmp_path / "audio_mono-mic").mkdir()
    (tmp_path / "audio_mono-mic" / "05_a_comp_mic.wav").write_bytes(b"")

    code = main(["--full", "--data-dir", str(tmp_path), "--out", str(tmp_path / "out")])

    printed = capsys.readouterr().out
    assert code == 0
    assert "confidence" in printed and "precision" in printed
    # One note is far short of a 50-note band, so no threshold is supported.
    assert "HIDE (precision ≥ 0.5)" in printed
    assert "not supported" in printed
    [written] = (tmp_path / "out").iterdir()
    summary = json.loads(written.read_text())["summary"]
    assert summary["all"]["precision_by_confidence"]["0.9"] == {
        "estimated": 1,
        "matched": 1,
        "precision": 1.0,
    }
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest apps/eval/tests/test_calibration.py apps/eval/tests/test_full.py -q`
Expected: a collection error, `ModuleNotFoundError: No module named 'guitarvis_eval.calibration'`. The two `test_full.py` tests need `mir_eval` and skip without the `eval-full` extra, as the existing full-mode tests do.

- [ ] **Step 3: Write the calibration module**

Create `apps/eval/src/guitarvis_eval/calibration.py`:

```python
"""How often a note at each confidence is right, and the rule that turns
that into the client's thresholds (spec 006, "Where the thresholds come
from").

A transcribed note is "right" when match_notes pairs it with the truth.
The bands are measured like every other number here, never gated.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from guitarvis_core.contracts import NoteEvent

BANDS = 10  # each 0.1 wide
MIN_BAND_NOTES = 50
HIDE_PRECISION = 0.5  # below HIDE, a note is more often wrong than right
FULL_PRECISION = 0.8

_EMPTY = (0,) * BANDS


@dataclass(frozen=True)
class ConfidenceBands:
    """Band i holds confidences in [i/10, (i+1)/10); the top band takes 1.0."""

    estimated: tuple[int, ...] = _EMPTY
    matched: tuple[int, ...] = _EMPTY

    def __add__(self, other: "ConfidenceBands") -> "ConfidenceBands":
        return ConfidenceBands(
            tuple(a + b for a, b in zip(self.estimated, other.estimated, strict=True)),
            tuple(a + b for a, b in zip(self.matched, other.matched, strict=True)),
        )

    def precision(self, band: int) -> float | None:
        estimated = self.estimated[band]
        return self.matched[band] / estimated if estimated else None


def band_of(confidence: float) -> int:
    return min(max(int(confidence * BANDS), 0), BANDS - 1)


def confidence_bands(
    estimated: Sequence[NoteEvent], matched: Collection[int]
) -> ConfidenceBands:
    """Tally each estimated note by band. `matched` holds the indices into
    `estimated` that match_notes paired with a true note."""
    counts = [0] * BANDS
    hits = [0] * BANDS
    for index, note in enumerate(estimated):
        band = band_of(note.confidence)
        counts[band] += 1
        hits[band] += index in matched
    return ConfidenceBands(tuple(counts), tuple(hits))


def threshold(
    bands: ConfidenceBands,
    min_precision: float,
    min_notes: int = MIN_BAND_NOTES,
) -> float | None:
    """The lower edge of the lowest band such that every band at or above
    it, among bands holding at least `min_notes` notes, has precision of at
    least `min_precision`.

    None when the measurement cannot support a threshold: no band holds
    enough notes, or the highest one that does falls short.
    """
    supported = [b for b in range(BANDS) if bands.estimated[b] >= min_notes]
    if not supported:
        return None
    failing = [b for b in supported if (bands.precision(b) or 0.0) < min_precision]
    if not failing:
        return 0.0
    lowest = max(failing) + 1
    if lowest > max(supported):
        return None
    return lowest / BANDS
```

- [ ] **Step 4: Tally bands in `score_full`, and summarise them**

In `apps/eval/src/guitarvis_eval/runner.py`:

Add the import above `from guitarvis_eval.dataset import Excerpt`:

```python
from guitarvis_eval.calibration import BANDS, ConfidenceBands, confidence_bands
```

Add a field to `ExcerptScore`, after `chords`:

```python
    confidence: ConfidenceBands | None = None  # full mode only
```

Append two sentences to the `score_full` docstring, after "…over those matching the truth.":

```python
    The confidence bands tally the transcriber's notes too, for the same
    reason: they calibrate what the transcriber's confidence means.
```

In `score_full`'s `return ExcerptScore(...)`, add after the `chords=` argument:

```text
        confidence=confidence_bands(events, {e for _, e in heard}),
```

Replace `summarize`:

```python
def summarize(scores: Sequence[ExcerptScore]) -> dict[str, object]:
    """Totals overall ("all") and per style ("comp", "solo"). Counts are
    summed before dividing, so long excerpts weigh more than short ones.
    Confidence bands appear here only: per excerpt, they are mostly empty."""
    groups: dict[str, list[ExcerptScore]] = {"all": list(scores)}
    for score in scores:
        groups.setdefault(score.style, []).append(score)
    return {
        group: _total(members, with_bands=True)
        for group, members in sorted(groups.items())
    }
```

Change `_total`'s signature to:

```python
def _total(
    scores: Sequence[ExcerptScore], *, with_bands: bool = False
) -> dict[str, object]:
```

Then, just before its `return out`:

```python
    bands = [s.confidence for s in scores if s.confidence is not None]
    if with_bands and bands:
        out["precision_by_confidence"] = _bands(sum(bands, ConfidenceBands()))
```

Add this function directly above `_tally`:

```python
def _bands(bands: ConfidenceBands) -> dict[str, object]:
    """Keyed by each band's lower edge: "0.3" holds [0.3, 0.4)."""
    return {
        f"{band / BANDS:.1f}": {
            "estimated": bands.estimated[band],
            "matched": bands.matched[band],
            "precision": bands.precision(band),
        }
        for band in range(BANDS)
    }
```

- [ ] **Step 5: Print the bands and the thresholds**

In `apps/eval/src/guitarvis_eval/__main__.py`, add the import after `from guitarvis_eval.baseline import LowestFretMapper`:

```python
from guitarvis_eval.calibration import (
    FULL_PRECISION,
    HIDE_PRECISION,
    MIN_BAND_NOTES,
    ConfidenceBands,
    threshold,
)
```

In `main`, replace `_print_table(summary)` with:

```python
    _print_table(summary)
    if args.full:
        bands = [s.confidence for s in scores if s.confidence is not None]
        _print_thresholds(sum(bands, ConfidenceBands()))
```

At the end of `_print_table`'s group loop, after the `for key, label in rows:` block, at the same indentation as that `for`, add:

```python
        bands = totals.get("precision_by_confidence")
        if isinstance(bands, dict):
            print(f"  {'confidence':<12}{'notes':>8}{'matched':>9}{'precision':>11}")
            for lower, band in bands.items():
                assert isinstance(band, dict)
                print(
                    f"  {lower:<12}{band['estimated']:>8}{band['matched']:>9}"
                    f"{_percent(band['precision']):>11}"
                )
```

Add this function directly below `_print_table`:

```python
def _print_thresholds(bands: ConfidenceBands) -> None:
    """The calibration rule from spec 006, over every excerpt."""
    print(f"confidence thresholds (bands of {MIN_BAND_NOTES}+ notes)")
    for name, precision in (("HIDE", HIDE_PRECISION), ("FULL", FULL_PRECISION)):
        value = threshold(bands, precision)
        shown = "not supported" if value is None else f"{value:.1f}"
        print(f"  {name} (precision ≥ {precision:.1f}){'':<8} {shown}")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest apps/eval/tests -q`
Expected: all pass. The two new `test_full.py` tests skip without `mir_eval`.

If the `eval-full` extra is installed (`uv run python -c "import mir_eval"` succeeds), they run, and should pass. Otherwise run them once with it: `uv sync --extra eval-full && uv run pytest apps/eval/tests/test_full.py -q`. Task 4 needs that extra anyway.

Run: `uv run mypy apps/eval/src apps/eval/tests`
Expected: `Success`.

- [ ] **Step 7: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add apps/eval/src/guitarvis_eval/calibration.py apps/eval/src/guitarvis_eval/runner.py \
  apps/eval/src/guitarvis_eval/__main__.py apps/eval/tests/test_calibration.py \
  apps/eval/tests/test_full.py
git commit -m "feat(eval): measure precision by confidence band in full mode

Each transcribed note is tallied into a 0.1-wide confidence band, with
whether it matched the truth. The summary records precision_by_confidence,
and make eval prints the bands with the HIDE and FULL thresholds that
spec 006's rule picks from them. Measured, never gated.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Calibrate the thresholds on GuitarSet

No code. Run full-mode evaluation on the test split, commit the results file, and record the thresholds in `calibration.md`. Task 5 writes them into `confidence.ts`. This task downloads about 650 MB once and then runs for several minutes on CPU, so start the run in the background.

**Files:**
- Create: `eval/results/<date>-<sha>-full-test.json`, written by the run
- Create: `docs/specs/006-tab-view-sync/calibration.md`

**Interfaces:**
- Consumes: Task 3's `make eval ARGS=--full` output.
- Produces: two numbers, `HIDE` and `FULL`, in calibration.md's *Chosen values* table. Task 5 copies them.

- [ ] **Step 1: Start from a clean tree**

A results file measured with uncommitted changes gets a `-dirty` name and must not be committed. `git_state` counts untracked files as uncommitted.

Run: `git status --porcelain`
Expected: nothing.

The repo root holds an untracked `tab.json`: the first song run through the api, which Task 5 commits as a test fixture. If `git status` lists it, move it into the gitignored `tmp/` rather than deleting it:

```bash
mv tab.json tmp/first-song.tabdoc.json
git status --porcelain   # now prints nothing
```

Anything else listed has to be committed or moved aside too.

- [ ] **Step 2: Install full mode and its data**

```bash
uv sync --extra eval-full
make eval-data ARGS=--audio
```

Expected: `uv sync` reports the ML stack and `mir_eval`. `eval-full` includes the worker's `ml` extra, so `make worker` keeps working. `make eval-data` downloads the GuitarSet mic audio, about 650 MB, into `~/.cache/guitarvis/guitarset` and skips anything already there.

- [ ] **Step 3: Run the evaluation**

```bash
make eval ARGS=--full 2>&1 | tee tmp/calibration-run.txt
```

Expected: one `[n/60] <excerpt>` line per excerpt, then a table per group (`all`, `comp`, `solo`). Each table includes the ten confidence rows, and two final lines follow:

```text
confidence thresholds (bands of 50+ notes)
  HIDE (precision ≥ 0.5)         0.N
  FULL (precision ≥ 0.8)         0.N
```

The last line is `wrote …/eval/results/<date>-<sha>-full-test.json`. The name must not end in `-dirty`. If it does, go back to Step 1, delete the dirty file, and run again.

- [ ] **Step 4: Decide the values**

If both thresholds printed a number, those numbers are the chosen values.

If either printed `not supported`, the measurement cannot support a threshold by the spec's rule. That is the case the spec reserves for a decision made "with that evidence in hand and the reasoning written down". **Stop and take the `all` band table to your human partner.** The choice is theirs. Record it, and their reasoning, in Step 5.

- [ ] **Step 5: Write `calibration.md`**

Create `docs/specs/006-tab-view-sync/calibration.md`. Fill each `…` from `tmp/calibration-run.txt` and the results file's name. The band table is the `all` group's ten rows, as printed.

````markdown
# Confidence calibration

**Spec:** [006 — Confidence](spec.md#confidence)
**Results:** [`eval/results/…`](../../../eval/results/…), from
`make eval ARGS=--full` on the test split (player 05), commit `…`, clean tree.

## Precision by confidence

Every note the transcriber produced on the test split, by its confidence
band, and the share that matched the truth: an onset within 50 ms at the
exact pitch. These are the `all` group's numbers.

| Confidence | Notes | Matched | Precision |
|---|---|---|---|
| 0.0–0.1 | … | … | … |
| 0.1–0.2 | … | … | … |
| 0.2–0.3 | … | … | … |
| 0.3–0.4 | … | … | … |
| 0.4–0.5 | … | … | … |
| 0.5–0.6 | … | … | … |
| 0.6–0.7 | … | … | … |
| 0.7–0.8 | … | … | … |
| 0.8–0.9 | … | … | … |
| 0.9–1.0 | … | … | … |

## Chosen values

| | Rule (spec 006) | Printed | Chosen |
|---|---|---|---|
| `HIDE` | the lowest band edge such that every band at or above it, among bands of 50 or more notes, has precision ≥ 0.5 | … | … |
| `FULL` | the same, with precision ≥ 0.8 | … | … |

`web/src/confidence.ts` holds the chosen values and cites this file.

## How far to trust this

GuitarSet is clean solo guitar, and full mode skips separation, so these
thresholds are optimistic for stems separated from full mixes. Real songs
will show more faded and hidden notes than GuitarSet predicts. The next
section measures that gap on real output.
````

If Step 4 needed your human partner's decision, add a paragraph under *Chosen values* that says what was chosen and why.

- [ ] **Step 6: Commit**

```bash
git add eval/results/*-full-test.json docs/specs/006-tab-view-sync/calibration.md
git commit -m "docs(eval): calibrate the confidence thresholds on GuitarSet

Full-mode evaluation on the test split, with precision by confidence
band. calibration.md records the bands and the HIDE and FULL values
spec 006's rule picks from them.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

`git add` with the glob picks up only new files. Check with `git show --stat HEAD` that exactly one results file and `calibration.md` went in.

---

### Task 5: The shared confidence rule

`confidence.ts` is the one place that decides how strongly a note or chord is drawn, and which passages are hidden. Phase 5's fretboards import it unchanged. The thresholds are Task 4's measurement. This task also commits the first real song as a fixture, and measures what the thresholds do to real documents.

**Files:**
- Create: `web/src/test/fixtures/first-song.tabdoc.json`, a copy of the first song through the api
- Create: `web/src/test/fixtures.test.ts`
- Create: `web/src/confidence.ts`, `web/src/confidence.test.ts`
- Create: `web/scripts/confidence-report.ts`
- Modify: `docs/specs/006-tab-view-sync/calibration.md` (append one section)

**Interfaces:**
- Consumes: `Note` from `web/src/types/tabDocument.ts`; `HIDE` and `FULL` from calibration.md.
- Produces, from `web/src/confidence.ts`:
  - the constants `HIDE`, `FULL`, `FADED = 0.35`, `MIN_RUN = 3` and `MAX_GAP_SEC = 1`;
  - `interface Thresholds { hide: number; full: number }` and `THRESHOLDS`;
  - `interface Passage { from: number; to: number }`;
  - `emphasis(confidence: number, thresholds?: Thresholds): number`;
  - `hiddenPassages(notes: readonly Note[], hide?: number): Passage[]`, sorted, with overlapping spans merged.

- [ ] **Step 1: Commit the real song as a fixture**

The file is the api's output for the first real song: 32 notes, a median confidence of 0.45, chords and beats, and no sections. Task 4 moved it to `tmp/first-song.tabdoc.json`. If Task 4 has not run, it is still `tab.json` at the repo root.

```bash
mkdir -p web/src/test/fixtures
python3 -m json.tool --indent 2 tmp/first-song.tabdoc.json > web/src/test/fixtures/first-song.tabdoc.json
```

Create `web/src/test/fixtures.test.ts`:

```typescript
/**
 * The real pipeline output the web tests draw on: the first song run
 * through the api. Assigned uncast below, so `tsc --noEmit` checks its shape
 * against the generated TabDocument, as types/tabDocument.test.ts does for
 * the minimal fixture.
 */
import { describe, expect, it } from "vitest";

import type { TabDocument } from "../types/tabDocument";
import firstSongJson from "./fixtures/first-song.tabdoc.json";

const FIRST_SONG: TabDocument = firstSongJson;

describe("the first-song fixture", () => {
  it("is real output: low confidence throughout, and no sections", () => {
    const confidences = (FIRST_SONG.notes ?? []).map((n) => n.confidence).sort((a, b) => a - b);

    expect(FIRST_SONG.schema_version).toBe(1);
    expect(confidences).toHaveLength(32);
    expect(confidences[16]).toBeLessThan(0.5);
    expect(confidences.at(-1)).toBeLessThan(0.9);
    expect(FIRST_SONG.sections).toEqual([]);
    expect(FIRST_SONG.chords?.length).toBeGreaterThan(0);
    expect(FIRST_SONG.timing.beats?.length).toBeGreaterThan(0);
  });
});
```

Run: `npm --prefix web test -- src/test/fixtures.test.ts`
Expected: PASS, 1 test. `tsc` passing is half the point here: it proves the real output matches the generated `TabDocument`.

- [ ] **Step 2: Write the failing tests**

The behaviour tests pass explicit thresholds, so they do not depend on the calibrated values. One test checks only that the shipped values are ordered and in range.

Create `web/src/confidence.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import {
  FADED,
  FULL,
  HIDE,
  emphasis,
  hiddenPassages,
  type Thresholds,
} from "./confidence";
import type { Note } from "./types/tabDocument";

const T: Thresholds = { hide: 0.4, full: 0.7 };
const WEAK = 0.2;
const STRONG = 0.9;

let ids = 0;
function note(t: number, confidence: number, dur = 0.25, string = 0): Note {
  ids += 1;
  return { id: `n${ids}`, t, dur, midi: 40 + string * 5, string, fret: 0, confidence };
}

describe("emphasis", () => {
  it("is FADED at and below hide, and 1 at and above full", () => {
    expect(emphasis(0, T)).toBe(FADED);
    expect(emphasis(0.4, T)).toBe(FADED);
    expect(emphasis(0.7, T)).toBe(1);
    expect(emphasis(1, T)).toBe(1);
  });

  it("is linear in between", () => {
    expect(emphasis(0.55, T)).toBeCloseTo((FADED + 1) / 2);
  });

  it("never decreases as confidence rises", () => {
    let previous = 0;
    for (let c = 0; c <= 1.0001; c += 0.01) {
      const value = emphasis(c, T);
      expect(value).toBeGreaterThanOrEqual(previous);
      previous = value;
    }
  });

  it("is a step when the thresholds are equal", () => {
    const step = { hide: 0.5, full: 0.5 };
    expect(emphasis(0.49, step)).toBe(FADED);
    expect(emphasis(0.5, step)).toBe(1);
  });

  it("ships thresholds in order, within [0, 1]", () => {
    expect(0 <= HIDE && HIDE <= FULL && FULL <= 1).toBe(true);
  });
});

describe("hiddenPassages", () => {
  it("hides a run of three weak notes, to the latest end", () => {
    const notes = [note(1, WEAK, 2), note(1.5, WEAK, 0.2), note(2, WEAK, 0.2)];

    expect(hiddenPassages(notes, 0.4)).toEqual([{ from: 1, to: 3 }]);
  });

  it("leaves a run of two, and a lone weak note, alone", () => {
    expect(hiddenPassages([note(1, WEAK), note(1.5, WEAK)], 0.4)).toEqual([]);
    expect(
      hiddenPassages([note(1, STRONG), note(1.5, WEAK), note(2, STRONG)], 0.4),
    ).toEqual([]);
  });

  it("breaks a run at a gap over one second", () => {
    const notes = [note(1, WEAK), note(1.5, WEAK), note(2.6, WEAK), note(3, WEAK)];

    expect(hiddenPassages(notes, 0.4)).toEqual([]);
  });

  it("counts weak notes in onset order across strings, whatever the input order", () => {
    const notes = [note(2, WEAK, 0.25, 5), note(1, WEAK, 0.25, 0), note(1.5, WEAK, 0.25, 3)];

    expect(hiddenPassages(notes, 0.4)).toEqual([{ from: 1, to: 2.25 }]);
  });

  it("keeps adjacent runs apart, so the strong note between them shows", () => {
    const notes = [
      note(1, WEAK), note(1.2, WEAK), note(1.4, WEAK),
      note(1.8, STRONG),
      note(2, WEAK), note(2.2, WEAK), note(2.4, WEAK),
    ];

    expect(hiddenPassages(notes, 0.4)).toEqual([
      { from: 1, to: 1.65 },
      { from: 2, to: 2.65 },
    ]);
  });

  it("merges runs whose spans overlap", () => {
    const notes = [
      note(1, WEAK, 3), note(1.2, WEAK), note(1.4, WEAK),
      note(1.8, STRONG),
      note(2, WEAK), note(2.2, WEAK), note(2.4, WEAK),
    ];

    expect(hiddenPassages(notes, 0.4)).toEqual([{ from: 1, to: 4 }]);
  });

  it("treats a note exactly at hide as strong", () => {
    expect(hiddenPassages([note(1, 0.4), note(1.2, 0.4), note(1.4, 0.4)], 0.4)).toEqual(
      [],
    );
  });
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `npm --prefix web test -- src/confidence.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './confidence'`.

- [ ] **Step 4: Write `confidence.ts`, with the calibrated values**

Create `web/src/confidence.ts` as below, with one change. **Set `HIDE` and `FULL` to the *Chosen* values in calibration.md.** The `0.4` and `0.7` below stand in for them: they are what the plan was checked with, not a measurement.

```typescript
/**
 * The confidence rule, shared by every view so that it cannot drift between
 * them. Phase 5's fretboards import this module unchanged.
 *
 * HIDE and FULL are measured, not chosen by eye. Where they came from, and
 * what they do to real songs, is recorded in
 * docs/specs/006-tab-view-sync/calibration.md.
 */
import type { Note } from "./types/tabDocument";

/** Below HIDE, a note is more often wrong than right (calibration.md). */
export const HIDE = 0.4;
/** At or above FULL, a note is right at least 80% of the time (calibration.md). */
export const FULL = 0.7;
/** The opacity of anything at or below HIDE. */
export const FADED = 0.35;
/** A passage is hidden when at least this many weak notes run together... */
export const MIN_RUN = 3;
/** ...with no gap between neighbouring onsets longer than this. */
export const MAX_GAP_SEC = 1;

export interface Thresholds {
  hide: number;
  full: number;
}

export const THRESHOLDS: Thresholds = { hide: HIDE, full: FULL };

/** A time span of the song, in seconds. */
export interface Passage {
  from: number;
  to: number;
}

/**
 * The opacity to draw a note or chord at: FADED at or below `hide`, 1 at or
 * above `full`, linear in between. Equal thresholds make it a step.
 */
export function emphasis(
  confidence: number,
  { hide, full }: Thresholds = THRESHOLDS,
): number {
  if (confidence >= full) return 1;
  if (confidence <= hide) return FADED;
  return FADED + ((1 - FADED) * (confidence - hide)) / (full - hide);
}

/**
 * The spans to hide: runs of at least MIN_RUN consecutive notes, in onset
 * order across all strings, all below `hide`, with no gap between
 * neighbouring onsets over MAX_GAP_SEC. A run hides from its first onset to
 * its latest end. A lone weak note fades but leaves no hole. Spans that
 * overlap are merged. Run once per document.
 */
export function hiddenPassages(
  notes: readonly Note[],
  hide: number = HIDE,
): Passage[] {
  const passages: Passage[] = [];
  let run: Note[] = [];

  const close = () => {
    if (run.length >= MIN_RUN) {
      const from = run[0].t;
      const to = Math.max(...run.map((note) => note.t + note.dur));
      const last = passages.at(-1);
      if (last !== undefined && from <= last.to) last.to = Math.max(last.to, to);
      else passages.push({ from, to });
    }
    run = [];
  };

  for (const note of [...notes].sort((a, b) => a.t - b.t)) {
    if (note.confidence >= hide) {
      close();
      continue;
    }
    const previous = run.at(-1);
    if (previous !== undefined && note.t - previous.t > MAX_GAP_SEC) close();
    run.push(note);
  }
  close();
  return passages;
}
```

Then confirm the two numbers match calibration.md:

```bash
grep -n -E "export const (HIDE|FULL) " web/src/confidence.ts
grep -n -E "^\| .(HIDE|FULL). \|" docs/specs/006-tab-view-sync/calibration.md
```

Expected: the values in the first command's two lines equal the *Chosen* column in the second command's two.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/confidence.test.ts src/test/fixtures.test.ts`
Expected: PASS, 13 tests.

- [ ] **Step 6: Measure the thresholds on real songs**

Create `web/scripts/confidence-report.ts`:

```typescript
/**
 * What the confidence thresholds do to real tab documents: the share of
 * notes they fade and hide. Recorded in
 * docs/specs/006-tab-view-sync/calibration.md as the sanity check on
 * thresholds measured on GuitarSet.
 *
 *   node scripts/confidence-report.ts <tab document JSON>...
 *
 * Node runs the TypeScript directly (type stripping, Node 22.18 and later),
 * using the same functions the views use.
 */
import { readFileSync } from "node:fs";

import { FULL, HIDE, hiddenPassages } from "../src/confidence.ts";
import type { Note } from "../src/types/tabDocument.ts";

function share(count: number, total: number): string {
  return total === 0 ? "—" : `${((100 * count) / total).toFixed(0)}%`;
}

console.log(`HIDE ${HIDE}, FULL ${FULL}`);
console.log("notes  at/below HIDE  partly faded  hidden  passages  document");
for (const path of process.argv.slice(2)) {
  const notes: Note[] = JSON.parse(readFileSync(path, "utf8")).notes ?? [];
  const weak = notes.filter((note) => note.confidence <= HIDE).length;
  const partly = notes.filter((note) => note.confidence > HIDE && note.confidence < FULL).length;
  const passages = hiddenPassages(notes);
  const hidden = notes.filter((note) => passages.some((p) => p.from <= note.t && note.t <= p.to));
  console.log(
    [
      String(notes.length).padStart(5),
      share(weak, notes.length).padStart(14),
      share(partly, notes.length).padStart(13),
      share(hidden.length, notes.length).padStart(7),
      String(passages.length).padStart(9),
      ` ${path}`,
    ].join(" "),
  );
}
```

Run it on the fixture, and on any other real tab documents to hand. These include `tmp/*.json` from earlier CLI runs, and `curl -s localhost:8000/jobs/<id>/document > tmp/<name>.json` for songs already in the local api:

```bash
node web/scripts/confidence-report.ts web/src/test/fixtures/first-song.tabdoc.json tmp/*.json
```

Expected: a header line with the values, then one row per document. A document with no notes shows `—`. With the stand-in values the fixture's row read `32  25%  56%  0%  0`.

Append to `docs/specs/006-tab-view-sync/calibration.md`. Paste the script's output into the code block. Then write one or two sentences on the gap: how the real songs' faded and hidden shares compare with what the GuitarSet bands predict.

````markdown
## On real songs

What the chosen values do to real pipeline output, from
`node web/scripts/confidence-report.ts` (`web/scripts/confidence-report.ts`
uses the same `hiddenPassages` the views use):

```text
…
```

…
````

- [ ] **Step 7: Lint, and commit**

Run: `npm --prefix web run lint`
Expected: no problems. ESLint covers `scripts/` too.

```bash
git add web/src/confidence.ts web/src/confidence.test.ts web/src/test/fixtures.test.ts \
  web/src/test/fixtures/first-song.tabdoc.json web/scripts/confidence-report.ts \
  docs/specs/006-tab-view-sync/calibration.md
git commit -m "feat(web): the shared confidence rule, with measured thresholds

emphasis() fades a note by its confidence, and hiddenPassages() hides
runs of weak notes. Both use the HIDE and FULL that calibration.md
measured on GuitarSet. The first real song through the api becomes a
fixture, and confidence-report.ts records what the thresholds do to it.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The note cursor and the Song

Every view asks the same question each frame: which notes overlap this window of time? `NoteCursor` answers it with work proportional to the notes on screen, not to the length of the song. `Song` is the document read once into what the views draw from. It holds the sorted tracks, the hidden passages and the strip's cursor, and fills an omitted optional track with an empty list.

**Files:**
- Create: `web/src/playback/cursor.ts`, `web/src/playback/cursor.test.ts`
- Create: `web/src/song.ts`, `web/src/song.test.ts`

**Interfaces:**
- Consumes: `hiddenPassages` and `Passage` (Task 5); `TabDocument`, `Note`, `Chord`, `Section` and `Beat` from the generated types.
- Produces:
  - `interface Span { t: number; dur: number }`.
  - `class NoteCursor<T extends Span> { constructor(notes: readonly T[]); window(from: number, to: number): T[] }`. `notes` must be sorted by onset.
  - `SCHEMA_VERSION = 1` and `canRead(doc: TabDocument): boolean`.
  - `buildSong(doc: TabDocument): Song`, where `Song` is `{ title, duration, tuning, notes, chords, sections, beats, warnings, hidden, cursor }`. Every track is sorted by onset. `tuning` falls back to standard. `cursor` is a `NoteCursor<Note>` over `notes`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/playback/cursor.test.ts`. Most cases compare the cursor with a brute-force filter over the same notes:

```typescript
import { describe, expect, it } from "vitest";

import { NoteCursor, type Span } from "./cursor";

interface Tagged extends Span {
  id: number;
}

/** What `window` must return, by brute force. */
function expected(notes: readonly Tagged[], from: number, to: number): number[] {
  return notes.filter((n) => n.t <= to && n.t + n.dur >= from).map((n) => n.id);
}

function ids(notes: readonly Tagged[]): number[] {
  return notes.map((n) => n.id);
}

/** A note every 0.25 s for a minute, some of them long. */
const SONG: Tagged[] = Array.from({ length: 240 }, (_, i) => ({
  id: i,
  t: i * 0.25,
  dur: i % 17 === 0 ? 3 : 0.2,
}));

describe("NoteCursor", () => {
  it("steps forward frame by frame", () => {
    const cursor = new NoteCursor(SONG);

    for (let now = 0; now < 60; now += 1 / 60) {
      expect(ids(cursor.window(now - 1, now + 4))).toEqual(expected(SONG, now - 1, now + 4));
    }
  });

  it("re-seats after a backward jump and a forward jump past the window", () => {
    const cursor = new NoteCursor(SONG);
    const windows: Array<[number, number]> = [
      [30, 35], [30.02, 35.02], [5, 10], [5.1, 10.1], [50, 55], [0, 1], [59, 64],
    ];

    for (const [from, to] of windows) {
      expect(ids(cursor.window(from, to))).toEqual(expected(SONG, from, to));
    }
  });

  it("re-seats when the window shrinks", () => {
    const cursor = new NoteCursor(SONG);

    cursor.window(10, 20);
    expect(ids(cursor.window(11, 12))).toEqual(expected(SONG, 11, 12));
  });

  it("finds overlapping notes still sounding from before the window", () => {
    const notes: Tagged[] = [
      { id: 0, t: 0, dur: 10 },
      { id: 1, t: 1, dur: 1 },
      { id: 2, t: 5, dur: 2 },
    ];
    const cursor = new NoteCursor(notes);

    expect(ids(cursor.window(6, 6))).toEqual([0, 2]);
  });

  it("finds a note longer than the window that spans it", () => {
    const cursor = new NoteCursor<Tagged>([{ id: 0, t: 0, dur: 30 }]);

    expect(ids(cursor.window(10, 11))).toEqual([0]);
    expect(ids(cursor.window(31, 32))).toEqual([]);
  });

  it("answers an empty song", () => {
    expect(new NoteCursor<Tagged>([]).window(0, 10)).toEqual([]);
  });
});
```

Create `web/src/song.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { buildSong, canRead } from "./song";
import firstSongJson from "./test/fixtures/first-song.tabdoc.json";
import minimalJson from "../../packages/core/tests/fixtures/minimal.tabdoc.json";
import type { TabDocument } from "./types/tabDocument";

const FIRST_SONG: TabDocument = firstSongJson;
const MINIMAL: TabDocument = minimalJson;

describe("buildSong", () => {
  it("sorts every track by onset", () => {
    const doc = structuredClone(FIRST_SONG);
    doc.notes = [...(doc.notes ?? [])].reverse();

    const song = buildSong(doc);

    const onsets = song.notes.map((n) => n.t);
    expect(onsets).toEqual([...onsets].sort((a, b) => a - b));
    expect(song.notes).toHaveLength(FIRST_SONG.notes?.length ?? -1);
  });

  it("reads the real first song: notes, chords, beats, and no sections", () => {
    const song = buildSong(FIRST_SONG);

    expect(song.notes.length).toBeGreaterThan(0);
    expect(song.chords.length).toBeGreaterThan(0);
    expect(song.beats.length).toBeGreaterThan(0);
    expect(song.sections).toEqual([]);
    expect(song.duration).toBeCloseTo(13.871);
  });

  it("fills omitted optional tracks with empty lists and standard tuning", () => {
    const doc: TabDocument = {
      source: MINIMAL.source,
      instrument: {},
      timing: {},
    };

    const song = buildSong(doc);

    expect(song.notes).toEqual([]);
    expect(song.chords).toEqual([]);
    expect(song.sections).toEqual([]);
    expect(song.beats).toEqual([]);
    expect(song.warnings).toEqual([]);
    expect(song.hidden).toEqual([]);
    expect(song.tuning).toEqual(["E2", "A2", "D3", "G3", "B3", "E4"]);
  });
});

describe("canRead", () => {
  it("reads version 1, and a document with no version", () => {
    expect(canRead(MINIMAL)).toBe(true);
    const unversioned: TabDocument = { ...MINIMAL };
    delete unversioned.schema_version;
    expect(canRead(unversioned)).toBe(true);
  });

  it("refuses any other version", () => {
    expect(canRead({ ...MINIMAL, schema_version: 2 })).toBe(false);
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/playback/cursor.test.ts src/song.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './cursor'` and `Cannot find module './song'`.

- [ ] **Step 3: Write the cursor**

Create `web/src/playback/cursor.ts`:

```typescript
/** Anything with an onset and a duration, in seconds. */
export interface Span {
  t: number;
  dur: number;
}

/**
 * The notes sounding at any moment of a time window, answered from notes
 * sorted once by onset.
 *
 * During normal playback the window moves forward a little each frame, and
 * two pointers follow it. A backward jump, a forward jump past the last
 * window, or a window that shrinks re-seats them by binary search. Per-call
 * work is proportional to the notes in the window, not the song's length.
 *
 * Stateful, so each view keeps its own: `new NoteCursor(song.notes)`.
 */
export class NoteCursor<T extends Span> {
  private readonly notes: readonly T[];
  private readonly longest: number;
  private lo = 0; // the first note with t >= from - longest
  private hi = 0; // the first note with t > to
  private from = Number.POSITIVE_INFINITY;
  private to = Number.NEGATIVE_INFINITY;

  /** `notes` must be sorted by onset. */
  constructor(notes: readonly T[]) {
    this.notes = notes;
    this.longest = notes.reduce((longest, note) => Math.max(longest, note.dur), 0);
  }

  /** The notes whose [t, t + dur] overlaps [from, to], in onset order. */
  window(from: number, to: number): T[] {
    const start = from - this.longest; // nothing earlier can still be sounding
    const following = from >= this.from && from <= this.to && to >= this.to;
    if (following) {
      while (this.lo < this.notes.length && this.notes[this.lo].t < start) this.lo++;
      while (this.hi < this.notes.length && this.notes[this.hi].t <= to) this.hi++;
    } else {
      this.lo = firstIndex(this.notes, (note) => note.t >= start);
      this.hi = firstIndex(this.notes, (note) => note.t > to);
    }
    this.from = from;
    this.to = to;

    const found: T[] = [];
    for (let i = this.lo; i < this.hi; i++) {
      const note = this.notes[i];
      if (note.t + note.dur >= from) found.push(note);
    }
    return found;
  }
}

/** The first index whose note passes `test`, which must be monotonic. */
function firstIndex<T>(items: readonly T[], test: (item: T) => boolean): number {
  let lo = 0;
  let hi = items.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (test(items[mid])) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}
```

- [ ] **Step 4: Write the Song**

Create `web/src/song.ts`:

```typescript
/**
 * A tab document, read once into what the views draw from.
 *
 * The page builds a Song when the document arrives and every view reads the
 * Song, never the raw document. The optional tracks are filled with empty
 * lists here, so the views handle "missing" and "empty" as one case.
 */
import { hiddenPassages, type Passage } from "./confidence";
import { NoteCursor } from "./playback/cursor";
import type { Beat, Chord, Note, Section, TabDocument } from "./types/tabDocument";

/** The only document version this client draws. */
export const SCHEMA_VERSION = 1;

const STANDARD_TUNING = ["E2", "A2", "D3", "G3", "B3", "E4"];

export interface Song {
  title: string;
  /** source.duration_sec: the length until the audio reports its own. */
  duration: number;
  /** Scientific pitch names, lowest string first. */
  tuning: readonly string[];
  /** Sorted by onset, as are chords, sections and beats. */
  notes: readonly Note[];
  chords: readonly Chord[];
  sections: readonly Section[];
  beats: readonly Beat[];
  warnings: readonly string[];
  hidden: readonly Passage[];
  /** The tab strip's cursor. Another view makes its own. */
  cursor: NoteCursor<Note>;
}

/** Whether this client understands the document. A missing version is 1,
 * as the schema's default says. */
export function canRead(doc: TabDocument): boolean {
  return (doc.schema_version ?? SCHEMA_VERSION) === SCHEMA_VERSION;
}

export function buildSong(doc: TabDocument): Song {
  const notes = byOnset(doc.notes ?? []);
  return {
    title: doc.source.title,
    duration: doc.source.duration_sec,
    tuning: doc.instrument.tuning ?? STANDARD_TUNING,
    notes,
    chords: byOnset(doc.chords ?? []),
    sections: byOnset(doc.sections ?? []),
    beats: byOnset(doc.timing.beats ?? []),
    warnings: doc.warnings ?? [],
    hidden: hiddenPassages(notes),
    cursor: new NoteCursor(notes),
  };
}

function byOnset<T extends { t: number }>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => a.t - b.t);
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/playback/cursor.test.ts src/song.test.ts`
Expected: PASS, 11 tests.

- [ ] **Step 6: Commit**

```bash
git add web/src/playback/cursor.ts web/src/playback/cursor.test.ts web/src/song.ts web/src/song.test.ts
git commit -m "feat(web): a note cursor, and the Song every view reads

NoteCursor finds the notes overlapping a time window, using two pointers
during playback and a binary search after a jump. buildSong reads a tab
document once: tracks sorted, omitted tracks empty, hidden passages found.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The clock

Song time, smooth enough to draw from. `MediaClock` extrapolates between coarse media updates and re-anchors on every event the element fires. It snaps back after 50 ms of drift, never runs backwards except after a seek, and freezes while buffering. This task also adds the test doubles that Tasks 8, 12 and 13 use: a scriptable media element, and an animation-frame queue.

**Files:**
- Create: `web/src/playback/clock.ts`, `web/src/playback/clock.test.ts`
- Create: `web/src/test/fakeMedia.ts`

**Interfaces:**
- Produces, from `clock.ts`:
  - `interface MediaLike`, the part of `HTMLMediaElement` the playback code uses: `src`, `currentTime`, `duration`, `paused`, `ended`, `playbackRate`, `defaultPlaybackRate`, `preservesPitch`, `play(): Promise<void>`, `pause()`, `addEventListener`, `removeEventListener`. An `HTMLAudioElement` satisfies it.
  - `interface Clock { now(): number }`, and `FakeClock`, which has a settable `t`.
  - `MAX_DRIFT_SEC = 0.05`.
  - `class MediaClock { constructor(media: MediaLike, perf?: () => number); now(): number; jump(): void; dispose(): void }`. `jump()` lets the next reading go backwards; the engine calls it when it seeks.
- Produces, from `test/fakeMedia.ts`:
  - `class FakeMedia implements MediaLike`. Setting `src` mimics the load algorithm: paused, time 0, duration NaN, and `playbackRate` reset to the default. It also has `emit(type)`, `loadMetadata(duration?)`, `advance(seconds)`, `end()`, `loads: string[]`, `refusePlay: Error | null`, `webkitPreservesPitch` and `listenerCount()`.
  - `class FakeFrames`, with `request`, `cancel`, `pending` and `flush()`.

- [ ] **Step 1: Write the test doubles**

Create `web/src/test/fakeMedia.ts`:

```typescript
/**
 * Test doubles for the playback code: a media element that fires events when
 * told to, and an animation-frame queue flushed by hand.
 */
import type { MediaLike } from "../playback/clock";

export class FakeMedia implements MediaLike {
  currentTime = 0;
  duration = Number.NaN;
  paused = true;
  playbackRate = 1;
  defaultPlaybackRate = 1;
  preservesPitch = false;
  webkitPreservesPitch = false;
  /** Every src ever set, in order. */
  readonly loads: string[] = [];
  /** When set, play() rejects with it, as a browser's autoplay policy may. */
  refusePlay: Error | null = null;
  private source = "";
  private finished = false;
  private readonly listeners = new Map<string, Set<() => void>>();

  /** As in a browser: true only while the position is still at the end. */
  get ended(): boolean {
    return this.finished && this.currentTime >= this.duration;
  }

  get src(): string {
    return this.source;
  }

  /** The media load algorithm, as far as the engine can see it. */
  set src(value: string) {
    this.source = value;
    this.loads.push(value);
    this.paused = true;
    this.finished = false;
    this.currentTime = 0;
    this.duration = Number.NaN;
    this.playbackRate = this.defaultPlaybackRate;
    this.emit("emptied");
  }

  play(): Promise<void> {
    if (this.refusePlay !== null) return Promise.reject(this.refusePlay);
    this.paused = false;
    this.finished = false;
    this.emit("play");
    this.emit("playing");
    return Promise.resolve();
  }

  pause(): void {
    if (this.paused) return;
    this.paused = true;
    this.emit("pause");
  }

  addEventListener(type: string, listener: () => void): void {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener);
    this.listeners.set(type, set);
  }

  removeEventListener(type: string, listener: () => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  listenerCount(): number {
    return [...this.listeners.values()].reduce((sum, set) => sum + set.size, 0);
  }

  emit(type: string): void {
    for (const listener of [...(this.listeners.get(type) ?? [])]) listener();
  }

  /** Metadata arrives, then enough data to play. */
  loadMetadata(duration = 180): void {
    this.duration = duration;
    this.emit("durationchange");
    this.emit("loadedmetadata");
    this.emit("canplay");
  }

  /** Playback moves on by `seconds` of song time and reports it. */
  advance(seconds: number): void {
    this.currentTime += seconds;
    this.emit("timeupdate");
  }

  /** Playback reaches the end, as a browser reports it. */
  end(): void {
    this.currentTime = this.duration;
    this.paused = true;
    this.finished = true;
    this.emit("timeupdate");
    this.emit("pause");
    this.emit("ended");
  }
}

/** requestAnimationFrame and cancelAnimationFrame, run by hand. */
export class FakeFrames {
  private readonly queue = new Map<number, () => void>();
  private next = 1;

  readonly request = (callback: () => void): number => {
    const id = this.next++;
    this.queue.set(id, callback);
    return id;
  };

  readonly cancel = (id: number): void => {
    this.queue.delete(id);
  };

  get pending(): number {
    return this.queue.size;
  }

  /** Run the frames queued so far; frames they request wait for the next flush. */
  flush(): void {
    const callbacks = [...this.queue.values()];
    this.queue.clear();
    for (const callback of callbacks) callback();
  }
}
```

- [ ] **Step 2: Write the failing tests**

Create `web/src/playback/clock.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { FakeMedia } from "../test/fakeMedia";
import { MediaClock } from "./clock";

function setup() {
  const media = new FakeMedia();
  let ms = 0;
  const clock = new MediaClock(media, () => ms);
  const wait = (milliseconds: number) => {
    ms += milliseconds;
  };
  return { media, clock, wait };
}

describe("MediaClock", () => {
  it("returns media time exactly while paused", () => {
    const { media, clock, wait } = setup();
    media.currentTime = 12.5;

    wait(500);

    expect(clock.now()).toBe(12.5);
  });

  it("extrapolates between coarse media updates", () => {
    const { media, clock, wait } = setup();
    void media.play();

    wait(16);
    expect(clock.now()).toBeCloseTo(0.016);
    wait(16);
    expect(clock.now()).toBeCloseTo(0.032); // media time has not moved yet
    media.currentTime = 0.03; // it catches up, within the drift allowance
    wait(16);
    expect(clock.now()).toBeCloseTo(0.048);
  });

  it("snaps to media time when extrapolation drifts more than 50 ms", () => {
    const { media, clock, wait } = setup();
    void media.play();
    media.currentTime = 1;
    media.emit("timeupdate");

    wait(200); // the element stalled without saying so
    media.currentTime = 1.1;

    expect(clock.now()).toBeCloseTo(1.1);
  });

  it("freezes while the element is waiting for data", () => {
    const { media, clock, wait } = setup();
    void media.play();
    media.currentTime = 3;
    media.emit("waiting");

    wait(1000);

    expect(clock.now()).toBe(3);
    media.emit("playing");
    wait(100);
    media.currentTime = 3.09;
    expect(clock.now()).toBeCloseTo(3.1);
  });

  it("never goes backwards on a correction", () => {
    const { media, clock, wait } = setup();
    void media.play();
    wait(40);
    const ahead = clock.now();
    media.currentTime = 0.01; // a late, low reading
    media.emit("timeupdate");

    expect(clock.now()).toBe(ahead);
  });

  it("goes backwards after a seek", () => {
    const { media, clock, wait } = setup();
    media.currentTime = 30;
    clock.now();

    media.currentTime = 10;
    media.emit("seeked");
    wait(16);

    expect(clock.now()).toBe(10);
  });

  it("goes backwards after a jump the engine announces", () => {
    const { media, clock } = setup();
    media.currentTime = 30;
    clock.now();

    media.currentTime = 10;
    clock.jump();

    expect(clock.now()).toBe(10);
  });

  it("follows a rate change mid-play", () => {
    const { media, clock, wait } = setup();
    void media.play();
    wait(1000);
    media.currentTime = 1;
    expect(clock.now()).toBeCloseTo(1);

    media.playbackRate = 0.5;
    media.emit("ratechange");
    wait(1000);
    media.currentTime = 1.5;

    expect(clock.now()).toBeCloseTo(1.5);
    wait(40);
    expect(clock.now()).toBeCloseTo(1.52);
  });

  it("stops listening when disposed", () => {
    const { media, clock } = setup();

    clock.dispose();

    expect(media.listenerCount()).toBe(0);
  });
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `npm --prefix web test -- src/playback/clock.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module '../playback/clock'` from `fakeMedia.ts`, and `'./clock'` from the test.

- [ ] **Step 4: Write the clock**

Create `web/src/playback/clock.ts`:

```typescript
/**
 * Song time, smooth enough to draw from.
 *
 * Media time is coarse in some browsers, and a strip that steps visibly reads
 * as out of sync even when it is not. MediaClock extrapolates between media
 * updates and corrects itself from the element whenever it can.
 */

/**
 * The part of an HTMLMediaElement the playback code uses, so tests can drive
 * a fake one. An HTMLAudioElement satisfies it.
 */
export interface MediaLike {
  src: string;
  currentTime: number;
  readonly duration: number;
  readonly paused: boolean;
  readonly ended: boolean;
  playbackRate: number;
  defaultPlaybackRate: number;
  preservesPitch: boolean;
  play(): Promise<void>;
  pause(): void;
  addEventListener(type: string, listener: () => void): void;
  removeEventListener(type: string, listener: () => void): void;
}

/** Song seconds, now. */
export interface Clock {
  now(): number;
}

/** A clock a test sets by hand. */
export class FakeClock implements Clock {
  t = 0;

  now(): number {
    return this.t;
  }
}

/** How far extrapolation may drift from media time before it snaps back. */
export const MAX_DRIFT_SEC = 0.05;

const ANCHORING_EVENTS = [
  "timeupdate",
  "seeked",
  "ratechange",
  "play",
  "pause",
  "waiting",
  "playing",
] as const;

export class MediaClock implements Clock {
  private readonly media: MediaLike;
  private readonly perf: () => number;
  private readonly listeners: Array<[string, () => void]>;
  private anchorTime = 0; // media seconds at the anchor
  private anchorAt = 0; // perf() milliseconds at the anchor
  private waiting = false;
  private last = 0;
  private mayGoBack = true;

  /** `perf` is performance.now(), injected so tests control it. */
  constructor(media: MediaLike, perf: () => number = () => performance.now()) {
    this.media = media;
    this.perf = perf;
    this.listeners = ANCHORING_EVENTS.map((type) => [type, () => this.observe(type)]);
    for (const [type, listener] of this.listeners) media.addEventListener(type, listener);
    this.anchor();
  }

  now(): number {
    const media = this.media.currentTime;
    let t = media;
    if (!this.media.paused && !this.waiting) {
      const elapsed = (this.perf() - this.anchorAt) / 1000;
      t = this.anchorTime + elapsed * this.media.playbackRate;
      if (Math.abs(t - media) > MAX_DRIFT_SEC) {
        this.anchor();
        t = media;
      }
    }
    // Small corrections never run the strip backwards. A seek may.
    if (t < this.last && !this.mayGoBack) t = this.last;
    this.mayGoBack = false;
    this.last = t;
    return t;
  }

  /** A seek is under way: let the next reading go backwards. */
  jump(): void {
    this.mayGoBack = true;
    this.anchor();
  }

  dispose(): void {
    for (const [type, listener] of this.listeners) this.media.removeEventListener(type, listener);
  }

  private observe(type: (typeof ANCHORING_EVENTS)[number]): void {
    if (type === "waiting") this.waiting = true;
    if (type === "playing" || type === "pause") this.waiting = false;
    if (type === "seeked") this.mayGoBack = true;
    this.anchor();
  }

  private anchor(): void {
    this.anchorTime = this.media.currentTime;
    this.anchorAt = this.perf();
  }
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/playback/clock.test.ts`
Expected: PASS, 9 tests.

- [ ] **Step 6: Commit**

```bash
git add web/src/playback/clock.ts web/src/playback/clock.test.ts web/src/test/fakeMedia.ts
git commit -m "feat(web): a media clock smooth enough to draw from

MediaClock extrapolates between coarse media updates, snaps back after
50 ms of drift, never runs backwards except after a seek, and freezes
while the element waits for data. FakeMedia and FakeFrames let the
playback code be tested without audio.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The PlaybackEngine

The one owner of the audio, and the one source of the current time. The engine owns a single media element. It runs one animation-frame loop that hands every view the same `t`. It sets speed so that pitch is kept, switches between the mix and the stem without losing the position, replaces expired audio URLs, and enforces the A/B loop.

**Files:**
- Create: `web/src/playback/engine.ts`, `web/src/playback/engine.test.ts`

**Interfaces:**
- Consumes: `MediaLike` and `MediaClock` (Task 7); `FakeMedia` and `FakeFrames` in tests.
- Produces, from `engine.ts`:
  - `type Source = "mix" | "guitar"`, `RATES = [0.5, 0.75, 1]`, `type Rate`.
  - `SEEK_STEP_SEC = 5`, `MIN_LOOP_SEC = 0.5`, `MAX_FAILURES = 3`.
  - `interface LoopPoints { a: number | null; b: number | null }`, which Task 9's `layout` takes.
  - `interface EngineState { playing; rate; source; loop; duration; buffering; error: "connection_lost" | null; time }`.
  - `audioUrl(jobId, source)`, which returns `/jobs/{id}/audio/{source}`.
  - `class PlaybackEngine`, constructed with `{ media, jobId, duration, now?, requestFrame?, cancelFrame? }`. Its members:
    - `canStretch: boolean`;
    - `onFrame(listener: (t: number) => void): () => void`;
    - `subscribe` and `getState`, which are arrow properties, safe to pass straight to `useSyncExternalStore`;
    - `redraw()`, `play()`, `pause()`, `toggle()`, `seek(t)` and `seekBy(seconds)`;
    - `setRate(rate)`, `setSource(source)`, `setLoopPoint("a" | "b"): boolean`, `clearLoop()` and `dispose()`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/playback/engine.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { FakeFrames, FakeMedia } from "../test/fakeMedia";
import { MAX_FAILURES, PlaybackEngine } from "./engine";

const JOB = "5f0c6c2e-0000-4000-8000-000000000001";
const MIX = `/jobs/${JOB}/audio/mix`;
const GUITAR = `/jobs/${JOB}/audio/guitar`;

function setup() {
  const media = new FakeMedia();
  const frames = new FakeFrames();
  let ms = 0;
  const engine = new PlaybackEngine({
    media,
    jobId: JOB,
    duration: 200,
    now: () => ms,
    requestFrame: frames.request,
    cancelFrame: frames.cancel,
  });
  const seen: number[] = [];
  engine.onFrame((t) => seen.push(t));
  /** Let song time pass while playing, as the element and the clock see it. */
  const play = (seconds: number) => {
    ms += seconds * 1000 * media.playbackRate;
    media.advance(seconds);
    frames.flush();
  };
  return { media, frames, engine, seen, play };
}

/** An engine with the mix loaded, playing from `at`. */
function playingAt(at: number) {
  const fixture = setup();
  fixture.media.loadMetadata(200);
  fixture.engine.seek(at);
  fixture.engine.play();
  fixture.frames.flush();
  return fixture;
}

describe("loading", () => {
  it("starts on the mix, paused, with pitch preserved", () => {
    const { media, engine } = setup();

    expect(media.src).toBe(MIX);
    expect(media.preservesPitch).toBe(true);
    expect(media.webkitPreservesPitch).toBe(true);
    expect(engine.getState()).toMatchObject({ playing: false, source: "mix", rate: 1 });
    expect(engine.canStretch).toBe(true);
  });

  it("uses the document's duration until the media reports its own", () => {
    const { media, engine } = setup();
    expect(engine.getState().duration).toBe(200);

    media.loadMetadata(201.5);

    expect(engine.getState().duration).toBe(201.5);
  });
});

describe("speed", () => {
  it("sets the rate and the default rate together, and keeps pitch", () => {
    const { media, engine } = setup();
    media.preservesPitch = false;

    engine.setRate(0.5);

    expect(media.playbackRate).toBe(0.5);
    expect(media.defaultPlaybackRate).toBe(0.5);
    expect(media.preservesPitch).toBe(true);
    expect(engine.getState().rate).toBe(0.5);
  });
});

describe("the mix and guitar toggle", () => {
  it("keeps the time, the play state and the rate", () => {
    const { media, engine, play } = playingAt(40);
    engine.setRate(0.75);
    play(2);

    engine.setSource("guitar");

    expect(media.src).toBe(GUITAR);
    expect(engine.getState()).toMatchObject({ source: "guitar", playing: true });
    media.loadMetadata(200);
    expect(media.currentTime).toBe(42);
    expect(media.paused).toBe(false);
    expect(media.playbackRate).toBe(0.75);
  });

  it("holds the strip still while the other file loads", () => {
    const { media, engine, frames, seen, play } = playingAt(40);
    play(2);

    engine.setSource("guitar");
    frames.flush();

    expect(media.currentTime).toBe(0); // the load algorithm reset it
    expect(seen.at(-1)).toBe(42);
  });

  it("keeps a paused song paused", () => {
    const { media, engine } = setup();
    media.loadMetadata(200);
    engine.seek(90);

    engine.setSource("guitar");
    media.loadMetadata(200);

    expect(media.currentTime).toBe(90);
    expect(media.paused).toBe(true);
    expect(engine.getState().playing).toBe(false);
  });

  it("survives a second toggle before the first file has loaded", () => {
    const { media, engine, play } = playingAt(40);
    play(2);

    engine.setSource("guitar");
    engine.setSource("mix");
    media.loadMetadata(200);

    expect(media.src).toBe(MIX);
    expect(media.currentTime).toBe(42);
    expect(media.paused).toBe(false);
  });

  it("seeks within a file that is still loading", () => {
    const { media, engine } = playingAt(40);

    engine.setSource("guitar");
    engine.seek(10);
    media.loadMetadata(200);

    expect(media.currentTime).toBe(10);
  });

  it("does not throw when the browser refuses to resume", async () => {
    const { media, engine } = playingAt(40);
    engine.setSource("guitar");
    media.refusePlay = new Error("NotAllowedError");

    media.loadMetadata(200);
    await Promise.resolve();

    expect(engine.getState().playing).toBe(false);
  });
});

describe("expired audio URLs", () => {
  it("asks the api again on a media error, and resumes where it was", () => {
    const { media, engine, play } = playingAt(100);
    play(3);

    media.emit("error");

    expect(media.loads).toEqual([MIX, MIX]);
    media.loadMetadata(200);
    expect(media.currentTime).toBe(103);
    expect(media.paused).toBe(false);
    expect(engine.getState().error).toBeNull();
  });

  it(`gives up after ${MAX_FAILURES} failures in a row`, () => {
    const { media, engine } = playingAt(100);

    for (let i = 0; i < MAX_FAILURES; i++) media.emit("error");

    expect(media.loads).toHaveLength(MAX_FAILURES); // the first load, then two retries
    expect(engine.getState()).toMatchObject({ error: "connection_lost", playing: false });
    engine.play();
    expect(media.paused).toBe(true);
  });

  it("counts only consecutive failures", () => {
    const { media, engine } = playingAt(100);

    for (let i = 0; i < MAX_FAILURES * 2; i++) {
      media.emit("error");
      media.loadMetadata(200); // recovered: canplay resets the count
    }

    expect(engine.getState().error).toBeNull();
  });
});

describe("the A/B loop", () => {
  function looping() {
    const fixture = playingAt(10);
    fixture.engine.setLoopPoint("a");
    fixture.engine.seek(20);
    fixture.engine.setLoopPoint("b");
    fixture.engine.seek(15);
    fixture.frames.flush();
    return fixture;
  }

  it("jumps back to A when playback crosses B", () => {
    const { media, engine, play } = looping();

    play(4.9);
    expect(media.currentTime).toBeCloseTo(19.9);
    play(0.2);

    expect(media.currentTime).toBe(10);
    expect(engine.getState().loop).toEqual({ a: 10, b: 20 });
  });

  it("holds from timeupdate alone, as in a background tab", () => {
    const { media } = looping();

    media.advance(5.1); // no animation frame runs

    expect(media.currentTime).toBe(10);
  });

  it("is released by seeking past B", () => {
    const { media, engine, play } = looping();

    engine.seek(25);
    play(1);

    expect(media.currentTime).toBe(26);
  });

  it("is entered by seeking before A and playing into it", () => {
    const { media, engine, play } = looping();

    engine.seek(5);
    for (let i = 0; i < 16; i++) play(1);

    expect(media.currentTime).toBeGreaterThanOrEqual(10);
    expect(media.currentTime).toBeLessThan(20);
  });

  it("refuses points less than half a second apart", () => {
    const { engine } = playingAt(10);
    engine.setLoopPoint("a");
    engine.seek(10.4);

    expect(engine.setLoopPoint("b")).toBe(false);
    expect(engine.getState().loop).toEqual({ a: 10, b: null });
  });

  it("accepts B before A, looping the span between them", () => {
    const { media, engine, play } = playingAt(20);
    engine.setLoopPoint("a");
    engine.seek(10);
    engine.setLoopPoint("b");

    for (let i = 0; i < 11; i++) play(1);

    expect(media.currentTime).toBeLessThan(20);
  });

  it("keeps looping when B is the very end of the song", () => {
    const { media, engine } = playingAt(190);
    engine.setLoopPoint("a");
    engine.seek(200);
    engine.setLoopPoint("b");
    engine.seek(195);

    media.end();

    expect(media.currentTime).toBe(190);
    expect(media.paused).toBe(false);
  });

  it("clears", () => {
    const { engine } = looping();

    engine.clearLoop();

    expect(engine.getState().loop).toEqual({ a: null, b: null });
  });
});

describe("the end, and frames", () => {
  it("pauses at the end, and plays again from zero", () => {
    const { media, engine } = playingAt(150);

    media.end();
    expect(engine.getState().playing).toBe(false);
    engine.play();

    expect(media.currentTime).toBe(0);
    expect(media.paused).toBe(false);
  });

  it("runs frames while playing and stops when paused", () => {
    const { engine, frames, play } = playingAt(0);
    play(1);
    expect(frames.pending).toBe(1);

    engine.pause();
    frames.flush();
    frames.flush();

    expect(frames.pending).toBe(0);
  });

  it("draws one frame after a seek while paused", () => {
    const { engine, frames, seen } = setup();
    frames.flush();

    engine.seek(30);
    frames.flush();

    expect(seen.at(-1)).toBe(30);
    expect(frames.pending).toBe(0);
  });

  it("gives every frame listener the same time", () => {
    const { engine, frames, play } = playingAt(5);
    const other: number[] = [];
    engine.onFrame((t) => other.push(t));
    const seen: number[] = [];
    engine.onFrame((t) => seen.push(t));

    play(0.5);
    frames.flush();

    expect(seen).toEqual(other.slice(-seen.length));
  });

  it("updates the time readout about four times a second, not every frame", () => {
    const { engine, play } = playingAt(0);
    let updates = 0;
    engine.subscribe(() => updates++);

    for (let i = 0; i < 60; i++) play(1 / 60);

    expect(updates).toBeGreaterThanOrEqual(3);
    expect(updates).toBeLessThanOrEqual(5);
  });

  it("lets go of the element when disposed", () => {
    const { media, engine, frames } = playingAt(5);

    engine.dispose();

    expect(media.paused).toBe(true);
    expect(media.listenerCount()).toBe(0);
    expect(frames.pending).toBe(0);
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/playback/engine.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './engine'`.

- [ ] **Step 3: Write the engine**

Create `web/src/playback/engine.ts`:

```typescript
/**
 * The PlaybackEngine: the one owner of the audio, and the one source of the
 * current time.
 *
 * It owns a single media element. Native time-stretching exists only on media
 * elements, which is what makes slow-down nearly free (ADR 0008). Views never
 * touch the element: they draw from `onFrame`, and the controls read
 * `getState` through useSyncExternalStore.
 */
import { MediaClock, type MediaLike } from "./clock";

export type Source = "mix" | "guitar";
export const RATES = [0.5, 0.75, 1] as const;
export type Rate = (typeof RATES)[number];

export const SEEK_STEP_SEC = 5;
export const MIN_LOOP_SEC = 0.5;
/** Consecutive media errors before the engine stops retrying. */
export const MAX_FAILURES = 3;
/** The time readout in the state moves in steps of about this (about 4 Hz). */
const READOUT_SEC = 0.25;

/** Loop points in song seconds. Both set means a loop. */
export interface LoopPoints {
  a: number | null;
  b: number | null;
}

export interface EngineState {
  playing: boolean;
  rate: Rate;
  source: Source;
  loop: LoopPoints;
  duration: number;
  buffering: boolean;
  error: "connection_lost" | null;
  /** The current time, updated about four times a second. Draw from onFrame. */
  time: number;
}

export interface EngineOptions {
  media: MediaLike;
  jobId: string;
  /** source.duration_sec, used until the media reports its own. */
  duration: number;
  /** performance.now(), injectable for tests. */
  now?: () => number;
  requestFrame?: (callback: () => void) => number;
  cancelFrame?: (id: number) => void;
}

/** The api path, never the presigned URL it redirects to: requesting the
 * path again is how an expired URL is replaced. */
export function audioUrl(jobId: string, source: Source): string {
  return `/jobs/${encodeURIComponent(jobId)}/audio/${source}`;
}

interface Pending {
  at: number;
  resume: boolean;
}

export class PlaybackEngine {
  /** Whether the browser can change speed without changing pitch. */
  readonly canStretch: boolean;
  private readonly media: MediaLike;
  private readonly jobId: string;
  private readonly clock: MediaClock;
  private readonly requestFrame: (callback: () => void) => number;
  private readonly cancelFrame: (id: number) => void;
  private readonly frameListeners = new Set<(t: number) => void>();
  private readonly stateListeners = new Set<() => void>();
  private readonly unlisten: Array<() => void> = [];
  private state: EngineState;
  private frame: number | null = null;
  /** A source being loaded: where to seek once it has metadata, and whether to play. */
  private pending: Pending | null = null;
  private failures = 0;
  /** The time at the last loop check. */
  private previous = 0;
  private disposed = false;

  constructor(options: EngineOptions) {
    this.media = options.media;
    this.jobId = options.jobId;
    this.canStretch = "preservesPitch" in this.media || "webkitPreservesPitch" in this.media;
    this.clock = new MediaClock(this.media, options.now);
    this.requestFrame =
      options.requestFrame ?? ((callback) => requestAnimationFrame(() => callback()));
    this.cancelFrame = options.cancelFrame ?? ((id) => cancelAnimationFrame(id));
    this.state = {
      playing: false,
      rate: 1,
      source: "mix",
      loop: { a: null, b: null },
      duration: options.duration,
      buffering: false,
      error: null,
      time: 0,
    };

    this.listen("loadedmetadata", () => this.onMetadata());
    this.listen("durationchange", () => this.syncDuration());
    this.listen("canplay", () => {
      this.failures = 0;
      this.update({ buffering: false });
    });
    this.listen("waiting", () => this.update({ buffering: true }));
    this.listen("playing", () => this.update({ buffering: false }));
    this.listen("play", () => this.syncPlaying());
    this.listen("pause", () => this.syncPlaying());
    this.listen("ended", () => this.onEnded());
    // Animation frames stop in a background tab; timeupdate does not, so the
    // loop holds there too.
    this.listen("timeupdate", () => this.tick());
    this.listen("error", () => this.onError());

    this.applyRate(1);
    this.load(0, false);
  }

  // --- for views and controls --------------------------------------------

  /** Call `listener` with the time on every frame while playing, and once
   * after any change while paused. Every listener gets the same t. */
  onFrame(listener: (t: number) => void): () => void {
    this.frameListeners.add(listener);
    this.redraw();
    return () => this.frameListeners.delete(listener);
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.stateListeners.add(listener);
    return () => this.stateListeners.delete(listener);
  };

  readonly getState = (): EngineState => this.state;

  /** Ask for one frame, e.g. after the canvas changed size. */
  redraw(): void {
    if (this.frame === null && !this.disposed) {
      this.frame = this.requestFrame(() => this.runFrame());
    }
  }

  // --- transport ------------------------------------------------------------

  play(): void {
    if (this.state.error !== null) return;
    if (this.pending !== null) {
      this.pending.resume = true;
      this.syncPlaying();
      return;
    }
    if (this.media.ended) this.seek(0);
    this.media.play().catch(() => this.syncPlaying());
  }

  pause(): void {
    if (this.pending !== null) {
      this.pending.resume = false;
      this.syncPlaying();
      return;
    }
    this.media.pause();
  }

  toggle(): void {
    if (this.state.playing) this.pause();
    else this.play();
  }

  seek(t: number): void {
    const target = Math.min(Math.max(t, 0), this.state.duration);
    this.previous = target;
    if (this.pending !== null) {
      this.pending.at = target;
    } else {
      this.media.currentTime = target;
      this.clock.jump();
    }
    this.update({ time: target });
    this.redraw();
  }

  seekBy(seconds: number): void {
    this.seek(this.time() + seconds);
  }

  setRate(rate: Rate): void {
    this.applyRate(rate);
    this.update({ rate });
  }

  /** Switch between the mix and the guitar stem, keeping time, play state
   * and rate. Costs a short gap while the other file loads. */
  setSource(source: Source): void {
    if (source === this.state.source || this.state.error !== null) return;
    const resume = this.state.playing;
    const at = this.time();
    this.update({ source });
    this.load(at, resume);
  }

  // --- the A/B loop ---------------------------------------------------------

  /** Set A or B at the current time. Refused, returning false, when it would
   * sit less than MIN_LOOP_SEC from the other point. */
  setLoopPoint(point: "a" | "b"): boolean {
    const t = this.time();
    const other = point === "a" ? this.state.loop.b : this.state.loop.a;
    if (other !== null && Math.abs(t - other) < MIN_LOOP_SEC) return false;
    this.update({ loop: { ...this.state.loop, [point]: t } });
    return true;
  }

  clearLoop(): void {
    this.update({ loop: { a: null, b: null } });
  }

  dispose(): void {
    this.disposed = true;
    if (this.frame !== null) this.cancelFrame(this.frame);
    this.frame = null;
    for (const unlisten of this.unlisten) unlisten();
    this.clock.dispose();
    this.media.pause();
    this.frameListeners.clear();
    this.stateListeners.clear();
  }

  // --- internals ------------------------------------------------------------

  /** The time to draw: held still while a source loads. */
  private time(): number {
    return this.pending?.at ?? this.clock.now();
  }

  private runFrame(): void {
    this.frame = null;
    const t = this.tick();
    for (const listener of this.frameListeners) listener(t);
    if (this.state.playing && this.pending === null) this.redraw();
  }

  /** Enforce the loop, refresh the readout, and return the time. */
  private tick(): number {
    const t = this.time();
    const loop = this.loopRange();
    if (loop !== null && this.pending === null) {
      const [a, b] = loop;
      // Only playback crossing B from inside the loop jumps back. Seeking
      // past B releases the loop; seeking before A plays into it.
      if (this.previous >= a && this.previous < b && t >= b) {
        this.seek(a);
        return a;
      }
    }
    this.previous = t;
    if (Math.abs(t - this.state.time) >= READOUT_SEC) this.update({ time: t });
    return t;
  }

  private loopRange(): [number, number] | null {
    const { a, b } = this.state.loop;
    return a === null || b === null ? null : [Math.min(a, b), Math.max(a, b)];
  }

  private load(at: number, resume: boolean): void {
    this.pending = { at, resume };
    this.media.src = audioUrl(this.jobId, this.state.source);
    this.syncPlaying();
  }

  private onMetadata(): void {
    this.syncDuration();
    const pending = this.pending;
    if (pending === null) return;
    this.pending = null;
    this.media.currentTime = pending.at;
    this.clock.jump();
    this.previous = pending.at;
    if (pending.resume) this.media.play().catch(() => this.syncPlaying());
    this.syncPlaying();
  }

  private onEnded(): void {
    const loop = this.loopRange();
    // A loop whose B is the very end keeps looping.
    if (loop !== null && this.previous >= loop[0] && this.previous <= loop[1]) {
      this.seek(loop[0]);
      this.play();
      return;
    }
    this.syncPlaying();
  }

  /** A network error, most likely an expired presigned URL: ask the api again. */
  private onError(): void {
    const at = this.time();
    const resume = this.state.playing;
    this.failures += 1;
    if (this.failures >= MAX_FAILURES) {
      this.pending = null;
      this.media.pause();
      this.update({ error: "connection_lost", playing: false, buffering: false });
      return;
    }
    this.load(at, resume);
  }

  private applyRate(rate: Rate): void {
    // The load algorithm resets playbackRate to the default on every src
    // change, so both are set, or the toggle would undo a speed change.
    this.media.defaultPlaybackRate = rate;
    this.media.playbackRate = rate;
    this.media.preservesPitch = true;
    if ("webkitPreservesPitch" in this.media) {
      (this.media as { webkitPreservesPitch: boolean }).webkitPreservesPitch = true;
    }
  }

  private syncPlaying(): void {
    this.update({ playing: this.pending?.resume ?? !this.media.paused });
  }

  private syncDuration(): void {
    const duration = this.media.duration;
    if (Number.isFinite(duration) && duration > 0) this.update({ duration });
  }

  private listen(type: string, listener: () => void): void {
    this.media.addEventListener(type, listener);
    this.unlisten.push(() => this.media.removeEventListener(type, listener));
  }

  private update(patch: Partial<EngineState>): void {
    const changed = (Object.keys(patch) as Array<keyof EngineState>).some(
      (key) => patch[key] !== this.state[key],
    );
    if (!changed) return;
    this.state = { ...this.state, ...patch };
    for (const listener of this.stateListeners) listener();
    this.redraw();
  }
}
```

Four details carry the design, and they are easy to undo by accident:

- `applyRate` sets `defaultPlaybackRate` as well as `playbackRate`, because the load algorithm resets the rate on every `src` change.
- While `pending` is set, `time()` returns the target time rather than the element's time, which is 0 until metadata arrives.
- `src` is always the api path, never the presigned URL, so setting it again fetches a fresh redirect.
- `tick` runs from `timeupdate` as well as from frames, because a background tab stops animation frames but not `timeupdate`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/playback`
Expected: PASS, 41 tests across the clock, the cursor and the engine.

- [ ] **Step 5: Commit**

```bash
git add web/src/playback/engine.ts web/src/playback/engine.test.ts
git commit -m "feat(web): the PlaybackEngine

One media element and one clock. Every view gets the same time each
frame. Speed keeps pitch, the mix/guitar toggle keeps time, play state
and rate, an expired audio URL is fetched again from the api, and the
A/B loop holds even in a background tab.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The tab strip's layout

Everything worth testing about the strip, as a pure function: a song, a time, a viewport and the loop points in, and a list of rectangles, lines and text out. The layout is linear in seconds, with the playhead fixed at 20% and 150 px per song second. The rows collapse as tracks go missing. Notes are past, sounding or upcoming, and faded by confidence. Hidden passages show no fret numbers.

**Files:**
- Create: `web/src/tab/layout.ts`, `web/src/tab/layout.test.ts`

**Interfaces:**
- Consumes: `emphasis` and `Passage` (Task 5); `Song` and `buildSong` (Task 6); `LoopPoints` (Task 8).
- Produces:
  - `PX_PER_SEC = 150`, `PLAYHEAD_AT = 0.2`, `EMPTY_MESSAGE` and `UNCLEAR_LABEL`.
  - `type Paint` (`"background" | "text" | "muted" | "accent" | "string" | "bar" | "playhead" | "loop" | "hidden"`) and `type Font`.
  - `type DrawOp`: a `rect`, `line` or `text` op, each with a `paint` and an `alpha`.
  - `interface Viewport { width; height }` and `interface Rows { sectionY; chordY; stringY; top; bottom; height }`.
  - `rowsOf(song): Rows`, `stringLabels(tuning): string[]`, and `layout(song, now, viewport, loop): DrawOp[]`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/tab/layout.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { FADED } from "../confidence";
import { buildSong } from "../song";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { Chord, Note, TabDocument } from "../types/tabDocument";
import {
  EMPTY_MESSAGE,
  PLAYHEAD_AT,
  PX_PER_SEC,
  UNCLEAR_LABEL,
  layout,
  rowsOf,
  stringLabels,
  type DrawOp,
} from "./layout";

const FIRST_SONG: TabDocument = firstSongJson;
const VIEW = { width: 800, height: 200 };
const NO_LOOP = { a: null, b: null };
const PLAYHEAD_X = VIEW.width * PLAYHEAD_AT;

type Text = Extract<DrawOp, { kind: "text" }>;
type Line = Extract<DrawOp, { kind: "line" }>;

function texts(ops: DrawOp[]): Text[] {
  return ops.filter((op): op is Text => op.kind === "text");
}

function lines(ops: DrawOp[], paint: string): Line[] {
  return ops.filter((op): op is Line => op.kind === "line" && op.paint === paint);
}

function frets(ops: DrawOp[]): Text[] {
  return texts(ops).filter((op) => op.font === "fret" || op.font === "fretBold");
}

let ids = 0;
function note(t: number, fields: Partial<Note> = {}): Note {
  ids += 1;
  return { id: `n${ids}`, t, dur: 0.5, midi: 45, string: 1, fret: 0, confidence: 0.95, ...fields };
}

function doc(fields: Partial<TabDocument> = {}): TabDocument {
  return {
    source: { title: "t", duration_sec: 60, audio_url: "/jobs/x/audio/mix" },
    instrument: {},
    timing: {},
    ...fields,
  };
}

describe("geometry", () => {
  it("puts a note at playheadX + (t - now) * pxPerSec", () => {
    const song = buildSong(doc({ notes: [note(11, { fret: 7 })] }));

    const [seven] = frets(layout(song, 10, VIEW, NO_LOOP));

    expect(seven.text).toBe("7");
    expect(seven.x).toBe(PLAYHEAD_X + PX_PER_SEC);
  });

  it("draws the playhead at a fifth of the width", () => {
    const song = buildSong(doc());

    const [playhead] = lines(layout(song, 0, VIEW, NO_LOOP), "playhead");

    expect(playhead.x1).toBe(PLAYHEAD_X);
  });

  it("leaves out notes outside the visible window", () => {
    const song = buildSong(doc({ notes: [note(0), note(100)] }));

    expect(frets(layout(song, 50, VIEW, NO_LOOP))).toEqual([]);
  });
});

describe("strings", () => {
  it("labels standard tuning e B G D A E, highest on top", () => {
    const song = buildSong(doc());
    const rows = rowsOf(song);

    expect(stringLabels(song.tuning)).toEqual(["E", "A", "D", "G", "B", "e"]);
    expect(rows.stringY[5]).toBeLessThan(rows.stringY[0]);
    const labels = texts(layout(song, 0, VIEW, NO_LOOP))
      .filter((op) => op.font === "label" && op.align === "center")
      .sort((a, b) => a.y - b.y)
      .map((op) => op.text);
    expect(labels).toEqual(["e", "B", "G", "D", "A", "E"]);
  });

  it("keeps drop D's top E in capitals", () => {
    expect(stringLabels(["D2", "A2", "D3", "G3", "B3", "E4"])).toEqual([
      "D", "A", "D", "G", "B", "E",
    ]);
  });

  it("names sharps and flats", () => {
    expect(stringLabels(["C#2", "Bb2"])).toEqual(["C#", "Bb"]);
  });

  it("places each note on its own string", () => {
    const song = buildSong(doc({ notes: [note(1, { string: 0 }), note(1, { string: 5, fret: 3 })] }));
    const rows = rowsOf(song);

    const ops = frets(layout(song, 1, VIEW, NO_LOOP));

    expect(ops.map((op) => op.y).sort()).toEqual([rows.stringY[5], rows.stringY[0]].sort());
  });
});

describe("note states", () => {
  const song = buildSong(doc({ notes: [note(1), note(2), note(3)] }));

  it("dims the past, accents what sounds, and leaves the rest plain", () => {
    const [past, sounding, upcoming] = frets(layout(song, 2.2, VIEW, NO_LOOP));

    expect(past.alpha).toBeLessThan(1);
    expect(past.paint).toBe("text");
    expect(sounding).toMatchObject({ paint: "accent", font: "fretBold", alpha: 1 });
    expect(upcoming).toMatchObject({ paint: "text", font: "fret", alpha: 1 });
  });

  it("fades a weak note by its confidence", () => {
    const weak = buildSong(doc({ notes: [note(2, { confidence: 0 })] }));

    const [faded] = frets(layout(weak, 0, VIEW, NO_LOOP));

    expect(faded.alpha).toBe(FADED);
  });
});

describe("the degradation ladder", () => {
  it("draws bar lines only at the first beat of a bar", () => {
    const beats = [1, 2, 3, 4, 1].map((beat, i) => ({ t: i * 0.5, bar: beat === 1 && i > 0 ? 2 : 1, beat }));
    const song = buildSong(doc({ timing: { beats } }));

    expect(lines(layout(song, 0, VIEW, NO_LOOP), "bar").map((op) => op.x1)).toEqual([
      PLAYHEAD_X,
      PLAYHEAD_X + 2 * PX_PER_SEC,
    ]);
  });

  it("with no beats, draws no bar lines and still places the notes", () => {
    const song = buildSong(doc({ notes: [note(1)] }));

    const ops = layout(song, 0, VIEW, NO_LOOP);

    expect(lines(ops, "bar")).toEqual([]);
    expect(frets(ops)).toHaveLength(1);
  });

  it("collapses the chord and section rows when their tracks are empty", () => {
    const bare = buildSong(doc());
    const full = buildSong(
      doc({
        chords: [{ t: 0, dur: 2, symbol: "Em", confidence: 0.9 }],
        sections: [{ t: 0, dur: 10, label: "intro" }],
      }),
    );

    expect(rowsOf(bare)).toMatchObject({ chordY: null, sectionY: null });
    expect(rowsOf(full).height).toBeGreaterThan(rowsOf(bare).height);
    const words = texts(layout(full, 0, VIEW, NO_LOOP)).map((op) => op.text);
    expect(words).toContain("Em");
    expect(words).toContain("intro");
  });

  it("with no notes, draws the bare strings and a message", () => {
    const song = buildSong(doc());

    const ops = layout(song, 0, VIEW, NO_LOOP);

    expect(lines(ops, "string")).toHaveLength(6);
    expect(texts(ops).map((op) => op.text)).toContain(EMPTY_MESSAGE);
  });

  it("draws the real first song, which has no sections", () => {
    const song = buildSong(FIRST_SONG);

    const ops = layout(song, 3, VIEW, NO_LOOP);

    expect(rowsOf(song).sectionY).toBeNull();
    expect(frets(ops).length).toBeGreaterThan(0);
    expect(lines(ops, "bar").length).toBeGreaterThan(0);
  });
});

describe("hidden passages", () => {
  const weak = (t: number) => note(t, { confidence: 0.05, fret: 9 });
  const chord: Chord = { t: 1, dur: 1, symbol: "Am", confidence: 0.9 };

  it("draws no fret numbers inside a hidden band", () => {
    const song = buildSong(doc({ notes: [weak(1), weak(1.3), weak(1.6), note(3, { fret: 5 })] }));

    const ops = layout(song, 0, VIEW, NO_LOOP);

    expect(song.hidden).toHaveLength(1);
    expect(frets(ops).map((op) => op.text)).toEqual(["5"]);
    expect(ops.some((op) => op.kind === "rect" && op.paint === "hidden")).toBe(true);
  });

  it("labels a band with no chord over it", () => {
    const song = buildSong(doc({ notes: [weak(1), weak(1.3), weak(1.6)] }));

    expect(texts(layout(song, 0, VIEW, NO_LOOP)).map((op) => op.text)).toContain(UNCLEAR_LABEL);
  });

  it("draws the chord over a band larger, at its own confidence, and no label", () => {
    const song = buildSong(
      doc({ notes: [weak(1), weak(1.3), weak(1.6)], chords: [{ ...chord, confidence: 0 }] }),
    );

    const ops = texts(layout(song, 0, VIEW, NO_LOOP));

    expect(ops.find((op) => op.text === "Am")).toMatchObject({ font: "chordLarge", alpha: FADED });
    expect(ops.map((op) => op.text)).not.toContain(UNCLEAR_LABEL);
  });
});

describe("the loop", () => {
  it("shades between A and B and marks both", () => {
    const song = buildSong(doc());

    const ops = layout(song, 0, VIEW, { a: 1, b: 2 });

    const band = ops.find((op) => op.kind === "rect" && op.paint === "loop");
    expect(band).toMatchObject({ x: PLAYHEAD_X + PX_PER_SEC, w: PX_PER_SEC });
    expect(lines(ops, "loop")).toHaveLength(2);
  });

  it("marks A alone before B is set", () => {
    const ops = layout(buildSong(doc()), 0, VIEW, { a: 1, b: null });

    expect(ops.some((op) => op.kind === "rect" && op.paint === "loop")).toBe(false);
    expect(lines(ops, "loop")).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/tab/layout.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './layout'`.

- [ ] **Step 3: Write the layout**

Create `web/src/tab/layout.ts`:

```typescript
/**
 * The tab strip as a list of things to draw. Pure: the same song, time,
 * viewport and loop always give the same list, so everything worth testing
 * about the strip is tested here, and TabStrip only paints.
 *
 * Position is linear in song seconds (ADR 0002): a bad beat grid moves the
 * bar lines and nothing else.
 */
import { emphasis, type Passage } from "../confidence";
import type { LoopPoints } from "../playback/engine";
import type { Song } from "../song";

/** Song seconds to pixels. At 0.5× the strip scrolls half as fast. */
export const PX_PER_SEC = 150;
/** The playhead's place, as a fraction of the width. Right of it is look-ahead. */
export const PLAYHEAD_AT = 0.2;
export const EMPTY_MESSAGE = "No notes to show";
export const UNCLEAR_LABEL = "unclear passage";

const PAD = 8;
const ROW = 20;
const STRING_GAP = 18;
const GUTTER = 22; // the string labels' column, drawn over the scrolling notes
const PAST_ALPHA = 0.45;

/** Colours by role. TabStrip maps each to a --tab-* custom property. */
export type Paint =
  | "background"
  | "text"
  | "muted"
  | "accent"
  | "string"
  | "bar"
  | "playhead"
  | "loop"
  | "hidden";

export type Font = "fret" | "fretBold" | "chord" | "chordLarge" | "label" | "message";
export type Align = "left" | "center";

export type DrawOp =
  | { kind: "rect"; x: number; y: number; w: number; h: number; paint: Paint; alpha: number }
  | {
      kind: "line";
      x1: number;
      y1: number;
      x2: number;
      y2: number;
      paint: Paint;
      width: number;
      alpha: number;
    }
  | {
      kind: "text";
      x: number;
      y: number;
      text: string;
      paint: Paint;
      font: Font;
      align: Align;
      alpha: number;
    };

/** CSS pixels. */
export interface Viewport {
  width: number;
  height: number;
}

export interface Rows {
  /** null when there are no sections: the row collapses. */
  sectionY: number | null;
  /** null when there are no chords. */
  chordY: number | null;
  /** By string, 0 the lowest. The highest string is drawn on top. */
  stringY: number[];
  top: number;
  bottom: number;
  /** The strip's height in CSS pixels. */
  height: number;
}

export function rowsOf(song: Song): Rows {
  let y = PAD;
  let sectionY: number | null = null;
  let chordY: number | null = null;
  if (song.sections.length > 0) {
    sectionY = y + ROW / 2;
    y += ROW;
  }
  if (song.chords.length > 0) {
    chordY = y + ROW / 2;
    y += ROW;
  }
  const count = song.tuning.length;
  const top = y + STRING_GAP / 2;
  const stringY = Array.from({ length: count }, (_, s) => top + (count - 1 - s) * STRING_GAP);
  const bottom = top + (count - 1) * STRING_GAP;
  return { sectionY, chordY, stringY, top, bottom, height: bottom + STRING_GAP / 2 + PAD };
}

/**
 * Letter names by string, lowest first. The top string is lowercased when it
 * shares a letter with the bottom one: e … E in standard tuning, while drop D
 * keeps its capital E.
 */
export function stringLabels(tuning: readonly string[]): string[] {
  const labels = tuning.map((name) => /^[A-Ga-g][#b]?/.exec(name)?.[0] ?? name);
  const top = labels.length - 1;
  if (top > 0 && labels[top].toLowerCase() === labels[0].toLowerCase()) {
    labels[top] = labels[top].toLowerCase();
  }
  return labels;
}

export function layout(song: Song, now: number, viewport: Viewport, loop: LoopPoints): DrawOp[] {
  const rows = rowsOf(song);
  const { width, height } = viewport;
  const playheadX = width * PLAYHEAD_AT;
  const x = (t: number) => playheadX + (t - now) * PX_PER_SEC;
  const from = now - playheadX / PX_PER_SEC;
  const to = now + (width - playheadX) / PX_PER_SEC;
  const onScreen = (start: number, end: number) => start <= to && end >= from;
  const hidden = song.hidden.filter((p) => onScreen(p.from, p.to));
  const isHidden = (t: number) => hidden.some((p) => p.from <= t && t <= p.to);
  const bandTop = rows.top - STRING_GAP / 2;
  const bandHeight = rows.bottom - rows.top + STRING_GAP;
  const ops: DrawOp[] = [];

  // The loop, under everything else.
  const { a, b } = loop;
  if (a !== null && b !== null) {
    const [lo, hi] = [Math.min(a, b), Math.max(a, b)];
    ops.push(rect(x(lo), 0, (hi - lo) * PX_PER_SEC, height, "loop", 0.15));
  }
  for (const [name, at] of [["A", a], ["B", b]] as const) {
    if (at === null) continue;
    ops.push(line(x(at), 0, x(at), height, "loop", 2));
    ops.push(text(x(at) + 4, PAD, name, "loop", "label"));
  }

  for (const y of rows.stringY) ops.push(line(0, y, width, y, "string"));

  for (const beat of song.beats) {
    if (beat.beat !== 1 || !onScreen(beat.t, beat.t)) continue;
    ops.push(line(x(beat.t), rows.top - 4, x(beat.t), rows.bottom + 4, "bar"));
  }

  for (const passage of hidden) {
    ops.push(rect(x(passage.from), bandTop, x(passage.to) - x(passage.from), bandHeight, "hidden", 0.85));
    const chordOver = song.chords.some((c) => overlaps(c.t, c.t + c.dur, passage));
    if (!chordOver) {
      const middle = (x(passage.from) + x(passage.to)) / 2;
      ops.push(text(middle, (rows.top + rows.bottom) / 2, UNCLEAR_LABEL, "muted", "label", "center"));
    }
  }

  for (const note of song.cursor.window(from, to)) {
    const y = rows.stringY[note.string];
    if (y === undefined || isHidden(note.t)) continue;
    const end = note.t + note.dur;
    const sounding = note.t <= now && now <= end;
    const alpha = (end < now ? PAST_ALPHA : 1) * emphasis(note.confidence);
    const fret = String(note.fret);
    const knockout = fret.length * 7 + 4; // so the string does not strike through it
    ops.push(line(x(note.t), y, x(end), y, sounding ? "accent" : "muted", 3, 0.3 * alpha));
    ops.push(rect(x(note.t) - knockout / 2, y - 7, knockout, 14, "background"));
    ops.push(
      text(x(note.t), y, fret, sounding ? "accent" : "text", sounding ? "fretBold" : "fret", "center", alpha),
    );
  }

  if (rows.chordY !== null) {
    for (const chord of song.chords) {
      if (!onScreen(chord.t, chord.t + chord.dur)) continue;
      // Over a hidden passage the chord is all there is to read, so it is
      // larger; its own confidence still sets its strength.
      const large = hidden.some((p) => overlaps(chord.t, chord.t + chord.dur, p));
      const left = Math.max(x(chord.t), GUTTER) + 2;
      const font = large ? "chordLarge" : "chord";
      ops.push(text(left, rows.chordY, chord.symbol, "text", font, "left", emphasis(chord.confidence)));
    }
  }

  if (rows.sectionY !== null) {
    for (const section of song.sections) {
      if (!onScreen(section.t, section.t + section.dur)) continue;
      const left = Math.max(x(section.t), GUTTER) + 2;
      ops.push(text(left, rows.sectionY, section.label, "muted", "label"));
    }
  }

  if (song.notes.length === 0) {
    ops.push(text(width / 2, (rows.top + rows.bottom) / 2, EMPTY_MESSAGE, "muted", "message", "center"));
  }

  ops.push(rect(0, bandTop, GUTTER, bandHeight, "background"));
  stringLabels(song.tuning).forEach((label, s) => {
    ops.push(text(GUTTER / 2, rows.stringY[s], label, "muted", "label", "center"));
  });

  ops.push(line(playheadX, 0, playheadX, height, "playhead", 2));
  return ops;
}

function overlaps(start: number, end: number, passage: Passage): boolean {
  return start < passage.to && end > passage.from;
}

function rect(x: number, y: number, w: number, h: number, paint: Paint, alpha = 1): DrawOp {
  return { kind: "rect", x, y, w, h, paint, alpha };
}

function line(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  paint: Paint,
  width = 1,
  alpha = 1,
): DrawOp {
  return { kind: "line", x1, y1, x2, y2, paint, width, alpha };
}

function text(
  x: number,
  y: number,
  value: string,
  paint: Paint,
  font: Font,
  align: Align = "left",
  alpha = 1,
): DrawOp {
  return { kind: "text", x, y, text: value, paint, font, align, alpha };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/tab/layout.test.ts`
Expected: PASS, 19 tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/tab/layout.ts web/src/tab/layout.test.ts
git commit -m "feat(web): lay out the tab strip as a pure draw list

Notes are placed linearly in song seconds under a fixed playhead, so a
bad beat grid moves only the bar lines. Rows collapse when their track is
empty, notes fade by confidence, and hidden passages show no fret numbers.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The api client, and one reason → text map

Every call returns a typed result or rejects with an `ApiError` that carries a `Reason`. `messages.ts` is typed `Record<Reason, Message>` against the generated `ErrorDetail["reason"]`. A reason added on the server therefore regenerates `api.ts`, and `tsc` fails until the new reason has text. `unreachable` is the client's own reason, for a request that got no answer from the api.

**Files:**
- Create: `web/src/api/messages.ts`, `web/src/api/client.ts`, `web/src/api/client.test.ts`
- Create: `web/src/test/fakeXhr.ts`, `web/src/test/jobs.ts`

**Interfaces:**
- Consumes: `JobView` and `ErrorDetail` from `web/src/types/api.ts` (Task 1); `TabDocument`.
- Produces, from `api/messages.ts`:
  - `type ServerReason = ErrorDetail["reason"]` and `type Reason = ServerReason | "unreachable"`;
  - `interface Message { headline; action }`;
  - `MESSAGES: Record<Reason, Message>` and `isReason(value): value is Reason`.
- Produces, from `api/client.ts`:
  - `MAX_UPLOAD_BYTES`;
  - `class ApiError extends Error { status: number | null; reason: Reason }`;
  - `type Fetch` and `interface Upload { job: JobView; created: boolean }`;
  - `getJob(jobId, fetcher?)` and `getDocument(jobId, fetcher?)`;
  - `createJob(file, onProgress?)`, which goes through `XMLHttpRequest`;
  - `errorFrom(status, body): ApiError`.
- Produces, from the test helpers: `FakeXhr` and `lastXhr()`; `JOB_ID`, `jobView(fields?)` and `errorBody(reason, message?)`.

- [ ] **Step 1: Write the test helpers**

Create `web/src/test/fakeXhr.ts`:

```typescript
/** An XMLHttpRequest for tests: records the request, answers when told. */
export class FakeXhr {
  static last: FakeXhr | null = null;

  method = "";
  url = "";
  readonly headers: Record<string, string> = {};
  body: unknown = null;
  status = 0;
  responseText = "";
  readonly upload: {
    onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null;
  } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeXhr.last = this;
  }

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }

  send(body: unknown): void {
    this.body = body;
  }

  progress(loaded: number, total: number): void {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }

  respond(status: number, body: unknown): void {
    this.status = status;
    this.responseText = typeof body === "string" ? body : JSON.stringify(body);
    this.onload?.();
  }

  fail(): void {
    this.onerror?.();
  }
}

/** The FakeXhr the code under test created, which must exist. */
export function lastXhr(): FakeXhr {
  if (FakeXhr.last === null) throw new Error("no XMLHttpRequest was made");
  return FakeXhr.last;
}
```

Create `web/src/test/jobs.ts`:

```typescript
/** JobViews for tests, shaped by the generated api types. */
import type { JobView } from "../types/api";

export const JOB_ID = "5f0c6c2e-0000-4000-8000-000000000001";

export function jobView(fields: Partial<JobView> = {}): JobView {
  return {
    id: JOB_ID,
    status: "queued",
    stage: null,
    percent: 0,
    attempts: 0,
    title: "Song",
    duration_sec: 13.871,
    failure: null,
    created_at: "2026-10-08T12:00:00Z",
    updated_at: "2026-10-08T12:00:00Z",
    ...fields,
  };
}

export function errorBody(reason: string, message = "From the api."): unknown {
  return { error: { reason, message } };
}
```

- [ ] **Step 2: Write the failing tests**

Create `web/src/api/client.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FakeXhr, lastXhr } from "../test/fakeXhr";
import { JOB_ID, errorBody, jobView } from "../test/jobs";
import {
  ApiError,
  MAX_UPLOAD_BYTES,
  createJob,
  errorFrom,
  getDocument,
  getJob,
  type Fetch,
} from "./client";
import { MESSAGES, isReason, type Reason } from "./messages";

function answering(status: number, body: unknown): Fetch {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  return async () => new Response(text, { status });
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("expected the call to reject");
}

describe("errorFrom", () => {
  it.each<[number, string, Reason]>([
    [404, "not_found", "not_found"],
    [409, "not_ready", "not_ready"],
    [413, "too_large", "too_large"],
    [422, "unsupported_format", "unsupported_format"],
    [429, "too_many_jobs", "too_many_jobs"],
    [500, "internal", "internal"],
    [503, "internal", "internal"],
  ])("maps a %i carrying %s", (status, sent, reason) => {
    const error = errorFrom(status, JSON.stringify(errorBody(sent, "Words.")));

    expect(error).toMatchObject({ status, reason, message: "Words." });
  });

  it("treats an answer without the api's error body as no answer", () => {
    expect(errorFrom(502, "<html>Bad gateway</html>").reason).toBe("unreachable");
    expect(errorFrom(500, "").reason).toBe("unreachable");
  });

  it("reads a bare 413 from a proxy as too large", () => {
    expect(errorFrom(413, "<html>Request Entity Too Large</html>").reason).toBe("too_large");
  });

  it("reads a reason this build does not know as internal, keeping the message", () => {
    const error = errorFrom(500, JSON.stringify(errorBody("brand_new", "Newer words.")));

    expect(error).toMatchObject({ reason: "internal", message: "Newer words." });
  });
});

describe("getJob and getDocument", () => {
  it("return what the api sent", async () => {
    await expect(getJob(JOB_ID, answering(200, jobView()))).resolves.toEqual(jobView());
    await expect(getDocument(JOB_ID, answering(200, { notes: [] }))).resolves.toEqual({
      notes: [],
    });
  });

  it("ask for the job's own paths", async () => {
    const paths: string[] = [];
    const recording: Fetch = async (path) => {
      paths.push(path);
      return new Response("{}");
    };

    await getJob(JOB_ID, recording);
    await getDocument(JOB_ID, recording);

    expect(paths).toEqual([`/jobs/${JOB_ID}`, `/jobs/${JOB_ID}/document`]);
  });

  it("reject with the mapped reason", async () => {
    const error = await rejection(getJob(JOB_ID, answering(404, errorBody("not_found"))));

    expect(error).toMatchObject({ status: 404, reason: "not_found" });
  });

  it("reject as unreachable when no answer comes back", async () => {
    const offline: Fetch = async () => {
      throw new TypeError("Failed to fetch");
    };

    const error = await rejection(getJob(JOB_ID, offline));

    expect(error).toMatchObject({ status: null, reason: "unreachable" });
  });
});

describe("createJob", () => {
  beforeEach(() => {
    FakeXhr.last = null;
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const song = () => new File([new Uint8Array([1, 2, 3])], "song.mp3", { type: "audio/mpeg" });

  it("posts the file as the `file` field", () => {
    void createJob(song());

    const xhr = lastXhr();
    expect([xhr.method, xhr.url]).toEqual(["POST", "/jobs"]);
    expect(xhr.body).toBeInstanceOf(FormData);
    expect((xhr.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("resolves a new job on 202 and an existing one on 200", async () => {
    const created = createJob(song());
    lastXhr().respond(202, jobView());
    const existing = createJob(song());
    lastXhr().respond(200, jobView({ status: "succeeded" }));

    await expect(created).resolves.toEqual({ job: jobView(), created: true });
    await expect(existing).resolves.toMatchObject({ created: false });
  });

  it("surfaces upload progress", () => {
    const fractions: number[] = [];
    void createJob(song(), (fraction) => fractions.push(fraction));

    lastXhr().progress(25, 100);
    lastXhr().progress(100, 100);

    expect(fractions).toEqual([0.25, 1]);
  });

  it("rejects with the mapped reason", async () => {
    const upload = createJob(song());
    lastXhr().respond(429, errorBody("too_many_jobs"));

    expect(await rejection(upload)).toMatchObject({ status: 429, reason: "too_many_jobs" });
  });

  it("rejects as unreachable on a network error", async () => {
    const upload = createJob(song());
    lastXhr().fail();

    expect(await rejection(upload)).toMatchObject({ status: null, reason: "unreachable" });
  });

  it("refuses a file over the limit without sending it", async () => {
    const big = song();
    Object.defineProperty(big, "size", { value: MAX_UPLOAD_BYTES + 1 });

    expect(await rejection(createJob(big))).toMatchObject({ reason: "too_large" });
    expect(FakeXhr.last).toBeNull();
  });
});

describe("MESSAGES", () => {
  it("gives every reason a headline and an action", () => {
    for (const [reason, message] of Object.entries(MESSAGES)) {
      expect(isReason(reason)).toBe(true);
      expect(message.headline.length).toBeGreaterThan(0);
      expect(message.action.length).toBeGreaterThan(0);
    }
    expect(Object.keys(MESSAGES)).toHaveLength(10); // nine from the api, plus unreachable
    expect(isReason("toString")).toBe(false);
  });
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `npm --prefix web test -- src/api/client.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './client'` and `'./messages'`.

- [ ] **Step 4: Write the messages**

Create `web/src/api/messages.ts`:

```typescript
/**
 * The one map from a failure reason to what the user reads.
 *
 * Typed against the generated api types: a reason added on the server
 * regenerates src/types/api.ts, and this file then fails to compile until the
 * new reason has text. That is the mechanism behind CONVENTIONS' "adding a
 * reason means updating the UI mapping".
 */
import type { ErrorDetail } from "../types/api";

/** Every reason the api can send. */
export type ServerReason = ErrorDetail["reason"];
/** Those, plus the client's own: a request that got no answer from the api. */
export type Reason = ServerReason | "unreachable";

export interface Message {
  headline: string;
  action: string;
}

export const MESSAGES: Record<Reason, Message> = {
  unsupported_format: {
    headline: "We couldn't read that file as audio.",
    action: "Try an MP3, WAV, FLAC or M4A file.",
  },
  no_guitar_detected: {
    headline: "We couldn't hear a guitar in that song.",
    action: "Try a song where the guitar is clearly audible.",
  },
  too_long: {
    headline: "That recording is too long.",
    action: "Upload a single song, up to ten minutes long.",
  },
  fetch_failed: {
    headline: "We couldn't fetch that audio.",
    action: "Upload the file itself instead.",
  },
  internal: {
    headline: "Something went wrong on our side.",
    action: "Try again in a few minutes.",
  },
  too_large: {
    headline: "That file is too large.",
    action: "Upload a smaller file. A compressed format such as MP3 helps.",
  },
  too_many_jobs: {
    headline: "You already have songs processing.",
    action: "Wait for one to finish, then try again.",
  },
  not_found: {
    headline: "We couldn't find that song.",
    action: "Upload it again.",
  },
  not_ready: {
    headline: "That song isn't ready yet.",
    action: "Wait a moment, then reload the page.",
  },
  unreachable: {
    headline: "We couldn't reach GuitarVis.",
    action: "Check your connection, then try again.",
  },
};

export function isReason(value: unknown): value is Reason {
  return typeof value === "string" && Object.hasOwn(MESSAGES, value);
}
```

- [ ] **Step 5: Write the client**

Create `web/src/api/client.ts`:

```typescript
/**
 * The api, from the browser. Every call resolves to a typed result or
 * rejects with an ApiError carrying a Reason, never a bare string.
 *
 * Paths are relative: the client is served from the api's origin (in
 * development, through the Vite proxy), so there is no CORS.
 */
import type { JobView } from "../types/api";
import type { TabDocument } from "../types/tabDocument";
import { isReason, type Reason } from "./messages";

/** Mirrors the api's default GUITARVIS_MAX_UPLOAD_MB, so a file far too big
 * is refused before it is sent. The api's own limit still decides. */
export const MAX_UPLOAD_BYTES = 150 * 1024 * 1024;

export class ApiError extends Error {
  /** The HTTP status, or null when no answer came back. */
  readonly status: number | null;
  readonly reason: Reason;

  constructor(status: number | null, reason: Reason, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.reason = reason;
  }
}

export type Fetch = (path: string, init?: RequestInit) => Promise<Response>;

const browserFetch: Fetch = (path, init) => fetch(path, init);

export interface Upload {
  job: JobView;
  /** False when the api already had this file: 200 rather than 202. */
  created: boolean;
}

export async function getJob(jobId: string, fetcher: Fetch = browserFetch): Promise<JobView> {
  return (await getJson(`/jobs/${encodeURIComponent(jobId)}`, fetcher)) as JobView;
}

export async function getDocument(
  jobId: string,
  fetcher: Fetch = browserFetch,
): Promise<TabDocument> {
  return (await getJson(`/jobs/${encodeURIComponent(jobId)}/document`, fetcher)) as TabDocument;
}

/**
 * POST /jobs. Through XMLHttpRequest, not fetch: only XHR reports upload
 * progress, and a WAV can be tens of megabytes.
 */
export function createJob(
  file: File,
  onProgress: (fraction: number) => void = () => {},
): Promise<Upload> {
  if (file.size > MAX_UPLOAD_BYTES) {
    // Sent anyway, the api would refuse it early and close the connection,
    // and some browsers report that as a network error, not as a 413.
    return Promise.reject(new ApiError(413, "too_large", "That file is over the upload limit."));
  }
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/jobs");
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
    };
    xhr.onerror = () => reject(noAnswer());
    xhr.onabort = () => reject(noAnswer());
    xhr.onload = () => {
      if (xhr.status !== 200 && xhr.status !== 202) {
        reject(errorFrom(xhr.status, xhr.responseText));
        return;
      }
      try {
        resolve({ job: JSON.parse(xhr.responseText) as JobView, created: xhr.status === 202 });
      } catch {
        reject(new ApiError(xhr.status, "unreachable", "The answer was not JSON."));
      }
    };
    const form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  });
}

/**
 * The ApiError for an error response. The api always answers with its error
 * body. A response without one came from something in between, a proxy
 * with the api down, say, so it counts as no answer from the api, except a
 * bare 413, which any proxy may send for an oversized upload.
 */
export function errorFrom(status: number, body: string): ApiError {
  const detail = errorDetail(body);
  if (detail !== null) {
    // A reason this build does not know (a newer api) reads as internal.
    const reason = isReason(detail.reason) ? detail.reason : "internal";
    return new ApiError(status, reason, detail.message);
  }
  if (status === 413) return new ApiError(status, "too_large", "That file is too large.");
  return new ApiError(status, "unreachable", `No answer from the api (HTTP ${status}).`);
}

async function getJson(path: string, fetcher: Fetch): Promise<unknown> {
  let response: Response;
  let body: string;
  try {
    response = await fetcher(path, { headers: { Accept: "application/json" } });
    body = await response.text();
  } catch {
    throw noAnswer();
  }
  if (!response.ok) throw errorFrom(response.status, body);
  try {
    return JSON.parse(body);
  } catch {
    throw new ApiError(response.status, "unreachable", "The answer was not JSON.");
  }
}

function noAnswer(): ApiError {
  return new ApiError(null, "unreachable", "No answer from the server.");
}

function errorDetail(body: string): { reason: string; message: string } | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || !("error" in parsed)) return null;
  const error: unknown = parsed.error;
  if (typeof error !== "object" || error === null) return null;
  if (!("reason" in error) || !("message" in error)) return null;
  const { reason, message } = error;
  return typeof reason === "string" && typeof message === "string" ? { reason, message } : null;
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/api/client.test.ts`
Expected: PASS, 21 tests.

- [ ] **Step 7: Check that the map is enforced**

Temporarily delete the `not_ready` entry from `MESSAGES`, then run `npm --prefix web run typecheck`.
Expected: `error TS2741: Property 'not_ready' is missing`. Restore the entry and rerun: no errors.

- [ ] **Step 8: Commit**

```bash
git add web/src/api web/src/test/fakeXhr.ts web/src/test/jobs.ts
git commit -m "feat(web): the api client and the one reason-to-text map

getJob, getDocument and createJob resolve to typed results or reject
with an ApiError carrying a Reason. MESSAGES is a Record over the
generated reason type, so a new server reason fails tsc until it has
text. An answer that is not the api's error body counts as no answer.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Routing and the upload page

There are two routes and no router library. The upload page takes a dropped or picked file, posts it with progress, and goes to `/songs/{id}`. That happens for a new job (202) and for one the api already had (200). Refusals show their mapped headline and action. The page tests are the first that need a DOM, so this task adds jsdom and Testing Library.

**Files:**
- Modify: `web/package.json`, `web/package-lock.json` (three dev dependencies)
- Create: `web/src/routing.ts`, `web/src/routing.test.ts`
- Create: `web/src/pages/Failure.tsx`, `web/src/pages/UploadPage.tsx`, `web/src/pages/UploadPage.test.tsx`

**Interfaces:**
- Consumes: `createJob`, `ApiError` and `Upload` (Task 10); `MESSAGES` and `Reason` (Task 10); `jobView` and `JOB_ID` (Task 10).
- Produces:
  - `type Route = { page: "upload" } | { page: "song"; jobId } | { page: "missing" }`.
  - `routeOf(pathname)`, `songPath(jobId)`, `navigate(path)`, `followLink(event)` (an `onClick` for `<a>`), and `useRoute()`.
  - `<Failure reason detail? />` and `<UploadAnother label? />`.
  - `<UploadPage upload? />`, where `upload` defaults to `createJob`.

- [ ] **Step 1: Add the DOM test dependencies**

```bash
npm --prefix web install --save-dev jsdom@^29.1.1 @testing-library/react@^16.3.3 @testing-library/dom@^10.4.2
```

Expected: `package.json` gains the three entries under `devDependencies`, and `package-lock.json` changes. Not jsdom 30: it needs Node 22.22. Vitest's `globals: true` (already set in `vite.config.ts`) lets Testing Library clean up after each test by itself.

- [ ] **Step 2: Write the failing tests**

Create `web/src/routing.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { routeOf, songPath } from "./routing";

describe("routeOf", () => {
  it("knows the two pages", () => {
    expect(routeOf("/")).toEqual({ page: "upload" });
    expect(routeOf("/songs/abc-123")).toEqual({ page: "song", jobId: "abc-123" });
    expect(routeOf("/songs/abc-123/")).toEqual({ page: "song", jobId: "abc-123" });
  });

  it("calls anything else missing", () => {
    expect(routeOf("/songs/")).toEqual({ page: "missing" });
    expect(routeOf("/songs/a/b")).toEqual({ page: "missing" });
    expect(routeOf("/jobs/abc")).toEqual({ page: "missing" });
    expect(routeOf("/songs/%E0")).toEqual({ page: "missing" });
  });

  it("round-trips a song path", () => {
    expect(routeOf(songPath("a b/c"))).toEqual({ page: "song", jobId: "a b/c" });
  });
});
```

Create `web/src/pages/UploadPage.test.tsx`:

```tsx
// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type Upload } from "../api/client";
import { MESSAGES } from "../api/messages";
import { JOB_ID, jobView } from "../test/jobs";
import { UploadPage } from "./UploadPage";

const song = () => new File([new Uint8Array([1])], "song.mp3", { type: "audio/mpeg" });

function choose(file: File) {
  fireEvent.change(screen.getByLabelText(/choose one/i), { target: { files: [file] } });
}

describe("UploadPage", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("goes to the song's page once the upload is accepted", async () => {
    const upload = vi.fn(async (): Promise<Upload> => ({ job: jobView(), created: true }));
    render(<UploadPage upload={upload} />);

    choose(song());
    await act(async () => {});

    expect(upload).toHaveBeenCalledOnce();
    expect(window.location.pathname).toBe(`/songs/${JOB_ID}`);
  });

  it("takes a dropped file too", async () => {
    const upload = vi.fn(async (): Promise<Upload> => ({ job: jobView(), created: false }));
    render(<UploadPage upload={upload} />);

    fireEvent.drop(screen.getByText(/drop an audio file/i), {
      dataTransfer: { files: [song()] },
    });
    await act(async () => {});

    expect(window.location.pathname).toBe(`/songs/${JOB_ID}`);
  });

  it("shows upload progress", () => {
    render(
      <UploadPage
        upload={(_file, onProgress) => {
          onProgress?.(0.5);
          return new Promise(() => {});
        }}
      />,
    );

    choose(song());

    expect(screen.getByRole("status").textContent).toContain("50%");
  });

  it("shows the mapped text when the api refuses", async () => {
    render(
      <UploadPage
        upload={async () => {
          throw new ApiError(429, "too_many_jobs", "You already have 2 songs processing.");
        }}
      />,
    );

    choose(song());
    await act(async () => {});

    expect(screen.getByText(MESSAGES.too_many_jobs.headline)).toBeTruthy();
    expect(screen.getByText(MESSAGES.too_many_jobs.action)).toBeTruthy();
    expect(window.location.pathname).toBe("/");
  });

  it("calls anything else unreachable", async () => {
    render(
      <UploadPage
        upload={async () => {
          throw new TypeError("boom");
        }}
      />,
    );

    choose(song());
    await act(async () => {});

    expect(screen.getByText(MESSAGES.unreachable.headline)).toBeTruthy();
  });
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `npm --prefix web test -- src/routing.test.ts src/pages/UploadPage.test.tsx`
Expected: FAIL. `tsc` reports `Cannot find module './routing'` and `'./UploadPage'`.

- [ ] **Step 4: Write the routing**

Create `web/src/routing.ts`:

```typescript
/**
 * Two routes, no router library: "/" uploads, "/songs/{jobId}" plays.
 *
 * Client routes never start with /jobs or /health, which the Vite proxy
 * sends to the api, so a page load is never swallowed by the proxy.
 */
import { useSyncExternalStore, type MouseEvent } from "react";

export type Route = { page: "upload" } | { page: "song"; jobId: string } | { page: "missing" };

const NAVIGATED = "guitarvis:navigate";

export function routeOf(pathname: string): Route {
  if (pathname === "/") return { page: "upload" };
  const match = /^\/songs\/([^/]+)\/?$/.exec(pathname);
  if (match === null) return { page: "missing" };
  try {
    return { page: "song", jobId: decodeURIComponent(match[1]) };
  } catch {
    return { page: "missing" }; // a malformed escape, such as %E0
  }
}

export function songPath(jobId: string): string {
  return `/songs/${encodeURIComponent(jobId)}`;
}

export function navigate(path: string): void {
  window.history.pushState(null, "", path);
  window.dispatchEvent(new Event(NAVIGATED));
}

/** onClick for an <a>: navigate in place, unless the user asked for a new tab. */
export function followLink(event: MouseEvent<HTMLAnchorElement>): void {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
    return;
  }
  event.preventDefault();
  navigate(event.currentTarget.getAttribute("href") ?? "/");
}

export function useRoute(): Route {
  return routeOf(useSyncExternalStore(subscribe, () => window.location.pathname));
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(NAVIGATED, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(NAVIGATED, onChange);
  };
}
```

- [ ] **Step 5: Write the failure text and the upload page**

Create `web/src/pages/Failure.tsx`:

```tsx
import { MESSAGES, type Reason } from "../api/messages";
import { followLink } from "../routing";

/** A reason's mapped text, with the server's own words as detail when there are any. */
export function Failure({ reason, detail }: { reason: Reason; detail?: string }) {
  const message = MESSAGES[reason];
  return (
    <div className="failure" role="alert">
      <p className="headline">{message.headline}</p>
      <p>{message.action}</p>
      {detail !== undefined && <p className="detail">{detail}</p>}
    </div>
  );
}

export function UploadAnother({ label = "Upload another song" }: { label?: string }) {
  return (
    <a href="/" onClick={followLink}>
      {label}
    </a>
  );
}
```

Create `web/src/pages/UploadPage.tsx`:

```tsx
import { useState, type DragEvent } from "react";

import { ApiError, createJob } from "../api/client";
import type { Reason } from "../api/messages";
import { navigate, songPath } from "../routing";
import { Failure } from "./Failure";

type Upload =
  | { kind: "idle" }
  | { kind: "sending"; name: string; fraction: number }
  | { kind: "refused"; reason: Reason };

export interface UploadPageProps {
  upload?: typeof createJob;
}

/** Drop or pick a song; POST /jobs; go to its page. A re-upload lands on the
 * existing song, which may already be playable. */
export function UploadPage({ upload = createJob }: UploadPageProps) {
  const [state, setState] = useState<Upload>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);
  const sending = state.kind === "sending";

  const send = (file: File) => {
    if (sending) return;
    setState({ kind: "sending", name: file.name, fraction: 0 });
    upload(file, (fraction) => setState({ kind: "sending", name: file.name, fraction }))
      .then(({ job }) => navigate(songPath(job.id)))
      .catch((error: unknown) =>
        setState({
          kind: "refused",
          reason: error instanceof ApiError ? error.reason : "unreachable",
        }),
      );
  };

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
      {state.kind === "sending" && (
        <p role="status">
          Uploading {state.name} <progress value={state.fraction} max={1} />{" "}
          {Math.round(state.fraction * 100)}%
        </p>
      )}
      {state.kind === "refused" && <Failure reason={state.reason} />}
    </main>
  );
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/routing.test.ts src/pages/UploadPage.test.tsx`
Expected: PASS, 8 tests, with no `act(...)` warnings in the output.

- [ ] **Step 7: Commit**

```bash
git add web/package.json web/package-lock.json web/src/routing.ts web/src/routing.test.ts \
  web/src/pages/Failure.tsx web/src/pages/UploadPage.tsx web/src/pages/UploadPage.test.tsx
git commit -m "feat(web): routing and the upload page

Two routes, / and /songs/{id}, with pushState and no router library.
The upload page posts with progress and goes to the song's page, whether
the api made a new job or already had one. Refusals show their mapped text.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: The player

The player creates one `PlaybackEngine` per song and mounts the views and controls on it. The views are the warnings banner, the canvas tab strip, and the transport, speed, loop and source controls. Keys live on the window: Space plays and pauses, and ← and → seek. The strip's painter is thin, because all its logic is in `layout`. Without a 2D context, as in jsdom, it paints nothing.

**Files:**
- Create: `web/src/player/Warnings.tsx`, `web/src/player/keys.ts`, `web/src/player/Controls.tsx`, `web/src/player/Player.tsx`, `web/src/player/Player.test.tsx`
- Create: `web/src/tab/TabStrip.tsx`

**Interfaces:**
- Consumes: `PlaybackEngine`, `SEEK_STEP_SEC`, `RATES`, `Rate` and `Source` (Task 8); `MediaLike` (Task 7); `Song` and `buildSong` (Task 6); `layout`, `rowsOf`, `DrawOp`, `Paint` and `Font` (Task 9); `FakeMedia` and `JOB_ID` in tests.
- Produces:
  - `<Player song jobId createMedia />`. `createMedia` must be stable across renders.
  - `<Controls engine />`, and `clock(seconds)`, which formats `m:ss`.
  - `<Warnings warnings />`, `useTransportKeys(engine)`, and `<TabStrip song engine />`.
  - The CSS custom properties `--tab-<paint>` that TabStrip reads, which Task 13's `styles.css` defines.

- [ ] **Step 1: Write the failing tests**

Create `web/src/player/Player.test.tsx`:

```tsx
// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildSong } from "../song";
import { FakeMedia } from "../test/fakeMedia";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import { JOB_ID } from "../test/jobs";
import type { TabDocument } from "../types/tabDocument";
import { clock } from "./Controls";
import { Player } from "./Player";

const FIRST_SONG: TabDocument = firstSongJson;

function mount(fields: Partial<TabDocument> = {}, media = new FakeMedia()) {
  const createMedia = () => media;
  render(<Player song={buildSong({ ...FIRST_SONG, ...fields })} jobId={JOB_ID} createMedia={createMedia} />);
  act(() => media.loadMetadata(13.871));
  return media;
}

function press(key: string, target: Element | Window = window) {
  act(() => {
    fireEvent.keyDown(target, { key });
  });
}

describe("Player", () => {
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("plays and pauses from its button", () => {
    const media = mount();

    fireEvent.click(screen.getByRole("button", { name: "Play" }));

    expect(media.paused).toBe(false);
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
  });

  it("sets the speed, and shows which is on", () => {
    const media = mount();

    fireEvent.click(screen.getByRole("button", { name: "0.5×" }));

    expect(media.playbackRate).toBe(0.5);
    expect(screen.getByRole("button", { name: "0.5×" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("offers no speed control where pitch cannot be kept", () => {
    const media = new FakeMedia();
    Reflect.deleteProperty(media, "preservesPitch");
    Reflect.deleteProperty(media, "webkitPreservesPitch");

    mount({}, media);

    expect(screen.queryByRole("group", { name: "Speed" })).toBeNull();
  });

  it("switches to the guitar stem", () => {
    const media = mount();

    fireEvent.click(screen.getByRole("button", { name: "Guitar only" }));

    expect(media.src).toBe(`/jobs/${JOB_ID}/audio/guitar`);
  });

  it("plays and pauses on Space, and seeks on the arrows", () => {
    const media = mount();

    press(" ");
    expect(media.paused).toBe(false);
    press("ArrowRight");
    expect(media.currentTime).toBeCloseTo(5, 1); // plus the moment it has been playing
    press("ArrowLeft");
    expect(media.currentTime).toBeCloseTo(0, 1);
    press(" ");
    expect(media.paused).toBe(true);
  });

  it("leaves keys typed into a text field alone", () => {
    const media = mount();
    const field = document.createElement("input");
    document.body.append(field);

    press(" ", field);
    press("ArrowRight", field);

    expect(media.paused).toBe(true);
    expect(media.currentTime).toBe(0);
    field.remove();
  });

  it("leaves Space to a button that has keyboard focus", () => {
    const media = mount();

    press(" ", screen.getByRole("button", { name: "Guitar only" }));

    expect(media.paused).toBe(true);
  });

  it("keeps a mouse click from leaving focus on a control", () => {
    mount();

    const allowed = fireEvent.mouseDown(screen.getByRole("button", { name: "0.5×" }));

    expect(allowed).toBe(false); // default prevented: the button never takes focus
  });

  it("shows the document's warnings, and nothing when there are none", () => {
    mount({ warnings: ["Chord detection failed, so this tab has no chords."] });
    expect(screen.getByRole("complementary", { name: "Warnings" }).textContent).toContain(
      "Chord detection failed",
    );
  });

  it("shows no warnings box for a clean document", () => {
    mount({ warnings: [] });

    expect(screen.queryByRole("complementary", { name: "Warnings" })).toBeNull();
  });

  it("says when the audio connection is lost", () => {
    const media = mount();

    act(() => {
      for (let i = 0; i < 3; i++) media.emit("error");
    });

    expect(screen.getByRole("alert").textContent).toContain("lost the connection");
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
  });
});

describe("clock", () => {
  it("formats m:ss", () => {
    expect(clock(0)).toBe("0:00");
    expect(clock(65.9)).toBe("1:05");
    expect(clock(Number.NaN)).toBe("0:00");
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/player/Player.test.tsx`
Expected: FAIL. `tsc` reports `Cannot find module './Controls'` and `'./Player'`.

- [ ] **Step 3: Write the warnings banner and the keys**

Create `web/src/player/Warnings.tsx`:

```tsx
/** The document's warnings. A tab the user cannot tell is degraded is worse
 * than one labelled as such. */
export function Warnings({ warnings }: { warnings: readonly string[] }) {
  if (warnings.length === 0) return null;
  return (
    <aside className="warnings" aria-label="Warnings">
      <ul>
        {warnings.map((warning, index) => (
          <li key={index}>{warning}</li>
        ))}
      </ul>
    </aside>
  );
}
```

Create `web/src/player/keys.ts`:

```typescript
import { useEffect } from "react";

import { SEEK_STEP_SEC, type PlaybackEngine } from "../playback/engine";

/**
 * Space plays and pauses; ← and → seek five seconds. The handler sits on the
 * window. It leaves keys aimed at text fields alone, and leaves Space to a
 * focused button or link, which Space activates.
 */
export function useTransportKeys(engine: PlaybackEngine | null): void {
  useEffect(() => {
    if (engine === null) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (takesText(event.target)) return;
      if (event.key === " ") {
        if (activates(event.target)) return;
        event.preventDefault(); // and do not scroll the page
        if (!event.repeat) engine.toggle();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        engine.seekBy(-SEEK_STEP_SEC);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        engine.seekBy(SEEK_STEP_SEC);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [engine]);
}

const NOT_TEXT = new Set(["button", "checkbox", "radio", "range", "submit", "reset", "file"]);

function takesText(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
  return target instanceof HTMLInputElement && !NOT_TEXT.has(target.type);
}

function activates(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLButtonElement ||
    target instanceof HTMLAnchorElement ||
    target instanceof HTMLInputElement
  );
}
```

- [ ] **Step 4: Write the controls**

Create `web/src/player/Controls.tsx`. Every control button prevents the default on mouse down, so a click never leaves focus on it. That is Review Focus 1.

```tsx
import { useSyncExternalStore, type MouseEvent, type ReactNode } from "react";

import {
  RATES,
  SEEK_STEP_SEC,
  type PlaybackEngine,
  type Rate,
  type Source,
} from "../playback/engine";

const SOURCES: Array<[Source, string]> = [
  ["mix", "Full mix"],
  ["guitar", "Guitar only"],
];

/** A clicked button does not keep focus, so Space stays play/pause rather
 * than clicking the last button again. Keyboard focus still works. */
function keepFocus(event: MouseEvent) {
  event.preventDefault();
}

function Button({
  onClick,
  pressed,
  label,
  children,
}: {
  onClick: () => void;
  pressed?: boolean;
  label?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onMouseDown={keepFocus}
      onClick={onClick}
      aria-pressed={pressed}
      aria-label={label}
    >
      {children}
    </button>
  );
}

export function Controls({ engine }: { engine: PlaybackEngine }) {
  const state = useSyncExternalStore(engine.subscribe, engine.getState);
  const { a, b } = state.loop;

  return (
    <div className="controls">
      <div className="group">
        <Button onClick={() => engine.toggle()}>{state.playing ? "Pause" : "Play"}</Button>
        <Button onClick={() => engine.seekBy(-SEEK_STEP_SEC)} label="Back 5 seconds">
          −5 s
        </Button>
        <Button onClick={() => engine.seekBy(SEEK_STEP_SEC)} label="Forward 5 seconds">
          +5 s
        </Button>
        <span className="time">
          {clock(state.time)} / {clock(state.duration)}
        </span>
        {state.buffering && <span role="status">Buffering…</span>}
      </div>

      {engine.canStretch && (
        <div className="group" role="group" aria-label="Speed">
          {RATES.map((rate: Rate) => (
            <Button key={rate} pressed={state.rate === rate} onClick={() => engine.setRate(rate)}>
              {rate}×
            </Button>
          ))}
        </div>
      )}

      <div className="group" role="group" aria-label="Loop">
        <Button pressed={a !== null} onClick={() => engine.setLoopPoint("a")} label="Set loop start">
          A
        </Button>
        <Button pressed={b !== null} onClick={() => engine.setLoopPoint("b")} label="Set loop end">
          B
        </Button>
        <Button onClick={() => engine.clearLoop()} label="Clear loop">
          ×
        </Button>
      </div>

      <div className="group" role="group" aria-label="Audio">
        {SOURCES.map(([source, text]) => (
          <Button
            key={source}
            pressed={state.source === source}
            onClick={() => engine.setSource(source)}
          >
            {text}
          </Button>
        ))}
      </div>

      {state.error === "connection_lost" && (
        <div role="alert">
          <p>We lost the connection to the audio.</p>
          <button type="button" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      )}
    </div>
  );
}

/** m:ss */
export function clock(seconds: number): string {
  const whole = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
```

- [ ] **Step 5: Write the tab strip's painter**

Create `web/src/tab/TabStrip.tsx`:

```tsx
import { useEffect, useRef } from "react";

import type { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import { layout, rowsOf, type DrawOp, type Font, type Paint } from "./layout";

const PAINTS: Paint[] = [
  "background",
  "text",
  "muted",
  "accent",
  "string",
  "bar",
  "playhead",
  "loop",
  "hidden",
];

const FONTS: Record<Font, string> = {
  fret: "13px system-ui, sans-serif",
  fretBold: "bold 14px system-ui, sans-serif",
  chord: "13px system-ui, sans-serif",
  chordLarge: "bold 16px system-ui, sans-serif",
  label: "12px system-ui, sans-serif",
  message: "15px system-ui, sans-serif",
};

type Palette = Record<Paint, string>;

/** Colours come from the --tab-* custom properties in styles.css. */
function readPalette(element: Element): Palette {
  const style = getComputedStyle(element);
  const palette = {} as Palette;
  for (const paint of PAINTS) {
    palette[paint] = style.getPropertyValue(`--tab-${paint}`).trim() || "#888";
  }
  return palette;
}

function paint(
  context: CanvasRenderingContext2D,
  ops: DrawOp[],
  palette: Palette,
  width: number,
  height: number,
): void {
  context.globalAlpha = 1;
  context.fillStyle = palette.background;
  context.fillRect(0, 0, width, height);
  context.textBaseline = "middle";
  for (const op of ops) {
    context.globalAlpha = op.alpha;
    switch (op.kind) {
      case "rect":
        context.fillStyle = palette[op.paint];
        context.fillRect(op.x, op.y, op.w, op.h);
        break;
      case "line":
        context.strokeStyle = palette[op.paint];
        context.lineWidth = op.width;
        context.beginPath();
        context.moveTo(op.x1, op.y1);
        context.lineTo(op.x2, op.y2);
        context.stroke();
        break;
      case "text":
        context.fillStyle = palette[op.paint];
        context.font = FONTS[op.font];
        context.textAlign = op.align;
        context.fillText(op.text, op.x, op.y);
        break;
    }
  }
  context.globalAlpha = 1;
}

/**
 * The scrolling tab: a canvas repainted from the engine's frames. All the
 * logic is in layout(); this only scales for the display and paints. With no
 * 2D context (jsdom, or a browser without canvas) it paints nothing.
 */
export function TabStrip({ song, engine }: { song: Song; engine: PlaybackEngine }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const height = rowsOf(song).height;

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d") ?? null;
    if (canvas === null || context === null) return;

    let width = 0;
    let palette = readPalette(canvas);
    const resize = () => {
      width = canvas.clientWidth;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      palette = readPalette(canvas);
      engine.redraw();
    };
    resize();

    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    observer?.observe(canvas);
    const scheme = window.matchMedia?.("(prefers-color-scheme: dark)");
    scheme?.addEventListener("change", resize);
    const stop = engine.onFrame((t) => {
      paint(context, layout(song, t, { width, height }, engine.getState().loop), palette, width, height);
    });

    return () => {
      stop();
      observer?.disconnect();
      scheme?.removeEventListener("change", resize);
    };
  }, [song, engine, height]);

  return <canvas ref={canvasRef} className="tab-strip" style={{ height }} aria-label="Tab" />;
}
```

- [ ] **Step 6: Write the player**

Create `web/src/player/Player.tsx`:

```tsx
import { useEffect, useState } from "react";

import type { MediaLike } from "../playback/clock";
import { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import { TabStrip } from "../tab/TabStrip";
import { Controls } from "./Controls";
import { useTransportKeys } from "./keys";
import { Warnings } from "./Warnings";

export interface PlayerProps {
  song: Song;
  jobId: string;
  /** Must be stable across renders: a new function makes a new engine. */
  createMedia: () => MediaLike;
}

/** One engine per song; every view subscribes to it. Phase 5's fretboards
 * are more onFrame listeners beside the TabStrip. */
export function Player({ song, jobId, createMedia }: PlayerProps) {
  const [engine, setEngine] = useState<PlaybackEngine | null>(null);

  useEffect(() => {
    const created = new PlaybackEngine({ media: createMedia(), jobId, duration: song.duration });
    setEngine(created);
    return () => created.dispose();
  }, [song, jobId, createMedia]);

  useTransportKeys(engine);

  if (engine === null) return null;
  return (
    <section className="player">
      <Warnings warnings={song.warnings} />
      <TabStrip song={song} engine={engine} />
      <Controls engine={engine} />
    </section>
  );
}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/player/Player.test.tsx`
Expected: PASS, 12 tests. There must be no "Not implemented: HTMLCanvasElement.prototype.getContext" noise, because the tests stub `getContext`.

- [ ] **Step 8: Commit**

```bash
git add web/src/player web/src/tab/TabStrip.tsx
git commit -m "feat(web): the player: tab strip, transport, speed, loop and source

One engine per song. The tab strip paints layout()'s draw list on a
canvas each frame. Space plays and pauses and the arrows seek, except in
text fields. Speed is offered only where the browser can keep pitch.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: The song page, the app, and `make web`

The song page polls the job until it is terminal. Along the way it shows the stage in plain words, the percent, and retries. A failure shows its mapped text, and a success fetches the document, checks its version, builds the `Song` and mounts the player. A failed poll keeps polling, slower, under "Reconnecting…". The client never decides that a job has hung. This task also wires the routes into `App`, adds the styles, and sets up the dev proxy and `make web`. After it, the client runs end to end.

**Files:**
- Create: `web/src/pages/progress.ts`, `web/src/pages/SongPage.tsx`, `web/src/pages/SongPage.test.tsx`
- Modify: `web/src/App.tsx` (whole file below); create `web/src/App.test.tsx`
- Modify: `web/src/main.tsx` (one import); create `web/src/styles.css`, `web/src/vite-env.d.ts`
- Modify: `web/vite.config.ts`, `Makefile`

**Interfaces:**
- Consumes: `getJob`, `getDocument` and `ApiError` (Task 10); `buildSong`, `canRead` and `Song` (Task 6); `Player` (Task 12); `Failure`, `UploadAnother`, `UploadPage`, `useRoute` and `followLink` (Task 11).
- Produces:
  - `POLL_MS = 1500`, `MAX_POLL_MS = 10000` and `MAX_ATTEMPTS = 3`.
  - `stageText(stage)`, `retryText(job)` and `backoff(delay)`.
  - `interface SongApi { getJob; getDocument }` and `<SongPage jobId api? createMedia? />`.
  - `<App />`, and `make web`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/pages/SongPage.test.tsx`:

```tsx
// @vitest-environment jsdom
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { MESSAGES } from "../api/messages";
import { FakeMedia } from "../test/fakeMedia";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import { JOB_ID, jobView } from "../test/jobs";
import type { JobView } from "../types/api";
import type { TabDocument } from "../types/tabDocument";
import { SongPage, type SongApi } from "./SongPage";
import { MAX_POLL_MS, POLL_MS } from "./progress";

const FIRST_SONG: TabDocument = firstSongJson;
const media = new FakeMedia();
const createMedia = () => media;

/** Answers getJob from a script, one entry per poll; the last repeats. */
function scripted(
  answers: Array<JobView | ApiError>,
  document: () => Promise<TabDocument> = async () => FIRST_SONG,
) {
  const calls = { job: 0, document: 0 };
  const api: SongApi = {
    getJob: async () => {
      const answer = answers[Math.min(calls.job, answers.length - 1)];
      calls.job += 1;
      if (answer instanceof ApiError) throw answer;
      return answer;
    },
    getDocument: () => {
      calls.document += 1;
      return document();
    },
  };
  return { api, calls };
}

async function settle() {
  await act(async () => {});
}

async function wait(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function text(): string {
  return document.body.textContent ?? "";
}

describe("SongPage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("moves through queued, running and retrying, then mounts the player", async () => {
    const { api } = scripted([
      jobView({ status: "queued" }),
      jobView({ status: "running", stage: "separation", percent: 12, attempts: 1 }),
      jobView({ status: "running", stage: "transcription", percent: 40, attempts: 2 }),
      jobView({ status: "succeeded", percent: 100, attempts: 2 }),
    ]);
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);

    await settle();
    expect(text()).toContain("Waiting for a worker");
    await wait(POLL_MS);
    expect(text()).toContain("Isolating the guitar — 12%");
    expect(text()).not.toContain("Retrying");
    await wait(POLL_MS);
    expect(text()).toContain("Transcribing notes — 40%");
    expect(text()).toContain("Retrying — attempt 2 of 3");
    await wait(POLL_MS);

    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Guitar only" })).toBeTruthy();
    expect(media.src).toBe(`/jobs/${JOB_ID}/audio/mix`);
  });

  it("stops polling once the job is finished", async () => {
    const { api, calls } = scripted([jobView({ status: "succeeded" })]);
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);
    await settle();

    await wait(POLL_MS * 5);

    expect(calls.job).toBe(1);
    expect(calls.document).toBe(1);
  });

  it("reads an unknown stage as Working", async () => {
    const { api } = scripted([jobView({ status: "running", stage: "mastering", percent: 90 })]);
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);

    await settle();

    expect(text()).toContain("Working — 90%");
  });

  it("shows a failure's mapped text, the server's words, and a way out", async () => {
    const { api } = scripted([
      jobView({
        status: "failed",
        failure: {
          reason: "no_guitar_detected",
          message: "No clear guitar part was found in this recording.",
          stage: "separation",
        },
      }),
    ]);
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);

    await settle();

    expect(text()).toContain(MESSAGES.no_guitar_detected.headline);
    expect(text()).toContain(MESSAGES.no_guitar_detected.action);
    expect(text()).toContain("No clear guitar part was found in this recording.");
    expect(screen.getByRole("link", { name: "Upload another song" })).toBeTruthy();
  });

  it("says when there is no such song", async () => {
    const { api, calls } = scripted([new ApiError(404, "not_found", "There is no job with that id.")]);
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);

    await settle();
    await wait(MAX_POLL_MS);

    expect(text()).toContain(MESSAGES.not_found.headline);
    expect(screen.getByRole("link", { name: "Upload a song" })).toBeTruthy();
    expect(calls.job).toBe(1);
  });

  it("keeps polling, slower, through a lost connection, and recovers", async () => {
    const lost = new ApiError(null, "unreachable", "No answer from the server.");
    const { api, calls } = scripted([
      jobView({ status: "running", stage: "separation", percent: 5 }),
      lost,
      lost,
      jobView({ status: "running", stage: "separation", percent: 30 }),
    ]);
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);
    await settle();

    await wait(POLL_MS);
    expect(text()).toContain("Reconnecting…");
    expect(text()).toContain("Isolating the guitar — 5%"); // the last answer stays up
    await wait(POLL_MS);
    expect(calls.job).toBe(2); // the next poll waits twice as long
    await wait(POLL_MS);
    expect(calls.job).toBe(3);
    await wait(POLL_MS * 4);

    expect(calls.job).toBe(4);
    expect(text()).not.toContain("Reconnecting…");
    expect(text()).toContain("Isolating the guitar — 30%");
  });

  it("refuses a document from a newer schema", async () => {
    const { api } = scripted([jobView({ status: "succeeded" })], async () => ({
      ...FIRST_SONG,
      schema_version: 2,
    }));
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);

    await settle();

    expect(text()).toContain("processed by a newer version of GuitarVis");
    expect(screen.queryByRole("button", { name: "Play" })).toBeNull();
  });

  it("offers a retry when the document will not load", async () => {
    let fail = true;
    const { api } = scripted([jobView({ status: "succeeded" })], async () => {
      if (fail) throw new ApiError(null, "unreachable", "No answer.");
      return FIRST_SONG;
    });
    render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);
    await settle();

    fail = false;
    await act(async () => screen.getByRole("button", { name: "Try again" }).click());

    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
  });
});
```

Create `web/src/App.test.tsx`:

```tsx
// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("shows the upload page at the root", () => {
    render(<App />);

    expect(screen.getByLabelText(/choose one/i)).toBeTruthy();
  });

  it("says when there is no page, and links back without a page load", () => {
    window.history.replaceState(null, "", "/nowhere");
    render(<App />);
    expect(document.body.textContent).toContain("There is no page here.");

    fireEvent.click(screen.getByRole("link", { name: "Upload a song" }));

    expect(window.location.pathname).toBe("/");
    expect(screen.getByLabelText(/choose one/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/pages/SongPage.test.tsx src/App.test.tsx`
Expected: FAIL. `tsc` reports `Cannot find module './SongPage'` and `'./progress'`.

- [ ] **Step 3: Write the progress text and the song page**

Create `web/src/pages/progress.ts`:

```typescript
/** What the song page says while a job runs, and how often it asks. */
import type { JobView } from "../types/api";

export const POLL_MS = 1500;
export const MAX_POLL_MS = 10_000;
/** The api's Retry(max=2): three attempts in all. */
export const MAX_ATTEMPTS = 3;

const STAGES: Record<string, string> = {
  separation: "Isolating the guitar",
  transcription: "Transcribing notes",
  structure: "Finding the beat and chords",
  fretboard: "Working out fingerings",
};

/** `stage` is a plain string in the api, so an unknown one reads "Working". */
export function stageText(stage: string | null): string {
  return (stage !== null && STAGES[stage]) || "Working";
}

export function retryText(job: JobView): string | null {
  return job.attempts > 1 ? `Retrying — attempt ${job.attempts} of ${MAX_ATTEMPTS}` : null;
}

/** After a failed poll, wait twice as long, up to MAX_POLL_MS. */
export function backoff(delay: number): number {
  return Math.min(delay * 2, MAX_POLL_MS);
}
```

Create `web/src/pages/SongPage.tsx`. `API` and `newAudio` are module constants on purpose. A default written inline would be a new value on every render, which would restart polling or rebuild the engine each time.

```tsx
import { useEffect, useState } from "react";

import { ApiError, getDocument, getJob } from "../api/client";
import type { MediaLike } from "../playback/clock";
import { Player } from "../player/Player";
import { buildSong, canRead, type Song } from "../song";
import type { JobView } from "../types/api";
import type { TabDocument } from "../types/tabDocument";
import { Failure, UploadAnother } from "./Failure";
import { POLL_MS, backoff, retryText, stageText } from "./progress";

export interface SongApi {
  getJob: (jobId: string) => Promise<JobView>;
  getDocument: (jobId: string) => Promise<TabDocument>;
}

const API: SongApi = { getJob: (id) => getJob(id), getDocument: (id) => getDocument(id) };
const newAudio = (): MediaLike => new Audio();

interface Poll {
  job: JobView | null;
  missing: boolean;
  reconnecting: boolean;
}

/**
 * Poll the job until it is terminal. A failed poll keeps polling, slower.
 * The client never decides a job has hung: a row can sit at a stale percent
 * while RQ waits to retry it, and a job the system really lost is failed by
 * the api's reconciliation, which these reads trigger.
 */
function useJob(jobId: string, api: SongApi): Poll {
  const [poll, setPoll] = useState<Poll>({ job: null, missing: false, reconnecting: false });
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = POLL_MS;
    const check = async () => {
      try {
        const job = await api.getJob(jobId);
        if (cancelled) return;
        delay = POLL_MS;
        setPoll({ job, missing: false, reconnecting: false });
        if (job.status === "succeeded" || job.status === "failed") return;
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && error.reason === "not_found") {
          setPoll({ job: null, missing: true, reconnecting: false });
          return;
        }
        delay = backoff(delay);
        setPoll((previous) => ({ ...previous, reconnecting: true }));
      }
      timer = setTimeout(() => void check(), delay);
    };
    void check();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, api]);
  return poll;
}

type Loaded =
  | { kind: "loading" }
  | { kind: "ready"; song: Song }
  | { kind: "failed" }
  | { kind: "newer" };

function useSong(jobId: string, ready: boolean, api: SongApi): [Loaded, () => void] {
  const [loaded, setLoaded] = useState<Loaded>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    setLoaded({ kind: "loading" });
    api.getDocument(jobId).then(
      (doc) => {
        if (cancelled) return;
        setLoaded(canRead(doc) ? { kind: "ready", song: buildSong(doc) } : { kind: "newer" });
      },
      () => {
        if (!cancelled) setLoaded({ kind: "failed" });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [jobId, ready, api, attempt]);
  return [loaded, () => setAttempt((n) => n + 1)];
}

export interface SongPageProps {
  jobId: string;
  api?: SongApi;
  createMedia?: () => MediaLike;
}

export function SongPage({ jobId, api = API, createMedia = newAudio }: SongPageProps) {
  const { job, missing, reconnecting } = useJob(jobId, api);
  const [loaded, retry] = useSong(jobId, job?.status === "succeeded", api);

  if (missing) {
    return (
      <main className="song-page">
        <Failure reason="not_found" />
        <UploadAnother label="Upload a song" />
      </main>
    );
  }

  return (
    <main className="song-page">
      <h1>{job?.title ?? "Loading…"}</h1>
      {reconnecting && <p role="status">Reconnecting…</p>}
      {job !== null && <JobBody job={job} loaded={loaded} retry={retry} jobId={jobId} createMedia={createMedia} />}
    </main>
  );
}

function JobBody({
  job,
  loaded,
  retry,
  jobId,
  createMedia,
}: {
  job: JobView;
  loaded: Loaded;
  retry: () => void;
  jobId: string;
  createMedia: () => MediaLike;
}) {
  const retrying = retryText(job);
  switch (job.status) {
    case "queued":
      return (
        <div className="progress">
          <p>Waiting for a worker</p>
          {retrying !== null && <p>{retrying}</p>}
        </div>
      );
    case "running":
      return (
        <div className="progress">
          <p>
            {stageText(job.stage)} — {job.percent}%
          </p>
          <progress value={job.percent} max={100} />
          {retrying !== null && <p>{retrying}</p>}
        </div>
      );
    case "failed":
      return (
        <>
          <Failure reason={job.failure?.reason ?? "internal"} detail={job.failure?.message} />
          <UploadAnother />
        </>
      );
    case "succeeded":
      return <Finished loaded={loaded} retry={retry} jobId={jobId} createMedia={createMedia} />;
  }
}

function Finished({
  loaded,
  retry,
  jobId,
  createMedia,
}: {
  loaded: Loaded;
  retry: () => void;
  jobId: string;
  createMedia: () => MediaLike;
}) {
  switch (loaded.kind) {
    case "loading":
      return <p role="status">Loading the tab…</p>;
    case "failed":
      return (
        <div role="alert">
          <p>We couldn't load the tab.</p>
          <button onClick={retry}>Try again</button>
        </div>
      );
    case "newer":
      return (
        <p role="alert">
          This song was processed by a newer version of GuitarVis. Reload the page.
        </p>
      );
    case "ready":
      return <Player song={loaded.song} jobId={jobId} createMedia={createMedia} />;
  }
}
```

- [ ] **Step 4: Route to both pages**

Replace `web/src/App.tsx` with:

```tsx
/**
 * The client: an upload page, and a song page whose views all subscribe to
 * one PlaybackEngine and hold no playback state of their own.
 */
import { UploadAnother } from "./pages/Failure";
import { SongPage } from "./pages/SongPage";
import { UploadPage } from "./pages/UploadPage";
import { followLink, useRoute } from "./routing";

export function App() {
  const route = useRoute();
  return (
    <>
      <header className="masthead">
        <a href="/" onClick={followLink}>
          GuitarVis
        </a>
      </header>
      {route.page === "upload" && <UploadPage />}
      {route.page === "song" && <SongPage key={route.jobId} jobId={route.jobId} />}
      {route.page === "missing" && (
        <main>
          <p>There is no page here.</p>
          <UploadAnother label="Upload a song" />
        </main>
      )}
    </>
  );
}
```

- [ ] **Step 5: Style it**

Create `web/src/styles.css`. Colours are tokens, with a dark set, and the canvas reads the `--tab-*` ones:

```css
/* Colours are tokens. The tab strip's canvas reads the --tab-* ones. */
:root {
  color-scheme: light dark;
  --bg: #fbfaf7;
  --fg: #1f1d1a;
  --muted: #6b665d;
  --accent: #c2410c;
  --border: #d8d3c8;
  --panel: #f1ede4;

  --tab-background: #fbfaf7;
  --tab-text: #1f1d1a;
  --tab-muted: #7a7469;
  --tab-accent: #c2410c;
  --tab-string: #c9c3b6;
  --tab-bar: #9e978a;
  --tab-playhead: #c2410c;
  --tab-loop: #2563eb;
  --tab-hidden: #e7e1d4;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #171614;
    --fg: #ece8df;
    --muted: #a39d91;
    --accent: #fb923c;
    --border: #3a3631;
    --panel: #23211e;

    --tab-background: #171614;
    --tab-text: #ece8df;
    --tab-muted: #a39d91;
    --tab-accent: #fb923c;
    --tab-string: #45403a;
    --tab-bar: #6d675e;
    --tab-playhead: #fb923c;
    --tab-loop: #60a5fa;
    --tab-hidden: #2b2824;
  }
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 16px/1.5 system-ui, sans-serif;
}

main {
  max-width: 1100px;
  margin: 0 auto;
  padding: 16px;
}

.masthead {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.masthead a {
  color: var(--fg);
  font-weight: 700;
  text-decoration: none;
}

.drop-zone {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: center;
  padding: 48px 16px;
  border: 2px dashed var(--border);
  border-radius: 12px;
  background: var(--panel);
  cursor: pointer;
}

.drop-zone.dragging {
  border-color: var(--accent);
}

.failure {
  margin: 16px 0;
  padding: 12px 16px;
  border-left: 4px solid var(--accent);
  background: var(--panel);
}

.failure .headline {
  font-weight: 700;
}

.failure .detail {
  color: var(--muted);
}

.warnings {
  margin-bottom: 12px;
  padding: 8px 16px;
  border-radius: 8px;
  background: var(--panel);
  color: var(--muted);
}

.tab-strip {
  display: block;
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 8px;
}

.controls {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 12px;
}

.controls .group {
  display: flex;
  gap: 4px;
  align-items: center;
}

.controls button {
  min-width: 40px;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel);
  color: var(--fg);
  font: inherit;
  cursor: pointer;
}

.controls button[aria-pressed="true"] {
  border-color: var(--accent);
  color: var(--accent);
}

.time {
  font-variant-numeric: tabular-nums;
  color: var(--muted);
}

progress {
  width: 100%;
  max-width: 400px;
}
```

In `web/src/main.tsx`, import it after `App`:

```typescript
import { App } from "./App";
import "./styles.css";
```

TypeScript 6 refuses a side-effect import it has no declaration for. Create `web/src/vite-env.d.ts`, which gives it Vite's declarations for `*.css`:

```typescript
/// <reference types="vite/client" />
```

- [ ] **Step 6: Proxy the api, and add `make web`**

Replace `web/vite.config.ts` with:

```typescript
// defineConfig comes from vitest/config, not vite: the vite one does not type
// the `test` block, and tsc would reject it.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const API = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    // The api's paths go through to it, so in development the client and the
    // api share an origin: no CORS, and <audio> loads /jobs/{id}/audio/...
    // directly. Client routes live under /songs, never /jobs.
    proxy: { "/jobs": API, "/health": API },
  },
  test: {
    globals: true,
    environment: "node",
  },
});
```

In `Makefile`, add `web` to `.PHONY`:

```make
.PHONY: help install lint format typecheck test test-py test-web \
        schema schema-check check eval eval-data services migrate api worker web clean
```

Then add the target after `worker`:

```make
web: ## Serve the web client on localhost:5173, proxying the api on :8000
	$(NPM) run dev
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/pages/SongPage.test.tsx src/App.test.tsx`
Expected: PASS, 10 tests.

Run: `npm --prefix web test && npm --prefix web run lint && npm --prefix web run build`
Expected: 14 test files and 132 tests pass, ESLint reports nothing, and `vite build` writes `dist/`.

Run: `make check`
Expected: exit 0.

- [ ] **Step 8: Look at it running**

With `make services`, `make api` and `make worker` running, run `make web` in another terminal. Then:

```bash
curl -s localhost:5173/songs/anything | grep -c 'id="root"'   # 1: the SPA fallback
curl -s localhost:5173/health                                  # the api's answer, through the proxy
```

Open `http://localhost:5173/` in a browser, upload a short song, and watch the stages move. If the local api already holds a finished job, open `http://localhost:5173/songs/<its id>`. The first real song's id is in its `source.audio_url`. Press Space, and check that the strip scrolls with the audio. This is a look, not the acceptance run, which is Task 15. Note anything that surprises you for that task.

- [ ] **Step 9: Commit**

```bash
git add web/src/pages/progress.ts web/src/pages/SongPage.tsx web/src/pages/SongPage.test.tsx \
  web/src/App.tsx web/src/App.test.tsx web/src/main.tsx web/src/styles.css \
  web/src/vite-env.d.ts web/vite.config.ts Makefile
git commit -m "feat(web): the song page, the routes, and make web

The song page polls until the job is terminal, shows the stage, percent
and retries, maps failures to text, and mounts the player once the
document is in. A failed poll backs off to 10 s under Reconnecting, and
the client never decides a job has hung. Vite proxies the api, so the
client and the api share an origin.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: ADR 0008, and the docs

No code. ADR 0008 resolves open decision 7, provided Task 15's listening test passes. The docs gain the new command, the second generated contract, the reason-to-text mechanism and the new things that bite. 005's carried findings get marked where this branch closed them.

**Files:**
- Create: `docs/decisions/0008-native-time-stretch.md`
- Modify: `docs/decisions/README.md`, `docs/specs/001-guitarvis-design/spec.md` (one line under open decision 7), `docs/CONVENTIONS.md`, `CLAUDE.md`, `README.md`, `CONTRIBUTING.md`, `docs/specs/005-api-job-queue/review-notes.md`

**Interfaces:** none.

- [ ] **Step 1: Write ADR 0008**

Create `docs/decisions/0008-native-time-stretch.md`:

```markdown
# 0008. Slow-down uses the browser's own time-stretching, on one media element

**Status:** Accepted, provided the listening test in [acceptance.md](../specs/006-tab-view-sync/acceptance.md) passes
**Date:** 2026-10-08
**Spec:** [006-tab-view-sync](../specs/006-tab-view-sync/spec.md#the-audio-path-one-media-element)

## Context

Learners slow a passage down to play along with it, so 0.5× and 0.75× have to
keep the song in tune. The design spec called pitch-preserved slow-down the
largest client-side risk (open decision 7), on the assumption that
`playbackRate` shifts pitch. That is no longer true for media elements:
current browsers time-stretch them natively when `preservesPitch` is set.
Web Audio buffer sources still shift pitch with rate, and would need a phase
vocoder.

## Decision

The `PlaybackEngine` plays through a single `HTMLMediaElement`, with
`preservesPitch` (and `webkitPreservesPitch` where it exists) set, and with
`playbackRate` and `defaultPlaybackRate` set together to 0.5, 0.75 or 1. A
browser that has neither property gets no speed control, rather than audio
at the wrong pitch.

## Consequences

Slow-down costs almost nothing to build, and the clock is the element's own.
In exchange:

- **Switching between the mix and the guitar stem leaves a short gap**, because
  it changes `src`. It is not an instant crossfade.
- **Stretch quality is whatever the browser's algorithm gives.** That is judged
  by ear in acceptance.md, per browser.
- **Output latency is not compensated.**

Revisit if the listening test fails in a browser people need, or if the
toggle gap proves bad. The alternative is Web Audio with both tracks decoded,
behind the same `PlaybackEngine`, so no view changes (see the spec's
*Rejected alternatives*). It brings back the phase vocoder, needs CORS on the
storage bucket, and costs about 170 MB of decoded audio per four-minute song.
```

- [ ] **Step 2: Update the decisions index and the design spec**

In `docs/decisions/README.md`, add to the *Accepted* table:

```markdown
| [0008](0008-native-time-stretch.md) | Slow-down uses the browser's own time-stretching, on one media element |
```

Then delete the *Still open* row that begins `| Pitch-preserved slow-down |`.

In `docs/specs/001-guitarvis-design/spec.md`, under open decision 7 (the paragraph ending "Decide with the audio path in hand."), add a line:

```markdown
   **Resolved by [ADR 0008](../../decisions/0008-native-time-stretch.md):**
   native time-stretching on one media element, per the listening test in
   [006's acceptance notes](../006-tab-view-sync/acceptance.md).
```

In `README.md`'s *Documentation* list, change "including the thirteen decisions still open" to "including the decisions still open".

- [ ] **Step 3: Update `docs/CONVENTIONS.md`**

Replace the Python bullet that begins **Failures carry a typed reason** with:

```markdown
- **Failures carry a typed reason**, never a bare string. `FailureReason` in
  `guitarvis_core.contracts` is the closed set, and `web/src/api/messages.ts`
  maps each member to actionable text. Adding a reason means updating that
  mapping, and `tsc` refuses the build until you do.
```

In *TypeScript*, replace the bullet that begins **Views subscribe to `(tabDocument, currentTime)`** with:

```markdown
- **Views draw from `engine.onFrame(t)` and read the `Song`**, never the raw
  document. They hold no playback state and never talk to sibling views. A
  new view is one more `onFrame` listener, not a refactor.
- **The client and the api share an origin.** Client code uses relative
  paths. `make web` proxies `/jobs` and `/health` to the api, and hosting must
  keep both behind one origin, or add CORS deliberately. Client routes live
  under `/songs/`, never `/jobs/`.
```

Replace the bullet `` `web/src/types/tabDocument.ts` is generated. Never hand-edit it; run `make schema`. `` with:

```markdown
- `web/src/types/tabDocument.ts` and `web/src/types/api.ts` are generated.
  Never hand-edit them; run `make schema`.
- **Confidence thresholds are measured.** `HIDE` and `FULL` in
  `web/src/confidence.ts` come from
  [calibration.md](specs/006-tab-view-sync/calibration.md). After a
  transcriber change, run `make eval ARGS=--full` and revisit them.
```

Add a row to the *Mechanisms over notes* table:

```markdown
| Every failure reason has UI text | `Record<Reason, …>` in `web/src/api/messages.ts`, over the generated `web/src/types/api.ts` |
```

- [ ] **Step 4: Update `CLAUDE.md`**

In *Commands*, insert `` `make web` · `` after `` `make worker` · ``.

In *Build phases*, move `← **next**` from phase 4 to phase 5:

```markdown
4. Web client: tab view and sync
5. 2D fretboard, then 3D guitar ← **next**
```

In *Things that will bite you*, replace the line `` - `web/src/types/tabDocument.ts` is generated. Editing it by hand fails CI. `` with:

```markdown
- `web/src/types/tabDocument.ts` and `web/src/types/api.ts` are generated.
  Editing either by hand fails CI.
```

Then append:

```markdown
- `make web` proxies `/jobs` and `/health` to `localhost:8000`, so the client
  needs `make api` running. The client assumes the api is on its origin.
- Web tests that need a DOM start with `// @vitest-environment jsdom`.
  Everything else runs on `node`. jsdom stays on 29.x until the dev machine's
  Node is 22.22 or later.
- `HIDE` and `FULL` in `web/src/confidence.ts` are measured
  (`docs/specs/006-tab-view-sync/calibration.md`), not tuned by eye.
```

- [ ] **Step 5: Update `README.md` and `CONTRIBUTING.md`**

In `README.md`, replace the *Status* paragraph with:

```markdown
**Status: phase 4 of 6 done.** Upload a song in the browser, watch it
process, and play it back with a scrolling tab strip in sync with the audio:
slowed down, looped, or with the guitar isolated. The 2D fretboard and the
3D guitar (phase 5) are next.
```

In `README.md`'s *Running the service*, add after the block that ends `make worker`:

````markdown
Then the client, in a third terminal:

```bash
make web           # localhost:5173, proxying the api
```

Open `http://localhost:5173`, drop in a song, and wait for the four stages.
Space plays and pauses, and ← and → seek five seconds.
````

In `CONTRIBUTING.md`'s *Commands* table, add after the `make worker` row:

```markdown
| `make web` | Serve the web client on `localhost:5173`, proxying the api |
```

In the same table, change the `make schema` row to read `Regenerate the JSON Schemas and the web types`.

- [ ] **Step 6: Mark 005's findings**

In `docs/specs/005-api-job-queue/review-notes.md`:

- At the end of the bullet that begins **Lost jobs can lock an IP out.**, add: `**Resolved in 006:** at the limit, POST /jobs reconciles every row it counted (JobStore.active_jobs) and counts again.`
- At the end of the bullet that begins **A row can say running while RQ's retry waits.**, add: `**Handled in 006:** the song page never decides a job has hung; it keeps polling, and shows what the api reports.`

- [ ] **Step 7: Verify and commit**

Run: `make check`
Expected: exit 0.

```bash
git add docs/decisions/0008-native-time-stretch.md docs/decisions/README.md \
  docs/specs/001-guitarvis-design/spec.md docs/CONVENTIONS.md CLAUDE.md README.md \
  CONTRIBUTING.md docs/specs/005-api-job-queue/review-notes.md
git commit -m "docs: ADR 0008, and the docs for the web client

Slow-down uses native time-stretching on one media element, which
resolves open decision 7 subject to the listening test. The conventions
gain the reason-to-text mechanism, same-origin hosting and measured
thresholds. CLAUDE.md, the README and CONTRIBUTING gain make web.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Manual acceptance, then the PR

Some checks cannot be automated honestly: syncing by ear, stretch quality per browser, and the offset between the mix and the stem. This task needs your human partner. The agent prepares the page and the services. The person listens and records the results. ADR 0008's resolution depends on the listening test, so the PR does not open until `acceptance.md` is filled in.

**Files:**
- Create: `docs/specs/006-tab-view-sync/acceptance.md`
- Modify: `docs/specs/006-tab-view-sync/plan.md` (tick the checkboxes)

**Interfaces:** none.

- [ ] **Step 1: Write the record to fill in**

Create `docs/specs/006-tab-view-sync/acceptance.md`:

```markdown
# Manual acceptance

**Spec:** [006 — Manual acceptance](spec.md#manual-acceptance)

Checks that cannot be automated honestly. A person runs each one in a
browser against real services, and records the result here before the PR is
opened.

## Setup

- Commit: …
- Machine and OS: …
- Audio output: wired / Bluetooth (which one)
- Songs: title, length and format of each

## End to end

- [ ] Upload from the upload page: the progress bar moves, and the page changes to the song
- [ ] The song page names each of the four stages, with a moving percent
- [ ] Re-uploading the same file lands on the same song
- [ ] At 1×, the tab strip stays in sync by ear across the whole song
- [ ] At 0.5×, the same
- [ ] Mix → guitar → mix while playing keeps the position and keeps playing
- [ ] A and B set a loop that repeats; × clears it
- [ ] Playback still works after the presigned URLs expire: leave a song paused for over 15 minutes, then play and seek

Notes: …

## Speed listening test (ADR 0008)

At 0.75× and 0.5×, on a guitar-heavy passage. "Usable" means you could play
along with it. "Unusable" means smeared or watery enough that you could not.

| Browser | Version | 0.75× | 0.5× | Verdict |
|---|---|---|---|---|
| Chrome | … | … | … | … |
| Firefox | … | … | … | … |
| Safari | … | … | … | untested if no Mac is to hand — not assumed to pass |

## Offset between the mix and the stem

After switching, is the guitar early or late against where it was in the
mix? By roughly how much, and on which file format? …

## Output latency

Does the strip visibly lead the audio? Compare wired output with Bluetooth,
if both are to hand. …
```

- [ ] **Step 2: Bring the services up for your human partner**

```bash
make services && make migrate
```

Then, in separate terminals: `make api`, `make worker` (which needs `uv sync --extra ml`, or the `eval-full` extra from Task 4), and `make web`.

Check that all three answer:

```bash
curl -s localhost:8000/health
curl -s localhost:5173/health
curl -s -o /dev/null -w "%{http_code}\n" localhost:5173/
```

Expected: `"status":"ok"` twice, then `200`.

- [ ] **Step 3: Stop for the listening test**

**Ask your human partner** to run the checks in `acceptance.md` at `http://localhost:5173` and fill it in. Do not fill in any result yourself, and do not mark a browser as passing on their behalf.

When they are done:

- If any browser's verdict is "unusable", the spec says that browser gets no speed control. That is a code change, and a deviation from what ADR 0008 accepts. Raise it with your human partner before going further. Do not open the PR.
- If the strip visibly leads the audio, or the mix/stem offset is audible, record it. The spec's *Risks* names the follow-ups (an offset setting; a pipeline fix). Neither is in this phase.

- [ ] **Step 4: Verify everything**

Run: `GUITARVIS_REQUIRE_SERVICES=1 make check`
Expected: exit 0, with nothing skipped for want of services.

Tick every checkbox in this plan that was done, and leave unticked any that was not. Then commit both files:

```bash
git add docs/specs/006-tab-view-sync/acceptance.md docs/specs/006-tab-view-sync/plan.md
git commit -m "docs: 006's manual acceptance and plan checkboxes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Open the PR**

Pushing and opening a PR are visible to others, so confirm with your human partner first. Then:

Write the body to `tmp/pr-body.md` (`tmp/` is gitignored), from `.github/pull_request_template.md`:

- **Spec:** `docs/specs/006-tab-view-sync/spec.md`.
- *What changed*: one paragraph.
- *Verification*: tick the boxes for what was run, and link `acceptance.md` and `calibration.md`.
- *Deviations from the spec*: copy the section below.

End the body with:

```text
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Then:

```bash
git push -u origin 006-tab-view-sync
gh pr create --base main --title "Tab view and sync (phase 4)" --body-file tmp/pr-body.md
```

Expected: `gh` prints the PR's URL. Give it to your human partner.

---

## Decisions the spec left open

The plan settles these. The PR's *Deviations from the spec* section copies them.

- **`schema-check` excludes `web/src/types/*.test.ts`.** The spec says it widens to "all of `web/src/types/`". That directory also holds the hand-written `tabDocument.test.ts`, so the check covers every generated file there instead.
- **The error body is two models.** `ErrorDetail` (`reason`, `message`) sits inside `ErrorBody` (`error`), so the generated types name the inner object too. The client's `Reason` is `ErrorDetail["reason"] | "unreachable"`.
- **`make eval` prints the thresholds as well as the bands.** `calibration.threshold()` encodes the spec's rule, so Task 4 copies numbers rather than applying the rule by hand. The results file stores the bands only.
- **Any failed poll except a 404 keeps polling, with backoff.** The spec names network errors and 503. A 500 is retried the same way, because the client never decides a job is dead.
- **An error response without the api's error body counts as `unreachable`,** except a bare 413, which counts as `too_large`. A server reason this build does not know reads as `internal`, keeping the server's message.
- **The client refuses a file over 150 MB before sending it** (Review Focus 3). This mirrors the api's default limit. The api's own limit still decides.
- **A loop's points may be set in either order.** The loop is the span between them, and a B at the very end of the song still loops (Review Focus 5).
- **Space is left to a button the user reached by keyboard,** and mouse clicks never leave focus on a control (Review Focus 1).
- **Unknown paths show "There is no page here"**, with a link to upload, rather than the upload page.
- **`Song` holds the tab strip's cursor.** A later view makes its own `NoteCursor` over `song.notes`, because a cursor is stateful.
- **jsdom is 29.x, not 30,** because of the Node 22.22 floor.
