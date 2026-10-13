import { describe, expect, it } from "vitest";

import { buildSong } from "../song";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { Note, TabDocument } from "../types/tabDocument";
import { END_PAD, MIN_FRETS, neckOf } from "./neck";

const FIRST_SONG: TabDocument = firstSongJson;
const WIDTH = 1000;
const SEMITONE = 2 ** (-1 / 12);

let ids = 0;
function note(fret: number, fields: Partial<Note> = {}): Note {
  ids += 1;
  return { id: `n${ids}`, t: ids, dur: 0.5, midi: 40 + fret, string: 0, fret, confidence: 0.95, ...fields };
}

function doc(fields: Partial<TabDocument> = {}): TabDocument {
  return {
    source: { title: "t", duration_sec: 60, audio_url: "/jobs/x/audio/mix" },
    instrument: {},
    timing: {},
    ...fields,
  };
}

function neckFor(frets: number[], fields: Partial<TabDocument> = {}, width = WIDTH) {
  return neckOf(buildSong(doc({ notes: frets.map((fret) => note(fret)), ...fields })), width);
}

describe("the range", () => {
  it("shows twelve frets, or two beyond the song's highest", () => {
    expect(neckFor([0, 3, 8]).frets).toBe(12);
    expect(neckFor([0, 10]).frets).toBe(12);
    expect(neckFor([11]).frets).toBe(13);
    expect(neckFor([5, 20]).frets).toBe(22);
  });

  it("shows twelve frets for a song with no notes", () => {
    expect(neckFor([]).frets).toBe(MIN_FRETS);
  });

  it("fits the real first song, which reaches fret 8, in twelve", () => {
    expect(neckOf(buildSong(FIRST_SONG), WIDTH).frets).toBe(12);
  });
});

describe("fret spacing", () => {
  const neck = neckFor([20]);
  const width = (n: number) => neck.wireX[n] - neck.wireX[n - 1];

  it("puts the nut first and fret N's wire at the fingerboard's end", () => {
    expect(neck.wireX).toHaveLength(neck.frets + 1);
    expect(neck.wireX[neck.frets]).toBeCloseTo(WIDTH - END_PAD);
    for (let n = 1; n <= neck.frets; n++) expect(neck.wireX[n]).toBeGreaterThan(neck.wireX[n - 1]);
  });

  it("makes each fret 2^(-1/12) the width of the one before", () => {
    for (let n = 2; n <= neck.frets; n++) expect(width(n) / width(n - 1)).toBeCloseTo(SEMITONE, 9);
  });

  it("makes a fret half as wide as the one twelve below it", () => {
    expect(width(13) / width(1)).toBeCloseTo(0.5, 9);
  });

  it("puts a note midway between its two wires, and an open string's left of the nut", () => {
    for (let n = 1; n <= neck.frets; n++) {
      expect(neck.noteX[n]).toBeCloseTo((neck.wireX[n - 1] + neck.wireX[n]) / 2);
    }
    expect(neck.noteX[0]).toBeLessThan(neck.wireX[0]);
    expect(neck.noteX[0]).toBeGreaterThan(neck.labelX);
  });

  it("gives finite positions before the panel has been measured", () => {
    const unmeasured = neckFor([5], {}, 0);

    for (const x of [...unmeasured.wireX, ...unmeasured.noteX]) expect(Number.isFinite(x)).toBe(true);
    expect(unmeasured.wireX[unmeasured.frets]).toBe(unmeasured.wireX[0]);
  });
});

describe("strings", () => {
  const labelsTopDown = (tuning: string[]) =>
    [...neckFor([], { instrument: { tuning } }).strings].sort((a, b) => a.y - b.y).map((s) => s.label);

  it("puts the lowest string on top, E A D G B e from top to bottom", () => {
    expect(labelsTopDown(["E2", "A2", "D3", "G3", "B3", "E4"])).toEqual(["E", "A", "D", "G", "B", "e"]);
  });

  it("does the same in drop D", () => {
    expect(labelsTopDown(["D2", "A2", "D3", "G3", "B3", "E4"])).toEqual(["D", "A", "D", "G", "B", "E"]);
  });

  it("draws lower strings thicker", () => {
    const weights = neckFor([]).strings.map((s) => s.weight);

    expect(weights[0]).toBeCloseTo(2.5);
    expect(weights[5]).toBeCloseTo(1);
    for (let s = 1; s < weights.length; s++) expect(weights[s]).toBeLessThan(weights[s - 1]);
  });

  it("sizes the height by the string count, never by the width", () => {
    const six = neckFor([]);
    const seven = neckFor([], { instrument: { tuning: ["B1", "E2", "A2", "D3", "G3", "B3", "E4"] } });

    expect(neckFor([], {}, 400).height).toBe(six.height);
    expect(seven.height).toBeGreaterThan(six.height);
    expect(six.height).toBeGreaterThan(six.numberY);
    expect(six.top).toBeLessThan(six.strings[0].y);
    expect(six.bottom).toBeGreaterThan(six.strings[5].y);
  });
});

describe("inlays", () => {
  it("marks 3, 5, 7, 9 and a double 12 on a twelve-fret neck", () => {
    const neck = neckFor([]);

    expect(neck.inlays).toEqual([3, 5, 7, 9, 12].map((fret) => ({ x: neck.noteX[fret], double: fret === 12 })));
  });

  it("adds the frets past 12 only as the range reaches them", () => {
    const frets = (neck: ReturnType<typeof neckOf>) =>
      neck.inlays.map((inlay) => neck.noteX.indexOf(inlay.x));

    expect(frets(neckFor([14]))).toEqual([3, 5, 7, 9, 12, 15]);
    expect(frets(neckFor([20]))).toEqual([3, 5, 7, 9, 12, 15, 17, 19, 21]);
  });
});
