/**
 * What the chord lane draws, decided apart from the drawing: which cells
 * there are, how strongly each is shown, and which of them the playhead has
 * passed. The lane itself, and the chord list beside it, only paint these.
 */
import { CHORD_THRESHOLDS, emphasis } from "../confidence";
import type { Position } from "../playback/cursor";
import type { Chord } from "../types/tabDocument";

/** One cell of the lane. */
export interface LaneCell {
  symbol: string;
  /** How strongly to draw it. Faded, never hidden: a doubtful chord is still a chord. */
  opacity: number;
}

/**
 * One cell per chord, in order, each at the opacity the chord thresholds give
 * its confidence. The same rule draws the guitar's overlay, so the two never
 * disagree about a chord.
 */
export function laneCells(chords: readonly Chord[]): LaneCell[] {
  return chords.map((chord) => ({
    symbol: chord.symbol,
    opacity: emphasis(chord.confidence, CHORD_THRESHOLDS),
  }));
}

/** Where a cell stands against the playhead. */
export type CellState = "played" | "current" | "coming";

/**
 * `current` is the cell at `at.current`; any other cell before `at.next` is
 * played. So a short chord that began inside a long one is played while the
 * long one is still current, and between chords no cell is current.
 */
export function cellState(index: number, at: Position): CellState {
  if (index === at.current) return "current";
  return index < at.next ? "played" : "coming";
}

/**
 * Each symbol once, in the order first heard: the chord list the sidebar
 * shows, where a song that returns to Am ten times lists it once.
 */
export function distinctSymbols(chords: readonly Chord[]): string[] {
  return [...new Set(chords.map((chord) => chord.symbol))];
}
