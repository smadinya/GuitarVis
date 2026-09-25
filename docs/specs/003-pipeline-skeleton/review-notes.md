# Pipeline Skeleton — Carried Findings

A whole-branch review of 003 found these. None blocks the merge; all are
deliberately deferred rather than forgotten. This file exists because the
review's own ledger lives in `.superpowers/`, which is gitignored and will not
survive it. Spec 004 (fretboard mapper) should read this before starting.

- **Test-helper duplication.** `test_ingest.py`, `test_cli.py`, and
  `test_separation.py` each define their own `write_wav`; `test_ingest.py` and
  `test_cli.py` each define their own `requires_ffprobe` marker; and
  `test_cli.py`, `test_pipeline.py`, and `test_transcription.py` each define an
  unrelated `StubTranscriber`. A shared `conftest.py` under `apps/worker/tests`
  is the fix — not attempted here to keep this review's diff scoped to
  behaviour, not test infrastructure.

- **Progress looks frozen during separation.** `_report` only fires after a
  stage completes, and separation dominates runtime (minutes on CPU). A user
  watching the CLI sees `0%` for most of the run, then `separation 40%` all at
  once. Sub-stage progress would need Demucs's own progress output plumbed
  through, which is out of scope here.

- **Stage 4's narrow `except NotImplementedError` must widen deliberately.**
  `pipeline.py` now carries a comment at the point where this bites — a real
  `ViterbiFretboardMapper` implementation can legitimately raise
  `NotImplementedError` for an unsupported case (an exotic tuning, an
  unplayable interval), and the current bare except would swallow that as if
  stage 4 were still a stub.

- **`--tuning` validation covers syntax, not the fretboard invariant.** The
  CLI now rejects a malformed pitch name or a wrong string count, but nothing
  yet checks that a given tuning is physically sane (e.g. wildly overlapping
  or inverted strings). Stage 4 still has to enforce
  `guitarvis_core.fretboard.check_invariant` on its own output regardless of
  what tuning it was handed — this fix narrows the input, it does not replace
  that gate.

- **The ML dependency resolve is platform-asymmetric and undocumented.** On
  Linux, `uv.lock` pins `numpy==1.26.4`; on `darwin`/`x86_64` it resolves
  `numpy` 2.x instead (`librosa` and `scipy` split the same way). Nothing in
  the repo currently explains why, and a Linux/macOS contributor running the
  same test against different numpy major versions is a real place for a
  silent behavioural difference to hide.

- **No real-song end-to-end run has ever been performed.** The dev machine
  this branch was built on has no `ffmpeg`, so `probe_duration` and everything
  downstream of it is untested against actual audio — only against synthetic
  wavs and stubs. The success condition stated in `spec.md` ("a real song
  processed end to end") has not literally been verified yet.

- **`DemucsSeparator(work_dir=None)` still falls back to the audio file's own
  directory.** The CLI always passes `work_dir`, so the fallback is unreachable
  from the shipped entry point — but the phase-3 worker will be the second
  caller, and if it constructs `DemucsSeparator()` bare, stems accumulate beside
  each downloaded job file in a long-lived container. Make `work_dir` a required
  argument when that phase lands; fixing the seven test construction sites and
  the static-conformance assignment is in-scope work there, and was not worth
  churning a merge-ready branch for.

- **The CLI's output write is guarded only by `OSError`.** Everything around the
  pipeline run is now caught and mapped to a typed failure, but a non-`OSError`
  raised by `model_dump_json` or `write_text` would still surface as a traceback.
  Narrow gap, one `except` clause to close.

