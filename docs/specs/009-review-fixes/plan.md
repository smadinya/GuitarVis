# Review Fixes for the 3D Guitar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the thirteen bugs filed against 008: #7, #9, #10 to #20.

**Architecture:** No new modules except `web/src/log.ts`. The worker's
loudness moves after stage 4. The web fixes stay in `web/src/guitar/stage.ts`,
`Guitar.tsx`, `player/GuitarBoundary.tsx`, `player/Player.tsx` and
`playback/engine.ts`.

**Spec:** [spec.md](spec.md) · **Fixes:** [008-3d-guitar](../008-3d-guitar/spec.md)

## Global Constraints

- **Branch `009-review-fixes`.** Never commit to `main`.
- **Test first.** Each fix starts with a test that fails for the issue's
  reason, then the code that makes it pass.
- **One commit per issue, or per pair where one fix needs the other.** The
  message ends `Fixes #N.` In the repo's style: `fix(web): …`,
  `fix(worker): …`, `docs: …`.
- **`make check` is the gate**, after `make services`. While another task's
  edits may be in the tree, run the narrow checks instead: `uv run pytest`,
  `uv run ruff check . && uv run ruff format --check .`, `uv run mypy …` for
  Python, and `npm run test`, `npm run typecheck`, `npm run lint` in `web/`.
- **No change to `tabdoc.py`, `SCHEMA_VERSION` or `CACHE_VERSION`.**
- **No new private OrbitControls field.** `stopMomentum` stays the only one.
- **React never renders at frame rate. The guitar never calls
  `engine.redraw()`. A view never imports another view.** Text lives in
  `web/src/labels.ts`.
- **Errors are logged with `logError` from `web/src/log.ts`**, never
  `console.*` directly. Tests spy on `console.error` and silence it.

## Task 1: Worker loudness (#7, #9)

**Files:** `packages/core/src/guitarvis_core/` (the shared window constant),
`packages/core/src/guitarvis_core/contracts.py`,
`apps/worker/src/guitarvis_worker/loudness.py`, `pipeline.py`,
`stages/fretboard.py`, `caching.py`, and their tests in `apps/worker/tests/`.
Docs: 008's `spec.md` (*Shape of the change*, *Loudness*, *Testing*), the
pipeline-stage skill and 001's degradation table if their wording names the
order.

- [ ] **#7, test.** In `test_loudness.py`, onsets 1.00, 1.04 and 1.08 give two
  groups: {1.00, 1.04} and {1.08}. Run it and watch it fail (one group today).
- [ ] **#7, code.** `_strums` compares each onset with its group's first
  onset. Move the 50 ms window into `guitarvis_core`, and import it in
  `stages/fretboard.py` (in place of `VOICING_WINDOW_SEC`'s definition) and in
  `loudness.py` (in place of `STRUM_WINDOW_SEC`). Fix the docstrings that
  describe chaining.
- [ ] **#7, spec.** Amend 008's *Loudness*, "Strums", with a line
  "Amended by [009](../009-review-fixes/spec.md)". Commit: `Fixes #7.`
- [ ] **#9, test.** In the pipeline tests: a mapper that builds `TabNote`s
  without loudness, as eval's `LowestFretMapper` does, still yields notes with
  loudness in the document. Run it and watch it fail.
- [ ] **#9, code.** `measure_loudness` takes and returns `TabNote`s.
  `run_pipeline` calls it after stage 4, on the mapper's notes, inside the same
  degrade-and-log `try`. `NoteEvent` loses `loudness`. The mapper stops
  copying it. `CachedTranscriber`'s loader drops a `loudness` key from old
  entries, with a test that loads one. Check that the fretboard stage is not
  cached, and that `CACHE_VERSION` therefore stays.
- [ ] **#9, docs.** Update `loudness.py`'s module docstring and
  `contracts.py`'s docstrings. Amend 008's *Shape of the change*, *Loudness*
  ("Where", "Contract") and *Testing* ("the mapper copies loudness"). Update
  the pipeline-stage skill if it says loudness runs before the mapper.
  Commit: `Fixes #9.`
- [ ] `uv run pytest`, ruff and mypy pass.

## Task 2: The camera (#10, #14, #11, #20)

**Files:** `web/src/guitar/stage.ts`, `web/src/guitar/stage.test.ts`,
`docs/specs/008-3d-guitar/acceptance.md`.

- [ ] **#10.** Test: dispatch the controls' `start` and `end` with no
  `change`, resize the box, and expect the home pose for the new aspect. Then
  a `start`, a `change` and an `end`, a resize, and expect the camera kept.
  Code: a `gesture` flag set on `start` and cleared on `end`. `change` sets
  `touched` only while `gesture` is set. `start` still drops the tween.
  Commit: `Fixes #10.`
- [ ] **#14.** Test: `resetView()` after a pan, resize within the 700 ms, run
  the tween out, and expect the new aspect's home. Code: in `resize()`, when
  `!touched`, set `tween.to = this.home()` if a tween runs, else
  `place(this.home())`. Commit: `Fixes #14.`
- [ ] **#11.** Test: stub `devicePixelRatio`, change it, resize, and expect
  `setPixelRatio` with the new value, capped at `MAX_PIXEL_RATIO`. A second
  test fires the `(resolution: …dppx)` query's `change` and expects the same.
  Code: `resize()` calls
  `setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO))`
  before `setSize`. A watcher follows `(resolution: ${ratio}dppx)`, sets
  itself up again for each new ratio, and is undone on dispose.
  Commit: `Fixes #11.`
- [ ] **#20.** Test: in 2D, a shift-, ctrl- and meta-`pointerdown` (mouse,
  left button) then a `pointermove` moves the controls' target. In 3D a
  shift-drag still pans through OrbitControls' own path, unchanged. Code: a
  capture-phase `pointerdown` listener on the canvas's box. In 2D, for a mouse
  press with a modifier held, it calls `stopPropagation()` and dispatches a
  copy on the canvas with `shiftKey`, `ctrlKey` and `metaKey` false. A copy
  has no modifiers, so the listener ignores it. Answer the question in 008's
  `acceptance.md` ("fixed by 009"). Commit: `Fixes #20.`
