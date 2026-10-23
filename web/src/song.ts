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

/** What a document with no tuning means, and what the header calls "Standard
 * tuning" when a document's own matches it. */
export const STANDARD_TUNING: readonly string[] = ["E2", "A2", "D3", "G3", "B3", "E4"];

/** A hidden passage, and whether a chord sounds over any of it. One with no
 * chord is labelled as unclear; over one with a chord, the chord is all
 * there is to read. */
export interface HiddenPassage extends Passage {
  chorded: boolean;
}

export interface Song {
  title: string;
  /** source.duration_sec: the length until the audio reports its own. */
  duration: number;
  /** Scientific pitch names, lowest string first. */
  tuning: readonly string[];
  /** timing.tempo_bpm_avg, in beats per minute; null when the document has no
   * tempo, or one that is not a positive number. */
  tempo: number | null;
  /** Sorted by onset, as are chords, sections and beats. */
  notes: readonly Note[];
  chords: readonly Chord[];
  sections: readonly Section[];
  beats: readonly Beat[];
  warnings: readonly string[];
  /** Sorted, and never overlapping. */
  hidden: readonly HiddenPassage[];
  /** The tab strip's cursors. Another view makes its own. */
  cursor: NoteCursor<Note>;
  chordCursor: NoteCursor<Chord>;
  sectionCursor: NoteCursor<Section>;
}

/** Whether this client understands the document. A missing version is 1,
 * as the schema's default says. */
export function canRead(doc: TabDocument): boolean {
  return (doc.schema_version ?? SCHEMA_VERSION) === SCHEMA_VERSION;
}

export function buildSong(doc: TabDocument): Song {
  const tempo = doc.timing.tempo_bpm_avg;
  const notes = byOnset(doc.notes ?? []);
  const chords = byOnset(doc.chords ?? []);
  const sections = byOnset(doc.sections ?? []);
  return {
    title: doc.source.title,
    duration: doc.source.duration_sec,
    tuning: doc.instrument.tuning ?? STANDARD_TUNING,
    tempo: typeof tempo === "number" && Number.isFinite(tempo) && tempo > 0 ? tempo : null,
    notes,
    chords,
    sections,
    beats: byOnset(doc.timing.beats ?? []),
    warnings: doc.warnings ?? [],
    hidden: hiddenPassages(notes).map((passage) => ({
      ...passage,
      chorded: chords.some((c) => c.t < passage.to && c.t + c.dur > passage.from),
    })),
    cursor: new NoteCursor(notes),
    chordCursor: new NoteCursor(chords),
    sectionCursor: new NoteCursor(sections),
  };
}

function byOnset<T extends { t: number }>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => a.t - b.t);
}
