# Player Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the song page around a docked transport, a sections sidebar, a chord lane and a scrubber that shows the sections and the loop. How the tab strip, the guitar and the engine draw does not change.

**Architecture:** Three pure modules decide what the new views show. `TrackCursor` in `playback/cursor.ts` says which span is current at a time, for chords and sections. `player/lane.ts` gives the chord cells and their states, and `player/scrub.ts` gives positions on the scrubber as fractions. The components only draw. They follow playback by 006's rule: the lane, the sidebar and the guitar's chord overlay re-render only when their index changes, and the scrubber's knob moves by direct style writes on `onFrame`. `Player` owns the view choice (`3D · Fretboard · Tab only`) and lays the page out as a CSS grid with a sticky transport. `Guitar` takes the view as a prop.

**Tech Stack:** React 18.3, TypeScript 6.0, Vite 8.3, Vitest 5.0 with jsdom 29.1, Testing Library 16. No new dependencies.

**Spec:** [spec.md](spec.md) · **Parent:** [001-guitarvis-design](../001-guitarvis-design/spec.md) · **Builds on:** [006](../006-tab-view-sync/spec.md), [007](../007-2d-fretboard/spec.md), [008](../008-3d-guitar/spec.md) · **Visual reference:** *Web mockups · WebPlayer* in the [design system](https://claude.ai/artifact/3Zc4v6XxdR3viHReBX6weE)

**Checked while writing**, against this repo's jsdom 29.1.1 and vitest 5.0.1:
- jsdom has `PointerEvent`, and `fireEvent.pointerDown(el, { clientX })` delivers `clientX`. It has no `setPointerCapture`, `scrollIntoView` or `Element.scrollTo`. `scrollLeft` can be assigned.
- A `vi.mock` of a module that `React.lazy` imports runs its factory only when the lazy component first renders. A test can therefore tell whether the guitar's chunk was fetched.
- `<Profiler onRender>` is called once per commit under vitest, so a test can count a view's renders across frames.
- A React `onKeyDown` that calls `preventDefault()` runs before the window's listener, and that listener sees `defaultPrevented`. `useTransportKeys` already returns early on that.

**Not run:** this plan's code, which has not been assembled. Task 14 is a person's job.

## Before Task 1

The branch `011-player-redesign` exists, and `docs/specs/011-player-redesign/` is untracked. Commit the spec and this plan together:

```bash
git add docs/specs/011-player-redesign/spec.md docs/specs/011-player-redesign/plan.md
git commit -m "docs: 011 player redesign, spec and plan

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Global Constraints

Every task inherits these.

- **Never commit to `main`.** Work on `011-player-redesign`. `.githooks/pre-commit` refuses `main`.
- **`make check` is the gate.** Run `make services` first, or the integration tests skip locally and fail in CI.
- **No change to `tabdoc.py`, `schema/`, the api, the worker, `SCHEMA_VERSION` or `CACHE_VERSION`.** `web/src/types/` is generated: never edit it. `Song` gains `tempo` and nothing else.
- **What draws stays as it is.** `guitar/stage.ts` and the modules under it, `tab/` and `playback/engine.ts` do not change. Their tests pass unmodified. The exception is the guitar's view-toggle tests, which move to `ViewSwitch.test.tsx` (Task 6). `playback/cursor.ts` gains `TrackCursor`; `NoteCursor` and `inWindow` are untouched.
- **`confidence.ts` is imported unchanged.** A chord's opacity is `emphasis(confidence, CHORD_THRESHOLDS)` wherever it is drawn: in the lane and in the guitar's overlay. Chords are faded, never hidden.
- **React never renders at frame rate.** A view that follows playback subscribes with `engine.onFrame`. It then either calls `setState` only when its index changes (the lane, the sidebar, the overlay) or writes styles directly (the scrubber). `state.time` from `useSyncExternalStore` (about 4 Hz) is only for the transport's readout and the slider's aria values.
- **three.js is reached only through `React.lazy`.** Nothing outside `web/src/guitar/` imports a `guitar/` module, except `Player.tsx`'s lazy import and the tests. That is why `VIEW_KEY` moves out of `Guitar.tsx`.
- **A view never imports another view.** `guitar/` may import from `playback/`, `confidence.ts`, `labels.ts` and `song.ts`, never from `player/`.
- **A click never leaves focus behind.** Every button in the transport, the view switch, the sidebar and the warnings line calls `keepFocus` on mousedown, so that Space stays play/pause after a click. Every button that shows only an icon has an `aria-label`.
- **Exact values from the spec:**
  - Tokens: `--bg-raised` is `#ffffff` in light and `#1f1d1b` in dark. `--on-accent` is `#ffffff` in light and `#171614` in dark. No existing token changes.
  - Page: `main.song-page` has a `max-width` of 1280 px. The body's columns are `minmax(0, 1fr) 248px`. Below 900 px it is one column with the sidebar after the main column, and the transport wraps onto two rows. The transport is `position: sticky; bottom: 0`.
  - Play button: 48 px, round, `--accent` background, icon in `--on-accent`.
  - Overlay: the current chord in bold 32 px monospace, as `.guitar-message.chord`. The next chord is in `--muted`.
  - Lane cells: **played** in `--fg`. **current** has `--accent` text and an `--accent` ring on `--bg-raised`. **coming** in `--muted`.
  - The loop's band and edges are in `--tab-loop`.
  - View values are `"3d" | "2d" | "tab"`, labelled `3D`, `Fretboard` and `Tab only`, in a group named `View`. The storage key is `guitarvis.guitar-view`. Anything else read from storage means 3D.
  - Copy: "N things to know about this tab", "Show" / "Hide"; "Sections", "No sections found", "Chords"; "Full mix", "Guitar only". `aria-label`s: "Play" / "Pause", "Back 5 seconds" / "Forward 5 seconds", "Set loop start" / "Set loop end" / "Clear loop". Legend: "Sounding", "Less sure".
  - Slider: `role="slider"`, with `aria-valuetext` like `"1:07, Verse 1"`. The arrow keys seek ±`SEEK_STEP_SEC`, and Home and End go to the ends.
  - Keys: `[` calls `engine.setLoopPoint("a")` and `]` calls `engine.setLoopPoint("b")`.
- **The spec's open question takes its default.** The legend has no "Next", and the approach rings stay dropped.
- **Decisions the spec leaves open, made here:**
  - `TrackCursor` lives in `playback/cursor.ts`, not `lane.ts`. The sidebar, the transport and the guitar's overlay use it too, and `guitar/` may not import `player/`. Its tests are the ones the spec lists under `lane.test.ts` for "the current index".
  - The back link reads "Upload another song" and goes to `/`. There is no library yet.
  - A loop button's accessible name is "Set loop start" while A is unset and "Set loop start (0:40)" once it is set, and the same for B. The old label stays as the prefix, and a screen reader hears the time.
  - The slider's accessible name is "Position", and the lane's is "Chord lane".
  - The metadata line is `m:ss · Standard tuning · about N bpm`. A tuning that is not standard reads its letters, e.g. `D A D G B E tuning`. The tempo part appears only when `tempo` is not null.
  - `SongPage` shows its own `<h1>` only until the player is up. From then on the player's header carries the title.
- **Running tests:** `npm --prefix web test -- <path>` runs `tsc --noEmit` and then `vitest run <path>` inside `web/`, with paths relative to `web/`. While a module does not exist yet, `tsc` is what fails.
- **jsdom:** a test that needs the DOM begins with `// @vitest-environment jsdom`. Everything else runs on `node`.
- **Style:** double quotes, semicolons and two-space indents. `npm --prefix web run lint` is authoritative. Each export gets a doc comment that says why, as the surrounding code does.
- End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

Inputs the spec implies but its test list never exercises, most likely first. Each one is pinned by a test in the task named.

1. **A drag while the song plays.** Frames keep coming during a drag. If they move the knob, it jumps back under the pointer every frame. Expected: the knob follows the pointer, nothing seeks until release, and the release seeks once. A cancelled pointer seeks nowhere and the knob returns to the playhead. → Task 11: `previews a drag without seeking, and seeks once on release, whatever the frames do meanwhile` and `drops a cancelled drag without seeking`.
2. **An arrow key on the focused scrubber.** The window's key handler also seeks on the arrows, so a slider that handles them without `preventDefault` seeks 10 s. Expected: 5 s. → Task 11: `seeks five seconds once per arrow key, though the page's keys listen too`.
3. **B set before A.** People press `]` and then `[`, or set B at an earlier time than A. The engine and the tab strip both treat the loop as min→max. Expected: the scrubber draws the same band. → Task 3: `draws a loop whose B is before its A from B to A`.
4. **A seek backwards.** ←, Home and a section click all jump back, and a cursor that only moves forward would keep the later section or chord lit. Expected: the earlier one lights. → Task 1: `finds the earlier span after a backward jump`. Task 8: `highlights the current section as the song plays, and the earlier one after a seek back`.
5. **Switching views mid-song.** The view lives in `Player`, beside the engine. A change that rebuilt the engine would stop the audio and reload the file. Expected: the audio plays on and no file is reloaded. → Task 6: `keeps the audio playing on one engine through a switch to Tab only and back`.

## File map

| Path | Responsibility | Task |
|---|---|---|
| `web/src/playback/cursor.ts` | + `TrackCursor`, `Position`, `samePosition` | 1 |
| `web/src/player/lane.ts` | `laneCells`, `cellState`, `distinctSymbols` | 2 |
| `web/src/player/scrub.ts` | `fraction`, `timeAt`, `scrubMarks` | 3 |
| `web/src/player/keys.ts` | + `[` and `]` | 4 |
| `web/src/test/engine.ts` | `fakeEngine`: an engine over `FakeMedia`, with frames run by hand | 4 |
| `web/src/player/time.ts` | `clock`, moved from `Controls.tsx` | 5 |
| `web/src/player/Button.tsx` | `Button`, `keepFocus`, moved from `Controls.tsx` | 5 |
| `web/src/icons.tsx` | the transport's and the warnings' inline SVG icons | 5 |
| `web/src/player/Warnings.tsx` | collapsed to one line | 5 |
| `web/src/player/ViewSwitch.tsx` | `PageView`, `VIEW_KEY`, `useStoredView`, `ViewSwitch` | 6 |
| `web/src/guitar/Guitar.tsx` | takes `view`; loses its toggle; gains the overlay and legend | 6, 10 |
| `web/src/song.ts` | + `tempo`; exports `STANDARD_TUNING` | 7 |
| `web/src/player/Header.tsx` | back link, title, `details`, view switch | 7 |
| `web/src/pages/SongPage.tsx` | its `<h1>` only until the player shows | 7 |
| `web/src/player/Sections.tsx` | the sidebar | 8 |
| `web/src/player/ChordLane.tsx` | the lane | 9 |
| `web/src/guitar/NowNext.tsx` | `NowNext`, `Legend` | 10 |
| `web/src/player/Scrubber.tsx` | the slider | 11 |
| `web/src/player/Transport.tsx` | the docked bar; replaces `Controls.tsx`, which is deleted | 12 |
| `web/src/player/Player.tsx` | owns the view, lays out the page | 6, 7, 8, 9, 12 |
| `web/src/styles.css` | tokens, layout, each new view's rules | 5–12 |
| `docs/specs/001-guitarvis-design/spec.md`, `docs/specs/011-player-redesign/acceptance.md` | the records | 13 |

---

### Task 1: Where a span list stands at a moment

**Files:**
- Modify: `web/src/playback/cursor.ts`
- Test: `web/src/playback/cursor.test.ts`

**Interfaces:**
- Produces:
  ```ts
  /** Where a sorted list of spans stands at one moment. */
  export interface Position {
    /** The span sounding at t, read as NoteCursor reads it (both ends
     * included), the latest onset winning; -1 when none is. */
    current: number;
    /** The first span with onset after t; the list's length when none is. */
    next: number;
  }
  export class TrackCursor<T extends Span> {
    constructor(items: readonly T[]); // sorted by onset
    at(t: number): Position;
  }
  export function samePosition(a: Position, b: Position): boolean;
  ```

- [ ] **Step 1: Write the failing tests** — a new `describe("TrackCursor")` in `cursor.test.ts`

```ts
const span = (t: number, dur: number) => ({ t, dur });

describe("TrackCursor", () => {
  it("has nothing current in an empty list", () => {
    expect(new TrackCursor([]).at(3)).toEqual({ current: -1, next: 0 });
  });

  it("follows a single span, both ends included", () => {
    const cursor = new TrackCursor([span(1, 1)]);
    expect(cursor.at(0)).toEqual({ current: -1, next: 0 });
    expect(cursor.at(1)).toEqual({ current: 0, next: 1 });
    expect(cursor.at(2)).toEqual({ current: 0, next: 1 });
    expect(cursor.at(2.01)).toEqual({ current: -1, next: 1 });
  });

  it("has nothing current in a gap", () => {
    expect(new TrackCursor([span(0, 1), span(2, 1)]).at(1.5)).toEqual({ current: -1, next: 1 });
  });

  it("gives a shared boundary to the later span", () => {
    expect(new TrackCursor([span(0, 1), span(1, 1)]).at(1)).toEqual({ current: 1, next: 2 });
  });

  it("takes the latest onset among overlapping spans, and the earlier once the later ends", () => {
    const cursor = new TrackCursor([span(0, 4), span(1, 1)]);
    expect(cursor.at(1.5)).toEqual({ current: 1, next: 2 });
    expect(cursor.at(3)).toEqual({ current: 0, next: 2 });
  });

  it("finds the earlier span after a backward jump", () => {
    const cursor = new TrackCursor([span(0, 10), span(10, 10), span(20, 10)]);
    expect(cursor.at(25).current).toBe(2);
    expect(cursor.at(5)).toEqual({ current: 0, next: 1 });
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/playback/cursor.test.ts`
Expected: FAIL in `tsc`: `TrackCursor` is not exported.

- [ ] **Step 3: Implement `TrackCursor` in `cursor.ts`**

It holds its own `NoteCursor<T>` and a `Map<T, number>` from item to index, both built once. `current` is the index of `window(t, t).at(-1)`, the same reading `sounding()` uses for the guitar's centre chord, so the lane, the overlay and the centre never disagree. `next` is `firstIndex(items, (item) => item.t > t)`, reusing the module's private binary search. `samePosition` compares both fields. The class's doc comment says that each view keeps its own, as with `NoteCursor`.

- [ ] **Step 4: Run them to verify they pass**

Run: `npm --prefix web test -- src/playback/cursor.test.ts`
Expected: PASS, with the existing `NoteCursor` and `inWindow` tests unchanged.

- [ ] **Step 5: Commit**

```bash
git add web/src/playback/cursor.ts web/src/playback/cursor.test.ts
git commit -m "feat(web): TrackCursor, the current and next span at a moment

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The chord lane's cells

**Files:**
- Create: `web/src/player/lane.ts`
- Test: `web/src/player/lane.test.ts`

**Interfaces:**
- Consumes: `Position` (Task 1); `emphasis`, `CHORD_THRESHOLDS` from `confidence.ts`; `Chord` from `types/tabDocument`.
- Produces:
  ```ts
  export interface LaneCell { symbol: string; opacity: number }
  /** One cell per chord, in order; opacity by the chord thresholds. */
  export function laneCells(chords: readonly Chord[]): LaneCell[];
  export type CellState = "played" | "current" | "coming";
  /** `current` is the cell at at.current; any other cell before at.next is played. */
  export function cellState(index: number, at: Position): CellState;
  /** Each symbol once, in the order first heard. */
  export function distinctSymbols(chords: readonly Chord[]): string[];
  ```

- [ ] **Step 1: Write the failing tests**

```ts
const chord = (t: number, symbol: string, confidence = 0.9) => ({ t, dur: 2, symbol, confidence });

describe("laneCells", () => {
  it("is empty for no chords", () => expect(laneCells([])).toEqual([]));

  it("fades by the chord thresholds, never below FADED", () => {
    const mid = (CHORD_HIDE + CHORD_FULL) / 2;
    const cells = laneCells([chord(0, "Am", CHORD_FULL), chord(2, "C", mid), chord(4, "G", CHORD_HIDE), chord(6, "D", 0)]);
    expect(cells.map((c) => c.symbol)).toEqual(["Am", "C", "G", "D"]);
    expect(cells[0].opacity).toBe(1);
    expect(cells[1].opacity).toBeCloseTo((1 + FADED) / 2);
    expect(cells[2].opacity).toBe(FADED);
    expect(cells[3].opacity).toBe(FADED);
  });
});

describe("cellState", () => {
  const states = (count: number, at: Position) => Array.from({ length: count }, (_, i) => cellState(i, at));

  it("marks the cells before the current one played, and the rest coming", () => {
    expect(states(5, { current: 2, next: 3 })).toEqual(["played", "played", "current", "coming", "coming"]);
  });

  it("between chords, has no current cell", () => {
    expect(states(4, { current: -1, next: 2 })).toEqual(["played", "played", "coming", "coming"]);
  });

  it("plays a short chord out under a long one that is still current", () => {
    expect(states(3, { current: 0, next: 2 })).toEqual(["current", "played", "coming"]);
  });
});

describe("distinctSymbols", () => {
  it("lists each symbol once, first heard first", () => {
    expect(distinctSymbols([chord(0, "Am"), chord(2, "C"), chord(4, "Am"), chord(6, "G"), chord(8, "C")])).toEqual(["Am", "C", "G"]);
    expect(distinctSymbols([])).toEqual([]);
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/player/lane.test.ts`
Expected: FAIL: `./lane` does not exist.

- [ ] **Step 3: Implement the three functions in `lane.ts`**

- [ ] **Step 4: Run them to verify they pass**

Run: `npm --prefix web test -- src/player/lane.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/player/lane.ts web/src/player/lane.test.ts
git commit -m "feat(web): the chord lane's cells, states and chord list

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Positions on the scrubber

**Files:**
- Create: `web/src/player/scrub.ts`
- Test: `web/src/player/scrub.test.ts`

**Interfaces:**
- Consumes: `LoopPoints` from `playback/engine`; `Section` from `types/tabDocument`.
- Produces:
  ```ts
  /** t as a fraction of the track, clamped to [0, 1]; 0 when duration is not a positive finite number. */
  export function fraction(t: number, duration: number): number;
  /** The time under a pointer at clientX, for a track at `left` that is `width` wide; clamped to [0, duration]; 0 when width <= 0. */
  export function timeAt(clientX: number, left: number, width: number, duration: number): number;
  export interface ScrubMarks {
    /** A tick at each section start after the first, strictly inside (0, 1). */
    ticks: number[];
    /** Both points set: min to max, as the engine and the tab strip read them. */
    band: { from: number; to: number } | null;
    /** Each set point. */
    edges: Array<{ point: "a" | "b"; at: number }>;
  }
  export function scrubMarks(duration: number, sections: readonly Section[], loop: LoopPoints): ScrubMarks;
  ```

- [ ] **Step 1: Write the failing tests**

```ts
const section = (t: number, label = "s") => ({ t, dur: 10, label });
const NO_LOOP = { a: null, b: null };

describe("scrubMarks", () => {
  it("ticks each section start after the first", () => {
    expect(scrubMarks(40, [section(0), section(10), section(20)], NO_LOOP).ticks).toEqual([0.25, 0.5]);
  });

  it("drops a section that starts at or past the end", () => {
    expect(scrubMarks(40, [section(0), section(10), section(40), section(45)], NO_LOOP).ticks).toEqual([0.25]);
  });

  it("draws only A's edge while B is unset", () => {
    expect(scrubMarks(40, [], { a: 10, b: null })).toEqual({ ticks: [], band: null, edges: [{ point: "a", at: 0.25 }] });
  });

  it("draws the band between A and B, with both edges", () => {
    const marks = scrubMarks(40, [], { a: 10, b: 30 });
    expect(marks.band).toEqual({ from: 0.25, to: 0.75 });
    expect(marks.edges).toEqual([{ point: "a", at: 0.25 }, { point: "b", at: 0.75 }]);
  });

  it("draws a loop whose B is before its A from B to A", () => {
    expect(scrubMarks(40, [], { a: 30, b: 10 }).band).toEqual({ from: 0.25, to: 0.75 });
  });

  it("clamps a loop past the media's reported duration to the end", () => {
    const marks = scrubMarks(40, [], { a: 30, b: 50 });
    expect(marks.band).toEqual({ from: 0.75, to: 1 });
    expect(marks.edges[1]).toEqual({ point: "b", at: 1 });
  });

  it("marks nothing when the duration is zero", () => {
    expect(scrubMarks(0, [section(0), section(10)], { a: 1, b: 2 })).toEqual({ ticks: [], band: null, edges: [] });
  });
});

describe("fraction and timeAt", () => {
  it("clamp, and never divide by zero", () => {
    expect(fraction(5, 20)).toBe(0.25);
    expect(fraction(30, 20)).toBe(1);
    expect(fraction(-1, 20)).toBe(0);
    expect(fraction(5, 0)).toBe(0);
    expect(fraction(5, Number.NaN)).toBe(0);
    expect(timeAt(200, 100, 400, 20)).toBe(5);
    expect(timeAt(50, 100, 400, 20)).toBe(0);
    expect(timeAt(600, 100, 400, 20)).toBe(20);
    expect(timeAt(200, 100, 0, 20)).toBe(0);
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/player/scrub.test.ts`
Expected: FAIL: `./scrub` does not exist.

- [ ] **Step 3: Implement `fraction`, `timeAt` and `scrubMarks` in `scrub.ts`**

`scrubMarks` returns the empty marks when `fraction` would be meaningless (`!(duration > 0)` or not finite). Every position goes through `fraction`.

- [ ] **Step 4: Run them to verify they pass**

Run: `npm --prefix web test -- src/player/scrub.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/player/scrub.ts web/src/player/scrub.test.ts
git commit -m "feat(web): the scrubber's ticks, loop band and pointer time

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `[` and `]` set the loop

**Files:**
- Create: `web/src/test/engine.ts`, `web/src/player/keys.test.tsx`
- Modify: `web/src/player/keys.ts`

**Interfaces:**
- Produces, for every later component test:
  ```ts
  /** An engine over FakeMedia that has reported `duration`, with its frames run by hand. */
  export function fakeEngine(
    song: Song,
    options?: { duration?: number; media?: FakeMedia }, // duration defaults to song.duration
  ): {
    engine: PlaybackEngine;
    media: FakeMedia;
    frames: FakeFrames;
    /** Seek to t and run the frames that draw it, inside act(). */
    at: (t: number) => void;
  };
  ```
  It builds the engine with `requestFrame: frames.request`, `cancelFrame: frames.cancel` and `JOB_ID`, then calls `media.loadMetadata(duration)`.

- [ ] **Step 1: Write `fakeEngine` in `web/src/test/engine.ts`, then the failing tests**

```tsx
// @vitest-environment jsdom
function setup() {
  const { engine, at } = fakeEngine(buildSong(FIRST_SONG));
  renderHook(() => useTransportKeys(engine));
  return { engine, at };
}

const press = (key: string, init: KeyboardEventInit = {}, target: Element | Window = window) =>
  act(() => {
    fireEvent.keyDown(target, { key, ...init });
  });

describe("useTransportKeys", () => {
  it("sets loop A on [ and B on ], at the current time", () => {
    const { engine, at } = setup();
    at(2);
    press("[");
    at(6);
    press("]");
    expect(engine.getState().loop).toEqual({ a: 2, b: 6 });
  });

  it("leaves [ and ] typed into a text field alone", () => {
    const { engine } = setup();
    const field = document.createElement("input");
    document.body.append(field);
    press("[", {}, field);
    press("]", {}, field);
    expect(engine.getState().loop).toEqual({ a: null, b: null });
    field.remove();
  });

  it("leaves [ and ] with a modifier alone", () => {
    const { engine } = setup();
    press("[", { ctrlKey: true });
    press("]", { metaKey: true });
    press("[", { altKey: true });
    expect(engine.getState().loop).toEqual({ a: null, b: null });
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/player/keys.test.tsx`
Expected: FAIL on the first test: the loop stays `{ a: null, b: null }`.

- [ ] **Step 3: Add two branches to `useTransportKeys`**

`"["` and `"]"` each call `event.preventDefault()` and then `engine.setLoopPoint("a")` or `("b")`. They sit after the existing guards, so text fields, modifiers and `defaultPrevented` already leave them alone. Add the two keys to the doc comment.

- [ ] **Step 4: Run them to verify they pass**

Run: `npm --prefix web test -- src/player/keys.test.tsx src/player/Player.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/test/engine.ts web/src/player/keys.ts web/src/player/keys.test.tsx
git commit -m "feat(web): [ and ] set the loop's A and B

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Shared chrome, the tokens, and warnings on one line

**Files:**
- Create: `web/src/player/time.ts`, `web/src/player/time.test.ts`, `web/src/player/Button.tsx`, `web/src/icons.tsx`, `web/src/player/Warnings.test.tsx`
- Modify: `web/src/player/Controls.tsx`, `web/src/player/Warnings.tsx`, `web/src/player/Player.test.tsx`, `web/src/styles.css`

**Interfaces:**
- Produces:
  ```ts
  // player/time.ts: moved from Controls.tsx unchanged
  export function clock(seconds: number): string; // m:ss
  // player/Button.tsx: moved from Controls.tsx, plus `expanded` and `className`
  export function keepFocus(event: MouseEvent): void;
  export interface ButtonProps {
    onClick: () => void;
    pressed?: boolean;  // aria-pressed
    expanded?: boolean; // aria-expanded
    current?: boolean;  // aria-current="true" when true, absent otherwise (the sidebar, Task 8)
    label?: string;     // aria-label
    className?: string;
    children: ReactNode;
  }
  export function Button(props: ButtonProps): JSX.Element;
  // icons.tsx
  export function PlayIcon(): JSX.Element;
  export function PauseIcon(): JSX.Element;
  export function BackIcon(): JSX.Element;    // back 5 s
  export function ForwardIcon(): JSX.Element; // forward 5 s
  export function AlertIcon(): JSX.Element;
  export function Warnings({ warnings }: { warnings: readonly string[] }): JSX.Element | null;
  ```

- [ ] **Step 1: Move `clock` and its test**

Move `clock` to `time.ts`, and the `describe("clock")` block from `Player.test.tsx` to `time.test.ts`. Delete `Player.test.tsx`'s `import { clock } from "./Controls"`. Move `Button` and `keepFocus` to `Button.tsx`. `Controls.tsx` imports all three from their new homes, so the page still works until Task 12 deletes it.

- [ ] **Step 2: Write `icons.tsx`**

Each icon is `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true" focusable="false">`:

| Icon | Content |
|---|---|
| `PlayIcon` | `<path d="M8 5v14l11-7z"/>` |
| `PauseIcon` | `<path d="M7 5h4v14H7zM13 5h4v14h-4z"/>` |
| `BackIcon` | `<path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/>` and `<text x="12" y="15.5" fontSize="6.5" fontWeight="700" textAnchor="middle">5</text>` |
| `ForwardIcon` | `<path d="M4 13c0 4.4 3.6 8 8 8s8-3.6 8-8h-2c0 3.3-2.7 6-6 6s-6-2.7-6-6 2.7-6 6-6v4l5-5-5-5v4c-4.4 0-8 3.6-8 8z"/>` and the same `<text>` |
| `AlertIcon` | `<path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>` |

- [ ] **Step 3: Write the failing warnings tests**

```tsx
// @vitest-environment jsdom
const region = () => screen.getByRole("complementary", { name: "Warnings" });

describe("Warnings", () => {
  it("shows nothing for a clean document", () => {
    const { container } = render(<Warnings warnings={[]} />);
    expect(container.childElementCount).toBe(0);
  });

  it("shows a single warning's text, with no button", () => {
    render(<Warnings warnings={["Chord detection failed, so this tab has no chords."]} />);
    expect(region().textContent).toContain("Chord detection failed");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("collapses several warnings to a count, and expands them on demand", () => {
    render(<Warnings warnings={["one", "two", "three"]} />);
    expect(region().textContent).toContain("3 things to know about this tab");
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["one", "two", "three"]);
    expect(screen.getByRole("button", { name: "Hide" }).getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Show" }).getAttribute("aria-expanded")).toBe("false");
  });

  it("keeps a mouse click on Show from taking focus", () => {
    render(<Warnings warnings={["one", "two"]} />);
    expect(fireEvent.mouseDown(screen.getByRole("button", { name: "Show" }))).toBe(false);
  });
});
```

- [ ] **Step 4: Run them to verify the collapse tests fail**

Run: `npm --prefix web test -- src/player/Warnings.test.tsx src/player/time.test.ts`
Expected: the two tests with several warnings FAIL. The others PASS.

- [ ] **Step 5: Rewrite `Warnings`**

It keeps `<aside className="warnings" aria-label="Warnings">` and its doc comment's reason. With one warning it shows `AlertIcon` and that warning's text in a `<p>`. With more than one, it shows `AlertIcon`, a `<p>` saying "{n} things to know about this tab", and a `Button` with `expanded={open}` reading "Show" / "Hide". While `open`, the `<ul>` follows. `open` is `useState(false)` and is never persisted.

- [ ] **Step 6: Add the tokens and the warnings line to `styles.css`**

Add `--bg-raised` and `--on-accent` to both `:root` blocks, with the values under *Global Constraints*. `.warnings` becomes a flex row (`align-items: center; gap: 8px`), with the icon in `--accent` and the button pushed to the end (`margin-left: auto`). `.warnings ul` takes the full width (`flex-basis: 100%`).

- [ ] **Step 7: Run the web suite**

Run: `npm --prefix web test`
Expected: PASS, including `Player.test.tsx`'s two warnings tests, which pass unchanged.

- [ ] **Step 8: Commit**

```bash
git add web/src/player/time.ts web/src/player/time.test.ts web/src/player/Button.tsx web/src/icons.tsx \
  web/src/player/Warnings.tsx web/src/player/Warnings.test.tsx web/src/player/Controls.tsx \
  web/src/player/Player.test.tsx web/src/styles.css
git commit -m "feat(web): warnings on one line, with shared buttons, icons and tokens

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The view switch moves to the page

**Files:**
- Create: `web/src/player/ViewSwitch.tsx`, `web/src/player/ViewSwitch.test.tsx`, `web/src/player/TabOnly.test.tsx`
- Modify: `web/src/guitar/Guitar.tsx`, `web/src/guitar/Guitar.test.tsx`, `web/src/player/Player.tsx`, `web/src/player/Player.test.tsx`, `web/src/styles.css`

**Interfaces:**
- Consumes: `Button` (Task 5). It imports nothing from `guitar/`: `Player` narrows `PageView` to `"3d" | "2d"` before handing it to `Guitar`, whose `View` is the same two strings.
- Produces:
  ```ts
  export type PageView = "3d" | "2d" | "tab";
  /** 008's key, kept so that a returning user keeps their view. */
  export const VIEW_KEY = "guitarvis.guitar-view";
  /** The remembered view, and a setter that remembers it. A first visit, an unknown value, or storage that throws gives 3D. */
  export function useStoredView(): [PageView, (view: PageView) => void];
  export function ViewSwitch({ view, onChange }: { view: PageView; onChange: (view: PageView) => void }): JSX.Element;
  // Guitar.tsx
  export interface GuitarProps { song; engine; createRenderer?; view?: View } // view defaults to "3d"
  ```

- [ ] **Step 1: Move the toggle tests to `ViewSwitch.test.tsx`, and write the new ones**

```tsx
// @vitest-environment jsdom
function Harness() {
  const [view, setView] = useStoredView();
  return <ViewSwitch view={view} onChange={setView} />;
}
const pressed = (name: string) => screen.getByRole("button", { name }).getAttribute("aria-pressed");

describe("ViewSwitch", () => {
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("opens in 3D on a first visit", () => {
    render(<Harness />);
    expect(["3D", "Fretboard", "Tab only"].map(pressed)).toEqual(["true", "false", "false"]);
  });

  it("switches views, and remembers the choice", () => {
    const first = render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Fretboard" }));
    expect(localStorage.getItem(VIEW_KEY)).toBe("2d");
    first.unmount();

    const second = render(<Harness />);
    expect(pressed("Fretboard")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Tab only" }));
    expect(localStorage.getItem(VIEW_KEY)).toBe("tab");
    second.unmount();

    render(<Harness />);
    expect(pressed("Tab only")).toBe("true");
  });

  // Moved from Guitar.test.tsx, with "2D" read as "Fretboard":
  // "opens in 3D when the browser's storage throws, and still switches"
  // "ignores a stored view it does not know"

  it("keeps a mouse click from taking focus", () => {
    render(<Harness />);
    for (const name of ["3D", "Fretboard", "Tab only"]) {
      expect(fireEvent.mouseDown(screen.getByRole("button", { name }))).toBe(false);
    }
  });
});
```

In `Guitar.test.tsx`, delete "opens in 3D on a first visit", "switches views from the toggle, and remembers the choice", "opens in 3D when the browser's storage throws, and still switches" and "ignores a stored view it does not know". Rename "keeps a mouse click on the toggle from taking focus" to "keeps a mouse click on Reset view from taking focus", and drop its `2D` line. Drop `VIEW_KEY` from the import. `mount` also returns `song`. Then add:

```tsx
it("moves the camera when its view changes, on the same Stage and renderer", () => {
  const renderer = fakeRenderer();
  const createRenderer = vi.fn(() => renderer);
  const setView = vi.spyOn(Stage.prototype, "setView");
  const { song, engine, view } = mount(FIRST_SONG, renderer, createRenderer);

  view.rerender(<Guitar song={song} engine={engine} createRenderer={createRenderer} view="2d" />);

  expect(setView).toHaveBeenLastCalledWith("2d");
  expect(createRenderer).toHaveBeenCalledTimes(1);
  expect(renderer.dispose).not.toHaveBeenCalled();
});
```

In `Player.test.tsx`, add `localStorage.clear()` to `afterEach`, because the view now persists between tests. Then add:

```tsx
it("keeps the audio playing on one engine through a switch to Tab only and back", async () => {
  const media = mount();
  fireEvent.click(screen.getByRole("button", { name: "Play" }));
  const loads = media.loads.length;

  fireEvent.click(screen.getByRole("button", { name: "Tab only" }));
  expect(screen.queryByRole("img", { name: "Guitar" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "3D" }));
  await screen.findByRole("img", { name: "Guitar" });

  expect(media.paused).toBe(false);
  expect(media.loads).toHaveLength(loads);
});
```

Create `TabOnly.test.tsx`. It is its own file because it mocks the guitar's module, which the rest of `Player.test.tsx` needs for real:

```tsx
// @vitest-environment jsdom
const loaded = vi.hoisted(() => vi.fn());
vi.mock("../guitar/Guitar", () => {
  loaded();
  return { Guitar: () => <p>guitar stand-in</p> };
});

it("fetches the guitar's chunk only once a guitar view is chosen", async () => {
  localStorage.setItem(VIEW_KEY, "tab");
  const media = new FakeMedia();
  render(<Player song={buildSong(FIRST_SONG)} jobId={JOB_ID} createMedia={() => media} />);
  await act(async () => {});

  expect(screen.queryByText("guitar stand-in")).toBeNull();
  expect(loaded).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "3D" }));
  expect(await screen.findByText("guitar stand-in")).toBeTruthy();
  expect(loaded).toHaveBeenCalledTimes(1);
  localStorage.clear();
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/player src/guitar/Guitar.test.tsx`
Expected: FAIL in `tsc`: `./ViewSwitch` does not exist, and `Guitar` has no `view` prop.

- [ ] **Step 3: Write `ViewSwitch.tsx`**

`readView` and `writeView` come from `Guitar.tsx`, with `"tab"` accepted and the same try/catch fallbacks. `useStoredView` is `useState(readView)` plus a setter that writes. `ViewSwitch` renders `<div className="segmented" role="group" aria-label="View">` holding three `Button`s with `pressed`.

- [ ] **Step 4: Make `Guitar` take `view`**

Delete `VIEW_KEY`, `VIEWS`, `readView`, `writeView`, the `view` state and the `.guitar-views` group. `view` becomes a prop, defaulting to `"3d"`. The `[view]` effect keeps `viewRef.current = view; stageRef.current?.setView(view);` and loses `writeView`. In the doc comment, "on a view toggle" becomes "on a view change".

- [ ] **Step 5: `Player` owns the view**

`const [view, setView] = useStoredView();` goes before the `engine === null` return. Render `<ViewSwitch view={view} onChange={setView} />` above `<Warnings>` for now; Task 7 moves it into the header. Wrap the guitar's boundary, `Suspense` and `<Guitar … view={view} />` in `view !== "tab" && (…)`.

- [ ] **Step 6: Styles**

Delete `.guitar-views`. Add `.segmented`: an inline-flex group with a 1 px `--border` border, an 8 px radius and 2 px padding. Its buttons are borderless on a transparent background and use `.controls button`'s padding. `[aria-pressed="true"]` gets the `--bg-raised` background and `--accent` text.

- [ ] **Step 7: Run the web suite**

Run: `npm --prefix web test`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add web/src/player/ViewSwitch.tsx web/src/player/ViewSwitch.test.tsx web/src/player/TabOnly.test.tsx \
  web/src/guitar/Guitar.tsx web/src/guitar/Guitar.test.tsx web/src/player/Player.tsx \
  web/src/player/Player.test.tsx web/src/styles.css
git commit -m "feat(web): the page chooses 3D, Fretboard or Tab only

The guitar takes its view as a prop. Tab only never fetches the guitar's
chunk. The storage key is 008's, so a returning user keeps their view.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The header, and the song's tempo

**Files:**
- Create: `web/src/player/Header.tsx`, `web/src/player/Header.test.tsx`
- Modify: `web/src/song.ts`, `web/src/song.test.ts`, `web/src/player/Player.tsx`, `web/src/pages/SongPage.tsx`, `web/src/pages/SongPage.test.tsx`, `web/src/styles.css`

**Interfaces:**
- Consumes: `ViewSwitch`, `PageView` (Task 6); `clock` (Task 5); `stringLabels` from `labels.ts`; `followLink` from `routing.ts`.
- Produces:
  ```ts
  // song.ts
  export const STANDARD_TUNING: readonly string[]; // now exported
  interface Song { /* … */ tempo: number | null } // timing.tempo_bpm_avg; null unless a positive finite number
  // player/Header.tsx
  /** "Standard tuning", or the strings' letters, lowest first: "D A D G B E tuning". */
  export function tuningName(tuning: readonly string[]): string;
  /** Length, tuning, and the tempo when there is one, joined by " · ". */
  export function details(song: Song): string;
  export function Header(props: { song: Song; view: PageView; onView: (view: PageView) => void }): JSX.Element;
  ```

- [ ] **Step 1: Write the failing tests**

`song.test.ts`:

```ts
it("reads the tempo, and null when there is none", () => {
  expect(buildSong(FIRST_SONG).tempo).toBeCloseTo(117.454, 3);
  expect(buildSong({ ...FIRST_SONG, timing: {} }).tempo).toBeNull();
  expect(buildSong({ ...FIRST_SONG, timing: { tempo_bpm_avg: 0 } }).tempo).toBeNull();
});
```

`Header.test.tsx` (jsdom):

```tsx
const song = (fields: Partial<TabDocument> = {}) => buildSong({ ...FIRST_SONG, ...fields });

describe("details", () => {
  it("gives the length, the tuning and the tempo", () => {
    expect(details(song())).toBe("0:13 · Standard tuning · about 117 bpm");
  });
  it("leaves out a tempo the document lacks", () => {
    expect(details(song({ timing: {} }))).toBe("0:13 · Standard tuning");
  });
  it("names a tuning that is not standard by its strings", () => {
    expect(details(song({ instrument: { tuning: ["D2", "A2", "D3", "G3", "B3", "E4"] } }))).toBe("0:13 · D A D G B E tuning · about 117 bpm");
  });
});

describe("Header", () => {
  it("titles the page, links back to the upload page, and offers the views", () => {
    render(<Header song={song()} view="3d" onView={() => {}} />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Test");
    expect(screen.getByRole("link", { name: "Upload another song" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("group", { name: "View" })).toBeTruthy();
  });
});
```

`SongPage.test.tsx`:

```tsx
it("titles the page once, in the player's header", async () => {
  const { api } = scripted([jobView({ status: "succeeded" })]);
  render(<SongPage jobId={JOB_ID} api={api} createMedia={createMedia} />);
  await settle();
  await wait(POLL_MS);

  expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
  expect(screen.getAllByRole("heading", { level: 1 }).map((h) => h.textContent)).toEqual([FIRST_SONG.source.title]);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/song.test.ts src/player/Header.test.tsx src/pages/SongPage.test.tsx`
Expected: FAIL: there is no `tempo` and no `./Header`.

- [ ] **Step 3: Implement**

- `song.ts`: export `STANDARD_TUNING`, and set `tempo` from `doc.timing.tempo_bpm_avg`, or `null` unless it is a positive finite number.
- `Header.tsx`: a `<header className="song-header">` holding the back link (`<a href="/" onClick={followLink} className="back"><span aria-hidden="true">‹</span> Upload another song</a>`), then the `<h1>` and `<p className="details">`, then `ViewSwitch`. `tuningName` compares element-wise with `STANDARD_TUNING`, and otherwise joins `stringLabels(tuning)` with spaces. `details` uses `clock(song.duration)` and `Math.round(tempo)`.
- `Player.tsx`: `<Header song={song} view={view} onView={setView} />` replaces the bare `ViewSwitch`.
- `SongPage.tsx`: `const showsPlayer = job?.status === "succeeded" && loaded.kind === "ready";`, and the `<h1>` renders only when `!showsPlayer`.
- `styles.css`: `.song-header` is a grid of `auto 1fr auto` with `align-items: center`. The `h1` has no margin and is about 22 px. `.details` is `--muted` at 14 px. Below 900 px the view switch wraps onto its own row.

- [ ] **Step 4: Run the web suite**

Run: `npm --prefix web test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/song.ts web/src/song.test.ts web/src/player/Header.tsx web/src/player/Header.test.tsx \
  web/src/player/Player.tsx web/src/pages/SongPage.tsx web/src/pages/SongPage.test.tsx web/src/styles.css
git commit -m "feat(web): the song page's header, with length, tuning and tempo

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The sections sidebar, and the page's grid

**Files:**
- Create: `web/src/player/Sections.tsx`, `web/src/player/Sections.test.tsx`
- Modify: `web/src/player/Player.tsx`, `web/src/player/Player.test.tsx`, `web/src/styles.css`

**Interfaces:**
- Consumes: `TrackCursor`, `samePosition` (Task 1); `distinctSymbols` (Task 2); `fakeEngine` (Task 4); `Button`, `clock` (Task 5).
- Produces: `export function Sections({ song, engine }: { song: Song; engine: PlaybackEngine }): JSX.Element`

- [ ] **Step 1: Write the failing tests**

```tsx
// @vitest-environment jsdom
const SECTIONS = [
  { t: 0, dur: 4, label: "Intro" },
  { t: 4, dur: 5, label: "Verse 1" },
  { t: 9, dur: 4.871, label: "Chorus" },
];

function mount(fields: Partial<TabDocument> = { sections: SECTIONS }) {
  const song = buildSong({ ...FIRST_SONG, ...fields });
  const fake = fakeEngine(song);
  const onRender = vi.fn();
  render(
    <Profiler id="sections" onRender={onRender}>
      <Sections song={song} engine={fake.engine} />
    </Profiler>,
  );
  return { ...fake, onRender };
}
const current = () => screen.getAllByRole("button").filter((b) => b.getAttribute("aria-current") === "true").map((b) => b.textContent);

describe("Sections", () => {
  it("lists every section with its start", () => {
    mount();
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Intro 0:00", "Verse 1 0:04", "Chorus 0:09"]);
  });

  it("seeks to a section's start on a click, and leaves the loop alone", () => {
    const { engine, at } = mount();
    at(1);
    act(() => void engine.setLoopPoint("a"));
    at(3);
    act(() => void engine.setLoopPoint("b"));

    fireEvent.click(screen.getByRole("button", { name: /^Chorus/ }));

    expect(engine.getState().time).toBe(9);
    expect(engine.getState().loop).toEqual({ a: 1, b: 3 });
  });

  it("highlights the current section as the song plays, and the earlier one after a seek back", () => {
    const { at } = mount();
    at(5);
    expect(current()).toEqual(["Verse 1 0:04"]);
    at(10);
    expect(current()).toEqual(["Chorus 0:09"]);
    at(2);
    expect(current()).toEqual(["Intro 0:00"]);
  });

  it("renders again only when the section changes", () => {
    const { at, onRender } = mount();
    at(5);
    const renders = onRender.mock.calls.length;
    at(5.5);
    at(6);
    at(8.9);
    expect(onRender).toHaveBeenCalledTimes(renders);
    at(9.5);
    expect(onRender).toHaveBeenCalledTimes(renders + 1);
  });

  it("says when there are no sections", () => {
    mount({ sections: [] });
    expect(screen.getByRole("heading", { name: "Sections" })).toBeTruthy();
    expect(screen.getByText("No sections found")).toBeTruthy();
  });

  it("lists the song's chords once each, first heard first", () => {
    const chord = (t: number, symbol: string) => ({ t, dur: 1, symbol, confidence: 0.9 });
    mount({ sections: SECTIONS, chords: [chord(0, "Am"), chord(1, "C"), chord(2, "Am"), chord(3, "G")] });
    expect(screen.getByRole("heading", { name: "Chords" })).toBeTruthy();
    expect(screen.getByText("Am C G")).toBeTruthy();
  });

  it("keeps a mouse click on a section from taking focus", () => {
    mount();
    expect(fireEvent.mouseDown(screen.getByRole("button", { name: /^Intro/ }))).toBe(false);
  });
});
```

In `Player.test.tsx`, add a layout test that Tasks 9 and 12 extend:

```tsx
it("lays out the header, then warnings, guitar and tab strip, with the sections after them", async () => {
  mount({ warnings: ["w"] });
  const order = [
    screen.getByRole("heading", { level: 1 }),
    screen.getByRole("complementary", { name: "Warnings" }),
    await screen.findByRole("img", { name: "Guitar" }),
    screen.getByLabelText("Tab"),
    screen.getByRole("complementary", { name: "Sections" }),
  ];
  for (let i = 1; i < order.length; i++) {
    expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  }
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/player/Sections.test.tsx src/player/Player.test.tsx`
Expected: FAIL: there is no `./Sections`.

- [ ] **Step 3: Write `Sections`**

`<aside className="sections" aria-label="Sections">` holds an `<h2>Sections</h2>`. Under it is either `<p>No sections found</p>` or an `<ol>` with one `<li>` per section. Each `<li>` holds a `Button` containing the label, a space, then `<span className="time">{clock(section.t)}</span>`. A click calls `engine.seek(section.t)`. The current one is passed `current`, so it gets `aria-current="true"` and the rest get no attribute. When there are chords, `<h2>Chords</h2><p className="chord-list">{distinctSymbols(song.chords).join(" ")}</p>` follows.

Following playback: a `TrackCursor(song.sections)` and the last `Position`, both made inside an effect on `[song, engine]`. Its `engine.onFrame` callback calls `setCurrent(position.current)` only when `!samePosition(last, position)`.

- [ ] **Step 4: Lay out the page**

`Player` renders `Header`, then `<div className="player-body">` holding `<div className="player-main">` (warnings, guitar, tab strip) and `<Sections>`, then `Controls`. In `styles.css`:
- `.song-page { max-width: 1280px; }`
- `.player-body { display: grid; grid-template-columns: minmax(0, 1fr) 248px; gap: 16px; align-items: start; }`. Use `minmax(0, …)`, not a bare `1fr`: a bare `1fr` column will not shrink below its content, and the lane's overflow (Task 9) would widen it.
- `@media (max-width: 899px) { .player-body { grid-template-columns: minmax(0, 1fr); } }`
- `.sections`: `--panel` background, 8 px radius, 12 px padding. `h2` is small uppercase `--muted`. Its buttons are full width with the label left and the time right in monospace. `[aria-current="true"]` has `--accent` text on `--bg-raised`, with a 3 px `--accent` bar on the left as an inset shadow.

- [ ] **Step 5: Run the web suite**

Run: `npm --prefix web test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/src/player/Sections.tsx web/src/player/Sections.test.tsx \
  web/src/player/Player.tsx web/src/player/Player.test.tsx web/src/styles.css
git commit -m "feat(web): a sections sidebar that jumps and follows the song

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The chord lane

**Files:**
- Create: `web/src/player/ChordLane.tsx`, `web/src/player/ChordLane.test.tsx`
- Modify: `web/src/player/Player.tsx`, `web/src/player/Player.test.tsx`, `web/src/styles.css`

**Interfaces:**
- Consumes: `TrackCursor`, `samePosition` (Task 1); `laneCells`, `cellState` (Task 2); `fakeEngine` (Task 4).
- Produces: `export function ChordLane({ song, engine }: { song: Song; engine: PlaybackEngine }): JSX.Element | null`

- [ ] **Step 1: Write the failing tests**

```tsx
// @vitest-environment jsdom
const chord = (t: number, symbol: string, confidence = 0.9, dur = 2) => ({ t, dur, symbol, confidence });
const FOUR = [chord(0, "Am"), chord(2, "C"), chord(4, "G"), chord(6, "D")];

function mount(chords: Chord[] = FOUR) {
  const song = buildSong({ ...FIRST_SONG, chords });
  const fake = fakeEngine(song);
  const onRender = vi.fn();
  render(
    <Profiler id="lane" onRender={onRender}>
      <ChordLane song={song} engine={fake.engine} />
    </Profiler>,
  );
  return { ...fake, onRender };
}
const cells = () => within(screen.getByRole("list", { name: "Chord lane" })).getAllByRole("listitem");
const states = () => cells().map((c) => c.dataset.state);

describe("ChordLane", () => {
  it("draws one cell per chord, in order", () => {
    mount();
    expect(cells().map((c) => c.textContent)).toEqual(["Am", "C", "G", "D"]);
  });

  it("is not drawn for a song with no chords", () => {
    mount([]);
    expect(screen.queryByRole("list", { name: "Chord lane" })).toBeNull();
  });

  it("marks played, current and coming cells as the song plays", () => {
    const { at } = mount();
    at(3);
    expect(states()).toEqual(["played", "current", "coming", "coming"]);
    expect(cells()[1].getAttribute("aria-current")).toBe("true");
    at(0.5);
    expect(states()).toEqual(["current", "coming", "coming", "coming"]);
  });

  it("has no current cell between chords", () => {
    const { at } = mount([chord(0, "Am", 0.9, 1), chord(2, "C", 0.9, 1)]);
    at(1.5);
    expect(states()).toEqual(["played", "coming"]);
  });

  it("fades a weak chord by the chord thresholds", () => {
    mount([chord(0, "Am", CHORD_HIDE), chord(2, "C", CHORD_FULL)]);
    expect(cells().map((c) => c.style.opacity)).toEqual([String(FADED), "1"]);
  });

  it("renders again only when the current chord changes", () => {
    const { at, onRender } = mount();
    at(2.5);
    const renders = onRender.mock.calls.length;
    at(3);
    at(3.5);
    expect(onRender).toHaveBeenCalledTimes(renders);
    at(4.5);
    expect(onRender).toHaveBeenCalledTimes(renders + 1);
  });
});
```

In `Player.test.tsx`, put `screen.getByRole("list", { name: "Chord lane" })` between the guitar and the tab strip in the layout test, and add:

```tsx
it("keeps the chord lane in Tab only", () => {
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Tab only" }));
  expect(screen.getByRole("list", { name: "Chord lane" })).toBeTruthy();
  expect(screen.queryByRole("img", { name: "Guitar" })).toBeNull();
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/player/ChordLane.test.tsx src/player/Player.test.tsx`
Expected: FAIL: there is no `./ChordLane`.

- [ ] **Step 3: Write `ChordLane`**

- `cells = useMemo(() => laneCells(song.chords), [song])`.
- A `Position` in state, starting at `{ current: -1, next: 0 }`. It follows playback as `Sections` does: own `TrackCursor`, and `setState` only when `!samePosition`.
- `<ol className="chord-lane" aria-label="Chord lane" ref={laneRef}>` holds one `<li className="chord-cell" data-state={…} aria-current={… ? "true" : undefined} style={{ opacity }}>` per cell.
- When `position` changes, an effect centres the current cell, or the next one between chords: `lane.scrollLeft = cell.offsetLeft + cell.offsetWidth / 2 - lane.clientWidth / 2`. Do not use `scrollIntoView`, which would also scroll the page when the lane is off screen (and jsdom lacks it).
- When there are no chords it returns `null`. Put that return after the hooks, or split the component in two.

- [ ] **Step 4: Place it, and style it**

In `Player`, `<ChordLane>` goes between the guitar block and `<TabStrip>`, outside the `view !== "tab"` condition. In `styles.css`:
- `.chord-lane` is `position: relative` (so that cells' `offsetLeft` is measured from it) and `display: flex` with a 6 px gap. It has `overflow-x: auto`, `scroll-behavior: smooth`, no list style, and a 12 px bottom margin.
- `.chord-cell` is `flex: 0 0 64px`, centred, in bold 14 px monospace, with a 6 px radius.
- The states take the colours under *Global Constraints*. `current` gets `box-shadow: 0 0 0 2px var(--accent)`.
- `@media (prefers-reduced-motion: reduce) { .chord-lane { scroll-behavior: auto; } }`

- [ ] **Step 5: Run the web suite**

Run: `npm --prefix web test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/src/player/ChordLane.tsx web/src/player/ChordLane.test.tsx web/src/player/Player.tsx \
  web/src/player/Player.test.tsx web/src/styles.css
git commit -m "feat(web): a chord lane under the guitar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The guitar's chord overlay and legend

**Files:**
- Create: `web/src/guitar/NowNext.tsx`, `web/src/guitar/NowNext.test.tsx`
- Modify: `web/src/guitar/Guitar.tsx`, `web/src/guitar/Guitar.test.tsx`, `web/src/styles.css`

**Interfaces:**
- Consumes: `TrackCursor`, `inWindow` from `playback/cursor`; `isHidden`, `emphasis`, `CHORD_THRESHOLDS`, `FADED` from `confidence.ts`; `fakeEngine` (Task 4).
- Produces:
  ```ts
  /** The chord now, in the guitar's top-left, and the one after it. Hidden inside a hidden passage, where the guitar shows the chord itself. */
  export function NowNext({ song, engine }: { song: Song; engine: PlaybackEngine }): JSX.Element | null;
  /** What the dots mean: sounding, and less sure. */
  export function Legend(): JSX.Element;
  ```

- [ ] **Step 1: Write the failing tests**

`NowNext.test.tsx` (jsdom). With `notes: []` there are no hidden passages, so only the chords matter:

```tsx
const chord = (t: number, symbol: string, confidence = 0.9) => ({ t, dur: 1, symbol, confidence });

function mount(doc: TabDocument) {
  const song = buildSong(doc);
  const fake = fakeEngine(song);
  const view = render(<NowNext song={song} engine={fake.engine} />);
  return { ...fake, box: () => view.container.querySelector(".guitar-chords") as HTMLElement | null };
}

describe("NowNext", () => {
  const AM_C = { ...FIRST_SONG, notes: [], chords: [chord(1, "Am"), chord(2, "C")] };

  it("shows the chord sounding now and the one after it", () => {
    const { at, box } = mount(AM_C);
    at(1.5);
    expect(box()?.querySelector(".now")?.textContent).toBe("Am");
    expect(box()?.querySelector(".next")?.textContent).toBe("next C");
    at(2.5);
    expect(box()?.querySelector(".now")?.textContent).toBe("C");
    expect(box()?.querySelector(".next")).toBeNull();
  });

  it("before the first chord, shows only what is next", () => {
    const { at, box } = mount(AM_C);
    at(0.5);
    expect(box()?.querySelector(".now")).toBeNull();
    expect(box()?.querySelector(".next")?.textContent).toBe("next Am");
  });

  it("fades a weak chord as the lane does", () => {
    const { at, box } = mount({ ...FIRST_SONG, notes: [], chords: [chord(1, "Am", CHORD_HIDE)] });
    at(1.5);
    expect((box()?.querySelector(".now") as HTMLElement).style.opacity).toBe(String(FADED));
  });

  it("hides inside a hidden passage, where the guitar shows the chord itself", () => {
    const hiddenAm = {
      ...FIRST_SONG,
      notes: [1, 1.3, 1.6].map((t, i) => ({ id: `w${i}`, t, dur: 0.25, midi: 57, string: 2, fret: 7, confidence: 0.05 })),
      chords: [{ t: 1, dur: 2, symbol: "Am", confidence: 0.9 }],
    };
    const { at, box } = mount(hiddenAm);
    at(1.3);
    expect(box()?.hidden).toBe(true);
    at(2.5);
    expect(box()?.hidden).toBe(false);
  });

  it("draws nothing for a song with no chords", () => {
    const { box } = mount({ ...FIRST_SONG, chords: [] });
    expect(box()).toBeNull();
  });
});
```

`Guitar.test.tsx`, added:

```tsx
it("shows the legend and the chord overlay, and neither without WebGL", () => {
  const first = mount();
  expect(screen.getByText("Sounding")).toBeTruthy();
  expect(screen.getByText("Less sure")).toBeTruthy();
  expect(screen.queryByText("Next")).toBeNull();
  expect(first.view.container.querySelector(".guitar-chords")).toBeTruthy();
  first.view.unmount();

  const noWebGL = () => {
    throw new Error("Error creating WebGL context.");
  };
  const second = mount(FIRST_SONG, fakeRenderer(), noWebGL);
  expect(screen.queryByText("Sounding")).toBeNull();
  expect(second.view.container.querySelector(".guitar-chords")).toBeNull();
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/guitar/NowNext.test.tsx src/guitar/Guitar.test.tsx`
Expected: FAIL: there is no `./NowNext`.

- [ ] **Step 3: Write `NowNext` and `Legend`**

`NowNext` follows playback in an effect on `[song, engine]`, with its own `TrackCursor(song.chords)`. On each frame it works out `{ now: Chord | null, next: Chord | null, hidden }`:
- `now` is `chords[position.current]`, or null.
- `next` is `chords[position.next]`, or null.
- `hidden` is `isHidden(inWindow(song.hidden, t, t, (p) => p.from, (p) => p.to), t)`.

It calls `setState` only when one of the three changes (compare the chords by identity). It renders `<div className="guitar-chords" hidden={hidden}>`. Inside are `<span className="now" style={{ opacity: emphasis(now.confidence, CHORD_THRESHOLDS) }}>` when there is a `now`, and `<span className="next">next {symbol}</span>` when there is a `next`. It returns `null` when the song has no chords.

`Legend` renders `<ul className="guitar-legend" aria-label="Legend">` with two items: a `.legend-dot` then "Sounding", and a `.legend-dot` at `style={{ opacity: FADED }}` then "Less sure".

- [ ] **Step 4: Put them in the panel**

`Guitar` renders `<NowNext song={song} engine={engine} />` and `<Legend />` in the branch with "Reset view", never over the WebGL or failure message.

- [ ] **Step 5: Styles**

- `.guitar-chords` sits absolutely at `top: 8px; left: 12px`. It is a flex row with a 12 px gap and baseline alignment, has `pointer-events: none`, and wears `.guitar-message`'s halo `text-shadow`.
- `.guitar-chords[hidden] { display: none; }`. Flex would beat the attribute, as the comment on `.guitar-message[hidden]` says.
- `.guitar-chords .now` takes `.guitar-message.chord`'s font and `--guitar-chord` colour. `.next` is 15 px system-ui in `--muted`.
- `.guitar-legend` sits absolutely at `left: 12px; bottom: 8px`. It is a flex row of 13 px `--guitar-text` with no list style and `pointer-events: none`.
- `.legend-dot` is a 10 px `--guitar-dot` circle.

- [ ] **Step 6: Run the web suite**

Run: `npm --prefix web test`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add web/src/guitar/NowNext.tsx web/src/guitar/NowNext.test.tsx web/src/guitar/Guitar.tsx \
  web/src/guitar/Guitar.test.tsx web/src/styles.css
git commit -m "feat(web): the guitar shows the chord now and next, and a legend

No \"Next\" in the legend: approach rings stay dropped, as 007 decided.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: The scrubber

**Files:**
- Create: `web/src/player/Scrubber.tsx`, `web/src/player/Scrubber.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `fraction`, `timeAt`, `scrubMarks` (Task 3); `fakeEngine` (Task 4); `clock` (Task 5); `SEEK_STEP_SEC`; `useTransportKeys` (test only).
- Produces:
  ```ts
  export interface ScrubberProps {
    engine: PlaybackEngine;
    sections: readonly Section[];
    /** The current section's label, spoken with the time; null when none is current. */
    section: string | null;
  }
  export function Scrubber(props: ScrubberProps): JSX.Element;
  ```

- [ ] **Step 1: Write the failing tests**

```tsx
// @vitest-environment jsdom
const SECTIONS = [
  { t: 0, dur: 5, label: "Intro" },
  { t: 5, dur: 5, label: "Verse 1" },
  { t: 10, dur: 10, label: "Chorus" },
];
const RECT = { left: 100, width: 400, top: 0, right: 500, bottom: 24, height: 24, x: 100, y: 0, toJSON: () => ({}) } as DOMRect;

function mount() {
  const song = buildSong({ ...FIRST_SONG, sections: SECTIONS });
  const fake = fakeEngine(song, { duration: 20 });
  render(<Scrubber engine={fake.engine} sections={song.sections} section="Verse 1" />);
  const slider = screen.getByRole("slider", { name: "Position" });
  vi.spyOn(slider, "getBoundingClientRect").mockReturnValue(RECT);
  return { ...fake, slider };
}
const part = (slider: HTMLElement, name: string) => slider.querySelector(`.${name}`) as HTMLElement;

describe("Scrubber", () => {
  afterEach(() => vi.restoreAllMocks());

  it("is a slider over the song, speaking the time and the section", () => {
    const { slider, at } = mount();
    at(7);
    expect(["aria-valuemin", "aria-valuemax", "aria-valuenow", "aria-valuetext"].map((a) => slider.getAttribute(a))).toEqual(["0", "20", "7", "0:07, Verse 1"]);
  });

  it("moves the knob and the played part with each frame", () => {
    const { slider, at } = mount();
    at(5);
    expect(part(slider, "scrub-head").style.transform).toBe("translateX(25%)");
    expect(part(slider, "scrub-played").style.transform).toBe("scaleX(0.25)");
  });

  it("draws a tick at each section after the first, and the loop", () => {
    const { slider, engine, at } = mount();
    at(5);
    act(() => void engine.setLoopPoint("a"));
    at(15);
    act(() => void engine.setLoopPoint("b"));
    expect([...slider.querySelectorAll<HTMLElement>(".scrub-tick")].map((t) => t.style.left)).toEqual(["25%", "50%"]);
    const band = part(slider, "scrub-band");
    expect([band.style.left, band.style.width]).toEqual(["25%", "50%"]);
    expect(slider.querySelectorAll(".scrub-edge")).toHaveLength(2);
  });

  it("previews a drag without seeking, and seeks once on release, whatever the frames do meanwhile", () => {
    const { slider, engine, frames } = mount();
    const seek = vi.spyOn(engine, "seek");

    fireEvent.pointerDown(slider, { clientX: 200, pointerId: 1 });
    expect(screen.getByText("0:05")).toBeTruthy();
    act(() => {
      engine.redraw(); // a frame at t = 0, mid-drag
      frames.flush();
    });
    expect(part(slider, "scrub-head").style.transform).toBe("translateX(25%)");

    fireEvent.pointerMove(slider, { clientX: 300, pointerId: 1 });
    expect(part(slider, "scrub-head").style.transform).toBe("translateX(50%)");
    expect(seek).not.toHaveBeenCalled();

    fireEvent.pointerUp(slider, { clientX: 300, pointerId: 1 });
    expect(seek).toHaveBeenCalledTimes(1);
    expect(seek).toHaveBeenCalledWith(10);
    expect(screen.queryByText("0:10")).toBeNull();
  });

  it("drops a cancelled drag without seeking", () => {
    const { slider, engine, frames } = mount();
    const seek = vi.spyOn(engine, "seek");
    fireEvent.pointerDown(slider, { clientX: 300, pointerId: 1 });
    fireEvent.pointerCancel(slider, { pointerId: 1 });
    act(() => frames.flush());
    expect(seek).not.toHaveBeenCalled();
    expect(part(slider, "scrub-head").style.transform).toBe("translateX(0%)");
  });

  it("seeks five seconds once per arrow key, though the page's keys listen too", () => {
    const { slider, engine } = mount();
    renderHook(() => useTransportKeys(engine));
    const key = (k: string) => act(() => void fireEvent.keyDown(slider, { key: k }));
    key("ArrowRight");
    expect(engine.getState().time).toBe(5);
    key("ArrowLeft");
    expect(engine.getState().time).toBe(0);
    key("End");
    expect(engine.getState().time).toBe(20);
    key("Home");
    expect(engine.getState().time).toBe(0);
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/player/Scrubber.test.tsx`
Expected: FAIL: there is no `./Scrubber`.

- [ ] **Step 3: Write `Scrubber`**

It reads `duration`, `time` and `loop` through `useSyncExternalStore(engine.subscribe, engine.getState)`, and `marks = scrubMarks(duration, sections, loop)`.

```
<div className="scrubber" role="slider" tabIndex={0} aria-label="Position"
     aria-valuemin={0} aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(shown)}
     aria-valuetext={section === null ? clock(shown) : `${clock(shown)}, ${section}`}>
  <div className="scrub-track"><div className="scrub-played" ref={playedRef} /></div>
  {band}  {edges, data-point}  {ticks}          ← left/width as `${f * 100}%`
  <div className="scrub-head" ref={headRef}>
    <div className="scrub-knob" />
    {preview !== null && <span className="scrub-preview">{clock(preview)}</span>}
  </div>
</div>
```

`shown` is `preview ?? time`. The knob and the played part are never styled from JSX: only `place(f)` writes them, setting `head.style.transform = translateX(${f * 100}%)` and `played.style.transform = scaleX(${f})`. Otherwise a re-render at 4 Hz and the frames would fight over them.

- Frames: an effect on `[engine]` registers `engine.onFrame((t) => { if (drag.current === null) place(fraction(t, engine.getState().duration)); })`.
- `pointerdown` (primary button only): `currentTarget.setPointerCapture?.(pointerId)`, because jsdom lacks it. Then `t = timeAt(clientX, rect.left, rect.width, duration)`, `drag.current = t`, `place(fraction(t, duration))` and `setPreview(t)`.
- `pointermove`: the same as `pointerdown`, but only while `drag.current !== null`.
- `pointerup`: while dragging, `engine.seek(drag.current)`, then clear the drag and the preview.
- `pointercancel` and `lostpointercapture`: clear the drag and the preview, then `engine.redraw()` so the knob returns. After a `pointerup` there is no drag left, so they do nothing.
- `keydown`: ArrowRight and ArrowUp call `engine.seekBy(SEEK_STEP_SEC)`. ArrowLeft and ArrowDown call `engine.seekBy(-SEEK_STEP_SEC)`. Home calls `engine.seek(0)` and End calls `engine.seek(duration)`. Each one calls `preventDefault()`, which is what stops the window's handler seeking again. Other keys pass through.

- [ ] **Step 4: Styles**

- `.scrubber` is `position: relative`, about 24 px tall, `touch-action: none`, with `cursor: pointer`. It has a `:focus-visible` outline in `--accent`.
- `.scrub-track` is a 4 px `--border` bar, centred vertically. `.scrub-played` is `inset: 0`, in `--accent`, with `transform-origin: left`.
- `.scrub-band` is a `--tab-loop` fill at `opacity: 0.25`. `.scrub-edge` is a 2 px `--tab-loop` line. `.scrub-tick` is a 1 px `--muted` line on the middle half of the height.
- `.scrub-head` is `position: absolute; inset: 0; pointer-events: none`. The percentage in its `translateX` is of its own width, which is the track's. `.scrub-knob` is a 14 px `--accent` circle centred on the head's left edge. `.scrub-preview` sits above the knob in monospace.

- [ ] **Step 5: Run them to verify they pass**

Run: `npm --prefix web test -- src/player/Scrubber.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/src/player/Scrubber.tsx web/src/player/Scrubber.test.tsx web/src/styles.css
git commit -m "feat(web): a scrubber with section ticks and the loop

A drag previews and seeks once on release. The knob moves by style
writes on each frame, never through React.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: The docked transport

**Files:**
- Create: `web/src/player/Transport.tsx`, `web/src/player/Transport.test.tsx`
- Delete: `web/src/player/Controls.tsx`
- Modify: `web/src/player/Player.tsx`, `web/src/player/Player.test.tsx`, `web/src/styles.css`

**Interfaces:**
- Consumes: `TrackCursor` (Task 1); `fakeEngine` (Task 4); `Button`, `clock`, icons (Task 5); `Scrubber` (Task 11).
- Produces: `export function Transport({ song, engine }: { song: Song; engine: PlaybackEngine }): JSX.Element`

- [ ] **Step 1: Move the control tests, and write the new ones**

Move these tests from `Player.test.tsx` to `Transport.test.tsx` unchanged, except that they call the `mount` below and take `media` from its result (`const { media } = mount()`). The no-stretch test passes its prepared media as `mount({}, { media })`:
- "plays and pauses from its button"
- "sets the speed, and shows which is on"
- "offers no speed control where pitch cannot be kept"
- "switches to the guitar stem"
- "says when the audio cannot be played, and offers the other track and a reload"
- "suggests the mix when the guitar is what failed"
- "keeps the audio toggle usable in the error state, and clears the alert with it"

Delete "keeps a mouse click from leaving focus on a control" from `Player.test.tsx`; the last test below replaces it. `Player.test.tsx` keeps the keys, the tab strip's sizing, the guitar, the warnings, the layout and the view tests.

```tsx
// @vitest-environment jsdom
const SECTIONS = [
  { t: 0, dur: 60, label: "Intro" },
  { t: 60, dur: 60, label: "Verse 1" },
];

function mount(fields: Partial<TabDocument> = {}, options: { duration?: number; media?: FakeMedia } = {}) {
  const song = buildSong({ ...FIRST_SONG, ...fields });
  const fake = fakeEngine(song, options);
  render(<Transport song={song} engine={fake.engine} />);
  return fake;
}
const button = (name: string | RegExp) => screen.getByRole("button", { name });

describe("Transport", () => {
  // …the seven moved tests…

  it("labels its icon buttons, and seeks five seconds either way", () => {
    const { engine, at } = mount({}, { duration: 120 });
    at(10);
    fireEvent.click(button("Forward 5 seconds"));
    expect(engine.getState().time).toBe(15);
    fireEvent.click(button("Back 5 seconds"));
    expect(engine.getState().time).toBe(10);
    fireEvent.click(button("Play"));
    expect(button("Pause")).toBeTruthy();
  });

  it("shows the loop's times once set, and clears them", () => {
    const { at } = mount({}, { duration: 120 });
    at(40);
    fireEvent.click(button("Set loop start"));
    at(74);
    fireEvent.click(button("Set loop end"));
    expect(button("Set loop start (0:40)").textContent).toBe("A 0:40");
    expect(button("Set loop end (1:14)").textContent).toBe("B 1:14");

    fireEvent.click(button("Clear loop"));
    expect(button("Set loop start").textContent).toBe("A");
    expect(button("Set loop end").textContent).toBe("B");
  });

  it("shows the time with the current section, and the song's length", () => {
    const { at } = mount({ sections: SECTIONS }, { duration: 120 });
    at(67);
    expect(screen.getByText("1:07 · Verse 1")).toBeTruthy();
    expect(screen.getByText("2:00")).toBeTruthy();
    expect(screen.getByRole("slider", { name: "Position" }).getAttribute("aria-valuetext")).toBe("1:07, Verse 1");
  });

  it("puts the audio error above the bar", () => {
    const { media } = mount();
    act(() => {
      for (let i = 0; i < 3; i++) media.emit("error");
    });
    const alert = screen.getByRole("alert");
    const slider = screen.getByRole("slider", { name: "Position" });
    expect(alert.compareDocumentPosition(slider) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps a mouse click on any of its buttons from taking focus", () => {
    mount();
    const buttons = within(screen.getByRole("region", { name: "Transport" })).getAllByRole("button");
    expect(buttons).toHaveLength(11);
    for (const b of buttons) expect(fireEvent.mouseDown(b), b.textContent ?? "").toBe(false);
  });
});
```

The eleven are back, play, forward, three speeds, A, B, ×, and two sources. In `Player.test.tsx`, append `screen.getByRole("region", { name: "Transport" })` to the layout test's order.

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/player/Transport.test.tsx src/player/Player.test.tsx`
Expected: FAIL: there is no `./Transport`.

- [ ] **Step 3: Write `Transport`, and delete `Controls.tsx`**

It keeps every behaviour of `Controls`, including `SOURCES`, `otherSource` and the error wording:

```
<div className="transport" role="region" aria-label="Transport">
  {error && <div className="transport-error" role="alert"><p>…</p><Button …>Reload</Button></div>}
  <div className="transport-bar">
    <div className="transport-play">
      Back (BackIcon) · Play/Pause (className "play", PlayIcon/PauseIcon) · Forward (ForwardIcon)
    </div>
    <div className="transport-scrub">
      <Scrubber engine={engine} sections={song.sections} section={label} />
      <p className="time"><span>{clock(time)}{label !== null && ` · ${label}`}</span>
         {buffering && <span role="status">Buffering…</span>}<span>{clock(duration)}</span></p>
    </div>
    {engine.canStretch && <div className="segmented" role="group" aria-label="Speed">…</div>}
    <div className="loop" role="group" aria-label="Loop">A · B · ×</div>
    <div className="segmented" role="group" aria-label="Audio">Full mix · Guitar only</div>
  </div>
</div>
```

- `label`: `useMemo(() => new TrackCursor(song.sections), [song])`, read in render at `state.time`. That runs at the readout's 4 Hz, not per frame. It is `song.sections[current].label`, or `null`.
- The loop buttons' text is `A` or `` `A ${clock(a)}` ``. Their `label` is `"Set loop start"` or `` `Set loop start (${clock(a)})` ``, and the same for B. × keeps "Clear loop".

- [ ] **Step 4: Dock it**

`Player` renders `<Transport song={song} engine={engine} />` last, in place of `Controls`. In `styles.css`:
- Delete `.controls` and its rules.
- `.transport { position: sticky; bottom: 0; z-index: 1; background: var(--bg-raised); border-top: 1px solid var(--border); }`. Pad it, and pull it out to the page edges with negative side margins equal to `main`'s 16 px padding.
- `.transport-bar` is a flex row with a 16 px gap, `align-items: center` and `flex-wrap: wrap`. `.transport-scrub` is `flex: 1 1 240px`. `.time` is `display: flex; justify-content: space-between`.
- `.play` is 48 × 48 px with `border-radius: 50%`, an `--accent` background and `color: var(--on-accent)`. The other transport buttons share the old `.controls button` look.
- `@media (max-width: 899px) { .transport-scrub { order: -1; flex-basis: 100%; } }` makes the scrubber its own first row and the buttons the second.

- [ ] **Step 5: Run the web suite and the gate**

Run: `npm --prefix web test && npm --prefix web run lint && npm --prefix web run build`
Expected: PASS. Vite still lists the guitar as its own chunk of about 600 kB, and the entry chunk stays near the 168 kB that `vite.config.ts` records. An entry chunk that has grown by hundreds of kB means something outside `guitar/` imported a guitar module.

- [ ] **Step 6: Commit**

```bash
git rm web/src/player/Controls.tsx
git add web/src/player/Transport.tsx web/src/player/Transport.test.tsx web/src/player/Player.tsx \
  web/src/player/Player.test.tsx web/src/styles.css
git commit -m "feat(web): the transport docks to the bottom of the window

It replaces Controls, keeping every behaviour, and its tests move with
it. Icons on play and +/-5 s; the loop shows its times; the scrubber
shows the sections and the loop.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: The records

**Files:**
- Create: `docs/specs/011-player-redesign/acceptance.md`
- Modify: `docs/specs/001-guitarvis-design/spec.md` (*Client → Layout*)

- [ ] **Step 1: Point the parent spec at 011**

Under *Layout*, after the paragraph that ends "should not compete for the same space.", add: "**Superseded by [011](../011-player-redesign/spec.md#layout):** the view switch (3D · Fretboard · Tab only) is in the page header. A chord lane runs under the guitar, the sections sit in a sidebar, and the transport docks to the bottom of the window. The tab strip is still always shown."

- [ ] **Step 2: Write `acceptance.md`, blank**

Use 008's layout: a **Spec:** link to [the spec's *Manual acceptance*](spec.md#manual-acceptance), a sentence on what it is for, and "Filled in before the PR is merged." Then:
- *Setup*: commit; machine and OS; browsers and versions; the song's title, length, number of sections and number of chords. Use a song this database has not seen, or delete its job row first, as 008's record explains.
- One checkbox per item, under these headings:
  - *End to end*: the stack runs, and the song plays.
  - *Docked transport*: visible at every scroll position at 1440, 1024 and 800 px wide, and at a window height of 600 px. It never covers the tab strip's last row.
  - *Sections*: a click jumps to the section, and the highlight follows the song.
  - *Chord lane*: in step with the tab strip at 1× and 0.5×, the current cell stays in view, and weak chords are faded.
  - *Scrubber*: playhead and ticks. The loop is drawn at the same place on the scrubber and on the tab strip, including B set before A. A drag seeks once.
  - *Warnings*: one line, and they expand.
  - *Tab only*: no guitar chunk in the Network panel, and the lane stays.
  - *Keyboard only*: from load to a working loop, using Tab, Space, the arrows, `[` and `]`, and the scrubber's Home and End.
  - *Light and dark*, in *Chrome, Firefox, Safari*.
- Three free-text lines:
  - "Frame rate: browser …, React commits per second while playing: … (Performance panel)"
  - "Section labels on this song: good enough / numbered fallback needed, because …"
  - "The legend without "Next": missed / not missed, because …"

- [ ] **Step 3: Commit**

```bash
git add docs/specs/001-guitarvis-design/spec.md docs/specs/011-player-redesign/acceptance.md
git commit -m "docs: point the design spec's layout at 011, and the acceptance run to come

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: The acceptance run, then the PR

**A person runs this task.** It needs real services, a real song, three browsers, and judgement about how the page looks and feels. An agent executing this plan stops here and hands over.

**Files:**
- Modify: `docs/specs/011-player-redesign/acceptance.md`, `docs/specs/011-player-redesign/plan.md` (checkboxes)
- Maybe modify: `web/src/styles.css`, if the run calls for it

- [ ] **Step 1: Run every check in `acceptance.md`**

Run `make services`, `make migrate`, `make api`, `make worker` and `make web`. `make worker` needs `uv sync --extra ml`. Upload a real song, then work through the record and fill in each line.

- [ ] **Step 2: Change only what the run calls for**

The spec's *Risks* name the levers. If the page does not fit at 600 px, the answer is *Tab only*, not a shorter tab strip. If section labels are poor, numbered sections are a later client-side change: note it in the record and do not build it here. If React commits every frame, find the view that calls `setState` per frame and fix it.

- [ ] **Step 3: Commit the record**

```bash
git add docs/specs/011-player-redesign/acceptance.md
git commit -m "docs: 011's acceptance record

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Run the gate once more, and tick this plan's checkboxes**

Run: `make services && make check`
Expected: PASS. Then tick every checkbox in this plan, and commit as "docs: tick 011's plan checkboxes".

- [ ] **Step 5: Open the PR**

Use `.github/pull_request_template.md`, with **Spec:** `docs/specs/011-player-redesign/spec.md`. Under *Deviations from the spec*, list:
- `TrackCursor` lives in `playback/cursor.ts`, not `lane.ts`, and why.
- The back link's wording.
- The loop buttons' accessible names.
- Anything the acceptance run changed.

Under *What changed*, note that the design system's *WebPlayer* mockup should be refreshed from the shipped page after merge. End the description with:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
