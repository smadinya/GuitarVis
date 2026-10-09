/**
 * A tab document, read once into what the views draw from.
 *
 * The page builds a Song when the document arrives and every view reads the
 * Song, never the raw document. The optional tracks are filled with empty
 * lists here, so the views handle "missing" and "empty" as one case.
 */
import { hiddenPassages, type Passage } from "./confidence";
import { NoteCursor } from "./playback/cursor";
import type { Beat, Chord, Note, Section, TabDocument } from "./types/tabDocument";

/** The only document version this client draws. */
export const SCHEMA_VERSION = 1;

const STANDARD_TUNING = ["E2", "A2", "D3", "G3", "B3", "E4"];

export interface Song {
  title: string;
  /** source.duration_sec: the length until the audio reports its own. */
  duration: number;
  /** Scientific pitch names, lowest string first. */
  tuning: readonly string[];
  /** Sorted by onset, as are chords, sections and beats. */
  notes: readonly Note[];
  chords: readonly Chord[];
  sections: readonly Section[];
  beats: readonly Beat[];
  warnings: readonly string[];
  hidden: readonly Passage[];
  /** The tab strip's cursor. Another view makes its own. */
  cursor: NoteCursor<Note>;
}

/** Whether this client understands the document. A missing version is 1,
 * as the schema's default says. */
export function canRead(doc: TabDocument): boolean {
  return (doc.schema_version ?? SCHEMA_VERSION) === SCHEMA_VERSION;
}

export function buildSong(doc: TabDocument): Song {
  const notes = byOnset(doc.notes ?? []);
  return {
    title: doc.source.title,
    duration: doc.source.duration_sec,
    tuning: doc.instrument.tuning ?? STANDARD_TUNING,
    notes,
    chords: byOnset(doc.chords ?? []),
    sections: byOnset(doc.sections ?? []),
    beats: byOnset(doc.timing.beats ?? []),
    warnings: doc.warnings ?? [],
    hidden: hiddenPassages(notes),
    cursor: new NoteCursor(notes),
  };
}

function byOnset<T extends { t: number }>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => a.t - b.t);
}
