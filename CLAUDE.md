# GuitarVis — working notes for Claude

Audio in, guitar tablature out, rendered in three synced views. Four pipeline
stages — separation, transcription, structure, fretboard assignment — each
behind a narrow interface. The client and the pipeline meet at one JSON tab
document.

Start here: [`docs/specs/001-guitarvis-design/spec.md`](docs/specs/001-guitarvis-design/spec.md).

## Commands

`make install` · `make check` · `make test` · `make schema` · `make eval` ·
`make help`

`make check` is what CI runs. Run it before claiming anything works.

## Invariants — do not violate these

1. `pitch_of(string, fret, tuning) == note.midi`, for every note, always.
2. **Seconds are authoritative.** Never store a note position as bar/beat.
3. `apps/api` must not import torch, demucs, basic_pitch, librosa, or numpy.
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

1. Pipeline skeleton (CLI, no UI) ← **next**
2. Fretboard mapper and evaluation harness
3. API and job queue
4. Web client: tab view and sync
5. 2D fretboard, then 3D guitar
6. URL ingestion

Phases 1–2 hold the technical risk. The rest is conventional work.

## Things that will bite you

- The worker's ML dependencies are an optional extra. `uv sync --extra ml`.
- `web/src/types/tabDocument.ts` is generated. Editing it by hand fails CI.
- Transcription accuracy is 70–85% at best. Degrade, never fail: a broken stage
  omits its track and the job continues. Only "no usable guitar audio" fails a
  job outright.
