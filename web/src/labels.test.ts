import { describe, expect, it } from "vitest";

import { noteName, stringLabels } from "./labels";

describe("stringLabels", () => {
  it("labels standard tuning E A D G B e, lowest first", () => {
    expect(stringLabels(["E2", "A2", "D3", "G3", "B3", "E4"])).toEqual(["E", "A", "D", "G", "B", "e"]);
  });

  it("keeps drop D's top E in capitals", () => {
    expect(stringLabels(["D2", "A2", "D3", "G3", "B3", "E4"])).toEqual([
      "D", "A", "D", "G", "B", "E",
    ]);
  });

  it("names sharps and flats", () => {
    expect(stringLabels(["C#2", "Bb2"])).toEqual(["C#", "Bb"]);
  });
});

describe("noteName", () => {
  it("spells every pitch class with sharps", () => {
    const names = Array.from({ length: 12 }, (_, i) => noteName(60 + i));

    expect(names).toEqual(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]);
  });

  it("gives the same name in every octave", () => {
    // The low E string, open; the D string's second fret; the high e, open.
    expect([noteName(40), noteName(52), noteName(64)]).toEqual(["E", "E", "E"]);
  });
});
