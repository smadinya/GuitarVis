# Review Fixes for the 3D Guitar — Design

**Date:** 2026-10-17
**Status:** Draft for review
**Parent spec:** [001-guitarvis-design](../001-guitarvis-design/spec.md)
**Fixes:** [008-3d-guitar](../008-3d-guitar/spec.md), from its review

## Purpose

The review of branch `008-3d-guitar` filed thirteen bugs, #7 and #9 to #20.
008 merged with them open. This change fixes all thirteen. Two of them change
a rule that 008's spec states, and one changes a message it quotes. Those
three amend 008's spec in place, and this spec gives the reasons.

## Scope

In:

| Issue | Where | The bug in one line |
|---|---|---|
| #7  | worker | Strum groups chain without bound, so fast strumming gets one level |
| #9  | worker | Loudness reaches the document only if every mapper copies it |
| #10 | web    | A single click stops resizes from re-framing the home view |
| #11 | web    | The pixel ratio is read once, so browser zoom blurs the guitar |
| #12 | web    | WebGL contexts are not released when a song page unmounts |
| #13 | web    | The guitar freezes while an audio source loads |
| #14 | web    | A resize during a camera transition lands on a stale home view |
| #15 | web    | The guitar can draw twice in one frame while paused |
| #16 | web    | A throw in the guitar's frame callback stops every view's frames |
| #17 | web    | `GuitarBoundary` says "could not load" for any error, and logs nothing |
| #18 | web    | The WebGL message never clears after the Stage is rebuilt |
| #19 | web    | The WebGL message shows on a brief context loss, and misreads WebGL 1 |
| #20 | web    | Shift-, ctrl- or meta-drag does nothing in 2D |

Out: #8 and #21 (enhancements: the loudness RMS scan, and the duplicated
`readPalette` and `clamp`) and #22 (the acceptance record's `psql` line).
They are not bugs, and each can be a change of its own.

No change to the tab document, the api or `SCHEMA_VERSION`.

## Decisions

### Worker

**#7. A strum is anchored to its first onset.** A note joins the current
group when its onset is within 50 ms of the group's *first* onset, as the
mapper's voicings already work. Chaining from the previous note let a fast
strummed passage become one group, with one level for every strum in it. A
group now spans at most 50 ms. Onsets 1.00, 1.04 and 1.08 give two groups, and
a test pins that.

The window becomes one constant in `guitarvis_core`, imported by both the
mapper and the loudness helper. Today the helper restates the mapper's
`VOICING_WINDOW_SEC`, because a helper may not import a stage. Both may import
`guitarvis_core`.

Amends 008's *Loudness*, "Strums".

**#9. Loudness is measured after the fretboard mapper, from its `TabNote`s.**
`run_pipeline` measures it once stage 4 returns. `TabNote`s keep their onsets,
so the measurement is unchanged. Any transcriber still gets loudness, which
was 008's reason to measure outside the stages, and now any mapper does too,
with nothing to copy. Notes the mapper drops leave the strum groups, which is
better: they are not in the document. A strum can then differ from the
mapper's voicing. If the mapper drops a voicing's first note, the rest anchor
on the next note kept, and can take in the start of the next voicing. Only a
swing size is shared, in a rare case, so the helper does not try to rebuild
the voicings.

`NoteEvent` loses `loudness`. Nothing would set it, and an unset field that
claims to be "measured from the stem" invites the same mistake again. Cached
transcriptions written since 008 carry `"loudness": null`, so the cache loader
drops that key, and old entries still load. The transcription stage's output
does not change, so `CACHE_VERSION` stays put. The fretboard stage is not
cached.

Amends 008's *Shape of the change*, its *Loudness* ("Where" and "Contract")
and its *Testing* list, which says the mapper copies loudness.

### Web: the camera

**#10. Only a gesture that moves the camera counts as touching it.**
OrbitControls sends `start` on every pointer-down and wheel event, even when
nothing moves. `touched` is now set by a `change` that comes between a
gesture's `start` and `end`. `start` still drops a running tween. A `change`
outside a gesture does not count. The controls send one when they catch up
with a pose the stage placed directly, or while damping runs on after the
pointer is released.

**#14. A resize redirects a transition that is heading home.** While the
camera is untouched, a resize sets a running tween's destination to the new
aspect's home. With no tween running, it places the camera at home as before.
A double-click's tween marks the camera touched, so it is never redirected.

**#11. The pixel ratio is read on every resize.** `resize()` sets it before
`setSize`. Browser zoom changes the panel's CSS size, so the ResizeObserver
catches it. Moving the window to a monitor with a different ratio may not
change the CSS size, so the stage also follows a
`(resolution: <ratio>dppx)` media query. The query is set up again for each
new ratio.

**#20. In 2D, a modified drag pans.** OrbitControls turns a pan into a rotate
while shift, ctrl or meta is held, and rotation is off in 2D, so the drag was
dropped. 3D teaches shift-drag to pan, so the habit comes with the user to
2D. In 2D, a capture-phase `pointerdown` listener on the canvas's box catches
a mouse or pen press with a modifier held. OrbitControls treats every pointer
but touch as a mouse. It stops that event and sends a copy to
the canvas with the modifiers cleared. OrbitControls then starts a pan, and
the drag's moves and its release reach it unchanged.

