/**
 * The tab strip as a list of things to draw. Pure: the same song, time,
 * viewport and loop always give the same list, so everything worth testing
 * about the strip is tested here, and TabStrip only paints.
 *
 * Position is linear in song seconds (ADR 0002): a bad beat grid moves the
 * bar lines and nothing else.
 */
import { emphasis, type Passage } from "../confidence";
import type { LoopPoints } from "../playback/engine";
import type { Song } from "../song";

/** Song seconds to pixels. At 0.5× the strip scrolls half as fast. */
export const PX_PER_SEC = 150;
/** The playhead's place, as a fraction of the width. Right of it is look-ahead. */
export const PLAYHEAD_AT = 0.2;
export const EMPTY_MESSAGE = "No notes to show";
export const UNCLEAR_LABEL = "unclear passage";

const PAD = 8;
const ROW = 20;
const STRING_GAP = 18;
const GUTTER = 22; // the string labels' column, drawn over the scrolling notes
const PAST_ALPHA = 0.45;

/** Colours by role. TabStrip maps each to a --tab-* custom property. */
export type Paint =
  | "background"
  | "text"
  | "muted"
  | "accent"
  | "string"
  | "bar"
  | "playhead"
  | "loop"
  | "hidden";

export type Font = "fret" | "fretBold" | "chord" | "chordLarge" | "label" | "message";
export type Align = "left" | "center";

export type DrawOp =
  | { kind: "rect"; x: number; y: number; w: number; h: number; paint: Paint; alpha: number }
  | {
      kind: "line";
      x1: number;
      y1: number;
      x2: number;
      y2: number;
      paint: Paint;
      width: number;
      alpha: number;
    }
  | {
      kind: "text";
      x: number;
      y: number;
      text: string;
      paint: Paint;
      font: Font;
      align: Align;
      alpha: number;
    };

/** CSS pixels. */
export interface Viewport {
  width: number;
  height: number;
}

export interface Rows {
  /** null when there are no sections: the row collapses. */
  sectionY: number | null;
  /** null when there are no chords. */
  chordY: number | null;
  /** By string, 0 the lowest. The highest string is drawn on top. */
  stringY: number[];
  top: number;
  bottom: number;
  /** The strip's height in CSS pixels. */
  height: number;
}

export function rowsOf(song: Song): Rows {
  let y = PAD;
  let sectionY: number | null = null;
  let chordY: number | null = null;
  if (song.sections.length > 0) {
    sectionY = y + ROW / 2;
    y += ROW;
  }
  if (song.chords.length > 0) {
    chordY = y + ROW / 2;
    y += ROW;
  }
  const count = song.tuning.length;
  const top = y + STRING_GAP / 2;
  const stringY = Array.from({ length: count }, (_, s) => top + (count - 1 - s) * STRING_GAP);
  const bottom = top + (count - 1) * STRING_GAP;
  return { sectionY, chordY, stringY, top, bottom, height: bottom + STRING_GAP / 2 + PAD };
}

/**
 * Letter names by string, lowest first. The top string is lowercased when it
 * shares a letter with the bottom one: e … E in standard tuning, while drop D
 * keeps its capital E.
 */
