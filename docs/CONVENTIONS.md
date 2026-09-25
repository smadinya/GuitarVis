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
  `guitarvis_core.contracts` is the closed set, and the UI maps each member to
  actionable text. Adding a reason means updating that mapping.
- **A stage never imports another stage.** Stages take and return plain data;
  the worker orchestrates. If a stage needs to know what ran before it, the
  interface is wrong.
- **Heavy imports go inside the method that uses them**, never at module level.
  Importing a stage must not require the `ml` extra.
- `apps/api` imports nothing from the ML stack. This is enforced by
  `apps/api/tests/test_boundaries.py`, not by good intentions.

## TypeScript

- **One clock.** A `PlaybackEngine` owns the audio element and is the sole
  source of truth for current time.
- **Views subscribe to `(tabDocument, currentTime)` and hold no playback
  state.** They never communicate with sibling views. A fourth view should be a
  new subscriber, not a refactor.
- **Confidence rendering lives in one shared function**, used identically by
  all three views. The rule must not drift between them.
- `web/src/types/tabDocument.ts` is generated. Never hand-edit it; run
  `make schema`.
- Canvas for the tab strip, SVG for the 2D fretboard. A four-minute song has
  thousands of notes, and SVG nodes at that count stutter.

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
  requires bumping `SCHEMA_VERSION`.

## Testing

**Correctness is tested; quality is measured.** Confusing the two produces a CI
suite that fails because a model got two percent worse on a Tuesday, and a
suite people learn to ignore.

- **Tested, and gating CI:** the fretboard mapper and its invariant, tab
  document schema validation and round-tripping, the degradation ladder,
  playback sync against a fake clock, pipeline integration with separation
  stubbed. All deterministic, all CPU, no model weights.
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

Adding a rule to this document without a mechanism is worth doing, but expect
it to decay.
