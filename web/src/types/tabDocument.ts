/* GENERATED FILE — do not edit.
 * Source: schema/tab-document.schema.json (from packages/core tabdoc.py).
 * Regenerate with `make schema`.
 */

export type Technique = "bend" | "slide" | "hammer" | "pull" | "mute" | "harmonic";

export interface TabDocument {
  chords?: Chord[];
  instrument: Instrument;
  notes?: Note[];
  schema_version?: number;
  sections?: Section[];
  source: Source;
  timing: Timing;
}
export interface Chord {
  confidence: number;
  dur: number;
  symbol: string;
  t: number;
}
export interface Instrument {
  capo?: number;
  string_count?: number;
  /**
   * Scientific pitch names, low string first.
   */
  tuning?: string[];
}
export interface Note {
  confidence: number;
  dur: number;
  fret: number;
  id: string;
  midi: number;
  /**
   * 0 is the lowest string.
   */
  string: number;
  /**
   * Onset in seconds. Authoritative.
   */
  t: number;
  technique?: Technique | null;
}
export interface Section {
  dur: number;
  label: string;
  t: number;
}
export interface Source {
  audio_url: string;
  duration_sec: number;
  title: string;
}
export interface Timing {
  beats?: Beat[];
  tempo_bpm_avg?: number | null;
  time_signature?: string | null;
}
export interface Beat {
  bar: number;
  beat: number;
  t: number;
}