export function stringLabels(tuning: readonly string[]): string[] {
  const labels = tuning.map((name) => /^[A-Ga-g][#b]?/.exec(name)?.[0] ?? name);
  const top = labels.length - 1;
  if (top > 0 && labels[top].toLowerCase() === labels[0].toLowerCase()) {
    labels[top] = labels[top].toLowerCase();
  }
  return labels;
}

export function layout(song: Song, now: number, viewport: Viewport, loop: LoopPoints): DrawOp[] {
  const rows = rowsOf(song);
  const { width, height } = viewport;
  const playheadX = width * PLAYHEAD_AT;
  const x = (t: number) => playheadX + (t - now) * PX_PER_SEC;
  const from = now - playheadX / PX_PER_SEC;
  const to = now + (width - playheadX) / PX_PER_SEC;
  const onScreen = (start: number, end: number) => start <= to && end >= from;
  const hidden = song.hidden.filter((p) => onScreen(p.from, p.to));
  const isHidden = (t: number) => hidden.some((p) => p.from <= t && t <= p.to);
  const bandTop = rows.top - STRING_GAP / 2;
  const bandHeight = rows.bottom - rows.top + STRING_GAP;
  const ops: DrawOp[] = [];

  // The loop, under everything else.
  const { a, b } = loop;
  if (a !== null && b !== null) {
    const [lo, hi] = [Math.min(a, b), Math.max(a, b)];
    ops.push(rect(x(lo), 0, (hi - lo) * PX_PER_SEC, height, "loop", 0.15));
  }
  for (const [name, at] of [["A", a], ["B", b]] as const) {
    if (at === null) continue;
    ops.push(line(x(at), 0, x(at), height, "loop", 2));
    ops.push(text(x(at) + 4, PAD, name, "loop", "label"));
  }

  for (const y of rows.stringY) ops.push(line(0, y, width, y, "string"));

  for (const beat of song.beats) {
    if (beat.beat !== 1 || !onScreen(beat.t, beat.t)) continue;
    ops.push(line(x(beat.t), rows.top - 4, x(beat.t), rows.bottom + 4, "bar"));
  }

  for (const passage of hidden) {
    ops.push(rect(x(passage.from), bandTop, x(passage.to) - x(passage.from), bandHeight, "hidden", 0.85));
    const chordOver = song.chords.some((c) => overlaps(c.t, c.t + c.dur, passage));
    if (!chordOver) {
      const middle = (x(passage.from) + x(passage.to)) / 2;
      ops.push(text(middle, (rows.top + rows.bottom) / 2, UNCLEAR_LABEL, "muted", "label", "center"));
    }
  }

  for (const note of song.cursor.window(from, to)) {
    const y = rows.stringY[note.string];
    if (y === undefined || isHidden(note.t)) continue;
    const end = note.t + note.dur;
    const sounding = note.t <= now && now <= end;
    const alpha = (end < now ? PAST_ALPHA : 1) * emphasis(note.confidence);
    const fret = String(note.fret);
    const knockout = fret.length * 7 + 4; // so the string does not strike through it
    ops.push(line(x(note.t), y, x(end), y, sounding ? "accent" : "muted", 3, 0.3 * alpha));
    ops.push(rect(x(note.t) - knockout / 2, y - 7, knockout, 14, "background"));
    ops.push(
      text(x(note.t), y, fret, sounding ? "accent" : "text", sounding ? "fretBold" : "fret", "center", alpha),
    );
  }

  if (rows.chordY !== null) {
    for (const chord of song.chords) {
      if (!onScreen(chord.t, chord.t + chord.dur)) continue;
      // Over a hidden passage the chord is all there is to read, so it is
      // larger; its own confidence still sets its strength.
      const large = hidden.some((p) => overlaps(chord.t, chord.t + chord.dur, p));
      const left = Math.max(x(chord.t), GUTTER) + 2;
      const font = large ? "chordLarge" : "chord";
      ops.push(text(left, rows.chordY, chord.symbol, "text", font, "left", emphasis(chord.confidence)));
    }
  }

  if (rows.sectionY !== null) {
    for (const section of song.sections) {
      if (!onScreen(section.t, section.t + section.dur)) continue;
      const left = Math.max(x(section.t), GUTTER) + 2;
      ops.push(text(left, rows.sectionY, section.label, "muted", "label"));
    }
  }

  if (song.notes.length === 0) {
    ops.push(text(width / 2, (rows.top + rows.bottom) / 2, EMPTY_MESSAGE, "muted", "message", "center"));
  }

  ops.push(rect(0, bandTop, GUTTER, bandHeight, "background"));
  stringLabels(song.tuning).forEach((label, s) => {
    ops.push(text(GUTTER / 2, rows.stringY[s], label, "muted", "label", "center"));
  });

  ops.push(line(playheadX, 0, playheadX, height, "playhead", 2));
  return ops;
}

function overlaps(start: number, end: number, passage: Passage): boolean {
  return start < passage.to && end > passage.from;
}

function rect(x: number, y: number, w: number, h: number, paint: Paint, alpha = 1): DrawOp {
  return { kind: "rect", x, y, w, h, paint, alpha };
}

function line(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  paint: Paint,
  width = 1,
  alpha = 1,
): DrawOp {
  return { kind: "line", x1, y1, x2, y2, paint, width, alpha };
}

function text(
  x: number,
  y: number,
  value: string,
  paint: Paint,
  font: Font,
  align: Align = "left",
  alpha = 1,
): DrawOp {
  return { kind: "text", x, y, text: value, paint, font, align, alpha };
}
