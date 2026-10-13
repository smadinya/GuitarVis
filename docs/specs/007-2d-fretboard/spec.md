# 2D Fretboard — Design

**Date:** 2026-10-12
**Status:** Draft for review
**Parent spec:** [001-guitarvis-design](../001-guitarvis-design/spec.md)
**Builds on:** [006-tab-view-sync](../006-tab-view-sync/spec.md)

## Purpose

Build the first half of phase 5: a 2D fretboard that shows where the hand goes
while the song plays. The 3D guitar is the second half and gets its own spec.

After 006, a song plays with a scrolling tab strip, and the tab strip is the
only view. It is what a learner reads ahead from. It does not show the neck:
a fret number says which fret, not where that fret is under the hand, or how
far the hand has to travel to the next note. The parent spec gives that job
to the fretboard views, and calls the 2D one the cheapest to build.

006 built everything this view needs except the drawing: the
`PlaybackEngine` and its frames, the note cursor, the `Song`, and the shared
confidence rule. This phase adds one more `onFrame` listener.

The success conditions:

1. With `make services`, `make migrate`, `make api`, `make worker` and
   `make web` running, a song plays with the fretboard above the tab strip.
   Its notes light as they sound, at 1× and at 0.5×, in step with the audio
   and with the tab strip.
2. Upcoming notes arrive as closing rings, and stay readable in a real
   song's densest passage.
3. The fretboard fades and hides exactly the notes the tab strip fades and
   hides. A document with no notes, or with hidden passages, renders its
   fallback. Tests prove both.
4. `make check` gates all of it.

## Scope

**In:**
- the fretboard panel, above the tab strip;
- the neck, fitted to the song, with true fret spacing;
- sounding notes as dots named by pitch class, and upcoming notes as
  approach rings;
- the confidence rule and the hidden-passage fallback, from `confidence.ts`
  unchanged;
- moving the view text shared by the tab strip and the fretboard into one
  module;
- colour tokens for the fretboard, light and dark;
- a manual acceptance record.

**Out:**
- the 3D guitar, and the `[3D | 2D]` toggle. With one fretboard view there is
  nothing to toggle. Both come with the next spec, and open decision 9
  (simultaneous views) stays open;
- a hand-position band, or any fingering hint beyond the notes themselves;
- finger numbers. The tab document does not carry them;
- technique marks. `technique` is null in v1;
- click-to-seek, hover, and any interaction with the neck;
- bar lines, beats, sections and the A/B loop on the neck. The tab strip
  carries them;
- drawing a capo. v1 is always capo 0, and `Note.fret` is measured from the
  nut, so every position stays right whatever the capo;
- a left-handed mirror, and an orientation toggle;
- mobile layouts (open decision 10).

No change to `tabdoc.py`, the schema, the api, the worker or the evaluation.
No stage's output changes, so `CACHE_VERSION` does not move.

## Approach

### Shape of the change

```
web/src/
  labels.ts            the text views share: stringLabels, EMPTY_MESSAGE,
                       UNCLEAR_LABEL (moved from tab/layout.ts), and noteName
  fretboard/
    neck.ts            pure: (song, width) → Neck — the fret range, and where
                       every wire, string, note position and inlay sits
    layout.ts          pure: (song, cursors, t, neck) → Mark[] — dots, rings,
                       and the centred message
    marks.ts           the keyed updater: applies a Mark[] to an SVG layer
    Fretboard.tsx      React draws the neck from Neck; onFrame → layout → apply
  player/Player.tsx    mounts <Fretboard> above <TabStrip>
  styles.css           --fret-* tokens
```

This is 006's split again. Everything worth testing is in two pure modules,
and the component only draws.

### Rendering: SVG, with the notes updated outside React

The parent spec draws the 2D fretboard in SVG, and the mark count settles it.
The tab strip is canvas because a song has thousands of notes on it. The
fretboard shows at most one dot per string and a few dozen rings.

006 has a rule: React never re-renders at frame rate. The fretboard keeps it
by splitting the SVG in two.

- **The neck** is JSX. It depends only on the song and the panel's width, so
  React renders it on mount and again on resize, and never during playback.
- **The notes** are a `<g>` layer that React renders empty and then leaves
  alone. On every frame, `layout()` returns the marks for that instant, and
  `marks.ts` applies them to the layer. It keeps a map from each mark's key to
  its SVG node. It creates a node for a new key, sets attributes on an
  existing one, and removes the nodes whose keys are gone.

Keys are stable across frames: `dot:<note id>`, `ring:<string>:<fret>` and
`message`. So a note's dot is one node for its whole life, and a ring is one
node while it closes in.

Colours, stroke widths and fonts come from CSS classes on the nodes and from
custom properties in `styles.css`. Dark mode needs no code, and nothing reads
a palette as `TabStrip` must.

