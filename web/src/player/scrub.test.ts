import { describe, expect, it } from "vitest";

import { fraction, scrubMarks, timeAt } from "./scrub";

const section = (t: number, label = "s") => ({ t, dur: 10, label });
const NO_LOOP = { a: null, b: null };

describe("scrubMarks", () => {
  it("ticks each section start after the first", () => {
    expect(scrubMarks(40, [section(0), section(10), section(20)], NO_LOOP).ticks).toEqual([0.25, 0.5]);
  });

  it("drops a section that starts at or past the end", () => {
    expect(scrubMarks(40, [section(0), section(10), section(40), section(45)], NO_LOOP).ticks).toEqual([0.25]);
  });

  it("draws only A's edge while B is unset", () => {
    expect(scrubMarks(40, [], { a: 10, b: null })).toEqual({ ticks: [], band: null, edges: [{ point: "a", at: 0.25 }] });
  });

  it("draws the band between A and B, with both edges", () => {
    const marks = scrubMarks(40, [], { a: 10, b: 30 });
    expect(marks.band).toEqual({ from: 0.25, to: 0.75 });
    expect(marks.edges).toEqual([{ point: "a", at: 0.25 }, { point: "b", at: 0.75 }]);
  });

  it("draws a loop whose B is before its A from B to A", () => {
    expect(scrubMarks(40, [], { a: 30, b: 10 }).band).toEqual({ from: 0.25, to: 0.75 });
  });

  it("clamps a loop past the media's reported duration to the end", () => {
    const marks = scrubMarks(40, [], { a: 30, b: 50 });
    expect(marks.band).toEqual({ from: 0.75, to: 1 });
    expect(marks.edges[1]).toEqual({ point: "b", at: 1 });
  });

  it("marks nothing when the duration is zero", () => {
    expect(scrubMarks(0, [section(0), section(10)], { a: 1, b: 2 })).toEqual({ ticks: [], band: null, edges: [] });
  });
});

describe("fraction and timeAt", () => {
  it("clamp, and never divide by zero", () => {
    expect(fraction(5, 20)).toBe(0.25);
    expect(fraction(30, 20)).toBe(1);
    expect(fraction(-1, 20)).toBe(0);
    expect(fraction(5, 0)).toBe(0);
    expect(fraction(5, Number.NaN)).toBe(0);
    expect(timeAt(200, 100, 400, 20)).toBe(5);
    expect(timeAt(50, 100, 400, 20)).toBe(0);
    expect(timeAt(600, 100, 400, 20)).toBe(20);
    expect(timeAt(200, 100, 0, 20)).toBe(0);
  });
});
