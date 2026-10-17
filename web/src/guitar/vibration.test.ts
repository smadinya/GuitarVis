import { describe, expect, it } from "vitest";

import { amplitude, displacement, envelope, frequency, swing, type Plucked } from "./vibration";

const plucked = (fields: Partial<Plucked> = {}): Plucked => ({ onset: 1, until: 3, midi: 40, loudness: 0.5, ...fields });
const times = Array.from({ length: 200 }, (_, i) => 1 + i / 100);

describe("the shape along the string", () => {
  it("is still at the nut and at the fingerboard's end", () => {
    for (const t of times) {
      expect(Math.abs(displacement(plucked(), t, 0))).toBe(0);
      expect(Math.abs(displacement(plucked(), t, 1))).toBeLessThan(1e-12);
    }
  });

  it("is widest mid-string", () => {
    const middle = Math.abs(displacement(plucked(), 1.03, 0.5));
    for (let u = 0; u <= 1; u += 0.05) expect(Math.abs(displacement(plucked(), 1.03, u))).toBeLessThanOrEqual(middle);
  });

  it("is the note's envelope at the peak of its wobble, mid-string", () => {
    const t = 1 + 1 / 28;
    expect(displacement(plucked(), t, 0.5)).toBeCloseTo(envelope(plucked(), t), 9);
  });

  it("is the product of the envelope, the shape along the string and the swing", () => {
    const t = 1.2;
    expect(displacement(plucked(), t, 0.25)).toBeCloseTo(envelope(plucked(), t) * Math.sin(Math.PI / 4) * swing(plucked(), t), 9);
  });
});

describe("over time", () => {
  it("dies away", () => {
    const note = plucked();
    expect(envelope(note, 1.1)).toBeGreaterThan(envelope(note, 1.5));
    expect(envelope(note, 1.5)).toBeGreaterThan(envelope(note, 2.5));
  });

  it("comes to rest over the last 80 ms, and is still once the note is dark", () => {
    const note = plucked();
    const unfaded = amplitude(0.5) * Math.exp(-(2.96 - 1) / 0.7);
    expect(envelope(note, 2.96)).toBeCloseTo(unfaded / 2, 9);
    expect(envelope(note, 3)).toBe(0);
    expect(envelope(note, 4)).toBe(0);
    expect(envelope(note, 0.5)).toBe(0);
  });

  it("starts each pluck from rest", () => {
    expect(swing(plucked({ onset: 2.25 }), 2.25)).toBe(0);
  });

  it("wobbles at 7 Hz: a quarter period in, the swing is at its peak", () => {
    expect(swing(plucked(), 1 + 1 / 28)).toBeCloseTo(1, 9);
  });

  it("returns to rest after a half period, at 7 Hz", () => {
    expect(swing(plucked(), 1 + 1 / 14)).toBeCloseTo(0, 9);
  });
});

describe("loudness and pitch", () => {
  it("swings a louder note wider: 0.6 mm at 0, 3.2 mm at 1", () => {
    expect([amplitude(0), amplitude(0.5), amplitude(1), amplitude(2)]).toEqual([0.6, 1.9, 3.2, 3.2]);
    expect(envelope(plucked({ loudness: 1 }), 1.2)).toBeGreaterThan(envelope(plucked({ loudness: 0.1 }), 1.2));
  });

  it("swings a note without loudness 2 mm", () => {
    expect(amplitude(null)).toBe(2);
  });

  it("wobbles a higher note faster: 7 Hz for the low E, 14 Hz two octaves up", () => {
    expect(frequency(40)).toBe(7);
    expect(frequency(64)).toBeCloseTo(14, 9);
    expect(frequency(52)).toBeGreaterThan(frequency(40));
  });
});
