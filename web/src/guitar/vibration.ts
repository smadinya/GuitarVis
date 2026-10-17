/**
 * How a sounding string moves: its displacement at one point along the string
 * and one instant of song time. Pure, like sounding.ts, so the same note and
 * time always give the same motion.
 *
 * The motion is drawn slowed down, because a real string moves too fast to
 * see. Time is song time, so pausing freezes the string and 0.5x slows it.
 */
import type { SoundingNote } from "./sounding";

/** How long a pluck takes to die away, in seconds. */
export const DECAY_SEC = 0.7;
/** The last part of a note, in seconds, over which the string comes to rest. */
export const FADE_SEC = 0.08;
/** The low E's wobble, in Hz. */
export const BASE_HZ = 7;
/** The swing of the quietest note, in mm. */
export const QUIET_MM = 0.6;
/** The swing of the loudest note, in mm. */
export const LOUD_MM = 3.2;
/** The swing of a note with no loudness, in mm. */
export const UNKNOWN_MM = 2.0;
/** The opacity of a vibrating string's blur, relative to its emphasis. */
export const BLUR_OPACITY = 0.3;
/** Below this swing, in mm, a string is drawn still. */
export const STILL_MM = 0.05;

/** What a sounding string's motion needs from its note. */
export type Plucked = Pick<SoundingNote, "onset" | "until" | "midi" | "loudness">;

function clamp(x: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, x));
}

/** The swing of a note in mm: QUIET_MM at loudness 0, LOUD_MM at 1. */
export function amplitude(loudness: number | null): number {
  if (loudness === null) return UNKNOWN_MM;
  return QUIET_MM + (LOUD_MM - QUIET_MM) * clamp(loudness, 0, 1);
}

/** The wobble of a note in Hz: BASE_HZ at MIDI 40, doubling every two octaves. */
export function frequency(midi: number): number {
  return BASE_HZ * 2 ** ((midi - 40) / 24);
}

/** The shape along the string at u, from 0 at the nut to 1 at the fingerboard's end. */
export function profile(u: number): number {
  return Math.sin(Math.PI * u);
}

/** How far a note's swing is, in mm, at song time t: zero outside the note. */
export function envelope(note: Plucked, t: number): number {
  if (t < note.onset || t >= note.until) return 0;
  const fade = clamp((note.until - t) / FADE_SEC, 0, 1);
  return amplitude(note.loudness) * Math.exp(-(t - note.onset) / DECAY_SEC) * fade;
}

/**
 * The waveform's value at song time t, sin(2πf(t − onset)), from -1 to 1. It
 * starts at 0, at rest on the pluck.
 */
export function swing(note: Plucked, t: number): number {
  return Math.sin(2 * Math.PI * frequency(note.midi) * (t - note.onset));
}

/** The string's displacement in mm at point u and song time t. */
export function displacement(note: Plucked, t: number, u: number): number {
  return envelope(note, t) * profile(u) * swing(note, t);
}
