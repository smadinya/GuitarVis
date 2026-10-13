# 2D Fretboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first half of phase 5: a 2D fretboard above the tab strip. It lights each note where the hand plays it, in step with the audio.

**Architecture:** All of it is in `web/`. Two pure modules hold the logic. `fretboard/neck.ts` turns a song and a width into the neck's geometry. `fretboard/layout.ts` turns a song, the fretboard's own cursors, a time and the neck into a list of keyed marks. React renders the neck as SVG, on mount and on resize only. The notes go in an SVG layer that React leaves empty. On every `engine.onFrame`, a `MarkLayer` applies that frame's marks to the layer by key, so React never renders at frame rate. The text both views use moves into `labels.ts`.

**Tech Stack:** React 18.3, TypeScript 6.0, Vite 8.3, Vitest 5.0 with jsdom 29 and Testing Library 16, SVG styled through CSS custom properties. No new dependencies.

**Spec:** [spec.md](spec.md) · **Parent:** [001-guitarvis-design](../001-guitarvis-design/spec.md) · **Builds on:** [006-tab-view-sync](../006-tab-view-sync/spec.md)

**Checked while writing:** this plan's code was assembled in a scratch worktree of this branch, following the plan's own steps, and run. `npm --prefix web test` ran `tsc` and then 244 web tests in 20 files, up from 189 in 15. `npm --prefix web run lint` and `npm --prefix web run build` were both clean. Five rules were then broken on purpose, one at a time, and each broke its named test: dropping `litUntil`, narrowing the hidden-passage window, dropping the hidden check, reading the neck from the frame listener's closure rather than its ref, and resubscribing on resize. The component was also rendered in headless Chromium, light and dark; the message's halo came out of that. **Not run:** the Python half of `make check`, which this plan does not touch, and Task 6. A snippet that fails as written most likely has a transcription slip. Compare it with the plan before doubting the design.

