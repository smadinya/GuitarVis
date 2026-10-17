/**
 * What sounds on the guitar at one instant: the note on each string that is
 * lit, and a message when there is nothing else to read. Pure and pixel-free:
 * the same song and time always give the same answer, so everything worth
 * testing about *what* sounds is tested here, and the guitar only draws it.
 *
 * The guitar shows only the present. What is coming is the tab strip's to
 * show, and opacity means confidence and nothing else.
 */
import { CHORD_THRESHOLDS, emphasis, isHidden } from "../confidence";
import { EMPTY_MESSAGE, UNCLEAR_LABEL, noteName } from "../labels";
import { NoteCursor, inWindow } from "../playback/cursor";
import type { Song } from "../song";
import type { Chord, Note } from "../types/tabDocument";

/** The shortest time a note stays lit, in seconds: a 40 ms pick would
 * otherwise light for two frames. */
export const MIN_LIT = 0.15;

/** A note that sounds now. `key` is stable across frames, so whatever draws it
 * updates it in place rather than replacing it. */
export interface SoundingNote {
  key: string;
  string: number;
  fret: number;
  midi: number;
  name: string;
  opacity: number;
  /** Song seconds when it starts. */
  onset: number;
  /** Song seconds when it goes dark: see litUntil. */
  until: number;
  /** How loud it is, 0 to 1, or null when the document has no measure. */
  loudness: number | null;
}

/** Text for the middle of the guitar, where there is nothing to read from the
 * notes. */
export interface Message {
  text: string;
  chord: boolean;
  opacity: number;
}

export interface Sounding {
  /** At most one per string. */
  notes: SoundingNote[];
  message: Message | null;
}

/**
 * The guitar's own reading of a song, made once when it mounts. A cursor
 * follows one moving window, so the guitar keeps its own rather than share
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

export function sounding(song: Song, cursors: Cursors, now: number): Sounding {
  if (song.notes.length === 0) return { notes: [], message: message(EMPTY_MESSAGE, false, 1) };

  // Every note that could be lit now. A note lit by MIN_LIT started at most
  // MIN_LIT ago; a longer one is still within its duration.
  const notes = cursors.notes.window(now - MIN_LIT, now);
  // A long note may have started in a passage that is already over, and stays
  // hidden: read the passages back to the earliest onset in play.
  const since = Math.min(now, notes[0]?.t ?? now);
  const hidden = inWindow(song.hidden, since, now, (p) => p.from, (p) => p.to);

  const lit = new Map<number, SoundingNote>(); // by string: the latest onset wins
  for (const note of notes) {
    if (note.string < 0 || note.string >= song.tuning.length || note.fret < 0) continue;
    if (isHidden(hidden, note.t)) continue;

    const until = cursors.until.get(note) ?? note.t + Math.max(note.dur, MIN_LIT);
    if (note.t <= now && now <= until) {
      lit.set(note.string, {
        key: `dot:${note.id}`,
        string: note.string,
        fret: note.fret,
        midi: note.midi,
        name: noteName(note.midi),
        opacity: emphasis(note.confidence),
        onset: note.t,
        until,
        loudness: note.loudness ?? null,
      });
    }
  }

  let overlay: Message | null = null;
  if (isHidden(hidden, now)) {
    // Inside a hidden passage, the chord is all there is to read.
    const chord = cursors.chords.window(now, now).at(-1);
    overlay =
      chord === undefined
        ? message(UNCLEAR_LABEL, false, 1)
        : message(chord.symbol, true, emphasis(chord.confidence, CHORD_THRESHOLDS));
  }
  return { notes: [...lit.values()], message: overlay };
}

function message(text: string, chord: boolean, opacity: number): Message {
  return { text, chord, opacity };
}
