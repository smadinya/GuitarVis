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
/** Right of fret N's wire, so the last wire is not on the panel's edge. */
export const END_PAD = 12;
/** Inlay dots, by fret. Fret 12 has two. */
export const INLAY_FRETS = [3, 5, 7, 9, 12, 15, 17, 19, 21];

const GUTTER = 22; // the string labels' column
const OPEN_W = 2 * DOT_R + 8; // open-string notes, between the labels and the nut
const EDGE = 26; // above the top string: half a string gap of fingerboard, and a margin
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