- [ ] `npm run test`, `npm run typecheck` and `npm run lint` pass in `web/`.

## Task 3: Frames (#13, #15)

**Files:** `web/src/playback/engine.ts`, its tests, `web/src/guitar/stage.ts`,
`web/src/guitar/stage.test.ts`.

- [ ] **#13.** Engine test: the new check is false while paused, false while
  playing with a source loading, and true once `loadedmetadata` fires with a
  resume. Stage tests: move "leaves the drawing to the engine's frames while
  the song plays" past `media.loadMetadata()`, and add one in which Play
  pressed before the metadata leaves a view toggle drawing the stage's own
  frames. Code: the engine's check is true exactly when `runFrame` would ask
  for the next frame (`playing`, no `pending`, not disposed). `wake()` returns
  early on that, not on `playing`. Commit: `Fixes #13.`
- [ ] **#15.** Test: paused, a camera move under way (own frames running),
  seek with `at(t)`, flush both queues in each order, and expect one render
  per flush pair, with the new `t` drawn by the next own frame. Code: the
  engine's listener sets `this.t`. When `this.frame !== null` it returns, and
  the pending frame draws `t`. Otherwise it draws as now.
  Commit: `Fixes #15.`
- [ ] `npm run test`, `npm run typecheck` and `npm run lint` pass in `web/`.

## Task 4: Failures and lifecycle (#16, #17, #18, #19, #12)

**Files:** `web/src/log.ts` (new), `web/src/labels.ts`,
`web/src/playback/engine.ts`, `web/src/guitar/stage.ts`, `Guitar.tsx`,
`web/src/player/GuitarBoundary.tsx`, `web/src/player/Player.tsx`, their
tests. Docs: 008's `spec.md` *Rendering*, "No WebGL", and the message in
`acceptance.md`.

- [ ] **`log.ts`.** `export function logError(where: string, error: unknown):
  void`, calling `console.error(\`[guitarvis] ${where}\`, error)`.
- [ ] **#16.** Engine test: two frame listeners, the first throws; the second
  still gets `t`, the next frame is still requested, and the throw is logged.
  Stage test: a renderer whose `render` throws. The throw is logged once, the
  stage stops drawing, and `onFailed` is called once. Guitar test: the panel
  then shows `GUITAR_FAILED`. Code: `runFrame` wraps each listener. The Stage
  wraps both draw paths in one guard that logs, disposes and calls `onFailed`.
  `Guitar` keeps a `failed` state and shows `GUITAR_FAILED` in the panel.
  Commit: `Fixes #16.`
- [ ] **#17.** Tests: a lazy import that rejects shows `GUITAR_LOAD_FAILED`
  (as now). A Guitar that throws on render shows `GUITAR_FAILED`. Both are
  logged. A `Stage` constructor that throws disposes the renderer, releases
  its context, and reaches the boundary. Code: `GuitarChunkError` (exported
  from `GuitarBoundary.tsx`), thrown by `Player`'s lazy import's `.catch`.
  `componentDidCatch` logs. `getDerivedStateFromError` records which message.
  In `Guitar.tsx`, `new Stage` inside the `try`. On a throw, dispose and
  release the renderer and rethrow. Commit: `Fixes #17.`
- [ ] **#18.** Test: lose the context (the message shows after the grace),
  rebuild the Stage with a new song prop, and expect the view buttons back.
  Code: `setUnavailable(false)` after the Stage is built. Commit: `Fixes #18.`
- [ ] **#19.** Tests with fake timers: a loss restored within 1000 ms never
  shows the message. A loss not restored shows it at 1000 ms. A restore after
  that clears it. Dispose clears the timer. Code: `LOST_GRACE_MS = 1000` in
  `stage.ts`. `webglcontextlost` starts the timer, `webglcontextrestored`
  clears it, or reports `false` if it had fired. `NO_WEBGL` becomes "The
  guitar needs WebGL 2, which this browser does not have available." Amend
  008's *Rendering*, "No WebGL", and its acceptance record's quote.
  Commit: `Fixes #19.`
- [ ] **#12.** Tests: unmount calls `forceContextLoss` once. A rebuild on a
  new song does not. Under `<StrictMode>` the mount does not, and the final
  unmount does. Code: `Renderer` gains `forceContextLoss`. The fake renderers
  in `stage.test.ts` and `Guitar.test.tsx` gain it as `vi.fn()`. `Guitar`'s
  cleanup calls it after `stage.dispose()` when `!canvas.isConnected`.
  Commit: `Fixes #12.`
- [ ] `npm run test`, `npm run typecheck` and `npm run lint` pass in `web/`.

## Task 5: Finish

- [ ] `make services`, then `make check`.
- [ ] Tick this plan's boxes. Open the PR with the template. Its body closes
  each issue (`Fixes #7`, …).
