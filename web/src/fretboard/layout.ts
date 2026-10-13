/**
 * The fretboard at one instant, as marks to draw: a dot on each string that
 * sounds, and a message when there is nothing else to read. Pure: the same
 * song, time and neck always give the same marks, so everything worth testing
 * about the fretboard is tested here, and Fretboard only draws.
 *
 * The neck shows only the present. What is coming is the tab strip's to show,
 * and opacity means confidence and nothing else.
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

/** Each mark has a key that is stable across frames, so its SVG node is
 * updated in place rather than replaced. */
export type Mark =
  | { kind: "dot"; key: string; x: number; y: number; r: number; name: string; opacity: number }
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

  // Every note that could be lit now. A note lit by MIN_LIT started at most
  // MIN_LIT ago; a longer one is still within its duration.
  const notes = cursors.notes.window(now - MIN_LIT, now);
  // A long note may have started in a passage that is already over, and stays
  // hidden: read the passages back to the earliest onset in play.
  const since = Math.min(now, notes[0]?.t ?? now);
  const hidden = inWindow(song.hidden, since, now, (p) => p.from, (p) => p.to);

  const dots = new Map<number, Mark>(); // by string: the latest onset wins
  for (const note of notes) {
    const y = neck.strings[note.string]?.y;
    const x = neck.noteX[note.fret];
    if (y === undefined || x === undefined || isHidden(hidden, note.t)) continue;

    const until = cursors.until.get(note) ?? note.t + Math.max(note.dur, MIN_LIT);
    if (note.t <= now && now <= until) {
      const name = noteName(note.midi);
      const opacity = emphasis(note.confidence);
      dots.set(note.string, { kind: "dot", key: `dot:${note.id}`, x, y, r: DOT_R, name, opacity });
    }
  }

  const marks = [...dots.values()];
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
