# 3D Guitar — Design

**Date:** 2026-10-16
**Status:** Draft for review
**Parent spec:** [001-guitarvis-design](../001-guitarvis-design/spec.md)
**Builds on:** [007-2d-fretboard](../007-2d-fretboard/spec.md)
**Reference look:** [spike.html](spike.html), the throwaway prototype this
design was worked out on. Open it in a browser; it loads three.js from a CDN.

## Purpose

Build the second half of phase 5: a 3D guitar neck that shows where the hand
goes while the song plays, and that the learner can turn, move closer to, and
zoom in on a chord.

The same model replaces 007's flat SVG fretboard. A guitar seen square-on,
with the camera unable to tilt, is the 2D view. So the app draws one fretboard
in two ways, not two fretboards. A `[2D | 3D]` toggle picks the view.

The 3D view is easier to follow than the flat one because it looks like an
actual guitar. A learner can see a chord from the angle their own eyes see it,
or from the front, and can get close to one position on the neck.

The success conditions:

1. With `make services`, `make migrate`, `make api`, `make worker` and
   `make web` running, a song plays with the guitar above the tab strip. Its
   notes light and its strings vibrate as they sound, at 1× and at 0.5×, in
   step with the audio and the tab strip.
2. In 3D the learner can rotate, zoom and pan. In 2D they can zoom and pan,
   and the neck never tilts. 2D opens on the whole neck.
3. A loud note makes its string swing wider than a quiet one.
4. The guitar fades and hides exactly the notes the tab strip fades and hides,
   as 007's fretboard did. A document with no notes, or with hidden passages,
   renders its fallback. Tests prove both.
5. A browser without WebGL gets a message in the panel, and the tab strip and
   controls still work.
6. `make check` gates all of it.

## Scope

**In:**
- a procedural model of a guitar neck and headstock, after the spike;
- two views of it, 2D and 3D, with the toggle, camera controls, and a reset;
- sounding notes as dots named by pitch, and open strings as rings;
- string vibration, its size set by the note's loudness;
- a `loudness` on each note, measured by the worker from the guitar stem;
- string labels at the tuners, and fret numbers under the neck;
- the confidence rule and the hidden-passage fallback, from `confidence.ts`
  unchanged;
- removing 007's SVG fretboard, and keeping its note-selection logic;
- loading three.js only when the guitar is first shown;
- a manual acceptance record.

**Out:**
- the guitar's body, bridge and sound hole. The model is a neck and headstock;
- a downloaded 3D model (glTF). The model is built in code (open decision 8);
- any look-ahead on the neck. As in 007, the tab strip shows what is coming;
- a camera that moves by itself, e.g. to follow the notes (see *Rejected
  alternatives*);
- both views at once (open decision 9 stays open);
- hands, fingers, or finger numbers;
- technique marks (`technique` is null in v1), capo drawing, and a
  left-handed mirror;
- click-to-seek, hover, and any interaction with the notes;
- keyboard control of the camera;
- shadows, reflections and environment maps;
- mobile layouts (open decision 10).

No change to the api. No change to `SCHEMA_VERSION`: `loudness` is a new
optional field. No stage's cached output changes, so `CACHE_VERSION` does not
move (see *Loudness*).

## Decisions and where they came from

Settled in the design session, against the spike:

- the model, as in the spike: neck, tilted headstock, 3 + 3 tuners,
  rosewood board, maple neck, dark headstock;
- 2D is the same model square-on, never tilting;
- 2D can zoom and pan, and opens on the whole neck;
- 3D can rotate, zoom and pan;
- the neck is 1.7 times as wide as a real one, so the dots can be larger;
- dots as large as they can be without touching their neighbours;
- an open string is a hollow ring, not a filled dot;
- a sounding string vibrates along its whole length, nut to end of neck,
  wherever it is fretted;
- how far a string swings depends on how loud the note is.

Calls made in writing this spec, open to change:

