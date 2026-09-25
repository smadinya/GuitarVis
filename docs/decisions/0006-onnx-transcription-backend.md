# 0006. Stage 2 transcribes through ONNX Runtime, not TensorFlow

**Status:** Accepted
**Date:** 2026-09-25
**Spec:** [003-pipeline-skeleton](../specs/003-pipeline-skeleton/spec.md#stage-2s-backend)

## Context

The design spec chose `basic-pitch` as stage 2's starting model: polyphonic,
CPU-runnable, and it emits per-note activation strength that maps to the
confidence field the whole degradation ladder depends on.

It does not install. Version 0.4.0 — still the latest — requires
`tensorflow<2.15.1` unconditionally on Linux at Python ≥3.11, and no cp312
wheel of that TensorFlow exists. Its `onnx` extra adds `onnxruntime` alongside
that pin rather than replacing it, so the extra does not help. This left the
backend undecided through 002 and blocked phase 1.

A spike established three things. The published wheel ships
`saved_models/icassp_2022/nmp.onnx`. `basic_pitch.inference` selects a backend
from what is installed, warning about the ones that are missing rather than
failing. With only `onnxruntime` present, `ICASSP_2022_MODEL_PATH` resolves to
the ONNX model and `predict()` transcribes a polyphonic signal correctly in a
fraction of real time on CPU.

## Decision

Install `basic-pitch` with `tensorflow` removed from the resolved graph by a uv
dependency override, run inference through `onnxruntime`, and force
`resampy>=0.4.3` by the same mechanism — the pinned older resampy imports
`pkg_resources`, which setuptools ≥81 no longer ships.

## Consequences

The workspace stays on Python 3.12 and no TensorFlow enters the tree, so the
worker's dependency footprint is considerably smaller than planned and stage 2
needs no GPU.

The override neutralises TensorFlow's *installation*, not its *resolution*:
`uv.lock` still records the full TensorFlow dependency tree, pinned behind a
`sys_platform == 'never'` marker that is always false. `uv sync` therefore
never installs it, but the lockfile still carries and re-resolves those
entries on every `uv lock` refresh. This is deliberate — it is what makes the
override a lockfile-visible, diffable decision rather than a requirement that
silently vanished — but it means `uv.lock` is not evidence that TensorFlow is
absent from the dependency graph, only from the installed environment.

Two overrides now sit between us and upstream's stated requirements. They are
not pins that fail loudly when wrong: a future resolution could quietly satisfy
the real TensorFlow requirement, or an upstream reorganisation of
`saved_models/` could break model loading at import. Both are worth checking
first whenever stage 2 misbehaves after a dependency change.

Should the override mechanism ever stop working, the fallback is to vendor
`nmp.onnx` and drive onnxruntime directly, accepting that basic-pitch's note
creation logic would have to be reimplemented.
