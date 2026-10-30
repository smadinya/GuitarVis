# Conventions

Rules that outlive any one change. The reasoning lives in
[the design spec](specs/001-guitarvis-design/spec.md); this is the short form.

## Python

- `src/` layout in every package. Distribution names use hyphens
  (`guitarvis-core`), import names use underscores (`guitarvis_core`).
- **mypy is strict on the contract modules** — `tabdoc`, `contracts`,
  `fretboard` — and lenient elsewhere. Exploratory pipeline code should not be
  fought with type errors; the contract should.
- **Failures carry a typed reason**, never a bare string. `FailureReason` in
  `guitarvis_core.contracts` and the api's `HttpReason` together are the closed
  set the api can send (`Reason`, twelve values). `web/src/api/messages.ts` maps
  each of them, and the client's own `unreachable`, to actionable text. Adding
  a reason means updating that mapping, and `tsc` refuses the build until you
  do.
- **A stage never imports another stage.** Stages take and return plain data;
  the worker orchestrates. If a stage needs to know what ran before it, the
  interface is wrong.
- **Heavy imports go inside the method that uses them**, never at module level.
  Importing a stage must not require the `ml` extra.
- `apps/api` imports nothing from the ML stack, and never `guitarvis_worker`:
  it enqueues the worker's entry point by name. This is enforced by
  `apps/api/tests/test_boundaries.py`, not by good intentions.
- **yt-dlp runs only in `guitarvis_fetch.child`**, a process of its own
  (ADR 0010). Nothing else imports `yt_dlp`, and a link failure's words come
  from `guitarvis_fetch.catalog`, never from yt-dlp.
- **Postgres is the record of a job; Redis carries its id** (ADR 0007). Every
  write after a job starts is conditional on the status it expects.

## TypeScript

- **One clock.** A `PlaybackEngine` owns the audio element and is the sole
  source of truth for current time.
- **Views draw from `engine.onFrame(t)` and read the `Song`**, never the raw
  document. They hold no playback state and never talk to sibling views. A
  new view is one more `onFrame` listener, not a refactor.
- **The client and the api share an origin.** Client code uses relative
  paths. `make web` proxies `/jobs`, `/health` and `/features` to the api, and
  hosting must keep all three behind one origin, or add CORS deliberately.
  Client routes live under `/songs/`, never `/jobs/`.
- **Confidence rendering lives in one shared function**, used identically by
  all three views. The rule must not drift between them.
- `web/src/types/tabDocument.ts` and `web/src/types/api.ts` are generated.
  Never hand-edit them; run `make schema`.
- **Confidence thresholds are measured.** `HIDE` and `FULL` in
  `web/src/confidence.ts` come from
  [calibration.md](specs/006-tab-view-sync/calibration.md). After a
  transcriber change, run `make eval ARGS=--full` and revisit them.
- Canvas for the tab strip: a four-minute song has thousands of notes, and
  SVG nodes at that count stutter. The guitar is three.js, which draws both
  the 2D and the 3D view and is loaded lazily.

## The tab document

- **Seconds are authoritative.** Every note carries a wall-clock onset. Bars
  and beats live only in `timing.beats`. Never store a note position as
  bar/beat — a tempo error would then desynchronise playback from audio, which
  is the one thing a play-along app must never do.
- **The note list is flat.** Measures are computed from the beat grid at render
  time.
- **Optional tracks are omittable.** A job that loses chord detection omits the
  chord track; it does not send empty scaffolding, and the client renders the
  fallback.
- Changing a field means running `make schema` and committing both generated
  artifacts. Adding an optional field is additive; removing or retyping one
  requires bumping `SCHEMA_VERSION`. **This asymmetry does not hold for an
  external validator.** `extra="forbid"` makes every model's JSON Schema
  closed (`additionalProperties: false`, plus `Technique` as a closed enum),
  so a client validating a document against a bundled copy of
  `schema/tab-document.schema.json` — rather than against `TabDocument` itself
  — rejects a whole v2 document over one new optional field. Treat an
  additive change as breaking for any consumer of the committed schema file.

## Testing

**Correctness is tested; quality is measured.** Confusing the two produces a CI
suite that fails because a model got two percent worse on a Tuesday, and a
suite people learn to ignore.

- **Tested, and gating CI:** the fretboard mapper and its invariant, tab
  document schema validation and round-tripping, the degradation ladder,
  playback sync against a fake clock, pipeline integration with separation
  stubbed, the job lifecycle, stage caching and the HTTP surface — with the
  store contract suites and one end-to-end test running against real Postgres,
  Redis and RustFS. All deterministic, all CPU, no model weights.
- **Measured, never gating:** the GuitarSet harness, run via `make eval`,
  writing to `eval/results/`.

No CI job may read `eval/results/`.

## Mechanisms over notes

Where a rule matters, it is enforced by something that fails:

| Rule | Mechanism |
|---|---|
| No ML in `api` | `apps/api/tests/test_boundaries.py` |
| No commits on `main` | `.githooks/pre-commit` |
| Generated artifacts stay current | `make schema-check` in CI |
| Every note's fingering matches its pitch | `guitarvis_core.fretboard.check_invariant` |
| Evaluation never gates | `make eval` is unreachable from `make check` |
| api never imports the worker | `apps/api/tests/test_boundaries.py` |
| In-memory store twins behave like the real stores | shared contract suites in `packages/jobs/tests` |
| The migration matches the table the code queries | `packages/jobs/tests/test_migrations.py` |
| CI cannot pass by skipping the integration suite | `packages/jobs/tests/test_services_gate_ci.py` |
| The api never imports yt-dlp | `apps/api/tests/test_boundaries.py` |
| Every link failure has a catalog row, and no message carries yt-dlp's text | `packages/fetch/tests/test_catalog.py` |
| Fetching from YouTube never gates CI | `packages/fetch/tests/test_smoke_never_gates_ci.py` |
| Every failure reason has UI text | `Record<Reason, …>` in `web/src/api/messages.ts`, over the generated `web/src/types/api.ts` |

Adding a rule to this document without a mechanism is worth doing, but expect
it to decay.

`check_invariant` is tested directly (`packages/core/tests/test_fretboard.py`)
and `apps/worker/src/guitarvis_worker/pipeline.py` calls it on every note
stage 4 (`ViterbiFretboardMapper`) emits, raising
`PipelineError(FailureReason.INTERNAL, ...)` on a violation, so it gates the
mapper's real output on every job.