| Call | Why |
|---|---|
| The headstock is on the right, the lowest string on top | As in the screenshots the design began from: the guitar as someone facing the player sees it. 007 put the nut on the left |
| The camera never moves by itself | 007 rejected a view that follows the hand: it moves under the eye |
| Loudness is measured from the stem, and stored on each note | The document has no loudness. See *Loudness* |
| 3D on first visit; after that, the view last used in this browser | 3D is the showcase, and a learner who prefers 2D should not have to pick it every song |
| String labels at the tuners, fret numbers under the neck | 007 drew both. Dropping them would make the new view harder to read than the one it replaces |
| Vibration and the pulse are off under `prefers-reduced-motion` | 007 already turns the pulse off |
| A strum's notes share one loudness | Measured note by note, the last strings of a strum read louder, because the first are still ringing in their window |
| No user-facing warning when loudness cannot be measured; the worker logs it | `warnings` is for the tab's quality. Loudness only changes how far strings swing |
| A hidden note's string does not vibrate | A hidden note shows nothing, and a vibrating string would show its string |
| Plain three.js, not react-three-fiber | See *Rejected alternatives* |

## Approach

### Shape of the change

```
packages/core/…/tabdoc.py     Note gains loudness: float | None
packages/core/…/contracts.py  NoteEvent and TabNote gain loudness: float | None
apps/worker/…/loudness.py     measures loudness from the stem (new, not a stage)
apps/worker/…/pipeline.py     runs it after transcription; copies TabNote's
                              loudness to Note
apps/worker/…/stages/fretboard.py  the mapper copies NoteEvent's loudness to
                              TabNote
schema/, web/src/types/       regenerated

web/src/
  guitar/
    sounding.ts   pure: (song, cursors, t) → what sounds now: the notes and
                  the message. 007's layout.ts without the pixels
    geometry.ts   pure: (song) → Geometry — every dimension and position on
                  the model, in millimetres
    vibration.ts  pure: (note, t) → how a string is displaced along its length
    camera.ts     pure: home poses, limits, framing, double-click targets
    model.ts      builds the three.js scene graph from a Geometry
    notes.ts      the keyed updater: applies each frame's notes to meshes
    Guitar.tsx    the panel: renderer, controls, toggle, overlay, frames
  fretboard/      removed: Fretboard.tsx, neck.ts, marks.ts, layout.ts,
                  and their tests
  views.test.ts   pins the tab strip and sounding.ts to one hidden-note rule,
                  in place of the tab strip and fretboard/layout.ts
  player/Player.tsx  mounts <Guitar> above <TabStrip>, lazily
  player/Player.test.tsx  finds the panel by its new name, "Guitar"
  styles.css      --guitar-* tokens replace --fret-*
```

This is 006's and 007's split again. Everything worth testing sits in pure
modules that run on `node`, and the component owns only the renderer and the
wiring. three.js's scene graph builds in `node` without WebGL, so `model.ts`
is testable too. Only the renderer needs a browser.

The file split is a guide. The builder may merge or split modules, provided
the pure ones stay pure.

### Rendering: three.js, outside React

React renders the panel's chrome (the toggle, the reset button, the message
overlay and the canvas's box) and nothing per frame. 006's rule holds: React
never re-renders at frame rate.

On mount, `Guitar` creates a `WebGLRenderer`, a scene from `model.ts`, a
camera, and `OrbitControls` from three's addons. Each engine frame then does
this:

1. `sounding()` gives the notes and the message for `t`.
2. `notes.ts` applies the notes to dot and ring meshes, keyed by note id.
3. Each string is reshaped for `t` (see *Vibration*).
4. The overlay's text is set directly on its DOM node, if it changed.
5. The renderer draws.

The canvas has `role="img"` and the label "Guitar".

**Frames.** The engine emits frames while playing, and one after each change
while paused. The view needs frames of its own in two cases: while the camera
moves (a drag, damping, a transition), and while a dot's pulse runs. For
those it requests its own animation frames, drawing at the engine's last `t`,
and stops once nothing moves. It never calls `engine.redraw()` for them,
which would make every view redraw.

**Loading.** three.js is about 150 kB gzipped. `Player` loads `Guitar` with
`React.lazy`, so the upload page never downloads it. While it loads, the
panel shows at its final height, empty. If the chunk fails to load, an error
boundary in the player (`GuitarBoundary`) shows "The guitar could not load.
Reload the page to try again." in the panel, and the tab strip and controls
carry on. Degrade, never fail.