Rejected: wrapping OrbitControls' `_onMouseDown`. It is shorter, but it adds a
second private field the build depends on. `stopMomentum` is the one already
there, and #17 counts it as a risk. The copied event uses only public DOM.

008's spec already says any drag pans. This brings the build to the spec.
The question in 008's acceptance record is answered.

### Web: frames

**#13. The stage decides by whether the engine is emitting frames, not by
`playing`.** `playing` stays true while a source loads with a resume pending,
and the engine emits no frames then. The engine gains a read-only check that
is true exactly when its frame loop runs: playing, no source loading, not
disposed. `wake()` asks that. Drags, the view toggle, Reset view and pulses
then draw during a load.

The old test named "leaves the drawing to the engine's frames while the song
plays" ran in that loading state, because `FakeMedia` never fires
`loadedmetadata`. It moves past `media.loadMetadata()`. A new case covers a
load, where the stage must draw its own frames.

**#15. While the stage's own frame is pending, an engine frame only records
`t`.** The pending frame draws at that `t`. Cancelling the own frame when an
engine frame draws, as the issue suggests, does not cover the common order.
The own frame was requested first, so it runs first in the browser's frame,
and the engine's frame would then draw a second time. Deferring covers both
orders. While the camera moves, a seek shows one frame late, which no one can
see.

### Web: failures

**#16. A frame listener's throw stays in its view.** The engine calls each
listener inside its own `try`, logs a throw, and goes on to the next
listener. It still asks for the next frame. The tab strip and the audio carry
on, whichever view throws. The Stage also guards its own drawing, from engine
frames and its own. On a throw it logs once, disposes itself, and calls a new
`onFailed`. The panel then shows `GUITAR_FAILED` in place of the guitar.

**#17. The boundary logs, and words a fetch failure apart from a bug.**
- **Logging.** `web/src` has had no `console.*` calls. The convention is now
  one helper, `logError(where, error)` in `web/src/log.ts`, which calls
  `console.error` with a `[guitarvis]` prefix. The boundary's
  `componentDidCatch`, the engine's listener guard and the Stage's guard all
  use it.
- **Two messages.** `Player`'s lazy import wraps a rejection in a
  `GuitarChunkError`. The boundary shows `GUITAR_LOAD_FAILED` ("…Reload the
  page to try again.") for that error only. Every other error gets
  `GUITAR_FAILED`: a reload would only repeat a bug. A browser's own wording
  for a failed module fetch differs between browsers, so the boundary does not
  read it.
- **`new Stage` moves inside the `try`.** If the Stage throws, the renderer
  just made is disposed and its context released, and the error goes on to
  the boundary. It is a bug, not missing WebGL, so it must not show the WebGL
  message.

`GUITAR_FAILED` is "The guitar hit an error and stopped. The tab and the
audio carry on." It lives in `labels.ts` with `GUITAR_LOAD_FAILED`.

**#18. Building a working Stage clears the WebGL message.** The effect calls
`setUnavailable(false)` once its Stage exists. A context lost before a
rebuild then no longer leaves the message up.

**#19. A lost context shows the message only if it stays lost.** The Stage
reports a loss after `LOST_GRACE_MS` (1000 ms) with no restore, and a restore
within that time reports nothing. A GPU reset after a driver update, or after
sleep and wake, no longer flashes the message. The message becomes neutral,
because three r163 and later need WebGL 2, and a browser with only WebGL 1
was told WebGL was "turned off". The new text is "The guitar needs WebGL 2,
which this browser does not have available." It is true when WebGL is off,
when only WebGL 1 exists, and when the context stays lost.

Amends 008's *Rendering*, "No WebGL", and the message its acceptance record
quotes.

**#12. The guitar releases its WebGL context when its canvas leaves the
page.** `Renderer` gains `forceContextLoss`. `Guitar`'s effect cleanup calls
it only when the canvas is no longer connected to the document. React detaches
a deleted subtree's DOM before it runs passive cleanups, so on a real unmount
the canvas is already detached. On a rebuild after a song or engine change,
and on StrictMode's simulated unmount, the canvas stays. A context released
there would be the one the next renderer gets, already lost.

Rejected: a mount-only effect whose cleanup releases the context. StrictMode
runs that cleanup on its simulated unmount, and then reuses the canvas.

## Consequences

- One logging convention for the client.
- The engine is the only owner of "are frames running", and views ask it.
- 008's spec is amended in three places. Each amendment notes "Amended by 009"
  so a reader can find the reasons here.

## Risks

- **The copied pointer event (#20).** It is untrusted (`isTrusted` is false).
  OrbitControls does not check, and `setPointerCapture` accepts it, because
  its `pointerId` is a pointer that is really down. A three upgrade that starts
  checking would break only the modified drag. The test sees it, because it
  asserts the target moves.
- **"Detached means unmounted" (#12)** rests on React's commit order. A test
  mounts, rebuilds, unmounts and runs under StrictMode, and asserts when the
  context is released.
- **Engine frames isolate listeners (#16).** A view that throws every frame
  logs every frame. The Stage disposes itself on its first throw, so for the
  guitar it is once. The tab strip has no such guard, and gets none here.
