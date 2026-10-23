# Player Redesign — Design

**Date:** 2026-10-22
**Status:** Draft for review
**Parent spec:** [001-guitarvis-design](../001-guitarvis-design/spec.md)
**Builds on:** [006-tab-view-sync](../006-tab-view-sync/spec.md),
[007-2d-fretboard](../007-2d-fretboard/spec.md),
[008-3d-guitar](../008-3d-guitar/spec.md)
**Mockup:** *Web mockups · WebPlayer* in the
[GuitarVis design system](https://claude.ai/artifact/3Zc4v6XxdR3viHReBX6weE)

## Purpose

Phases 4 and 5 built the player one view at a time: the tab strip, then the
fretboard above it, then the 3D guitar behind a `[2D | 3D]` toggle, with a
row of word buttons underneath. Each view works and stays in sync. The page
as a whole was never designed: it is the views stacked in the order they
shipped.

Using it shows four gaps.

1. **The transport scrolls away.** On a laptop the guitar and the tab fill
   the screen, and the controls sit below the fold. A player with a guitar on
   their lap has to scroll to reach Play.
2. **The song's structure is invisible.** The document carries `sections`
   and `chords`, but only the tab strip shows them, as small text that scrolls
   past. You cannot see where the chorus is or jump to it, and you cannot see
   the chord coming next until it is on the strip.
3. **The loop is hard to read.** A and B light up when set, but nothing says
   where they are. The only way to see the loop is to watch the tab strip
   reach it.
4. **Warnings shout and then stay.** Every warning is a full list item above
   the guitar, for the whole session.

This spec redesigns the song page around those gaps. It changes the layout
and adds three small views. It does not change how any existing view draws.

The success conditions:

1. With the stack running (`make services`, `migrate`, `api`, `worker`,
   `web`), a song plays with the transport always visible at the bottom of
   the window, at any scroll position and window height down to 600 px.
2. The section list shows every section in the document. Clicking one seeks
   to its start, and the current section stays highlighted as the song plays.
3. The chord lane shows the song's chords in order. The current chord is
   marked and the lane moves with the audio, in step with the tab strip at
   1× and 0.5×. Weak chords are faded by the same rule the tab strip uses.
4. The scrubber shows the playhead, the section boundaries and the A–B loop.
   Dragging it seeks.
5. Warnings collapse to one line with a count and can be expanded. They are
   never hidden entirely.
6. The guitar, tab strip and engine are unchanged except where this spec
   says so. Their tests pass unmodified.
7. `make check` gates all of it.

## Scope

**In:**
- the song page layout: header, main column, sections sidebar, docked
  transport;
- the header: back link, title, metadata line, the view switch
  (`3D · Fretboard · Tab only`) moved out of the guitar;
- a **chord lane** under the guitar;
- a **sections sidebar**: list, jump-to, current section;
- the **docked transport**: play, ±5 s, time, scrubber, speed, A–B loop with
  times, audio source;
- the **scrubber**, with section ticks and the loop drawn;
- the guitar's **now/next chord overlay** and dot legend;
- **collapsed warnings**;
- `[` and `]` to set loop A and B;
- a small inline icon module for the transport;
- two new colour tokens, `--bg-raised` and `--on-accent`, light and dark;
- a narrow layout (below 900 px) that stacks the sidebar under the main
  column, so the page does not break on a tablet;
- a manual acceptance record.

**Out:**
- the home page, library, processing view and URL field from the mockups.
  Each gets its own spec; the processing view needs api changes;
- the iOS app, and any phone-specific layout (open decision 10 stays open
  for phones);
- any change to how the tab strip, 2D fretboard or 3D guitar draw;
- chord diagrams (fingering boxes). The document has chord symbols, not
  shapes;
- click-to-seek on the tab strip or the guitar;
- editing the tab, renaming sections, or saving loops;
- tempo-based features (a metronome, bars-per-loop). The metadata line shows
  `tempo_bpm_avg` when present, and that is all;
- side-by-side 3D and 2D (open decision 9 stays open).

No change to `tabdoc.py`, the schema, the api or the worker. `Song` gains a
`tempo` field read from `timing.tempo_bpm_avg`; nothing else in the document
is new to the client.

## Decisions and where they came from

| # | Decision | Why |
|---|---|---|
| D1 | Transport docks to the bottom of the viewport | Gap 1. The bottom matches every media player the user already knows, and keeps the guitar and tab at the top where the eye is. |
| D2 | The view switch moves to the page header and gains *Tab only* | It chooses what the whole page shows, not how the guitar looks. *Tab only* is for readers who want the tab large and no WebGL. |
| D3 | Sections are a sidebar list, not tabs or a dropdown | A song has 4–10 sections; all fit, and seeing them all is the point. |
| D4 | The chord lane is a separate row, not a bigger tab-strip chord row | The tab strip's layout measures glyphs and spaces chords by time; a lane cell per chord reads as a sequence and can be wider than the strip allows. |
| D5 | The scrubber is HTML, not canvas | It has at most a few dozen marks. It needs to be keyboard-operable (`role="slider"`), which a canvas makes hard. |
| D6 | Icons on transport buttons, words everywhere else | Play/pause and ±5 s are universal. Speed, loop and source keep text (`0.75×`, `A 0:40`, `Guitar only`). Every icon button has an `aria-label`. |
| D7 | Warnings collapse to one line, expanded on demand | Gap 4. 006's rule — a degraded tab must say so — still holds: the line is always there while there are warnings. |

## Approach

### Shape of the change

```
web/src/
  song.ts                 + tempo: number | null
  icons.tsx               the transport's inline SVG icons
  player/
    Player.tsx            the new layout; owns the view choice
    Header.tsx            back, title, metadata, view switch
    ViewSwitch.tsx        3D · Fretboard · Tab only (persisted)
    ChordLane.tsx         onFrame → which cell is current
    Sections.tsx          list, seek on click, current via its own cursor
    Transport.tsx         replaces Controls.tsx: the docked bar
    Scrubber.tsx          slider: playhead, sections, loop
    Warnings.tsx          collapsed by default
    keys.ts               + [ and ]
    lane.ts               pure: (chords, t) → cells and the current index
    scrub.ts              pure: (duration, sections, loop, width) → marks
  guitar/Guitar.tsx       takes `view` as a prop; loses its own toggle;
                          gains the now/next overlay and legend
  styles.css              layout, transport, lane, sidebar; two tokens
```

006's split again: the logic worth testing lives in `lane.ts` and
`scrub.ts`, which are pure; the components only draw.

### Layout

```
┌────────────────────────────────────────────────────────────────────┐
│ ‹ Library   Porch session (take 2)            [3D|Fretboard|Tab]  ⋯│
│             3:42 · Standard tuning · about 92 bpm                  │
├──────────────────────────────────────────────────┬─────────────────┤
│ ⚠ 2 things to know about this tab …        Show  │ SECTIONS        │
│ ┌──────────────────────────────────────────────┐ │ Intro      0:00 │
│ │ Am  next C                       Reset view  │ │▌Verse 1    0:08 │
│ │            (guitar)                          │ │ Chorus     0:41 │
│ │ ● Sounding ○ Next ◐ Less sure                │ │ …               │
│ └──────────────────────────────────────────────┘ │                 │
│ [Am][C][G̲][D][Am][F][C][E7]          chord lane │ CHORDS          │
│ ┌──────────────────────────────────────────────┐ │ Am C G D F E7   │
│ │ tab strip                                    │ │                 │
│ └──────────────────────────────────────────────┘ │                 │
├──────────────────────────────────────────────────┴─────────────────┤
│ ↺5 (❚❚) ↻5  ──●───[▓▓]──|──|──   1:07 · Verse 1   0.5× 0.75× 1×    │
│                                     A 0:40  B 1:14  ×   Full mix|Guitar │
└────────────────────────────────────────────────────────────────────┘
```

- The page is a CSS grid: header, a body of `1fr 248px`, and the transport.
  The transport is `position: sticky; bottom: 0` inside the page, so it
  docks without leaving the document flow and never covers the last row of
  content.
- `main`'s `max-width` grows from 1100 px to 1280 px for the sidebar.
- Below 900 px the body is one column: sections and chords go under the
  tab strip, and the transport wraps onto two rows.
- *Tab only* removes the guitar and its chord overlay; the chord lane stays.
  The guitar chunk is not fetched while *Tab only* is chosen.

### The view switch

The choice is one of `"3d" | "2d" | "tab"`, persisted under the key the
guitar uses today (`VIEW_KEY`, read with a 3D fallback), so a returning
user keeps their view; `"tab"` is a new stored value. `Guitar` takes the
view as a prop and its internal `[2D | 3D]` buttons go. *Reset view* stays
on the guitar, as now.

### Chord lane

- One cell per chord in `song.chords`, in order, equal width, scrolling
  horizontally so the current cell stays in view (scrolled on a chord
  change, not every frame).
- Cell states: **played** (`--fg`), **current** (`--accent` text and ring on
  `--bg-raised`), **coming** (`--muted`).
- A cell's opacity comes from the shared confidence rule in
  `confidence.ts` with the chord thresholds (`CHORD_HIDE`, `CHORD_FULL`),
  unchanged. Chords are faded, never hidden — the rule the tab strip
  follows.
- No chords in the document: the lane is not rendered.
- It finds the current chord with its own `NoteCursor` over `song.chords`,
  as 007 established that each view makes its own. It updates on `onFrame`,
  touching the DOM only when the current index changes.

### Now/next overlay on the guitar

The current chord in `chord-large` (32 px mono) top-left, the next chord
beside it in `--muted`. During a hidden passage the guitar already shows the
chord large in the centre; the overlay then hides so the chord is not shown
twice. The legend (sounding / next / less sure) sits bottom-left.

**Open question:** the guitar draws only sounding notes today (007 dropped
approach rings). The mockup's "next" ring needs them back. Default: drop
"Next" from the legend and keep 007's decision; revisit after using it.

### Sections sidebar

- Lists `song.sections` with `label` and start time (`m:ss`, mono).
- Clicking a section calls `engine.seek(section.t)`. It does not change the
  loop.
- The current section is highlighted, found with its own cursor on
  `onFrame`, updating only on change.
- Below the list, the song's distinct chord symbols in first-heard order.
- No sections in the document: the heading reads "Sections" with "No
  sections found", so the sidebar does not jump in and out between songs.

### Docked transport

Replaces `Controls.tsx`. It keeps every behaviour `Controls` has and its
labels where they are words:

| Control | Change from today |
|---|---|
| Play/pause | 48 px round `--accent` button with an icon; `aria-label` "Play"/"Pause" |
| ±5 s | Icons, `aria-label` "Back 5 seconds"/"Forward 5 seconds" (unchanged) |
| Time | Moves under the scrubber: `1:07 · Verse 1` and the duration |
| Speed | Segmented control, same `RATES`; hidden when `!engine.canStretch` |
| Loop | `A 0:40` `B 1:14` `×` — the set times shown; unset reads `A` / `B` |
| Source | Segmented `Full mix · Guitar only` |
| Errors | `connection_lost` text and Reload move to a line above the bar |

The mousedown `preventDefault` that keeps Space as play/pause applies to
every transport control.

### Scrubber

A `role="slider"` with `aria-valuemin`/`max`/`now` and `aria-valuetext`
(`"1:07, Verse 1"`). `scrub.ts` turns duration, sections and loop into
positions as fractions of the width; the component draws them.

- Track, played portion and knob in `--accent`.
- A tick at each section start after the first.
- The loop as a `--tab-loop` band with solid edges, the same colour and
  meaning as on the tab strip.
- Pointer drag seeks on release, previewing the time while dragging, so a
  drag does not issue dozens of seeks. Arrow keys seek ±5 s, Home/End to the
  ends.
- The knob moves on `onFrame` by transform; React does not re-render it.

### Warnings

One line: an alert icon, "N things to know about this tab", and a "Show"
button that expands the full list (as today). Expanded state is per page
view, not persisted. One warning shows its text directly, with no button.

### Keys

`[` sets loop A, `]` sets loop B, through `engine.setLoopPoint`, with the
same text-field and modifier guards as Space and the arrows.

### Tokens

Two additions to `styles.css`, from the design system:

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg-raised` | `#ffffff` | `#1f1d1b` | Transport bar, current chord cell, segmented selection |
| `--on-accent` | `#ffffff` | `#171614` | Icon on the play button |

`--on-accent` matches `--guitar-dot-text`. No existing token changes.

### Testing

- `lane.test.ts`: cells and current index for empty, single, overlapping
  and gapped chords; the index at exact boundaries; fading by the shared
  thresholds.
- `scrub.test.ts`: positions for sections, loop with only A, A and B, a
  loop past the media's reported duration, and zero duration.
- `Transport`, `Sections`, `ChordLane`, `Warnings`, `ViewSwitch` under jsdom
  with a fake engine: each control calls the engine; aria labels and
  `aria-pressed`; Space still toggles after a click.
- `keys.test.ts` (new cases): `[`/`]` set points, are ignored in text fields
  and with modifiers.
- `Player.test.tsx`: *Tab only* does not mount the guitar or fetch its
  chunk.
- `song.test.ts`: `tempo` read from `timing.tempo_bpm_avg`, null when
  absent.
- Existing `Guitar`, `TabStrip` and engine tests stay green, with the
  guitar's toggle tests moved to `ViewSwitch`.

### Manual acceptance

`acceptance.md` in this folder, as 007 and 008 kept: a real song at 1× and
0.5× in Chrome, Firefox and Safari, light and dark, at 1440, 1024 and 800 px
wide; transport visible at every scroll position; section jump; loop drawn
on the scrubber and the tab strip at the same place; keyboard only from load
to loop.

## Rejected alternatives

- **A floating mini-player over the guitar.** Covers the views it controls,
  and moves when the window resizes. A docked bar is predictable.
- **Section markers only on the scrubber, no sidebar.** Ticks show where
  sections are but not what they are called; labels on a 500 px track
  collide.
- **Drawing the chord lane into the tab strip canvas.** Couples a new view
  to `layout.ts`'s glyph measurements and its scrolling window. A separate
  row keeps the strip unchanged (success condition 6).
- **Moving the transport to the top, under the header.** Keeps it visible
  too, but puts controls between the title and the music, and pushes the
  guitar down on short screens.
- **A `<input type="range">` scrubber.** Accessible for free, but cannot
  draw the loop band or section ticks without layering, and its styling
  differs per browser. A custom slider with the ARIA pattern costs little.

## Consequences

- `Controls.tsx` is deleted; its tests move to `Transport`.
- `Guitar` stops owning its view, so 008's view persistence moves to
  `ViewSwitch`. The storage key is kept so no user loses their choice.
- The page is wider (1280 px), which the tab strip's `ResizeObserver`
  already handles.
- The design system's *WebPlayer* mockup becomes the reference for this
  page; the shipped components in it should be refreshed after merge.

## Risks

- **Frame-rate re-renders.** Three new views follow playback. Each must
  update the DOM only on change (lane, sections) or by direct style writes
  (scrubber), never through React state per frame — 006's rule. Tests can't
  catch a slow page; the acceptance record checks it with the performance
  panel.
- **Sticky transport and the tab strip's height.** On a 600 px window the
  header, guitar, lane, strip and transport don't all fit. The guitar
  already clamps to 260 px; if that is not enough, *Tab only* is the answer
  rather than shrinking the strip.
- **Section quality.** The structure stage's labels may be generic or
  wrong. The sidebar makes them prominent. If they prove poor on real songs,
  the fallback is numbered sections ("Section 3") — a client-side change.
- **Scope creep from the mockups.** The mockups include a library, a link
  field and processing details. They stay out; each needs its own spec.