The SVG has `role="img"` and the label "Fretboard", as the tab strip's canvas
is labelled "Tab".

### The neck

```
        nut                                                  frets shrink →
   E  ○ ‖──────┼──────┼─────┼─────┼────┼────┼───┼───┼───┼──┼──┼──┤
   A    ‖──────┼──────┼─────┼─────┼────┼────┼───┼───┼───┼──┼──┼──┤
   D    ‖──────┼──────┼──(E)┼─────┼────┼────┼───┼───┼───┼──┼──┼──┤  ● sounding
   G    ‖──────┼──────┼─────┼──◯──┼────┼────┼───┼───┼───┼──┼──┼──┤  ◯ upcoming
   B    ‖──────┼──────┼─────┼─────┼────┼────┼───┼───┼───┼──┼──┼──┤
   e    ‖──────┼──────┼─────┼─────┼────┼────┼───┼───┼───┼──┼──┼──┤
                      •           •          •          •        ••
         1      2      3     4     5    6    7   8   9  10 11 12
```

**Orientation.** The nut is on the left and the lowest string is on top,
which is how a player looking down at their own neck sees it. Moving up the
neck moves right.

This is the reverse of the tab strip's string order, which puts the highest
string on top as printed tab does. Both views label their strings, with the
same labels.

**Labels.** The labels come from `instrument.tuning`, through
`stringLabels`. That is the tab strip's rule: the highest string is
lowercased when it shares a letter with the lowest, which gives `E A D G B e`
from top to bottom in standard tuning, and keeps drop D right. The labels
sit in a gutter left of the open-string column.

