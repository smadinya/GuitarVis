---
name: eval-harness
description: Use when running GuitarSet evaluation, interpreting note F1 or string accuracy, comparing runs, or considering adding quality checks to CI. Contains the rule that evaluation must never gate the build.
---

# Evaluation harness

Infrastructure, not a nice-to-have. Without it, "swap in a better model later"
is a wish; with it, it is a measurement.

```bash
make eval
```

Writes to `eval/results/`, which is **tracked in git** — the whole value is in
comparing runs over time. It looks generated. It is not disposable, and it must
never be added to `.gitignore`.

## The rule

**Evaluation is measured, never gated.**

`make eval` is unreachable from `make check`, which is the only thing CI runs.
Do not wire it in. Do not add a threshold job. Do not have a workflow read
`eval/results/`.

`apps/eval/tests/test_eval_never_gates_ci.py` enforces one narrow piece of
this mechanically: it fails if any test file under `apps/eval/tests/` — which
`make check` does collect, via `testpaths` in `pyproject.toml` — contains the
literal path `eval/results`. It catches a test written to read that directory
and assert on a metric; it does not catch a threshold added anywhere else
(a workflow file, a script, a test in another package), so it is a tripwire
for the most likely mistake, not a complete guarantee.

A suite that fails because a model got two percent worse on a Tuesday is a
suite people learn to ignore — and then a real failure goes unnoticed.
Correctness is tested and gates the build; quality is measured and does not.
Confusing the two is how a CI suite becomes noise.

If you are about to add a quality check to CI, that is a decision requiring a
new ADR superseding
[`docs/decisions/0004-evaluation-is-measured-not-gated.md`](../../../docs/decisions/0004-evaluation-is-measured-not-gated.md),
not an implementation detail.

## The metrics

| Metric | Meaning |
|---|---|
| **note F1** | An onset within 50ms with the correct pitch counts as a hit |
| **string accuracy** | Of correctly-pitched notes, the share on the right string |
| **chord accuracy** | Frame-wise agreement with the ground-truth chord |

Ground truth is GuitarSet: audio with string and fret annotations, roughly
three hours of clean solo guitar. Held-out set only.

## Reading the numbers honestly

GuitarSet is clean solo guitar. Real material is dense, distorted, and mixed.
Expect production accuracy meaningfully below what the harness reports, and
treat the number as a relative signal between runs rather than a promise to
users. The design spec's 70–85% figure is for clean recordings.

**String accuracy is the one that isolates stage 4.** Note F1 can fall while
string accuracy holds, which means transcription regressed and the
deterministic mapper is fine. The reverse means the mapper's cost weights
changed for the worse.

## Before a model swap

Run the harness on the current model first and commit the result. A swap
without a before-number is not a measurement, and the whole reason the pipeline
is staged is to make that comparison possible.