**No WebGL.** If the renderer cannot be created, or the context is lost and
not restored, the panel shows "The guitar needs WebGL, which this browser has
turned off." The tab strip and controls carry on. Degrade, never fail.

### The model

All dimensions are in millimetres. The nut is at x = 0, and the neck runs
toward −x. The headstock is at +x, and the fingerboard faces +z. The lowest
string is on top (+y). [spike.html](spike.html) is the reference for every
number below.

**Scale length.** 650 mm. Wire n sits at

```
x(n) = −650 · (1 − 2^(−n/12))
```

so frets are spaced as on a real guitar. This is 007's rule, with a real
length in place of a width fitted to the panel.

**Frets.** The neck has F = max(20, the song's highest fret) frets. A note on
fret n sits between wires n − 1 and n, so F wires hold every note. The
mapper's highest fret is 20, inclusive, so F is 20 for every document the
pipeline makes, and the neck is the same for every song. The fingerboard ends
10 mm past wire F.

**Width.** Across the neck, everything is 1.7 times a real guitar's size
(`WIDE`). Lengths along the neck stay real. Let `a` run from 0 at the nut to
1 at the fingerboard's end. Then:
- the fingerboard's half-width is `WIDE · (22 + 6.5a)`;
- the outer strings sit `WIDE · (17.5 + 7a)` either side of the centre, with
  the others evenly between;
- the strings sit `2.8 + 1.6a` above the fingerboard.

**Furniture**, after the spike:
- a nut of bone;
- nickel fret wires;
- a maple neck back, half an ellipse in section;
- inlay dots at frets 3, 5, 7, 9, 15, 17, 19 and 21, and a pair at 12, drawn
  only up to F;
- a headstock tilted back 13°, in the spike's outline, stretched by `WIDE`
  across.

**Tuners.** Half the strings, rounded up, tune on the upper side of the
headstock and the rest on the lower. On each side, the outermost string's post
is nearest the nut. That gives 3 + 3 for six strings, with the low E and high
e closest to the nut, and no strings crossing. Each post has a bushing, a
shaft, and a button standing out past the headstock's edge.

**Strings.** The lower half are wound, in bronze, and the upper half plain,
in nickel, each as thick as its real gauge. Each runs from the end of the
fingerboard over the nut to its post. Only the part over the fingerboard
vibrates.

**Labels.** Each string's label, from `stringLabels`, sits on the headstock
face beside its post. A row of fret numbers lies in the fingerboard's plane,
just below its lower edge. Both use text textures, and the text faces the
front, so 2D reads it square-on.

**Colours.** The wood, metal and bone are fixed: wood is wood in dark mode
too. The scene's background, the dots and the overlay text come from CSS
tokens, read on mount and again when the colour scheme changes, as
`TabStrip` reads its palette.

### The notes, frame by frame

**What sounds.** 007's `layout.ts` decides which notes are lit and what
message shows, and then turns both into SVG pixels. The deciding half moves
to `guitar/sounding.ts` unchanged. These rules come with it:
- `MIN_LIT` and `litUntil`;
- the latest onset wins on each string;
- `emphasis()` for opacity;
- `isHidden()` against `song.hidden`;
- the chord symbol or `UNCLEAR_LABEL` inside a hidden passage;
- `EMPTY_MESSAGE` for a song with no notes.

The pixels stay behind. `sounding()` returns, for each lit note, its key
`dot:<note id>`, string, fret, name, opacity, onset and loudness, and the
message if there is one. Its tests are `layout.test.ts`'s, without the
coordinates. The guitar makes its own cursors when it mounts, as 007's
fretboard did.

**Fretted notes** are dots:
- filled in `--guitar-dot`, with a thin light edge and the note's name in
  `--guitar-dot-text`. As in 007, that is white on the light theme's accent
  and dark on the dark theme's lighter one, for contrast;
- centred between the note's two wires, on its string, just above the
  string;
- lying in the fingerboard's plane, so they read square-on in 2D and lie on
  the board like stickers in 3D;
- with radius 0.49 times the gap between strings at that fret. Two dots on
  neighbouring strings at one fret then almost touch, and never overlap.

**Open strings** are rings: a hollow ring in `--guitar-dot` with the name
inside, on the string, 12 mm past the nut, over the headstock. The ring is
hollow, so its name sits on the dark headstock and is drawn light in both
themes.

**The pulse.** A dot or ring swells to 1.5 times its size as it appears and
settles over 220 ms, ease-out. These are the spike's numbers; 007's CSS pulse
was 1.4 times over 150 ms, and the acceptance run may settle on either. Its
job is 007's: each pluck of a repeated note shows. Every onset gets its own
mesh, keyed by note id, and that is what makes the pulse fire. It runs on
wall-clock time, so a dot that appears after a seek pulses too.

**Confidence.** A dot's opacity is `emphasis(note.confidence)`, and means
nothing else. A hidden note gets no dot and no vibration.

**The message**, `EMPTY_MESSAGE`, a chord symbol, or `UNCLEAR_LABEL`, is an
HTML overlay centred on the panel. It takes 007's `.fret-message` look,
translated from SVG to HTML. The fonts and sizes carry over: 15 px system-ui
for a message, bold 32 px monospace for a chord. The SVG stroke halo becomes a
`text-shadow` halo in the background colour, so the strings never strike
through the text. A chord symbol shows at
`emphasis(chord.confidence, CHORD_THRESHOLDS)`.

### Vibration

A sounding string vibrates along its whole length over the fingerboard, from
the nut to the fingerboard's end, wherever it is fretted. The part over the
headstock stays still. A real string moves far too fast to see, so this is
drawn slowed down: a translucent blur around the string, which is how the eye
sees a moving string, with the string itself wobbling inside it.

For a note sounding on string s, at time t, the displacement across the neck
(along y) at position u along the string, from 0 at the nut to 1 at the end,
is

```
y(u, t) = A · sin(π u) · sin(2π f · (t − onset))
A       = amplitude(loudness) · e^(−(t − onset) / 0.7 s) · fade
f       = 7 Hz · 2^((midi − 40) / 24)
```

- **`fade`** runs from 1 to 0 over the last 80 ms before the note goes dark,
  so the string comes to rest rather than snapping still.
- **`f`** is a wobble the eye can follow. A higher note wobbles faster: 7 Hz
  for the low E, about 14 Hz two octaves up.
- **Time is song time**, so pausing freezes the string, and 0.5× slows it.
- **A new onset on the string restarts it**, so each pluck shows.
- **The blur** spans `±(A · sin(π u) + the string's radius)`, at 30% opacity
  times the note's emphasis. A doubtful note's blur is as faint as its dot.

**Loudness to amplitude.** `amplitude` maps loudness 0 to 0.6 mm and 1 to
3.2 mm, linearly. A note with no loudness, from a document made before this
change, gets 2.0 mm. These numbers are starting points, judged in the
acceptance run.

**Cost.** Each string over the fingerboard is a tube of about 160 segments by
6 sides, reshaped only while it vibrates. That is under 6,000 vertices a
frame for six strings, well within budget.

### Loudness

The vibration needs to know how loud each note is, and the document does not
say. Basic Pitch's per-note strength exists, but transcription already uses it
as `confidence`. Reusing it would make one number mean two things, and a
later recalibration of confidence would change how strings swing.

So the worker measures loudness directly from the guitar stem:

- **Where.** In `run_pipeline`, after transcription and before the
  fretboard mapper, by a helper module in the worker that reads the stem. It
  is not a stage and not part of `Transcriber`. Any transcriber, including a
  future guitar-specific one, gets loudness for free, and the transcription
  stage's cached output does not change. That is why `CACHE_VERSION` stays
  put.
- **Strums.** Notes are grouped first: a note whose onset is within 50 ms of
  the group's first onset joins that group. So a group spans at most 50 ms,
  as the mapper's voicings do. The window is one constant,
  `VOICING_WINDOW_SEC` in `guitarvis_core.contracts`, and the mapper and the
  helper both import it. Every note in a group shares one level, measured
  over the window from the group's first onset to 50 ms after its last.
  Measured note by note, a strum's later strings would catch the earlier ones
  still ringing and read louder. Amended by
  [009](../009-review-fixes/spec.md).
- **What.** That window's RMS level, in decibels, relative to the 95th
  percentile of all the song's group levels, mapped from −30 dB…0 dB onto
  0…1 and clipped.
- **How.** Stdlib only, like `measure_rms` in `separation.py`, so it runs in
  CI without the ml extra.
- **Contract.** `NoteEvent` and `TabNote` gain
  `loudness: float | None = None`. Old cache entries, which lack it, still
  load. The mapper copies it from `NoteEvent` to `TabNote`, and
  `run_pipeline` copies it from `TabNote` to `Note`.
- **Document.** `Note` gains `loudness: float | None`, in `[0, 1]`,
  described as "How loud the note is, relative to the song's loud notes. Not
  confidence." It is optional and additive, so `SCHEMA_VERSION` stays 1. Run
  `make schema` and commit both artifacts (invariant 5).
- **Degrade.** If the stem cannot be read for this, every note's loudness is
  `None`, the worker logs a warning, and the job carries on. The client then
  draws every string at the default amplitude. The document gets no warning:
  `warnings` tells the user the tab may be wrong, and this changes only how
  far strings swing. The degradation tables in the pipeline-stage skill and
  the parent spec gain this row.

### The two views

One scene, one perspective camera (22° field of view), and one
`OrbitControls`. The view sets what the controls may do.

**2D**, the locked front view:
- The camera looks straight at the fingerboard, along −z, and never tilts:
  rotation is off.
- Scroll or pinch zooms toward the pointer.
- A drag, with any button or one finger, pans.
- The home pose frames the whole model, from the fingerboard's end to the
  tuner buttons, with a 4% margin.

**3D**:
- Drag rotates, scroll or pinch zooms toward the pointer, and right-drag or
  shift-drag pans.
- The home pose is the spike's three-quarter view: the camera low, in front,
  and off the body end, looking up the neck toward the headstock.

**Both:**
- Double-clicking the neck moves the camera to that spot. In 2D it ends
  260 mm in front of the spot. In 3D it ends 190 mm away along the current
  view direction.
- "Reset view" returns to the current view's home.
- Switching views moves the camera to the new view's home.
- Every camera move that the user did not drag animates over 700 ms, easing
  in and out.
- Zoom stops between about 35 mm and 1800 mm from the target. Panning keeps
  the target over the model, so the guitar cannot be lost off-screen.
- Until the user moves the camera, a resize re-frames the home pose. After
  that, a resize keeps the camera and changes only the aspect.

**The toggle.** `[2D | 3D]` sits at the panel's top left and "Reset view" at
its top right, as buttons with `aria-pressed`. The choice is remembered in
`localStorage` under one key, read and written inside `try`/`catch`, and a
first visit gets 3D.

**Size.** The panel fills the main column's width. Its height is what 2D's
home pose needs to show the whole model edge to edge: about width / 2.8,
clamped to between 260 and 460 px.

### The other cases

- **No notes.** The bare guitar and `EMPTY_MESSAGE`.
- **Paused, and seeking.** The engine's frame after a seek re-seats the
  cursors, so the dots and strings are right at once. A paused string holds
  its displacement, frozen.
- **The A/B loop.** The jump back to A is a seek.
- **Reduced motion.** No pulse, and no vibration: the strings stay still and
  the dots carry the notes. The camera's transitions jump instead of
  animating.
- **Dark mode.** The background and dots follow the tokens. The guitar keeps
  its colours.

### Testing

Everything below runs in `make check`. Pure modules run on `node`.
`Guitar.test.tsx` opts into jsdom, with a fake renderer injected, because
jsdom has no WebGL.

- **`sounding.ts`:** `layout.test.ts`'s cases, against string and fret
  rather than x and y:
  - a dot lit across `[t, t + dur]`, and for `MIN_LIT` when `dur` is shorter;
  - the latest onset wins on one string;
  - no mark before its onset;
  - opacity is `emphasis`;
  - a hidden note stays hidden after its passage ends;
  - the chord symbol or "unclear passage" inside a hidden passage;
  - the empty message;
  - loudness passes through, or `null` when the note has none.
- **`geometry.ts`:**
  - F = max(20, highest), so a note on fret 20 needs no 21st;
  - the wires follow 2^(−n/12) from a 650 mm scale;
  - a fretted note sits between its two wires, and an open note past the nut;
  - the lowest string is on top, in standard tuning and in drop D;
  - neighbouring dots at one fret do not overlap, at fret 1 and at fret F;
  - the tuners' sides and order, for 6 strings and for an odd count;
  - inlays fall only up to F, with a pair at 12.
- **`vibration.ts`:**
  - the displacement is zero at the nut and at the fingerboard's end;
  - it is largest mid-string;
  - it decays with time;
  - it is zero once the note is dark;
  - a louder note swings wider;
  - with no loudness, it uses the default;
  - a higher note wobbles faster.
- **`camera.ts`:**
  - the 2D home pose frames the whole model at wide and narrow aspects;
  - a 2D pose always looks along −z;
  - the pan clamp keeps the target over the model;
  - a double-click target lies on the fingerboard.
- **`model.ts`** (on `node`, with the text textures stubbed):
  - one fret wire per fret, and one string per tuning entry;
  - one tuner per string.
- **`notes.ts`:**
  - a new key creates a mesh;
  - the same key in the next frame reuses it;
  - a gone key removes and disposes of it;
  - an open note gets a ring.
- **`Guitar`** (jsdom, fake renderer):
  - it subscribes to `onFrame`, and unsubscribes and disposes the renderer
    on unmount;
  - the toggle switches views and remembers the choice;
  - a renderer that throws gives the WebGL message;
  - a hidden passage shows its message in the overlay.
- **`views.test.ts`:** its separating song, run through the tab strip's
  layout and `sounding()`, pins both to `isHidden`. It replaces the fretboard
  layout with `sounding()` and keeps every case.
- **`Player`:** the guitar panel, named "Guitar", sits above the tab strip.
- **Worker:**
  - loudness for a stem with one loud and one quiet pluck orders them
    correctly;
  - the notes of one strum share one level;
  - an unreadable stem gives `None` for every note, and the job completes;
  - the mapper copies loudness from `NoteEvent` to `TabNote`;
  - `run_pipeline` copies it from `TabNote` to `Note`.
- **Fixtures:** `first-song.tabdoc.json` is unchanged and omits `loudness`.
  `minimal.tabdoc.json` carries an explicit `"loudness": null` on both notes,
  because its lossless round-trip test requires every emitted key, as it does
  for `technique: null`. Between them they test the fallback. Add a note with
  loudness to a test-local document where a test needs one.

### Manual acceptance

Recorded in `acceptance.md` in this folder, before the PR is merged. 007's
record was committed blank and the PR merged without the run. This one is
filled in first, and its questions include the ones 007 left open.

- **End to end,** in a browser against real services, with a real song:
  - at 1× and at 0.5×, dots and vibration match the audio and the tab strip;
  - a repeated pluck on one fret shows each pluck;
  - loud and quiet notes look different, and the default amplitude for an old
    document looks natural;
  - the vibration helps more than it distracts;
  - with only the present on the neck, the tab strip gives enough warning to
    move the hand.
- **The views:**
  - 2D opens on the whole neck, zooms and pans, and never tilts;
  - 3D rotates, zooms and pans;
  - double-click, reset, and switching views work;
  - the choice is remembered across a reload.
- **Readability:** in 2D at full width, the note names on the dots can be
  read without zooming. If not, say at what width they stop.
- **Frame rate** on the dev machine's browser, playing, with the 3D view
  moving. Record the browser and roughly the frames per second.
- **Dark mode,** **reduced motion,** **resizing** during playback, and
  **WebGL turned off.**
- **The string orders.** The tab strip puts the highest string on top, and
  the guitar the lowest. Say whether reading both together confused.

## Rejected alternatives

**react-three-fiber.** The parent spec named it, and it fits a scene that
React builds and changes. This scene changes every frame from the engine, and
006's rule keeps that out of React. With r3f, the frame work would run in
`useFrame` against refs anyway, and r3f's own render loop would have to be
bent to the engine's frames. It is two more packages and a reconciler, for
JSX that would only describe the model once. Plain three.js keeps 007's split
of pure modules plus a thin component, and the spike already uses it.

**Keeping the SVG fretboard as the 2D view.** It is built and tested. But two
fretboards would mean two drawings of the same neck to keep in step. The SVG
neck is fitted to the song, has its nut on the left, and has no headstock, so
switching between it and the 3D model would turn the picture around. The
model seen square-on is the 2D view the design asked for.

**Keeping the SVG fretboard as the no-WebGL fallback.** It would cover the
few browsers without WebGL, at the price of a second fretboard maintained for
them alone. The tab strip still works there.

**A real-width neck.** Strings 7 to 10 mm apart over a neck about 460 mm long
gave dots about 5 px across in 2D at full width, too small for a name. The
spike tried 1.35 times wide and then 1.7.

**Fitting the 2D view to the song's frets,** as 007 did. With zoom, the
learner can fit it themselves, and the design asked for the whole neck first.

**Dots that always face the camera.** Easier to read at a steep angle, but
they float off the board and stop looking like fingers on frets. The spike's
flat dots were kept.

**Vibration from the fret, not the nut.** Physically right, since a fretted
string is stopped at the fret. The spike built it first, and the design chose
the whole string, nut to end: the whole string moving reads better as "this
string sounds".

**Loudness from `confidence`.** It is Basic Pitch's strength today, so it
would cost nothing. But it would tie the vibration to the confidence rule,
and opacity already means confidence.

**Loudness measured in the browser.** It would mean decoding the whole stem in
the browser, minutes of audio held in memory, and CORS on presigned URLs. The
worker already has the stem on disk.

**A camera that follows the notes.** It keeps the sounding notes on screen
when zoomed in. But the neck then moves under the eye, which 007 rejected for
the flat fretboard. Reset and double-click are one click away.

**A sourced glTF model.** Better-looking for less work on the model, but with
licensing and size to manage, and its proportions would not stretch to
`WIDE`. The design began from a procedural model and kept it.

## Consequences

- **Phase 5 is done.** The parent spec's open decision 8, about the 3D
  asset, is resolved: procedural. Its note that the 3D guitar uses
  react-three-fiber is superseded by this spec.
- **007's SVG fretboard is gone.** Its note-selection rules live on in
  `guitar/sounding.ts`. Its spec stays as the record of why those rules are as
  they are.
- **The neck is no longer fitted to the song.** Every song gets the same
  20-fret neck. Zoom replaces the fitting.
- **The nut moves to the right.** 007's flat neck had the nut on the left.
- **The tab document grows `loudness`.** It is additive. Per the tab-document
  skill, a client validating raw JSON against a bundled v1 schema would reject
  a document carrying it, so state that in the PR.
- **A new dependency:** `three` (and `@types/three`), in a lazy chunk. The
  upload page's bundle does not grow.
- **New colour tokens.** `--guitar-*` replace `--fret-*`.

## Risks

- **Frame rate on weak GPUs.** The scene is small, but per-frame tube updates
  and a 2× pixel ratio on a large panel add up. If the acceptance run
  stutters, cap the pixel ratio at 1.5 first, then reshape strings every
  other frame.
- **Text size in 2D.** The whole neck at full width gives dots of roughly 10
  to 14 px across. The acceptance run says whether names read without zoom.
  If not, the fix is a taller panel or a larger `WIDE`, both constants.
- **The vibration distracts.** It is new motion next to the tab strip the
  learner reads from. The acceptance run judges it, and the amplitude
  constants are the lever.
- **Loudness that does not track the ear.** RMS over 50 ms of a separated stem
  can be fooled by bleed from other instruments. If loud and quiet do not
  look different in the acceptance run, the window and the range are the
  first things to change. A bad loudness only changes how far strings swing.
- **Two string orders, and now a flipped neck.** The tab strip puts the
  highest string on top. The guitar puts the lowest on top, with the nut on
  the right. The acceptance run asks.
- **jsdom cannot test the drawing.** Everything that decides what is drawn is
  pure and tested. The drawing itself is checked by eye in the acceptance
  run.