**Range.**
- The neck shows frets 0 to N, where N = max(12, the song's highest fret + 2).
- N is computed once per song, so the neck never rescales during playback.
- A song in open position gets twelve wide frets. A song up the neck still
  fits, with two frets to spare beyond its highest note.
- The mapper never assigns a fret above 20, so N is at most 22 for a document
  the pipeline made. The rule does not depend on that.

**Spacing.** Frets are spaced as on a real neck: each is 2^(−1/12) the width
of the one before, so a fret is half as wide as the one twelve below it.
Wire n, counting the nut as wire 0, sits at

```
x(n) = nutX + W · (1 − 2^(−n/12)) / (1 − 2^(−N/12))
```

for a fingerboard W pixels wide. The fretboard teaches distance under the
hand, so it draws distance as the hand finds it. Fitting the range to the
song keeps the shrinking frets readable. With N = 22, the narrowest fret is
under a third the width of the first.

**Note positions.**
- A note on fret n ≥ 1 is drawn midway between wires n − 1 and n.
- An open-string note, fret 0, is drawn in a narrow column just left of the
  nut.

**Furniture.**
- Strings are thicker from high to low, from about 1 px to 2.5 px. It makes
  "low E on top" plain at a glance.
- Inlay dots sit at frets 3, 5, 7, 9, 15, 17, 19 and 21, with a double dot at
  12. Only those within the range are drawn.
- A muted row of fret numbers runs under the neck, one per fret.

**Size.**
- The panel fills the main column's width.
- Its height depends only on the string count: a fixed gap between strings,
  about 30 px, plus room for the fret numbers. That is about 230 px for six
  strings.
- A dot's radius r is fixed, about 11 px: room for a two-character name such
  as `C#`. A dot is then about as wide as the 22nd fret at the main column's
  full width, so only on a neck that long do the top frets' dots fill them.
- A `ResizeObserver` recomputes the neck from the new width. The height does
  not change.

### The marks, frame by frame

`layout()` turns `(song, t, neck)` into the marks for that instant.

**Cursors.** The fretboard makes its own `NoteCursor` over `song.notes`, and
another over `song.chords`, when it mounts. It does not share the tab strip's,
in `Song`. A cursor's pointers follow one moving window. Two views asking for
different windows each frame would push it into a binary search on every
call. `song.ts` already says that another view makes its own.

**Sounding notes: dots.**
- A note is lit from its onset `t` to `t + max(dur, MIN_LIT)`, where
  `MIN_LIT` is 0.15 s. A 40 ms pick otherwise lights for two frames and
  cannot be seen.
- A string sounds one note at a time, so a later onset on the same string
  ends the earlier note. Among the lit notes on a string, only the latest
  onset is drawn, so there is at most one dot per string. This also absorbs
  transcribed durations that run past the next note.
- A dot is filled in the accent colour, with the note's name inside.

**Note names.** `noteName(midi)` gives the pitch class only, so `E2` and `E4`
both read `E`. The fret already says which octave.

Names are spelled with sharps: `C#`, never `D♭`. The document has no key, so
there is no right choice between a sharp and a flat. Sharps match the chord
symbols, which the structure stage also spells with sharps. A dot therefore
reads `A#` under an `A#` chord, never `B♭`.

**Upcoming notes: approach rings.**
- A note gets a ring while its onset is within `LOOKAHEAD`, 1.5 s, after
  now.
- The window is in song seconds, as the tab strip's scroll is. At 0.5× the
  rings close half as fast, in step with the slowed audio.
- A ring is drawn at the note's position, and its radius shrinks linearly:
  from 2r at the far edge of the window, to r at the onset. r is the dot's
  radius. At the onset the ring meets the dot that fills it.
- Rings are not labelled. The name appears when the note sounds.
- **One ring per position, the nearest.** A strummed chord repeated four
  times in 1.5 s would otherwise stack four rings on each of six positions.
  Only the soonest onset at each string and fret gets a ring.
- A position can hold a dot and a ring at once. That is the cue for a
  repeated note: it sounds now, and is about to sound again.

The parent spec asks for a look-ahead of about 2 s, and every view receives
it. The tab strip shows about 4 s ahead and is what the learner reads from.
The fretboard shows the present, so its look-ahead only has to give the hand
time to move. 1.5 s does that at moderate tempos without crowding the neck.
It is one constant, and the acceptance run checks it.

**Confidence.** The fretboard imports `confidence.ts` unchanged, as 006
promised.
- A dot's and a ring's opacity is `emphasis(note.confidence)`. Opacity means
  confidence and nothing else. How soon a note comes is the ring's size, so
  a faint ring is always a doubtful note, never a distant one.
- A note whose onset `isHidden` gets no dot and no ring, at any time. It is
  the same test the tab strip applies to the same `song.hidden`, so both views
  hide the same notes.
- While now is inside a hidden passage:
  - with a chord sounding at that instant, the neck shows its symbol, large
    and centred, at `emphasis(chord.confidence, CHORD_THRESHOLDS)`;
  - with none, it shows `UNCLEAR_LABEL`, "unclear passage", the tab strip's
    wording.

**The other cases.**
- **No notes.** The bare neck and `EMPTY_MESSAGE`, "No notes to show", as on
  the tab strip. The warnings banner says why.
- **Paused, and seeking.** The engine emits one frame after each seek or state
  change, so a paused fretboard shows that exact instant. A seek re-seats the
  cursors, so the dots and rings are right immediately after a jump.
- **The A/B loop.** The jump back to A is a seek, so the rings for the start
  of the loop appear as the loop restarts. No ring announces the jump before
  it happens. The tab strip shows the loop.

### Shared view text

`stringLabels`, `EMPTY_MESSAGE` and `UNCLEAR_LABEL` live in `tab/layout.ts`
today. The fretboard needs all three. The parent spec says views do not
communicate with each other, and a view importing another view's layout is
the start of that. So the three move to `web/src/labels.ts`, with `noteName`
beside them, and `tab/layout.ts` imports them from there. Their tests move
with them. The tab strip draws exactly what it drew.

### Testing

Everything below runs in `make check`. Pure modules run on `node`. The updater
and the component opt into jsdom per file, as 006's page tests do.

- **`labels.ts`:**
  - `stringLabels` keeps its existing cases: standard tuning, drop D, sharps
    and flats;
  - `noteName` spells with sharps, and gives the same name in every octave.
- **`neck.ts`:**
  - N = max(12, highest fret + 2), and N = 12 for a song with no notes;
  - wire positions rise, and follow the 2^(−n/12) rule: wire N sits at the
    fingerboard's end, and each fret is 2^(−1/12) the width of the one
    before;
  - a note's x is between its two wires, and fret 0's is left of the nut;
  - the lowest string is on top, in standard tuning and in drop D;
  - inlays fall only within the range, with a double dot at 12.
- **`layout.ts`:**
  - a dot is lit across `[t, t + dur]`, and for `MIN_LIT` when `dur` is
    shorter;
  - on one string, the latest onset wins;
  - a ring appears at `t − LOOKAHEAD` with radius 2r, is r at the onset, and
    is linear between;
  - one ring per position, the nearest, and a dot and a ring can share a
    position;
  - opacity is `emphasis(confidence)` for dots and rings;
  - a hidden note gets neither a dot nor a ring, even before its passage
    starts;
  - inside a hidden passage, the sounding chord's symbol shows, or "unclear
    passage" with no chord;
  - a document with no notes gives the message.
- **`marks.ts`** (jsdom):
  - a new key creates a node;
  - the same key in the next frame reuses the same node and updates its
    attributes;
  - a missing key removes its node.
- **`Fretboard`** (jsdom):
  - it draws N + 1 wires and one string per tuning entry;
  - it subscribes to `onFrame` and unsubscribes on unmount;
  - the `Player` test finds the fretboard above the tab strip.
- **Fixtures:** the existing `minimal.tabdoc.json` and
  `first-song.tabdoc.json`, which uses frets 0 to 8 and so draws twelve.

### Manual acceptance

Recorded in `acceptance.md` in this folder before the PR is opened, as in 006:

- **End to end,** in a browser against real services, with a real song:
  - at 1×, the dots light with the audio and with the tab strip;
  - at 0.5×, the same, with the rings closing half as fast;
  - in the song's densest passage, the rings stay readable;
  - 1.5 s of warning is enough to move the hand. If it is not, the value
    chosen and why go in the record;
  - a seek and an A/B loop leave the board right.
- **Dark mode,** and resizing the window during playback.
- **The two string orders.** Say whether reading the fretboard and the tab
  strip together, with their rows reversed, was confusing.

## Rejected alternatives

**Canvas, reusing the tab strip's painter.** The most reuse. `paint()`, the
palette and the pixel-ratio handling would move out of `TabStrip` and gain a
circle op. But canvas buys speed the fretboard does not need, and costs what
SVG gives for free: crisp scaling, styling through CSS, and a painter jsdom
can test. It stays the fallback if SVG updates stutter (see *Risks*). Because
the layout is pure, that swap touches only the painter.

**SVG re-rendered by React every frame.** The least code: `setState(t)` and
JSX. It re-renders the panel sixty times a second, which 006 rules out, and
that would not stay cheap once the 3D view shares the page.

**Fading ghosts,** the parent spec's literal wording: every note in the
look-ahead drawn faint, brightening as it nears. Brightness would then mean
both "soon" and "confident", and a faint ghost would be ambiguous. That is
the silent wrongness the parent spec warns against.

**Only the next onset.** The cleanest picture, but it shows one step ahead.
In a fast run the hand needs more warning than one note gives.

**The whole neck, always.** Frets 0 to 20 for every song shows where a
passage sits on the whole neck, but shrinks every dot. A song in open
position, the commonest case for a beginner, would use a third of the panel.

**Equal fret spacing.** Readable at every fret, but distances on screen would
not be distances under the hand, and that is what this view teaches.

**Following the hand.** A neck that pans or zooms to the current position
moves under the eye as the learner tries to read it.

**High e on top, as in the tab strip.** Each note would sit on the same row
in both views. The neck is drawn as the player sees their own instead, so
the picture matches the guitar in their hands. The labels carry the
difference.

**Fret numbers in the dots.** They would tie the dot to the number printed
in the tab strip. But the tab strip already prints that number, and the
fret-number row under the neck says which fret a dot is on. A note name adds
what neither view shows.

**Spelling note names by key.** `B♭` in a song in F would read better than
`A#`. But the document has no key, and guessing one would make the dots
disagree with the chord symbols, which are spelled with sharps.

## Consequences

- **Phase 5 is half done.** The 3D guitar is a third `onFrame` listener. Its
  spec adds the `[3D | 2D]` toggle, and can reuse `neck.ts`'s fret
  arithmetic.
- **The parent spec's look-ahead is refined.** "Look-ahead notes appear
  ghosted" becomes approach rings, and the fretboard looks 1.5 s ahead, not
  2 s. The tab strip still shows about 4 s.
- **One screen shows two string orders.** The tab strip puts the highest
  string on top and the fretboard puts the lowest. If that confuses
  learners, a later orientation setting is a change to `neck.ts` alone.
- **`labels.ts` holds the text views share.** A later view takes its labels
  from there, not from another view.
- **New colour tokens.** `styles.css` gains `--fret-*` properties, light and
  dark.
- No new dependencies, and no change outside `web/` and this folder.

## Risks

- **SVG updates per frame.** The layer changes a few dozen attributes a
  frame, well within what browsers handle. If a slow machine stutters during
  the acceptance run, the canvas painter is the fallback.
- **Crowded rings.** One ring per position bounds them by the positions in
  use. In a fast passage across many positions they can still crowd the neck.
  At the far edge of the window a ring's radius is 2r, about 22 px, and
  strings are about 30 px apart, so new rings on neighbouring strings at the
  same fret overlap until they close in. The acceptance run
  checks the densest passage of a real song. `LOOKAHEAD` and the starting
  radius are the levers.
- **Two string orders.** See *Consequences*. The acceptance record says
  whether it confused.
- **Sustain is the transcriber's.** A dot lasts as long as `dur`, and
  `basic-pitch`'s durations are rough. A long, wrong sustain keeps a dot lit
  until the next note on that string. The tab strip draws the same duration as
  a tail, so the views agree, even when both are wrong.
