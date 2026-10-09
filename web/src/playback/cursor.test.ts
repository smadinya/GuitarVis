import { describe, expect, it } from "vitest";

import { NoteCursor, type Span } from "./cursor";

interface Tagged extends Span {
  id: number;
}

/** What `window` must return, by brute force. */
function expected(notes: readonly Tagged[], from: number, to: number): number[] {
  return notes.filter((n) => n.t <= to && n.t + n.dur >= from).map((n) => n.id);
}

function ids(notes: readonly Tagged[]): number[] {
  return notes.map((n) => n.id);
}

/** A note every 0.25 s for a minute, some of them long. */
const SONG: Tagged[] = Array.from({ length: 240 }, (_, i) => ({
  id: i,
  t: i * 0.25,
  dur: i % 17 === 0 ? 3 : 0.2,
}));

describe("NoteCursor", () => {
  it("steps forward frame by frame", () => {
    const cursor = new NoteCursor(SONG);

    for (let now = 0; now < 60; now += 1 / 60) {
      expect(ids(cursor.window(now - 1, now + 4))).toEqual(expected(SONG, now - 1, now + 4));
    }
  });

  it("re-seats after a backward jump and a forward jump past the window", () => {
    const cursor = new NoteCursor(SONG);
    const windows: Array<[number, number]> = [
      [30, 35], [30.02, 35.02], [5, 10], [5.1, 10.1], [50, 55], [0, 1], [59, 64],
    ];

    for (const [from, to] of windows) {
      expect(ids(cursor.window(from, to))).toEqual(expected(SONG, from, to));
    }
  });

  it("re-seats when the window shrinks", () => {
    const cursor = new NoteCursor(SONG);

    cursor.window(10, 20);
    expect(ids(cursor.window(11, 12))).toEqual(expected(SONG, 11, 12));
  });

  it("finds overlapping notes still sounding from before the window", () => {
    const notes: Tagged[] = [
      { id: 0, t: 0, dur: 10 },
      { id: 1, t: 1, dur: 1 },
      { id: 2, t: 5, dur: 2 },
    ];
    const cursor = new NoteCursor(notes);

    expect(ids(cursor.window(6, 6))).toEqual([0, 2]);
  });

  it("finds a note longer than the window that spans it", () => {
    const cursor = new NoteCursor<Tagged>([{ id: 0, t: 0, dur: 30 }]);

    expect(ids(cursor.window(10, 11))).toEqual([0]);
    expect(ids(cursor.window(31, 32))).toEqual([]);
  });

  it("answers an empty song", () => {
    expect(new NoteCursor<Tagged>([]).window(0, 10)).toEqual([]);
  });
});
