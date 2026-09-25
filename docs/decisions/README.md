# Architecture decisions

One file per decision. Each records what was chosen and what it costs, and
links the spec section that argued it rather than restating it.

New decisions take the next number and start from [`template.md`](template.md).

## Accepted

| # | Decision |
|---|---|
| [0001](0001-staged-pipeline.md) | Staged pipeline rather than an end-to-end learned tab model |
| [0002](0002-seconds-are-authoritative.md) | Seconds are authoritative; musical position is derived |
| [0003](0003-deterministic-fretboard.md) | Fretboard assignment is deterministic code |
| [0004](0004-evaluation-is-measured-not-gated.md) | Evaluation is measured, never gated |
| [0005](0005-uv-workspace-monorepo.md) | A uv workspace monorepo with a shared core package |
| [0006](0006-onnx-transcription-backend.md) | Stage 2 transcribes through ONNX Runtime, not TensorFlow |

## Still open

From the design spec's
[Open decisions](../specs/001-guitarvis-design/spec.md#open-decisions). Each
names the default v1 takes and what would force a different answer. Resolving
one means writing the next ADR.

| Question | v1 default |
|---|---|
| Chord source: detected from the stem, or derived from notes | Detected from the stem |
| Beat tracker: `librosa` or `madmom` | `librosa` — **`madmom`'s non-commercial clause needs an answer before any commercial launch** |
| Tuning detection | Assume standard tuning |
| Capo detection | Assume no capo; schema slot exists |
| Polyphony ceiling in dense strums | Undecided; needs real output to judge |
| Multiple simultaneous guitar parts | Treated as one part; splitting is out of scope |
| Pitch-preserved slow-down | Undecided; the largest client-side risk |
| 3D guitar asset: procedural or sourced glTF | Procedural |
| Simultaneous 2D and 3D views | One at a time |
| Mobile and responsive scope | Desktop viewport only; bears on the planned iOS app |
| Accounts and persistence | Anonymous, session-scoped |
| Hosting and GPU | Undecided; needed before public users |
| Retention policy for stored copyrighted audio | Undecided; **needed before launch** |
| Schema evolution for external (non-in-repo) validators | Undecided — `extra="forbid"` closes every model's JSON Schema, so an additive optional-field change, safe for in-repo `TabDocument.model_validate` consumers, still breaks a client validating against a bundled copy of `schema/tab-document.schema.json` (e.g. a future iOS app); no compatibility policy exists yet for that case |
