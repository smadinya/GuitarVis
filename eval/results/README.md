# Evaluation results

Tracked metric history. Each run of `make eval` writes a dated file here, and
those files are committed, because the point is comparing runs over time.

**This directory is deliberately not gitignored.** It looks generated. It is
not disposable.

Metrics, per the design spec:

- **note F1** — an onset within 50ms with the correct pitch counts as a hit
- **string accuracy** — of correctly-pitched notes, the share placed on the
  right string
- **chord accuracy** — frame-wise agreement with the ground-truth chord

These numbers are measured, never gated. No CI job may read them.
