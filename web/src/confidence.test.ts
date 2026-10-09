import { describe, expect, it } from "vitest";

import {
  FADED,
  FULL,
  HIDE,
  emphasis,
  hiddenPassages,
  type Thresholds,
} from "./confidence";
import type { Note } from "./types/tabDocument";

const T: Thresholds = { hide: 0.4, full: 0.7 };
const WEAK = 0.2;
const STRONG = 0.9;

let ids = 0;
function note(t: number, confidence: number, dur = 0.25, string = 0): Note {
  ids += 1;
  return { id: `n${ids}`, t, dur, midi: 40 + string * 5, string, fret: 0, confidence };
}

describe("emphasis", () => {
  it("is FADED at and below hide, and 1 at and above full", () => {
    expect(emphasis(0, T)).toBe(FADED);
    expect(emphasis(0.4, T)).toBe(FADED);
    expect(emphasis(0.7, T)).toBe(1);
    expect(emphasis(1, T)).toBe(1);
  });

  it("is linear in between", () => {
    expect(emphasis(0.55, T)).toBeCloseTo((FADED + 1) / 2);
  });

  it("never decreases as confidence rises", () => {
    let previous = 0;
    for (let c = 0; c <= 1.0001; c += 0.01) {
      const value = emphasis(c, T);
      expect(value).toBeGreaterThanOrEqual(previous);
      previous = value;
    }
  });

  it("is a step when the thresholds are equal", () => {
    const step = { hide: 0.5, full: 0.5 };
    expect(emphasis(0.49, step)).toBe(FADED);
    expect(emphasis(0.5, step)).toBe(1);
  });

  it("ships thresholds in order, within [0, 1]", () => {
    expect(0 <= HIDE && HIDE <= FULL && FULL <= 1).toBe(true);
  });
});

describe("hiddenPassages", () => {
  it("hides a run of three weak notes, to the latest end", () => {
    const notes = [note(1, WEAK, 2), note(1.5, WEAK, 0.2), note(2, WEAK, 0.2)];

    expect(hiddenPassages(notes, 0.4)).toEqual([{ from: 1, to: 3 }]);
  });

  it("leaves a run of two, and a lone weak note, alone", () => {
    expect(hiddenPassages([note(1, WEAK), note(1.5, WEAK)], 0.4)).toEqual([]);
    expect(
      hiddenPassages([note(1, STRONG), note(1.5, WEAK), note(2, STRONG)], 0.4),
    ).toEqual([]);
  });

  it("breaks a run at a gap over one second", () => {
    const notes = [note(1, WEAK), note(1.5, WEAK), note(2.6, WEAK), note(3, WEAK)];

    expect(hiddenPassages(notes, 0.4)).toEqual([]);
  });

  it("counts weak notes in onset order across strings, whatever the input order", () => {
    const notes = [note(2, WEAK, 0.25, 5), note(1, WEAK, 0.25, 0), note(1.5, WEAK, 0.25, 3)];

    expect(hiddenPassages(notes, 0.4)).toEqual([{ from: 1, to: 2.25 }]);
  });

  it("keeps adjacent runs apart, so the strong note between them shows", () => {
    const notes = [
      note(1, WEAK), note(1.2, WEAK), note(1.4, WEAK),
      note(1.8, STRONG),
      note(2, WEAK), note(2.2, WEAK), note(2.4, WEAK),
    ];

    expect(hiddenPassages(notes, 0.4)).toEqual([
      { from: 1, to: 1.65 },
      { from: 2, to: 2.65 },
    ]);
  });

  it("merges runs whose spans overlap", () => {
    const notes = [
      note(1, WEAK, 3), note(1.2, WEAK), note(1.4, WEAK),
      note(1.8, STRONG),
      note(2, WEAK), note(2.2, WEAK), note(2.4, WEAK),
    ];

    expect(hiddenPassages(notes, 0.4)).toEqual([{ from: 1, to: 4 }]);
  });

  it("treats a note exactly at hide as strong", () => {
    expect(hiddenPassages([note(1, 0.4), note(1.2, 0.4), note(1.4, 0.4)], 0.4)).toEqual(
      [],
    );
  });
});
