# GuitarVis

Takes a recording of a song, isolates the guitar, transcribes what it plays,
and renders the result as tablature you can play along with — in three synced
views: scrolling tab, a 2D fretboard, and a 3D guitar.

**Status: phase 3 of 6 done.** The pipeline runs end to end and emits real
tablature, and it now runs as a service: upload audio to the api, poll the
job, fetch the tab document and the audio to play it against. The web client
(phase 4) is next.

## How it works

```
upload ──▶ api ──▶ [jobs] ──▶ worker
                                │ separation      (progress 0–40%)
                                │ transcription   (40–65%)
                                │ structure       (65–80%)
                                │ fretboard       (80–100%)
                                ▼
                        tab document ──▶ api ──▶ web
```

Four independent stages, each behind a narrow interface. The last of them —
placing pitches on the neck — is deterministic code rather than a model, so
tablature correctness does not depend on transcription accuracy.

Everything the clients render is one JSON **tab document**, defined once in
`packages/core` and published as a JSON Schema in `schema/`. A future iOS or
desktop client reimplements rendering and nothing else.

## Honest limitations

Polyphonic guitar transcription with string and fret assignment is not a solved
problem. Expect roughly **70–85% note accuracy on clean recordings, and worse
on dense mixes.**

The design answers this rather than hoping it away: confidence is a first-class
field on every note and chord, low-confidence passages render de-emphasised or
fall back to chord symbols, and a stage that fails omits its track instead of
failing the job. A beginner cannot tell a wrong tab from a hard passage, and
will conclude they are bad at guitar — so silent wrongness is the failure mode
the whole design is shaped against.

v1 has no editing, so transcription errors cannot be corrected by hand.

## Layout

| Path | What lives there |
|---|---|
| `packages/core` | The tab document, the stage interfaces, the fretboard invariant |
| `packages/jobs` | The job record, object storage and the queue, shared by the api and the worker |
| `apps/api` | FastAPI. Thin; no ML code, enforced by test |
| `apps/worker` | The pipeline. The only component that needs torch |
| `apps/eval` | GuitarSet evaluation harness |
| `web` | React + TypeScript client |
| `schema` | Generated JSON Schema — the cross-language contract |
| `docs/specs` | One numbered folder per feature: `spec.md`, `plan.md` |
| `docs/decisions` | ADRs, and the backlog of decisions still open |

## Getting started

```bash
make install   # uv sync, npm ci, and wire up the git hooks
make check     # lint, typecheck, test, and the contract drift check
make help      # every command
```

Requires Python 3.12+, Node 22+, [uv](https://docs.astral.sh/uv/), and
Docker for `make services`.

## Running the pipeline

The worker ships a CLI that runs ingestion and all four stages against a
local audio file:

```bash
uv sync --extra ml
uv run guitarvis-worker process song.mp3 -o song.json
```

This needs `ffmpeg` (for duration probing) and, the first time, a download of
the Demucs and basic-pitch model weights. Notes stage 4 cannot place — outside
the neck's range, or in a chord no hand could play — are dropped rather than
given a wrong fret, and the document's warnings say how many.

Demucs stems — hundreds of MB, uncompressed — are written to a temporary
directory that is deleted once the run finishes, rather than next to your
audio file. Since separation dominates runtime, pass `--stems-dir DIR` to
keep them instead — useful for inspecting what Demucs produced, or for
feeding a stem into something else without re-running separation by hand:

```bash
uv run guitarvis-worker process song.mp3 -o song.json --stems-dir ./stems
```

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

Uploading the same file again returns the same job, unless that job failed.
Uploads and stems stay in storage until you run `docker compose down -v`.

## Documentation

- [Design spec](docs/specs/001-guitarvis-design/spec.md) — the whole system,
  including the thirteen decisions still open
- [Contributing](CONTRIBUTING.md) — workflow and commands
- [Conventions](docs/CONVENTIONS.md) — how the code is written
- [Decisions](docs/decisions/) — what was chosen and why

## Licence

MIT. See [LICENSE](LICENSE).
