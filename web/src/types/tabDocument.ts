/* GENERATED FILE — do not edit.
 * Source: schema/tab-document.schema.json (from packages/core tabdoc.py).
 * Regenerate with `make schema`.
 */

export type Confidence = number;
export type Dur = number;
export type Symbol = string;
export type T = number;
export type Chords = Chord[];
export type Capo = number;
export type StringCount = number;
/**
 * Scientific pitch names, low string first.
 */
export type Tuning = string[];
export type Confidence1 = number;
export type Dur1 = number;
export type Fret = number;
export type Id = string;
export type Midi = number;
/**
 * 0 is the lowest string.
 */
export type String = number;
/**
 * Onset in seconds. Authoritative.
 */
export type T1 = number;
export type Technique = "bend" | "slide" | "hammer" | "pull" | "mute" | "harmonic";
export type Notes = Note[];
export type SchemaVersion = number;
export type Dur2 = number;
export type Label = string;
export type T2 = number;
export type Sections = Section[];
export type AudioUrl = string;
export type DurationSec = number;
export type Title = string;
export type Bar = number;
export type Beat1 = number;
export type T3 = number;
export type Beats = Beat[];
export type TempoBpmAvg = number | null;
export type TimeSignature = string | null;

export interface TabDocument {
  chords?: Chords;
  instrument: Instrument;
  notes?: Notes;
  schema_version?: SchemaVersion;
  sections?: Sections;
  source: Source;
  timing: Timing;
}
export interface Chord {
  confidence: Confidence;
  dur: Dur;
  symbol: Symbol;
  t: T;
}
export interface Instrument {
  capo?: Capo;
  string_count?: StringCount;
  tuning?: Tuning;
}
export interface Note {
  confidence: Confidence1;
  dur: Dur1;
  fret: Fret;
  id: Id;
  midi: Midi;
  string: String;
  t: T1;
  technique?: Technique | null;
}
export interface Section {
  dur: Dur2;
  label: Label;
  t: T2;
}
export interface Source {
  audio_url: AudioUrl;
  duration_sec: DurationSec;
  title: Title;
}
export interface Timing {
  beats?: Beats;
  tempo_bpm_avg?: TempoBpmAvg;
  time_signature?: TimeSignature;
}
export interface Beat {
  bar: Bar;
  beat: Beat1;
  t: T3;
}