**Amended after Task 5:** the approach rings were dropped before the acceptance run, as too distracting (see the spec's *Rejected alternatives*). Tasks 3 to 5 below still show the ring code as it was first built and committed. A later commit removes it: `LOOKAHEAD`, the `ring` mark, its SVG group, the `--fret-ring` token and their tests. Task 6's step on changing `LOOKAHEAD` no longer applies. The Global Constraints' ring values and `LOOKAHEAD`, Review Focus 3, and Task 6's introduction and record template also still describe the rings as first planned. The spec and `acceptance.md` are current.

## Global Constraints

Repo-wide rules from `CLAUDE.md` and `docs/CONVENTIONS.md`, and the values the spec fixes. Every task inherits them.

- **Never commit to `main`.** Work on the branch `007-2d-fretboard`, which already holds the spec. `.githooks/pre-commit` enforces this.
- **`make check` is the gate.** Run `make services` first. Without the services, the integration tests skip locally, and CI turns that skip into a failure.
- **Nothing changes outside `web/` and `docs/specs/007-2d-fretboard/`.** No change to `tabdoc.py`, the schema, the api, the worker or the evaluation. `CACHE_VERSION` does not move. No new dependencies.
- **Generated files are never hand-edited:** `web/src/types/tabDocument.ts`, `web/src/types/api.ts`.
- **`web/src/confidence.ts` is imported unchanged.** A mark's opacity comes from `emphasis(...)` and from nothing else.
- **A view never imports another view.** The fretboard takes its text from `web/src/labels.ts`, never from `web/src/tab/`.
- **React never renders at frame rate.** The neck re-renders only when the song or the width changes. The notes go through `MarkLayer`.
- **Seconds are authoritative.** Every time here is in song seconds. `LOOKAHEAD` is too, so at 0.5× the rings close half as fast.
- **Exact values from the spec:**
  - N = max(12, the song's highest fret + 2), computed once per song
  - wire n sits at `nutX + W · (1 − 2^(−n/12)) / (1 − 2^(−N/12))`, the nut being wire 0
  - a note on fret n ≥ 1 sits midway between wires n − 1 and n; fret 0 sits in a column left of the nut
  - strings 30 px apart; about 230 px high for six strings; stroke widths from 2.5 px (lowest) to 1 px (highest)
  - the dot's radius r is 11 px; a ring closes linearly from 2r, `LOOKAHEAD` before the onset, to r at the onset
  - `MIN_LIT` = 0.15 s; `LOOKAHEAD` = 1.5 s
  - inlays at frets 3, 5, 7, 9, 15, 17, 19 and 21, with a double at 12, and only those within the range
  - note names spelled with sharps, with no octave
  - the nut on the left and the lowest string on top: `E A D G B e` from top to bottom in standard tuning
  - the SVG has `role="img"` and `aria-label="Fretboard"`
  - `EMPTY_MESSAGE` is "No notes to show"; `UNCLEAR_LABEL` is "unclear passage"
- **Running web tests:** `npm --prefix web test -- <path>` runs `tsc --noEmit`, then `vitest run <path>`, inside `web/`. Paths after `--` are relative to `web/`. Both halves matter. While a module does not exist yet, `tsc` is what fails.
- **jsdom.** A test that needs the DOM begins with `// @vitest-environment jsdom`. Everything else runs on the default `node` environment. jsdom stays on 29.x.
- **Style.** There is no TypeScript formatter. Match the existing code: double quotes, semicolons, two-space indent. ESLint is authoritative: `npm --prefix web run lint`.
- End every commit message with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

These are inputs the spec implies but never names, most likely first. Each one is pinned by a test in the task that owns the code.

1. **A long transcribed note, then a shorter note on the same string.** `basic-pitch` often runs a sustain past the next note. Read literally, "only the latest *lit* onset is drawn" brings the long note's dot back once the short one goes dark. Expected: the later onset ends the earlier note for good, as the spec's "a later onset on the same string ends the earlier note" says. → Task 3: `does not light a long note again after a shorter one on its string has ended it`.
2. **A weak note with a long sustain, still sounding after its hidden passage has ended.** A passage ends at the next confident onset, while the weak note's duration can run on past it. Expected: the note stays hidden, as it does in the tab strip, because its onset is in the passage. → Task 3: `keeps a hidden note dark after its passage ends, however long it sounds`.
3. **Resizing the window during playback.** Expected: the neck refits, and the dots and rings move with it on the next frame. They are not cleared for a frame, and the listener is not resubscribed. → Task 5: `refits the neck on resize, and moves a sounding note's dot with it, without resubscribing`.
4. **A note on a string or fret the neck does not have.** A document without a tuning gets standard tuning's six strings, whatever its notes say. Expected: such a note is skipped, as the tab strip skips it, with no crash and no `NaN` in the SVG. → Task 3: `skips a note on a string or fret the neck does not have`.
5. **The panel before it has been measured.** On the first render, and always in jsdom, the width is 0. Expected: the neck's positions are finite, with every wire at the nut, and nothing throws. → Task 2: `gives finite positions before the panel has been measured`.

## File map

| Path | Responsibility | Task |
|---|---|---|
| `web/src/labels.ts` | `EMPTY_MESSAGE`, `UNCLEAR_LABEL`, `stringLabels`, `noteName` | 1 |
| `web/src/tab/layout.ts`, `layout.test.ts` | import the shared text instead of defining it | 1 |
| `web/src/fretboard/neck.ts` | `neckOf(song, width)`: the range, wires, note positions, strings, inlays | 2 |
| `web/src/fretboard/layout.ts` | `cursorsOf`, `litUntil`, `layout(song, cursors, now, neck)`: the marks for one instant | 3 |
| `web/src/fretboard/marks.ts` | `MarkLayer`: the keyed SVG updater | 4 |
| `web/src/fretboard/Fretboard.tsx` | draws the neck; `onFrame` → `layout` → `MarkLayer.apply` | 5 |
| `web/src/player/Player.tsx`, `Player.test.tsx` | mounts the fretboard above the tab strip | 5 |
| `web/src/styles.css` | `--fret-*` tokens, light and dark, and the `.fret-*` classes | 5 |
| `docs/specs/007-2d-fretboard/acceptance.md` | the manual checks | 6 |

---

### Task 1: The text both views share

`stringLabels`, `EMPTY_MESSAGE` and `UNCLEAR_LABEL` move out of `tab/layout.ts` into `web/src/labels.ts`, and their tests move with them. `noteName` joins them there. The tab strip imports from the new module and draws exactly what it drew before.

**Files:**
- Create: `web/src/labels.ts`, `web/src/labels.test.ts`
- Modify: `web/src/tab/layout.ts` (one import added; two constants and `stringLabels` removed)
- Modify: `web/src/tab/layout.test.ts` (imports; one assertion and two tests move out)

**Interfaces:**
- Consumes: nothing new.
- Produces, from `web/src/labels.ts`:
  - `EMPTY_MESSAGE = "No notes to show"` and `UNCLEAR_LABEL = "unclear passage"`.
  - `stringLabels(tuning: readonly string[]): string[]`. Letter names by string, lowest first, with the top string lowercased when it shares a letter with the bottom one.
  - `noteName(midi: number): string`. The pitch class, spelled with sharps: `noteName(61) === "C#"`.
  - `tab/layout.ts` no longer exports `EMPTY_MESSAGE`, `UNCLEAR_LABEL` or `stringLabels`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/labels.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { noteName, stringLabels } from "./labels";

describe("stringLabels", () => {
  it("labels standard tuning E A D G B e, lowest first", () => {
    expect(stringLabels(["E2", "A2", "D3", "G3", "B3", "E4"])).toEqual(["E", "A", "D", "G", "B", "e"]);
  });

  it("keeps drop D's top E in capitals", () => {
    expect(stringLabels(["D2", "A2", "D3", "G3", "B3", "E4"])).toEqual([
      "D", "A", "D", "G", "B", "E",
    ]);
  });

  it("names sharps and flats", () => {
    expect(stringLabels(["C#2", "Bb2"])).toEqual(["C#", "Bb"]);
  });
});

describe("noteName", () => {
  it("spells every pitch class with sharps", () => {
    const names = Array.from({ length: 12 }, (_, i) => noteName(60 + i));

    expect(names).toEqual(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]);
  });

  it("gives the same name in every octave", () => {
    // The low E string, open; the D string's second fret; the high e, open.
    expect([noteName(40), noteName(52), noteName(64)]).toEqual(["E", "E", "E"]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/labels.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './labels'`.

- [ ] **Step 3: Write the module**

Create `web/src/labels.ts`:

```typescript
/**
 * The text the views share. A view takes its labels from here, never from
 * another view's layout: views do not talk to each other, and two copies of
 * one rule would drift.
 */

export const EMPTY_MESSAGE = "No notes to show";
export const UNCLEAR_LABEL = "unclear passage";

/** Pitch classes from C, spelled with sharps as the chord symbols are. */
const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

/**
 * Letter names by string, lowest first. The top string is lowercased when it
 * shares a letter with the bottom one: e … E in standard tuning, while drop D
 * keeps its capital E.
 */
export function stringLabels(tuning: readonly string[]): string[] {
  const labels = tuning.map((name) => /^[A-Ga-g][#b]?/.exec(name)?.[0] ?? name);
  const top = labels.length - 1;
  if (top > 0 && labels[top].toLowerCase() === labels[0].toLowerCase()) {
    labels[top] = labels[top].toLowerCase();
  }
  return labels;
}

/** A pitch's name without its octave: MIDI 40 and 64 are both "E". The
 * document has no key, so there is no right choice between a sharp and a
 * flat; sharps match the chord symbols. */
export function noteName(midi: number): string {
  return NOTE_NAMES[((midi % 12) + 12) % 12];
}
```

- [ ] **Step 4: Point the tab strip at it**

In `web/src/tab/layout.ts`, add the import beside the others:

```typescript
import { CHORD_THRESHOLDS, emphasis, isHidden, type Passage } from "../confidence";
import { EMPTY_MESSAGE, UNCLEAR_LABEL, stringLabels } from "../labels";
import { inWindow } from "../playback/cursor";
```

Then delete these two lines, below `PLAYHEAD_AT`:

```typescript
export const EMPTY_MESSAGE = "No notes to show";
export const UNCLEAR_LABEL = "unclear passage";
```

And delete the whole of `stringLabels`, with its doc comment, between `rowsOf` and `layout`:

```typescript
/**
 * Letter names by string, lowest first. The top string is lowercased when it
 * shares a letter with the bottom one: e … E in standard tuning, while drop D
 * keeps its capital E.
 */
export function stringLabels(tuning: readonly string[]): string[] {
  const labels = tuning.map((name) => /^[A-Ga-g][#b]?/.exec(name)?.[0] ?? name);
  const top = labels.length - 1;
  if (top > 0 && labels[top].toLowerCase() === labels[0].toLowerCase()) {
    labels[top] = labels[top].toLowerCase();
  }
  return labels;
}
```

In `web/src/tab/layout.test.ts`, replace the import block from `"./layout"`:

```typescript
import {
  EMPTY_MESSAGE,
  GLYPH_W,
  PLAYHEAD_AT,
  PX_PER_SEC,
  UNCLEAR_LABEL,
  layout,
  rowsOf,
  stringLabels,
  type DrawOp,
} from "./layout";
```

with these two imports. The first goes after the `../confidence` import, and the second stays where the block was:

```typescript
import { EMPTY_MESSAGE, UNCLEAR_LABEL } from "../labels";
```

```typescript
import { GLYPH_W, PLAYHEAD_AT, PX_PER_SEC, layout, rowsOf, type DrawOp } from "./layout";
```

In the test `labels standard tuning e B G D A E, highest on top`, delete this one line. The test still checks the order the strip draws its labels in, and `labels.test.ts` now checks `stringLabels` itself.

```typescript
    expect(stringLabels(song.tuning)).toEqual(["E", "A", "D", "G", "B", "e"]);
```

Delete the two tests that moved to `labels.test.ts`:

```typescript
  it("keeps drop D's top E in capitals", () => {
    expect(stringLabels(["D2", "A2", "D3", "G3", "B3", "E4"])).toEqual([
      "D", "A", "D", "G", "B", "E",
    ]);
  });

  it("names sharps and flats", () => {
    expect(stringLabels(["C#2", "Bb2"])).toEqual(["C#", "Bb"]);
  });

```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/labels.test.ts src/tab/layout.test.ts`
Expected: PASS, 29 tests: 5 in `labels.test.ts` and 24 in `layout.test.ts`. The strip's own tests are untouched apart from their imports, so it draws what it drew.

Then check that nothing else imported the moved names from `tab/`:

Run: `grep -rn "stringLabels\|EMPTY_MESSAGE\|UNCLEAR_LABEL" web/src web/scripts`
Expected: matches only in `labels.ts`, `labels.test.ts`, `tab/layout.ts` and `tab/layout.test.ts`. The last two import from `../labels`.

- [ ] **Step 6: Commit**

```bash
git add web/src/labels.ts web/src/labels.test.ts web/src/tab/layout.ts web/src/tab/layout.test.ts
git commit -m "refactor(web): move the text views share into labels.ts

The fretboard needs the string labels and the two messages, and a view
importing another view's layout is the start of views talking to each
other. noteName joins them: pitch classes spelled with sharps, as the
chord symbols are.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The neck

The neck's geometry as a pure function of the song and the panel's width. The range is fitted to the song once. The frets are spaced as on a real neck, the lowest string is on top, and the inlays are marked. The height depends only on the string count.

The neck is laid out like this, in CSS pixels. Left to right: a 22 px gutter for the string labels, then a 30 px open-string column, then the nut at x = 52. The fingerboard runs from the nut to `width − 12`. The 12 px at the end leaves room for a ring at its widest on the last fret. Top to bottom: the first string at y = 26, which leaves room above it for a ring at 2r = 22. Then one string every 30 px. Then a row of inlay dots, 26 px below the last string, and the fret numbers 18 px below that. For six strings, that makes the panel 232 px high.

**Files:**
- Create: `web/src/fretboard/neck.ts`, `web/src/fretboard/neck.test.ts`

**Interfaces:**
- Consumes: `stringLabels` (Task 1); `Song` and `buildSong` from `web/src/song.ts` (existing).
- Produces, from `web/src/fretboard/neck.ts`:
  - `MIN_FRETS = 12`, `SPARE_FRETS = 2`, `DOT_R = 11`, `STRING_GAP = 30`, `END_PAD = 12`, `INLAY_FRETS = [3, 5, 7, 9, 12, 15, 17, 19, 21]`.
  - `interface NeckString { label: string; y: number; weight: number }`.
  - `interface Inlay { x: number; double: boolean }`.
  - `interface Neck { frets; width; height; wireX: number[]; noteX: number[]; strings: NeckString[]; top; bottom; stringsFrom; labelX; inlayY; numberY; inlays: Inlay[] }`. `frets` is N. `wireX` and `noteX` are indexed by fret and have N + 1 entries each. `strings` is indexed by string, 0 the lowest. `top` and `bottom` are the fingerboard's edges, which the wires span.
  - `neckOf(song: Song, width: number): Neck`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/fretboard/neck.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { buildSong } from "../song";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { Note, TabDocument } from "../types/tabDocument";
import { END_PAD, MIN_FRETS, neckOf } from "./neck";

const FIRST_SONG: TabDocument = firstSongJson;
const WIDTH = 1000;
const SEMITONE = 2 ** (-1 / 12);

let ids = 0;
function note(fret: number, fields: Partial<Note> = {}): Note {
  ids += 1;
  return { id: `n${ids}`, t: ids, dur: 0.5, midi: 40 + fret, string: 0, fret, confidence: 0.95, ...fields };
}

function doc(fields: Partial<TabDocument> = {}): TabDocument {
  return {
    source: { title: "t", duration_sec: 60, audio_url: "/jobs/x/audio/mix" },
    instrument: {},
    timing: {},
    ...fields,
  };
}

function neckFor(frets: number[], fields: Partial<TabDocument> = {}, width = WIDTH) {
  return neckOf(buildSong(doc({ notes: frets.map((fret) => note(fret)), ...fields })), width);
}

describe("the range", () => {
  it("shows twelve frets, or two beyond the song's highest", () => {
    expect(neckFor([0, 3, 8]).frets).toBe(12);
    expect(neckFor([0, 10]).frets).toBe(12);
    expect(neckFor([11]).frets).toBe(13);
    expect(neckFor([5, 20]).frets).toBe(22);
  });

  it("shows twelve frets for a song with no notes", () => {
    expect(neckFor([]).frets).toBe(MIN_FRETS);
  });

  it("fits the real first song, which reaches fret 8, in twelve", () => {
    expect(neckOf(buildSong(FIRST_SONG), WIDTH).frets).toBe(12);
  });
});

describe("fret spacing", () => {
  const neck = neckFor([20]);
  const width = (n: number) => neck.wireX[n] - neck.wireX[n - 1];

  it("puts the nut first and fret N's wire at the fingerboard's end", () => {
    expect(neck.wireX).toHaveLength(neck.frets + 1);
    expect(neck.wireX[neck.frets]).toBeCloseTo(WIDTH - END_PAD);
    for (let n = 1; n <= neck.frets; n++) expect(neck.wireX[n]).toBeGreaterThan(neck.wireX[n - 1]);
  });

  it("makes each fret 2^(-1/12) the width of the one before", () => {
    for (let n = 2; n <= neck.frets; n++) expect(width(n) / width(n - 1)).toBeCloseTo(SEMITONE, 9);
  });

  it("makes a fret half as wide as the one twelve below it", () => {
    expect(width(13) / width(1)).toBeCloseTo(0.5, 9);
  });

  it("puts a note midway between its two wires, and an open string's left of the nut", () => {
    for (let n = 1; n <= neck.frets; n++) {
      expect(neck.noteX[n]).toBeCloseTo((neck.wireX[n - 1] + neck.wireX[n]) / 2);
    }
    expect(neck.noteX[0]).toBeLessThan(neck.wireX[0]);
    expect(neck.noteX[0]).toBeGreaterThan(neck.labelX);
  });

  it("gives finite positions before the panel has been measured", () => {
    const unmeasured = neckFor([5], {}, 0);

    for (const x of [...unmeasured.wireX, ...unmeasured.noteX]) expect(Number.isFinite(x)).toBe(true);
    expect(unmeasured.wireX[unmeasured.frets]).toBe(unmeasured.wireX[0]);
  });
});

describe("strings", () => {
  const labelsTopDown = (tuning: string[]) =>
    [...neckFor([], { instrument: { tuning } }).strings].sort((a, b) => a.y - b.y).map((s) => s.label);

  it("puts the lowest string on top, E A D G B e from top to bottom", () => {
    expect(labelsTopDown(["E2", "A2", "D3", "G3", "B3", "E4"])).toEqual(["E", "A", "D", "G", "B", "e"]);
  });

  it("does the same in drop D", () => {
    expect(labelsTopDown(["D2", "A2", "D3", "G3", "B3", "E4"])).toEqual(["D", "A", "D", "G", "B", "E"]);
  });

  it("draws lower strings thicker", () => {
    const weights = neckFor([]).strings.map((s) => s.weight);

    expect(weights[0]).toBeCloseTo(2.5);
    expect(weights[5]).toBeCloseTo(1);
    for (let s = 1; s < weights.length; s++) expect(weights[s]).toBeLessThan(weights[s - 1]);
  });

  it("sizes the height by the string count, never by the width", () => {
    const six = neckFor([]);
    const seven = neckFor([], { instrument: { tuning: ["B1", "E2", "A2", "D3", "G3", "B3", "E4"] } });

    expect(neckFor([], {}, 400).height).toBe(six.height);
    expect(seven.height).toBeGreaterThan(six.height);
    expect(six.height).toBeGreaterThan(six.numberY);
    expect(six.top).toBeLessThan(six.strings[0].y);
    expect(six.bottom).toBeGreaterThan(six.strings[5].y);
  });
});

describe("inlays", () => {
  it("marks 3, 5, 7, 9 and a double 12 on a twelve-fret neck", () => {
    const neck = neckFor([]);

    expect(neck.inlays).toEqual([3, 5, 7, 9, 12].map((fret) => ({ x: neck.noteX[fret], double: fret === 12 })));
  });

  it("adds the frets past 12 only as the range reaches them", () => {
    const frets = (neck: ReturnType<typeof neckOf>) =>
      neck.inlays.map((inlay) => neck.noteX.indexOf(inlay.x));

    expect(frets(neckFor([14]))).toEqual([3, 5, 7, 9, 12, 15]);
    expect(frets(neckFor([20]))).toEqual([3, 5, 7, 9, 12, 15, 17, 19, 21]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/fretboard/neck.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './neck'`.

- [ ] **Step 3: Write the module**

Create `web/src/fretboard/neck.ts`:

```typescript
/**
 * The neck, fitted to a song: where every fret wire, string, note position
 * and inlay sits. Pure, and it depends only on the song and the width, so
 * the fretboard draws it on mount and on resize, never during playback.
 *
 * The nut is on the left and the lowest string on top, as a player looking
 * down at their own neck sees it. Frets are spaced as on a real neck, each
 * 2^(-1/12) the width of the one before: this view teaches distance under
 * the hand, so it draws distance as the hand finds it.
 */
import { stringLabels } from "../labels";
import type { Song } from "../song";

/** The fewest frets drawn: a song in open position gets twelve wide ones. */
export const MIN_FRETS = 12;
/** Frets drawn beyond the song's highest note. */
export const SPARE_FRETS = 2;
/** A note dot's radius, in CSS pixels: room for a name such as C#. */
export const DOT_R = 11;
export const STRING_GAP = 30;
/** Right of fret N's wire: room for a ring at its widest on the last fret. */
export const END_PAD = 12;
/** Inlay dots, by fret. Fret 12 has two. */
export const INLAY_FRETS = [3, 5, 7, 9, 12, 15, 17, 19, 21];

const GUTTER = 22; // the string labels' column
const OPEN_W = 2 * DOT_R + 8; // open-string notes, between the labels and the nut
const EDGE = 26; // above the top string: room for a ring at its widest, 2r
const NUMBERS = 18; // from the inlay row to the fret numbers
const BELOW = 12; // under the fret numbers
const THICKEST = 2.5; // the lowest string's stroke, in CSS pixels
const THINNEST = 1;

export interface NeckString {
  /** As stringLabels gives it. */
  label: string;
  y: number;
  /** Stroke width: the lower the string, the thicker. */
  weight: number;
}

export interface Inlay {
  x: number;
  /** Fret 12's pair. */
  double: boolean;
}

export interface Neck {
  /** N: frets 1 to N are drawn, after the open-string column. */
  frets: number;
  width: number;
  height: number;
  /** x of each wire, by fret: the nut is wire 0, fret N's wire is last. */
  wireX: number[];
  /** x of a note's centre, by fret: midway between its two wires. Fret 0's
   * is the open-string column, left of the nut. */
  noteX: number[];
  /** By string index, 0 the lowest, which is drawn on top. */
  strings: NeckString[];
  /** The fingerboard's edges: half a string gap beyond the outer strings.
   * The wires span them. */
  top: number;
  bottom: number;
  /** Where the strings start: the open-string column's left edge. */
  stringsFrom: number;
  /** The string labels' column. */
  labelX: number;
  /** The row of inlay dots under the neck, and the fret numbers under that. */
  inlayY: number;
  numberY: number;
  inlays: Inlay[];
}

/** The neck for `song`, `width` CSS pixels wide. N is fixed by the song, so
 * the neck never rescales during playback. */
export function neckOf(song: Song, width: number): Neck {
  const highest = song.notes.reduce((max, note) => Math.max(max, note.fret), 0);
  const frets = Math.max(MIN_FRETS, highest + SPARE_FRETS);

  const nutX = GUTTER + OPEN_W;
  // Zero before the panel is measured, never negative.
  const board = Math.max(width - nutX - END_PAD, 0);
  const wireX = Array.from(
    { length: frets + 1 },
    (_, n) => nutX + (board * (1 - 2 ** (-n / 12))) / (1 - 2 ** (-frets / 12)),
  );
  const noteX = wireX.map((x, n) => (n === 0 ? GUTTER + OPEN_W / 2 : (wireX[n - 1] + x) / 2));

  const count = song.tuning.length;
  const labels = stringLabels(song.tuning);
  const strings = labels.map((label, s) => ({
    label,
    y: EDGE + s * STRING_GAP,
    weight: count > 1 ? THICKEST - ((THICKEST - THINNEST) * s) / (count - 1) : THICKEST,
  }));
  const lowestY = EDGE + Math.max(count - 1, 0) * STRING_GAP;
  const inlayY = lowestY + EDGE;
  const numberY = inlayY + NUMBERS;

  return {
    frets,
    width,
    height: numberY + BELOW,
    wireX,
    noteX,
    strings,
    top: EDGE - STRING_GAP / 2,
    bottom: lowestY + STRING_GAP / 2,
    stringsFrom: GUTTER,
    labelX: GUTTER / 2,
    inlayY,
    numberY,
    inlays: INLAY_FRETS.filter((fret) => fret <= frets).map((fret) => ({
      x: noteX[fret],
      double: fret === 12,
    })),
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/fretboard/neck.test.ts`
Expected: PASS, 14 tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/fretboard/neck.ts web/src/fretboard/neck.test.ts
git commit -m "feat(web): lay out the fretboard's neck, fitted to the song

Frets 0 to max(12, highest + 2), spaced as on a real neck so distance on
screen is distance under the hand. The nut is on the left and the lowest
string on top, as a player sees their own neck. The height depends only
on the string count.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The marks, frame by frame

Everything worth testing about the fretboard, as a pure function. The inputs are a song, the fretboard's own cursors, a time and the neck. The output is a list of keyed marks:
- a dot on each string that sounds, named by pitch;
- a closing ring at each position about to sound;
- a message when the neck has nothing else to show.

Hidden notes get no mark, by the same `isHidden` test over the same `song.hidden` that the tab strip uses.

Two details go beyond the spec's wording. Both are listed under *Decisions the spec left open*, below.
- `litUntil` makes a later onset end an earlier note on its string for good, not only while the later note is lit (Review Focus 1).
- The hidden passages are read back to the earliest onset in play, not just the current window (Review Focus 2).

**Files:**
- Create: `web/src/fretboard/layout.ts`, `web/src/fretboard/layout.test.ts`

**Interfaces:**
- Consumes:
  - `emphasis`, `isHidden` and `CHORD_THRESHOLDS` from `web/src/confidence.ts` (existing, unchanged);
  - `EMPTY_MESSAGE`, `UNCLEAR_LABEL` and `noteName` (Task 1);
  - `NoteCursor` and `inWindow` from `web/src/playback/cursor.ts` (existing);
  - `Song` and `buildSong` (existing);
  - `DOT_R`, `Neck` and `neckOf` (Task 2).
- Produces, from `web/src/fretboard/layout.ts`:
  - `MIN_LIT = 0.15` and `LOOKAHEAD = 1.5`, in seconds.
  - `type Mark`, a union of three kinds. Each has a stable `key` and an `opacity`.
    - `{ kind: "dot"; key: "dot:<note id>"; x; y; r; name }`
    - `{ kind: "ring"; key: "ring:<string>:<fret>"; x; y; r }`
    - `{ kind: "message"; key: "message"; x; y; text; chord: boolean }`
  - `interface Cursors { notes: NoteCursor<Note>; chords: NoteCursor<Chord>; until: ReadonlyMap<Note, number> }`, and `cursorsOf(song: Song): Cursors`.
  - `litUntil(notes: readonly Note[]): Map<Note, number>`.
  - `layout(song: Song, cursors: Cursors, now: number, neck: Neck): Mark[]`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/fretboard/layout.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import minimalJson from "../../../packages/core/tests/fixtures/minimal.tabdoc.json";
import { CHORD_FULL, FADED, emphasis, isHidden } from "../confidence";
import { EMPTY_MESSAGE, UNCLEAR_LABEL } from "../labels";
import { buildSong, type Song } from "../song";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { Chord, Note, TabDocument } from "../types/tabDocument";
import { LOOKAHEAD, MIN_LIT, cursorsOf, layout, type Mark } from "./layout";
import { DOT_R, neckOf } from "./neck";

const FIRST_SONG: TabDocument = firstSongJson;
const MINIMAL: TabDocument = minimalJson;
const WIDTH = 1000;

type Dot = Extract<Mark, { kind: "dot" }>;
type Ring = Extract<Mark, { kind: "ring" }>;
type Message = Extract<Mark, { kind: "message" }>;

let ids = 0;
function note(t: number, fields: Partial<Note> = {}): Note {
  ids += 1;
  return { id: `n${ids}`, t, dur: 0.5, midi: 45, string: 1, fret: 0, confidence: 0.95, ...fields };
}

function doc(fields: Partial<TabDocument> = {}): TabDocument {
  return {
    source: { title: "t", duration_sec: 60, audio_url: "/jobs/x/audio/mix" },
    instrument: {},
    timing: {},
    ...fields,
  };
}

/** The fretboard for one song, laid out at any time with one set of cursors,
 * as the component does. */
function board(song: Song) {
  const neck = neckOf(song, WIDTH);
  const cursors = cursorsOf(song);
  const at = (now: number) => layout(song, cursors, now, neck);
  return {
    neck,
    at,
    dots: (now: number) => at(now).filter((m): m is Dot => m.kind === "dot"),
    rings: (now: number) => at(now).filter((m): m is Ring => m.kind === "ring"),
    message: (now: number) => at(now).find((m): m is Message => m.kind === "message"),
  };
}

function boardOf(notes: Note[], fields: Partial<TabDocument> = {}) {
  return board(buildSong(doc({ notes, ...fields })));
}

describe("dots", () => {
  it("lights a note across [t, t + dur], at its string and fret, named by pitch", () => {
    const fretboard = boardOf([note(1, { dur: 0.5, string: 2, fret: 2, midi: 52 })]);
    const { neck } = fretboard;

    expect(fretboard.dots(0.99)).toEqual([]);
    expect(fretboard.dots(1)).toHaveLength(1);
    expect(fretboard.dots(1.5)).toHaveLength(1);
    expect(fretboard.dots(1.51)).toEqual([]);
    expect(fretboard.dots(1.2)[0]).toMatchObject({
      x: neck.noteX[2],
      y: neck.strings[2].y,
      r: DOT_R,
      name: "E",
    });
  });

  it("holds a short note for MIN_LIT", () => {
    const fretboard = boardOf([note(1, { dur: 0.04 })]);

    expect(fretboard.dots(1 + MIN_LIT - 0.01)).toHaveLength(1);
    expect(fretboard.dots(1 + MIN_LIT + 0.01)).toEqual([]);
  });

  it("draws an open string in the column left of the nut", () => {
    const fretboard = boardOf([note(1, { fret: 0 })]);

    expect(fretboard.dots(1)[0].x).toBe(fretboard.neck.noteX[0]);
    expect(fretboard.dots(1)[0].x).toBeLessThan(fretboard.neck.wireX[0]);
  });

  it("keys a dot by its note, so it is one node for its whole life", () => {
    const sounding = note(1, { dur: 1 });
    const fretboard = boardOf([sounding]);

    expect(fretboard.dots(1.1)[0].key).toBe(`dot:${sounding.id}`);
    expect(fretboard.dots(1.9)[0].key).toBe(`dot:${sounding.id}`);
  });

  it("draws one dot per string: the latest onset wins", () => {
    const early = note(1, { dur: 2, fret: 2 });
    const late = note(1.5, { dur: 2, fret: 4 });
    const fretboard = boardOf([early, late]);

    expect(fretboard.dots(1.2).map((d) => d.key)).toEqual([`dot:${early.id}`]);
    expect(fretboard.dots(1.6).map((d) => d.key)).toEqual([`dot:${late.id}`]);
  });

  it("does not light a long note again after a shorter one on its string has ended it", () => {
    const long = note(0, { dur: 4, fret: 2 });
    const short = note(1, { dur: 0.05, fret: 4 });
    const fretboard = boardOf([long, short]);

    expect(fretboard.dots(0.5).map((d) => d.key)).toEqual([`dot:${long.id}`]);
    expect(fretboard.dots(1.05).map((d) => d.key)).toEqual([`dot:${short.id}`]);
    expect(fretboard.dots(2)).toEqual([]);
  });

  it("draws notes on different strings together", () => {
    const chord = [0, 1, 2].map((string) => note(1, { string, fret: 2 }));

    expect(boardOf(chord).dots(1.1)).toHaveLength(3);
  });

  it("skips a note on a string or fret the neck does not have", () => {
    // A document with no tuning gets six strings; its notes might not fit.
    const fretboard = boardOf([note(1, { string: 6, fret: 3 }), note(1, { string: 0, fret: -1 })]);

    expect(fretboard.at(1)).toEqual([]);
  });
});

describe("rings", () => {
  const coming = note(2, { string: 3, fret: 5, midi: 60 });
  const fretboard = boardOf([coming]);

  it("appears LOOKAHEAD before the onset at twice the dot's radius", () => {
    expect(fretboard.rings(2 - LOOKAHEAD - 0.01)).toEqual([]);
    expect(fretboard.rings(2 - LOOKAHEAD)[0]).toMatchObject({
      x: fretboard.neck.noteX[5],
      y: fretboard.neck.strings[3].y,
      r: 2 * DOT_R,
    });
  });

  it("closes linearly to the dot's radius at the onset, where the dot fills it", () => {
    expect(fretboard.rings(2 - LOOKAHEAD / 2)[0].r).toBeCloseTo(1.5 * DOT_R);
    expect(fretboard.rings(2)[0].r).toBe(DOT_R);
    expect(fretboard.dots(2)).toHaveLength(1);
    expect(fretboard.rings(2.01)).toEqual([]);
  });

  it("is unlabelled: the name appears when the note sounds", () => {
    expect(fretboard.rings(1.5)[0]).not.toHaveProperty("name");
  });

  it("draws one ring per position, for the nearest onset", () => {
    const strums = [1, 1.3, 1.6, 1.9].map((t) => note(t, { string: 0, fret: 3 }));
    const strummed = boardOf(strums);

    const rings = strummed.rings(0.8);

    expect(rings).toHaveLength(1);
    expect(rings[0].key).toBe("ring:0:3");
    expect(rings[0].r).toBeCloseTo(DOT_R * (1 + 0.2 / LOOKAHEAD));
  });

  it("can share a position with a dot: the cue for a repeated note", () => {
    const repeated = boardOf([note(1, { fret: 3 }), note(1.4, { fret: 3 })]);

    const marks = repeated.at(1.1);

    expect(marks.map((m) => m.kind).sort()).toEqual(["dot", "ring"]);
    const [dot, ring] = [marks.find((m) => m.kind === "dot"), marks.find((m) => m.kind === "ring")];
    expect([dot?.x, dot?.y]).toEqual([ring?.x, ring?.y]);
  });
});

describe("confidence", () => {
  it("sets the opacity of dots and rings by emphasis(confidence)", () => {
    const fretboard = boardOf([
      note(1, { string: 0, confidence: 0.55 }),
      note(1.5, { string: 1, confidence: 0.2 }),
    ]);

    const marks = fretboard.at(1);

    expect(marks.find((m) => m.kind === "dot")?.opacity).toBe(emphasis(0.55));
    expect(marks.find((m) => m.key === "ring:1:0")?.opacity).toBe(FADED);
  });

  const weak = (t: number) => note(t, { confidence: 0.05, string: 2, fret: 7 });

  it("gives a note in a hidden passage neither a dot nor a ring, even before the passage", () => {
    const fretboard = boardOf([weak(1), weak(1.3), weak(1.6), note(3, { fret: 5 })]);

    expect(fretboard.at(0.5)).toEqual([]); // all three hidden notes are within LOOKAHEAD
    expect(fretboard.dots(1.35)).toEqual([]);
    expect(fretboard.rings(1.9).map((r) => r.key)).toEqual(["ring:1:5"]);
  });

  it("keeps a hidden note dark after its passage ends, however long it sounds", () => {
    const fretboard = boardOf([
      weak(1),
      weak(1.3),
      note(1.6, { confidence: 0.05, string: 3, dur: 3 }),
      note(2, { fret: 5 }),
    ]);

    expect(fretboard.dots(3)).toEqual([]);
  });

  it("lights every note the tab strip shows, and no other, across the real first song", () => {
    const song = buildSong(FIRST_SONG);
    const fretboard = board(song);
    const lit = new Set<string>();

    for (let now = 0; now <= song.duration; now += 1 / 120) {
      for (const dot of fretboard.dots(now)) lit.add(dot.key);
    }

    const shown = song.notes.filter((n) => !isHidden(song.hidden, n.t)).map((n) => `dot:${n.id}`);
    expect(song.hidden.length).toBeGreaterThan(0);
    expect([...lit].sort()).toEqual(shown.sort());
  });
});

describe("hidden passages", () => {
  const weak = (t: number) => note(t, { confidence: 0.05 });
  const am: Chord = { t: 1, dur: 1, symbol: "Am", confidence: 0.9 };

  it("shows the sounding chord's symbol, at the chord's own confidence", () => {
    const fretboard = boardOf([weak(1), weak(1.3), weak(1.6)], { chords: [{ ...am, confidence: 0 }] });

    expect(fretboard.message(1.2)).toMatchObject({ text: "Am", chord: true, opacity: FADED });
  });

  it("shows a confident chord at full strength", () => {
    const fretboard = boardOf([weak(1), weak(1.3), weak(1.6)], { chords: [{ ...am, confidence: CHORD_FULL }] });

    expect(fretboard.message(1.2)?.opacity).toBe(1);
  });

  it("says the passage is unclear when no chord sounds", () => {
    const fretboard = boardOf([weak(1), weak(1.3), weak(1.6)], { chords: [{ ...am, t: 5 }] });

    expect(fretboard.message(1.2)).toMatchObject({ text: UNCLEAR_LABEL, chord: false });
  });

  it("shows no message outside a passage", () => {
    const fretboard = boardOf([weak(1), weak(1.3), weak(1.6)], { chords: [am] });

    expect(fretboard.message(0.5)).toBeUndefined();
    expect(fretboard.message(2.5)).toBeUndefined();
  });

  it("centres the message on the fingerboard", () => {
    const fretboard = boardOf([weak(1), weak(1.3), weak(1.6)]);
    const { neck } = fretboard;

    expect(fretboard.message(1.2)).toMatchObject({
      x: (neck.wireX[0] + neck.wireX[neck.frets]) / 2,
      y: (neck.top + neck.bottom) / 2,
    });
  });
});

describe("the other cases", () => {
  it("draws the minimal fixture: the open low E, and a ring closing on the D string's second fret", () => {
    const fretboard = board(buildSong(MINIMAL));

    expect(fretboard.at(0.1)).toEqual([
      expect.objectContaining({ kind: "ring", key: "ring:2:2" }),
      expect.objectContaining({ kind: "dot", key: "dot:n_0000", name: "E", x: fretboard.neck.noteX[0] }),
    ]);
  });

  it("shows the message, and nothing else, for a document with no notes", () => {
    const fretboard = boardOf([]);

    expect(fretboard.at(0)).toEqual([expect.objectContaining({ kind: "message", text: EMPTY_MESSAGE })]);
  });

  it("is right straight after a jump back, as when an A/B loop restarts", () => {
    const notes = Array.from({ length: 40 }, (_, i) => note(i * 0.25, { string: i % 6, fret: i % 9 }));
    const song = buildSong(doc({ notes }));
    const playing = board(song);

    for (let now = 0; now <= 8; now += 1 / 60) playing.at(now);

    expect(playing.at(2)).toEqual(board(song).at(2));
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/fretboard/layout.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './layout'`.

- [ ] **Step 3: Write the module**

Create `web/src/fretboard/layout.ts`:

```typescript
/**
 * The fretboard at one instant, as marks to draw: a dot on each string that
 * sounds, a closing ring at each position about to, and a message when there
 * is nothing else to read. Pure: the same song, time and neck always give the
 * same marks, so everything worth testing about the fretboard is tested here,
 * and Fretboard only draws.
 *
 * Opacity means confidence and nothing else. How soon a note comes is its
 * ring's size, so a faint ring is always a doubtful note, never a distant one.
 */
import { CHORD_THRESHOLDS, emphasis, isHidden } from "../confidence";
import { EMPTY_MESSAGE, UNCLEAR_LABEL, noteName } from "../labels";
import { NoteCursor, inWindow } from "../playback/cursor";
import type { Song } from "../song";
import type { Chord, Note } from "../types/tabDocument";
import { DOT_R, type Neck } from "./neck";

/** The shortest time a dot stays lit, in seconds: a 40 ms pick would
 * otherwise light for two frames. */
export const MIN_LIT = 0.15;
/** How far ahead rings appear, in song seconds, so at 0.5× they close half
 * as fast. Enough to move the hand at moderate tempos. */
export const LOOKAHEAD = 1.5;

/** Each mark has a key that is stable across frames, so its SVG node is
 * updated in place rather than replaced. */
export type Mark =
  | { kind: "dot"; key: string; x: number; y: number; r: number; name: string; opacity: number }
  | { kind: "ring"; key: string; x: number; y: number; r: number; opacity: number }
  | { kind: "message"; key: string; x: number; y: number; text: string; chord: boolean; opacity: number };

/**
 * The fretboard's own reading of a song, made once when it mounts. A cursor
 * follows one moving window, so the fretboard keeps its own rather than share
 * the tab strip's.
 */
export interface Cursors {
  notes: NoteCursor<Note>;
  chords: NoteCursor<Chord>;
  /** When each note goes dark: see litUntil. */
  until: ReadonlyMap<Note, number>;
}

export function cursorsOf(song: Song): Cursors {
  return {
    notes: new NoteCursor(song.notes),
    chords: new NoteCursor(song.chords),
    until: litUntil(song.notes),
  };
}

/**
 * When each note stops being drawn: at the end of its duration, held for at
 * least MIN_LIT, or at the next onset on its string, whichever is first. A
 * string sounds one note at a time, so a later note ends an earlier one, and
 * a long transcribed sustain cannot light again once a shorter note after it
 * has gone dark. `notes` must be sorted by onset.
 */
export function litUntil(notes: readonly Note[]): Map<Note, number> {
  const until = new Map<Note, number>();
  const last = new Map<number, Note>(); // by string
  for (const note of notes) {
    const previous = last.get(note.string);
    if (previous !== undefined) {
      until.set(previous, Math.min(until.get(previous) ?? note.t, note.t));
    }
    until.set(note, note.t + Math.max(note.dur, MIN_LIT));
    last.set(note.string, note);
  }
  return until;
}

export function layout(song: Song, cursors: Cursors, now: number, neck: Neck): Mark[] {
  const middle = {
    x: (neck.wireX[0] + neck.wireX[neck.frets]) / 2,
    y: (neck.top + neck.bottom) / 2,
  };
  if (song.notes.length === 0) return [message(middle, EMPTY_MESSAGE, false, 1)];

  // Every note that could be lit now or ringed soon. A note lit by MIN_LIT
  // started at most MIN_LIT ago; a longer one is still within its duration.
  const notes = cursors.notes.window(now - MIN_LIT, now + LOOKAHEAD);
  // A long note may have started in a passage that is already over, and stays
  // hidden: read the passages back to the earliest onset in play.
  const since = Math.min(now, notes[0]?.t ?? now);
  const hidden = inWindow(song.hidden, since, now + LOOKAHEAD, (p) => p.from, (p) => p.to);

  const dots = new Map<number, Mark>(); // by string: the latest onset wins
  const rings = new Map<string, Mark>(); // by position: the soonest onset wins
  for (const note of notes) {
    const y = neck.strings[note.string]?.y;
    const x = neck.noteX[note.fret];
    if (y === undefined || x === undefined || isHidden(hidden, note.t)) continue;
    const opacity = emphasis(note.confidence);

    const until = cursors.until.get(note) ?? note.t + Math.max(note.dur, MIN_LIT);
    if (note.t <= now && now <= until) {
      const name = noteName(note.midi);
      dots.set(note.string, { kind: "dot", key: `dot:${note.id}`, x, y, r: DOT_R, name, opacity });
    }

    const ahead = note.t - now;
    const key = `ring:${note.string}:${note.fret}`;
    if (ahead >= 0 && ahead <= LOOKAHEAD && !rings.has(key)) {
      // 2r at the far edge of the window, r at the onset, where the dot fills it.
      rings.set(key, { kind: "ring", key, x, y, r: DOT_R * (1 + ahead / LOOKAHEAD), opacity });
    }
  }

  const marks = [...rings.values(), ...dots.values()];
  if (isHidden(hidden, now)) {
    // Inside a hidden passage, the chord is all there is to read.
    const chord = cursors.chords.window(now, now).at(-1);
    marks.push(
      chord === undefined
        ? message(middle, UNCLEAR_LABEL, false, 1)
        : message(middle, chord.symbol, true, emphasis(chord.confidence, CHORD_THRESHOLDS)),
    );
  }
  return marks;
}

function message(at: { x: number; y: number }, text: string, chord: boolean, opacity: number): Mark {
  return { kind: "message", key: "message", ...at, text, chord, opacity };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/fretboard/layout.test.ts`
Expected: PASS, 25 tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/fretboard/layout.ts web/src/fretboard/layout.test.ts
git commit -m "feat(web): lay out the fretboard's dots and rings as keyed marks

A note is lit from its onset for max(dur, 0.15 s), until the next onset
on its string ends it. One dot per string, named by pitch class. Coming
notes get a ring 1.5 s ahead that closes from 2r to r; one per position,
the nearest. Opacity is the shared emphasis() and nothing else, and
hidden notes get no mark. Inside a hidden passage the neck shows the
sounding chord, or says the passage is unclear.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The keyed updater

This applies each frame's marks to an SVG layer without React. Each key keeps one node. A new key gets a node, a key that stays has its node's attributes updated, and a key that is gone has its node removed. Rings, dots and the message go into three groups, drawn in that order, so a dot covers the ring that closes on it whatever order the marks arrive in. Attributes are written only when they change.

**Files:**
- Create: `web/src/fretboard/marks.ts`, `web/src/fretboard/marks.test.ts`

**Interfaces:**
- Consumes: `Mark` (Task 3).
- Produces: `class MarkLayer`, from `web/src/fretboard/marks.ts`:
  - `constructor(layer: SVGGElement)`. Appends three groups to `layer`: `g.fret-rings`, `g.fret-dots` and `g.fret-messages`.
  - `apply(marks: readonly Mark[]): void`.
  - `dispose(): void`. Removes the groups, and every node in them.
  - The nodes it makes, which Task 5's CSS styles:
    - a ring is `circle.fret-ring`, with `cx`, `cy` and `r`;
    - a dot is `g.fret-dot`, with `transform="translate(x y)"`, holding a `circle` with `r` and a `text` with the name;
    - the message is `text.fret-message`, with the class `fret-chord` added when it shows a chord.
  - Every node has an `opacity` attribute.

- [ ] **Step 1: Write the failing tests**

Create `web/src/fretboard/marks.test.ts`:

```typescript
// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import type { Mark } from "./layout";
import { MarkLayer } from "./marks";

const SVG = "http://www.w3.org/2000/svg";

function dot(key: string, fields: Partial<Extract<Mark, { kind: "dot" }>> = {}): Mark {
  return { kind: "dot", key, x: 10, y: 20, r: 11, name: "E", opacity: 1, ...fields };
}

function ring(key: string, r: number): Mark {
  return { kind: "ring", key, x: 30, y: 40, r, opacity: 0.5 };
}

describe("MarkLayer", () => {
  let layer: SVGGElement;
  let marks: MarkLayer;

  beforeEach(() => {
    const svg = document.createElementNS(SVG, "svg");
    layer = document.createElementNS(SVG, "g");
    svg.append(layer);
    document.body.replaceChildren(svg);
    marks = new MarkLayer(layer);
  });

  const nodes = (selector: string) => [...layer.querySelectorAll(selector)];

  it("creates a node for a new key", () => {
    marks.apply([dot("dot:n1", { name: "C#", opacity: 0.35 })]);

    const [node] = nodes(".fret-dot");
    expect(node.getAttribute("transform")).toBe("translate(10 20)");
    expect(node.getAttribute("opacity")).toBe("0.35");
    expect(node.querySelector("circle")?.getAttribute("r")).toBe("11");
    expect(node.querySelector("text")?.textContent).toBe("C#");
  });

  it("reuses the node for the same key, and updates its attributes", () => {
    marks.apply([ring("ring:0:3", 22)]);
    const [before] = nodes(".fret-ring");

    marks.apply([ring("ring:0:3", 16.5)]);

    const [after] = nodes(".fret-ring");
    expect(after).toBe(before);
    expect(after.getAttribute("r")).toBe("16.5");
    expect(nodes(".fret-ring")).toHaveLength(1);
  });

  it("removes the node of a key that is gone", () => {
    marks.apply([dot("dot:n1"), dot("dot:n2", { y: 50 })]);

    marks.apply([dot("dot:n2", { y: 50 })]);

    expect(nodes(".fret-dot").map((n) => n.getAttribute("transform"))).toEqual(["translate(10 50)"]);
  });

  it("draws rings under dots, and a message over both, whatever order they arrive in", () => {
    const message: Mark = { kind: "message", key: "message", x: 0, y: 0, text: "Am", chord: true, opacity: 1 };

    marks.apply([message, dot("dot:n1"), ring("ring:0:3", 20)]);

    const order = nodes(".fret-ring, .fret-dot, .fret-message").map((n) => n.getAttribute("class"));
    expect(order).toEqual(["fret-ring", "fret-dot", "fret-message fret-chord"]);
  });

  it("restyles the message when it changes from a chord to the unclear label", () => {
    const chord: Mark = { kind: "message", key: "message", x: 0, y: 0, text: "Am", chord: true, opacity: 1 };
    marks.apply([chord]);
    const [before] = nodes(".fret-message");

    marks.apply([{ ...chord, text: "unclear passage", chord: false }]);

    expect(nodes(".fret-message")).toEqual([before]);
    expect(before.getAttribute("class")).toBe("fret-message");
    expect(before.textContent).toBe("unclear passage");
  });

  it("removes everything it drew on dispose", () => {
    marks.apply([dot("dot:n1"), ring("ring:0:3", 20)]);

    marks.dispose();

    expect(layer.childNodes).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/fretboard/marks.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './marks'`.

- [ ] **Step 3: Write the module**

Create `web/src/fretboard/marks.ts`:

```typescript
/**
 * The keyed updater: applies each frame's marks to an SVG layer without
 * React. A mark's key is stable across frames, so its node is created once,
 * has its attributes set while the key lasts, and is removed when the key is
 * gone. Colours, strokes and fonts come from the classes, in styles.css.
 */
import type { Mark } from "./layout";

const SVG = "http://www.w3.org/2000/svg";

type Kind = Mark["kind"];

/** Drawn in this order, so a dot covers the ring that closes on it and a
 * message sits over both. */
const KINDS: readonly Kind[] = ["ring", "dot", "message"];

export class MarkLayer {
  private readonly groups: Record<Kind, SVGGElement>;
  private readonly nodes = new Map<string, SVGElement>();

  /** Takes `layer` over: React renders it empty and leaves it alone. */
  constructor(layer: SVGGElement) {
    const group = (kind: Kind) => {
      const g = document.createElementNS(SVG, "g");
      g.setAttribute("class", `fret-${kind}s`);
      layer.append(g);
      return g;
    };
    this.groups = { ring: group("ring"), dot: group("dot"), message: group("message") };
  }

  apply(marks: readonly Mark[]): void {
    const seen = new Set<string>();
    for (const mark of marks) {
      seen.add(mark.key);
      let node = this.nodes.get(mark.key);
      if (node === undefined) {
        node = create(mark.kind);
        this.groups[mark.kind].append(node);
        this.nodes.set(mark.key, node);
      }
      update(node, mark);
    }
    for (const [key, node] of this.nodes) {
      if (seen.has(key)) continue;
      node.remove();
      this.nodes.delete(key);
    }
  }

  /** Remove every mark, and the groups that held them. */
  dispose(): void {
    for (const kind of KINDS) this.groups[kind].remove();
    this.nodes.clear();
  }
}

function create(kind: Kind): SVGElement {
  switch (kind) {
    case "ring":
      return element("circle", "fret-ring");
    case "dot": {
      const dot = element("g", "fret-dot");
      dot.append(element("circle"), element("text"));
      return dot;
    }
    case "message":
      return element("text", "fret-message");
  }
}

function update(node: SVGElement, mark: Mark): void {
  set(node, "opacity", mark.opacity);
  switch (mark.kind) {
    case "ring":
      set(node, "cx", mark.x);
      set(node, "cy", mark.y);
      set(node, "r", mark.r);
      break;
    case "dot": {
      set(node, "transform", `translate(${mark.x} ${mark.y})`);
      const [circle, text] = node.children;
      set(circle, "r", mark.r);
      if (text.textContent !== mark.name) text.textContent = mark.name;
      break;
    }
    case "message":
      set(node, "class", mark.chord ? "fret-message fret-chord" : "fret-message");
      set(node, "x", mark.x);
      set(node, "y", mark.y);
      if (node.textContent !== mark.text) node.textContent = mark.text;
      break;
  }
}

function element(name: string, className?: string): SVGElement {
  const node = document.createElementNS(SVG, name);
  if (className !== undefined) node.setAttribute("class", className);
  return node;
}

/** Only writes what changed: most marks hold still for most frames. */
function set(node: Element, name: string, value: string | number): void {
  const text = String(value);
  if (node.getAttribute(name) !== text) node.setAttribute(name, text);
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/fretboard/marks.test.ts`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/fretboard/marks.ts web/src/fretboard/marks.test.ts
git commit -m "feat(web): apply the fretboard's marks to SVG by key

One node per key for the key's whole life: created when it appears,
updated in place, removed when it is gone. Rings, dots and the message
sit in three groups, so the stacking never depends on arrival order.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The fretboard, in the player

This is the component, with the player mounting it above the tab strip and the stylesheet giving it colour. React renders the neck from `neckOf`. The notes layer is a `<g>` that React renders empty and hands to a `MarkLayer`.

The component measures a plain `<div>` that wraps the SVG, never the SVG itself. So the SVG's width cannot feed back into its own measurement, which is the same trap `TabStrip`'s comments describe. The frame listener reads the neck from a ref. A resize then moves the marks on the next frame, without resubscribing, which would clear them for a frame (Review Focus 3).

**Files:**
- Create: `web/src/fretboard/Fretboard.tsx`, `web/src/fretboard/Fretboard.test.tsx`
- Modify: `web/src/player/Player.tsx` (whole file below), `web/src/player/Player.test.tsx` (one test added)
- Modify: `web/src/styles.css` (tokens and classes)

**Interfaces:**
- Consumes:
  - `neckOf` (Task 2), `cursorsOf` and `layout` (Task 3), and `MarkLayer` (Task 4);
  - `PlaybackEngine`'s `onFrame`, `redraw` and `seek` (existing);
  - `FakeMedia` and `FakeFrames` from `web/src/test/fakeMedia.ts`, and `JOB_ID` from `web/src/test/jobs.ts` (existing).
- Produces:
  - `Fretboard({ song, engine }: { song: Song; engine: PlaybackEngine })`, from `web/src/fretboard/Fretboard.tsx`. It renders `div.fretboard > svg[role=img][aria-label=Fretboard]`.
  - `Player` renders `<Fretboard>` between `<Warnings>` and `<TabStrip>`.
  - The `--fret-*` custom properties, light and dark, and the `.fretboard` and `.fret-*` classes in `web/src/styles.css`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/fretboard/Fretboard.test.tsx`:

```tsx
// @vitest-environment jsdom
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PlaybackEngine } from "../playback/engine";
import { buildSong, type Song } from "../song";
import { FakeFrames, FakeMedia } from "../test/fakeMedia";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import { JOB_ID } from "../test/jobs";
import type { TabDocument } from "../types/tabDocument";
import { Fretboard } from "./Fretboard";
import { neckOf } from "./neck";

const FIRST_SONG: TabDocument = firstSongJson;

/** A confident G on the low E string's third fret, from 1 s to 2 s. */
const ONE_NOTE: TabDocument = {
  ...FIRST_SONG,
  notes: [{ id: "g", t: 1, dur: 1, midi: 43, string: 0, fret: 3, confidence: 0.95 }],
  chords: [],
};

/** Stands in for the browser's: jsdom has none. */
class FakeResizeObserver {
  static last: FakeResizeObserver | null = null;
  constructor(readonly callback: () => void) {
    FakeResizeObserver.last = this;
  }
  observe() {}
  disconnect() {}
}

/** An engine whose animation frames run only when flushed. */
function engineFor(song: Song) {
  const frames = new FakeFrames();
  const engine = new PlaybackEngine({
    media: new FakeMedia(),
    jobId: JOB_ID,
    duration: song.duration,
    requestFrame: frames.request,
    cancelFrame: frames.cancel,
  });
  return { engine, frames };
}

function mount(doc: TabDocument = FIRST_SONG) {
  const song: Song = buildSong(doc);
  const { engine, frames } = engineFor(song);
  render(<Fretboard song={song} engine={engine} />);
  const svg = screen.getByRole("img", { name: "Fretboard" });
  /** Move the song to `t` and run the frame that draws it. */
  const at = (t: number) => {
    engine.seek(t);
    frames.flush();
  };
  return { song, engine, svg, at };
}

describe("Fretboard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    FakeResizeObserver.last = null;
  });

  it("draws N + 1 wires and one string per tuning entry", () => {
    const { svg } = mount();

    // The first song reaches fret 8, so the neck shows twelve.
    expect(svg.querySelectorAll(".fret-nut, .fret-wire")).toHaveLength(13);
    expect(svg.querySelectorAll(".fret-string")).toHaveLength(6);
    expect([...svg.querySelectorAll(".fret-label")].map((label) => label.textContent)).toEqual([
      "E", "A", "D", "G", "B", "e",
    ]);
    expect(svg.querySelectorAll(".fret-number")).toHaveLength(12);
  });

  it("lights a note while it sounds, named by pitch", () => {
    const { svg, at } = mount(ONE_NOTE);

    at(1.5);
    expect(svg.querySelector(".fret-dot text")?.textContent).toBe("G");

    at(3);
    expect(svg.querySelector(".fret-dot")).toBeNull();
  });

  it("rings a note before it sounds", () => {
    const { svg, at } = mount(ONE_NOTE);

    at(0.25);

    expect(svg.querySelectorAll(".fret-ring")).toHaveLength(1);
    expect(svg.querySelector(".fret-dot")).toBeNull();
  });

  it("shows the message for a document with no notes", () => {
    const { svg, at } = mount({ ...FIRST_SONG, notes: [] });

    at(0);

    expect(svg.querySelector(".fret-message")?.textContent).toBe("No notes to show");
  });

  it("subscribes to the engine's frames, and unsubscribes on unmount", () => {
    const song = buildSong(FIRST_SONG);
    const { engine } = engineFor(song);
    const stopped = vi.fn();
    const onFrame = engine.onFrame.bind(engine);
    vi.spyOn(engine, "onFrame").mockImplementation((listener) => {
      const stop = onFrame(listener);
      return () => {
        stopped();
        stop();
      };
    });

    const view = render(<Fretboard song={song} engine={engine} />);
    expect(engine.onFrame).toHaveBeenCalledTimes(1);

    view.unmount();
    expect(stopped).toHaveBeenCalledTimes(1);
  });

  it("refits the neck on resize, and moves a sounding note's dot with it, without resubscribing", () => {
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    const { song, engine, svg, at } = mount(ONE_NOTE);
    const onFrame = vi.spyOn(engine, "onFrame");
    at(1.5);
    const dot = svg.querySelector(".fret-dot");

    const box = svg.parentElement as HTMLElement;
    Object.defineProperty(box, "clientWidth", { configurable: true, value: 900 });
    act(() => FakeResizeObserver.last?.callback());
    at(1.5);

    const neck = neckOf(song, 900);
    expect(svg.getAttribute("width")).toBe("900");
    expect(svg.querySelector(".fret-dot")).toBe(dot);
    expect(dot?.getAttribute("transform")).toBe(`translate(${neck.noteX[3]} ${neck.strings[0].y})`);
    expect(onFrame).not.toHaveBeenCalled();
  });
});
```

In `web/src/player/Player.test.tsx`, add this test after `makes the canvas's CSS height the bitmap's height, so no frame is resampled`:

```tsx
  it("shows the fretboard above the tab strip", () => {
    mount();

    const fretboard = screen.getByRole("img", { name: "Fretboard" });
    const strip = screen.getByLabelText("Tab");

    expect(fretboard.compareDocumentPosition(strip) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm --prefix web test -- src/fretboard/Fretboard.test.tsx src/player/Player.test.tsx`
Expected: FAIL. `tsc` reports `Cannot find module './Fretboard'`.

- [ ] **Step 3: Write the component**

Create `web/src/fretboard/Fretboard.tsx`:

```tsx
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import { cursorsOf, layout } from "./layout";
import { MarkLayer } from "./marks";
import { neckOf } from "./neck";

const INLAY_R = 3;
const INLAY_PAIR = 5; // fret 12's two dots sit this far either side of its centre

/**
 * The 2D fretboard. React draws the neck, which changes only with the song
 * and the panel's width. The notes are a layer React renders empty and then
 * leaves alone: every frame, layout() gives the marks for that instant and a
 * MarkLayer applies them, so React never renders at frame rate.
 */
export function Fretboard({ song, engine }: { song: Song; engine: PlaybackEngine }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const layerRef = useRef<SVGGElement>(null);
  const [width, setWidth] = useState(0);
  const neck = useMemo(() => neckOf(song, width), [song, width]);
  const cursors = useMemo(() => cursorsOf(song), [song]);
  // Read by the frame listener, so a resize moves the marks without
  // resubscribing, which would clear them for a frame.
  const neckRef = useRef(neck);

  // Measured before the first paint, so the neck never shows at width 0. The
  // box is a plain div: its width does not depend on the SVG's.
  useLayoutEffect(() => {
    const box = boxRef.current;
    if (box === null) return;
    const measure = () => setWidth(box.clientWidth);
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(box);
    return () => observer?.disconnect();
  }, []);

  useEffect(() => {
    neckRef.current = neck;
    engine.redraw();
  }, [neck, engine]);

  useEffect(() => {
    const layer = layerRef.current;
    if (layer === null) return;
    const marks = new MarkLayer(layer);
    const stop = engine.onFrame((t) => marks.apply(layout(song, cursors, t, neckRef.current)));
    return () => {
      stop();
      marks.dispose();
    };
  }, [song, cursors, engine]);

  const end = neck.wireX[neck.frets];
  return (
    <div ref={boxRef} className="fretboard">
      <svg role="img" aria-label="Fretboard" width={neck.width} height={neck.height}>
        <rect
          className="fret-board"
          x={neck.wireX[0]}
          y={neck.top}
          width={end - neck.wireX[0]}
          height={neck.bottom - neck.top}
        />
        {neck.inlays.map(({ x, double }) =>
          (double ? [x - INLAY_PAIR, x + INLAY_PAIR] : [x]).map((cx) => (
            <circle key={cx} className="fret-inlay" cx={cx} cy={neck.inlayY} r={INLAY_R} />
          )),
        )}
        {neck.wireX.map((x, n) => (
          <line
            key={n}
            className={n === 0 ? "fret-nut" : "fret-wire"}
            x1={x}
            y1={neck.top}
            x2={x}
            y2={neck.bottom}
          />
        ))}
        {neck.strings.map(({ y, weight }, s) => (
          <line key={s} className="fret-string" x1={neck.stringsFrom} y1={y} x2={end} y2={y} strokeWidth={weight} />
        ))}
        {neck.strings.map(({ y, label }, s) => (
          <text key={s} className="fret-label" x={neck.labelX} y={y}>
            {label}
          </text>
        ))}
        {neck.noteX.slice(1).map((x, i) => (
          <text key={i} className="fret-number" x={x} y={neck.numberY}>
            {i + 1}
          </text>
        ))}
        <g ref={layerRef} />
      </svg>
    </div>
  );
}
```

- [ ] **Step 4: Mount it in the player**

Replace `web/src/player/Player.tsx` with:

```tsx
import { useEffect, useState } from "react";

import { Fretboard } from "../fretboard/Fretboard";
import type { MediaLike } from "../playback/clock";
import { PlaybackEngine } from "../playback/engine";
import type { Song } from "../song";
import { TabStrip } from "../tab/TabStrip";
import { Controls } from "./Controls";
import { useTransportKeys } from "./keys";
import { Warnings } from "./Warnings";

export interface PlayerProps {
  song: Song;
  jobId: string;
  /** Must be stable across renders: a new function makes a new engine. */
  createMedia: () => MediaLike;
}

/** One engine per song; every view subscribes to it. The fretboard sits
 * above the tab strip; the 3D guitar will be one more onFrame listener. */
export function Player({ song, jobId, createMedia }: PlayerProps) {
  const [engine, setEngine] = useState<PlaybackEngine | null>(null);

  useEffect(() => {
    const created = new PlaybackEngine({ media: createMedia(), jobId, duration: song.duration });
    setEngine(created);
    return () => created.dispose();
  }, [song, jobId, createMedia]);

  useTransportKeys(engine);

  if (engine === null) return null;
  return (
    <section className="player">
      <Warnings warnings={song.warnings} />
      <Fretboard song={song} engine={engine} />
      <TabStrip song={song} engine={engine} />
      <Controls engine={engine} />
    </section>
  );
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/fretboard/Fretboard.test.tsx src/player/Player.test.tsx`
Expected: PASS, 23 tests: 6 in `Fretboard.test.tsx` and 17 in `Player.test.tsx`.

- [ ] **Step 6: Give it colour**

The SVG takes every colour, stroke and font from these classes. Dark mode therefore needs no code. Nothing reads a palette, as `TabStrip` must.

In `web/src/styles.css`, replace the first line:

```css
/* Colours are tokens. The tab strip's canvas reads the --tab-* ones. */
```

with:

```css
/* Colours are tokens. The tab strip's canvas reads the --tab-* ones; the
   fretboard's SVG uses the --fret-* ones through its classes. */
```

In `:root`, after `--tab-hidden: #e7e1d4;`, add:

```css

  --fret-background: #fbfaf7;
  --fret-board: #f1ede4;
  --fret-wire: #b4ad9f;
  --fret-nut: #6b665d;
  --fret-string: #8c8578;
  --fret-inlay: #d2ccbf;
  --fret-text: #7a7469;
  --fret-dot: #c2410c;
  --fret-dot-text: #ffffff;
  --fret-ring: #c2410c;
  --fret-chord: #1f1d1a;
```

In the dark-mode `:root`, after `--tab-hidden: #2b2824;`, add:

```css

    --fret-background: #171614;
    --fret-board: #23211e;
    --fret-wire: #57524a;
    --fret-nut: #a39d91;
    --fret-string: #8a8478;
    --fret-inlay: #3d3934;
    --fret-text: #a39d91;
    --fret-dot: #fb923c;
    --fret-dot-text: #171614;
    --fret-ring: #fb923c;
    --fret-chord: #ece8df;
```

Then, after the `.tab-strip` rule and before `.controls {`, add:

```css
/* The SVG takes its width from this box, never the other way round. */
.fretboard {
  margin-bottom: 12px;
  border-radius: 8px;
  overflow: hidden;
  background: var(--fret-background);
  box-shadow: 0 0 0 1px var(--border);
}

.fretboard svg {
  display: block;
}

.fret-board {
  fill: var(--fret-board);
}

.fret-wire {
  stroke: var(--fret-wire);
  stroke-width: 2;
}

.fret-nut {
  stroke: var(--fret-nut);
  stroke-width: 5;
}

/* stroke-width comes from each string's attribute: lower strings are thicker. */
.fret-string {
  stroke: var(--fret-string);
}

.fret-inlay {
  fill: var(--fret-inlay);
}

.fret-label,
.fret-number,
.fret-dot text,
.fret-message {
  text-anchor: middle;
  dominant-baseline: central;
}

.fret-label,
.fret-number {
  fill: var(--fret-text);
  font: 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.fret-dot circle {
  fill: var(--fret-dot);
}

.fret-dot text {
  fill: var(--fret-dot-text);
  font: bold 11px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.fret-ring {
  fill: none;
  stroke: var(--fret-ring);
  stroke-width: 2;
}

/* A halo in the board's colour, so the strings do not strike through it. */
.fret-message {
  fill: var(--fret-text);
  font: 15px system-ui, sans-serif;
  paint-order: stroke;
  stroke: var(--fret-board);
  stroke-width: 6px;
  stroke-linejoin: round;
}

.fret-message.fret-chord {
  fill: var(--fret-chord);
  font: bold 32px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
```

- [ ] **Step 7: Run the whole web suite, the linter and the build**

Run: `npm --prefix web test`
Expected: PASS, 244 tests in 20 files.

Run: `npm --prefix web run lint && npm --prefix web run build`
Expected: no lint problems, and `✓ built`.

- [ ] **Step 8: Commit**

```bash
git add web/src/fretboard/Fretboard.tsx web/src/fretboard/Fretboard.test.tsx \
  web/src/player/Player.tsx web/src/player/Player.test.tsx web/src/styles.css
git commit -m "feat(web): show the 2D fretboard above the tab strip

React draws the neck on mount and on resize. The notes are a layer it
leaves alone: each frame, layout() gives the marks and a MarkLayer
applies them, so nothing renders at frame rate. The listener reads the
neck from a ref, so a resize moves the marks without resubscribing.
Colours are --fret-* tokens, light and dark.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Manual acceptance, then the PR

Some checks cannot be automated honestly. Whether the dots land with the audio, whether 1.5 s is enough warning, whether the rings stay readable in a real dense passage, and whether two string orders on one screen confuse: all need a person. This task needs your human partner. The agent writes the record and brings the services up, and the person plays real songs and fills the record in. The PR does not open until `acceptance.md` is filled in.

**Files:**
- Create: `docs/specs/007-2d-fretboard/acceptance.md`
- Modify: `docs/specs/007-2d-fretboard/plan.md` (tick the checkboxes)
- Possibly modify: `web/src/fretboard/layout.ts` (`LOOKAHEAD` only, if Step 3 says so)

**Interfaces:** none.

- [ ] **Step 1: Write the record to fill in**

Create `docs/specs/007-2d-fretboard/acceptance.md`:

```markdown
# Manual acceptance

**Spec:** [007 — Manual acceptance](spec.md#manual-acceptance)

Checks that cannot be automated honestly. A person runs each one in a
browser against real services, and records the result here before the PR is
opened.

## Setup

- Commit: …
- Machine, OS and browser: …
- Songs: title, length, and the frets they reach

## End to end

- [ ] At 1×, the dots light with the audio and with the tab strip
- [ ] At 0.5×, the same, and the rings close half as fast
- [ ] In the song's densest passage, the rings stay readable
- [ ] 1.5 s of warning is enough to move the hand
- [ ] A seek, forwards and back, leaves the board right at once
- [ ] An A/B loop leaves the board right each time it restarts
- [ ] A song in open position gets twelve wide frets; a song up the neck fits, with room to spare

Densest passage (song, and time): …

If 1.5 s was not enough, or was too much: the value chosen, and why: …

Notes: …

## Dark mode and resizing

- [ ] Dark mode: the neck, dots, rings and messages are all readable
- [ ] Resizing the window during playback refits the neck, and the dots and rings follow it

Notes: …

## The two string orders

The tab strip puts the highest string on top, and the fretboard the lowest.
Reading the two together, was the reversed order confusing? …
```

- [ ] **Step 2: Bring the services up for your human partner**

```bash
make services && make migrate
```

Then, in separate terminals: `make api`, `make worker` and `make web`. `make worker` runs the real stages, so it needs `uv sync --extra ml`.

Check that all three answer:

```bash
curl -s localhost:8000/health
curl -s localhost:5173/health
curl -s -o /dev/null -w "%{http_code}\n" localhost:5173/
```

Expected: `"status":"ok"` twice, then `200`.

- [ ] **Step 3: Stop for the acceptance run**

**Ask your human partner** to run the checks in `acceptance.md` at `http://localhost:5173`, with real songs, and to fill it in. Do not fill in any result yourself.

When they are done:

- **If 1.5 s is the wrong look-ahead,** change `LOOKAHEAD` in `web/src/fretboard/layout.ts` to the value they chose. Its tests are written in terms of `LOOKAHEAD`, so they hold. Run `npm --prefix web test -- src/fretboard`, and commit with a message giving the value and the reason. The record must already say why. Add the change to *Decisions the spec left open*, below.
- **If the SVG stutters during playback,** stop and raise it with your human partner. The spec names the canvas painter as the fallback, but that is a design change, not a fix. Do not open the PR.
- **If the two string orders confused them,** record it. The spec's *Consequences* names the follow-up, an orientation setting. It is not in this phase.

- [ ] **Step 4: Verify everything**

Run: `GUITARVIS_REQUIRE_SERVICES=1 make check`
Expected: exit 0, with nothing skipped for want of services.

Tick every checkbox in this plan that was done, and leave unticked any that was not. Then commit both files:

```bash
git add docs/specs/007-2d-fretboard/acceptance.md docs/specs/007-2d-fretboard/plan.md
git commit -m "docs: 007's manual acceptance and plan checkboxes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Open the PR**

Pushing and opening a PR are visible to others, so confirm with your human partner first. Then write the body to `tmp/pr-body.md` (`tmp/` is gitignored), from `.github/pull_request_template.md`:

- **Spec:** `docs/specs/007-2d-fretboard/spec.md`.
- *What changed*: one paragraph.
- *Verification*: tick the boxes for what was run, and link `acceptance.md`. No contract artifacts changed.
- *Deviations from the spec*: copy the section below.

End the body with:

```text
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Then:

```bash
git push -u origin 007-2d-fretboard
gh pr create --base main --title "2D fretboard (phase 5, first half)" --body-file tmp/pr-body.md
```

Expected: `gh` prints the PR's URL. Give it to your human partner.

---

## Decisions the spec left open

The plan settles these. The PR's *Deviations from the spec* section copies them.

- **A later onset ends an earlier note on its string for good.** The spec says both "a later onset on the same string ends the earlier note" and "among the lit notes on a string, only the latest onset is drawn". Those disagree when a long note is followed by a short one: under the second rule, the long note lights again once the short one goes dark. `litUntil` follows the first rule. Each note is lit until the end of `max(dur, MIN_LIT)`, or until the next onset on its string, whichever comes first (Review Focus 1).
- **The hidden passages are read back to the earliest onset in play.** A note still sounding may have started in a passage that is already over, and it stays hidden. This is the rule the tab strip applies to the same notes (Review Focus 2).
- **`Cursors` carries `until` beside the two cursors.** The map is computed once per song, with them.
- **The inlays sit in a row under the neck,** as the spec's sketch draws them, not on the fingerboard, where the dots would cover them. Fret 12's pair sits side by side.
- **The strings run through the open-string column,** so an open note's dot sits on its string. The fret numbers run from 1 to N, with none under the open column.
- **The message has a halo in the board's colour,** so the strings do not strike through it, as the tab strip knocks out the string behind each fret number. A chord symbol is drawn at 32 px, bold and monospace.
- **Dots and the message are drawn in two SVG groups, in that order.** The stacking never depends on the order in which marks first appeared.
- **The component measures a `<div>` that wraps the SVG,** and sizes the SVG from it.
- **The tab strip now reads its notes' hidden passages back to the earliest onset in play, too.** The final review found that 006's strip read them only from the screen's left edge, so a weak note sounding on after its band had scrolled off came back as a sounding tail, while the fretboard kept it hidden. Success condition 3 asks both views to hide the same notes, so the strip takes the fretboard's rule, for its notes only. `confidence.ts` stays unchanged, so the widening is written in both layouts; moving it into one helper there is a later change.
