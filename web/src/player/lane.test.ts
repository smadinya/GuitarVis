import { describe, expect, it } from "vitest";

import { CHORD_FULL, CHORD_HIDE, FADED } from "../confidence";
import type { Position } from "../playback/cursor";
import { cellState, distinctSymbols, laneCells } from "./lane";

const chord = (t: number, symbol: string, confidence = 0.9) => ({ t, dur: 2, symbol, confidence });

describe("laneCells", () => {
  it("is empty for no chords", () => expect(laneCells([])).toEqual([]));

  it("fades by the chord thresholds, never below FADED", () => {
    const mid = (CHORD_HIDE + CHORD_FULL) / 2;
    const cells = laneCells([chord(0, "Am", CHORD_FULL), chord(2, "C", mid), chord(4, "G", CHORD_HIDE), chord(6, "D", 0)]);
    expect(cells.map((c) => c.symbol)).toEqual(["Am", "C", "G", "D"]);
    expect(cells[0].opacity).toBe(1);
    expect(cells[1].opacity).toBeCloseTo((1 + FADED) / 2);
    expect(cells[2].opacity).toBe(FADED);
    expect(cells[3].opacity).toBe(FADED);
  });
});

describe("cellState", () => {
  const states = (count: number, at: Position) => Array.from({ length: count }, (_, i) => cellState(i, at));

  it("marks the cells before the current one played, and the rest coming", () => {
    expect(states(5, { current: 2, next: 3 })).toEqual(["played", "played", "current", "coming", "coming"]);
  });

  it("between chords, has no current cell", () => {
    expect(states(4, { current: -1, next: 2 })).toEqual(["played", "played", "coming", "coming"]);
  });

  it("plays a short chord out under a long one that is still current", () => {
    expect(states(3, { current: 0, next: 2 })).toEqual(["current", "played", "coming"]);
  });
});

describe("distinctSymbols", () => {
  it("lists each symbol once, first heard first", () => {
    expect(distinctSymbols([chord(0, "Am"), chord(2, "C"), chord(4, "Am"), chord(6, "G"), chord(8, "C")])).toEqual(["Am", "C", "G"]);
    expect(distinctSymbols([])).toEqual([]);
  });
});
