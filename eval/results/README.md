# Evaluation results

Tracked metric history. Each run of `make eval` writes a dated file here, and
those files are committed, because the point is comparing runs over time.

One file per run: `<date>-<commit>-<mode>-<split>.json`, where mode is
`oracle` or `full` and split is `test` or `dev`. Only `test` results belong
here; `dev` runs are for tuning and are not committed. A file whose `dirty`
field is `true` measured uncommitted code, and its name ends in `-dirty` so it
never overwrites a clean run. Rerun from a clean tree before committing.

**This directory is deliberately not gitignored.** It looks generated. It is
not disposable.

Metrics, per the design spec:

- **note F1** — an onset within 50ms with the correct pitch counts as a hit.
  Scored on the transcriber's output, before the mapper drops anything.
- **string accuracy** — of correctly-pitched notes, the share placed on the
  right string. In oracle mode a note the mapper dropped counts as wrong.
- **chord accuracy** — frame-wise agreement with the ground-truth chord, on a
  100ms grid. Frames whose chord has no major/minor reading (sus, dim, aug,
  power chords) are left out, since the analyzer cannot name them.

These numbers are measured, never gated. No CI job may read them.
