# GuitarVis — working notes for Claude

Audio in, guitar tablature out, rendered in three synced views. Four pipeline
stages — separation, transcription, structure, fretboard assignment — each
behind a narrow interface. The client and the pipeline meet at one JSON tab
document.

Start here: [`docs/specs/001-guitarvis-design/spec.md`](docs/specs/001-guitarvis-design/spec.md).

## Commands

`make install` · `make check` · `make test` · `make schema` · `make eval-data` · `make eval` ·
`make services` · `make migrate` · `make api` · `make worker` · `make web` · `make help`

`make check` is what CI runs. Run it before claiming anything works.

## Invariants — do not violate these

1. `pitch_of(string, fret, tuning) == note.midi`, for every note, always.
2. **Seconds are authoritative.** Never store a note position as bar/beat.
3. `apps/api` must not import torch, demucs, basic_pitch, librosa, or numpy —
   nor `guitarvis_worker`, which it reaches only through the queue.
4. **Evaluation never gates CI.** `make eval` stays out of `make check`.
5. After changing `tabdoc.py`, run `make schema` and commit both generated
   artifacts.
6. **Never commit to `main`.** Branch, then open a PR.

## Workflow

Every change starts with a spec folder: `docs/specs/NNN-short-name/` holding
`spec.md` and `plan.md`. The branch is named after the folder. This overrides
any default that would write specs elsewhere — see
`.claude/skills/spec-workflow/`.

## Skills in this repo

| Skill | Read it when |
|---|---|
| `spec-workflow` | Starting any change; writing a spec or plan |
| `tab-document` | Touching `tabdoc.py`, `schema/`, or the generated types |
| `pipeline-stage` | Adding or changing a stage in `apps/worker` |
| `eval-harness` | Running or interpreting the evaluation |

## Build phases

1. Pipeline skeleton (CLI, no UI)
2. Fretboard mapper and evaluation harness
3. API and job queue
4. Web client: tab view and sync
5. 2D fretboard, then 3D guitar ← **next**
6. URL ingestion

Phases 1–2 hold the technical risk. The rest is conventional work.

## Things that will bite you

- The worker's ML dependencies are an optional extra. `uv sync --extra ml`.
- `make eval` needs GuitarSet: run `make eval-data` once (annotations only,
  ~40 MB, into `~/.cache/guitarvis/guitarset`). Full mode needs
  `uv sync --extra eval-full` and `make eval-data ARGS=--audio` (~650 MB).
- Ingestion shells out to `ffprobe`. Without ffmpeg installed, ingest tests
  skip rather than fail — install it to actually run them.
- `web/src/types/tabDocument.ts` and `web/src/types/api.ts` are generated.
  Editing either by hand fails CI.
- Transcription accuracy is 70–85% at best. Degrade, never fail: a broken stage
  omits its track and the job continues. Only "no usable guitar audio" fails a
  job outright.
- Integration tests need `make services` (Postgres, Redis and RustFS, via
  Docker). Without them those tests skip locally; CI sets
  `GUITARVIS_REQUIRE_SERVICES=1`, which turns the skip into a failure. So
  `make check` can pass locally and fail in CI — run `make services` first.
- Object storage is RustFS, not MinIO: MinIO's community images are gone.
  Only `compose.yaml` names the server; the code speaks plain S3.
- Bump `CACHE_VERSION` in `apps/worker/src/guitarvis_worker/caching.py`
  whenever a stage's output for the same input changes. Nothing enforces it.
- `make worker` runs the real stages, so it needs `uv sync --extra ml`.
- `make web` proxies `/jobs` and `/health` to `localhost:8000`, so the client
  needs `make api` running. The client assumes the api is on its origin.
- Web tests that need a DOM start with `// @vitest-environment jsdom`.
  Everything else runs on `node`. jsdom stays on 29.x until the dev machine's
  Node is 22.22 or later.
- `HIDE` and `FULL` in `web/src/confidence.ts` are measured
  (`docs/specs/006-tab-view-sync/calibration.md`), not tuned by eye.
