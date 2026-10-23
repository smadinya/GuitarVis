import { describe, expect, it } from "vitest";

import { NoteCursor, samePosition, TrackCursor, type Span } from "./cursor";

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

  it("returns a note that ends exactly at the window's start", () => {
    // from - dur rounds above t here, so a bound written as `t < from - longest`
    // would prune a note that `t + dur >= from` keeps.
    const t = 28.190847716661406;
    const dur = 4.060984901227755;
    const from = t + dur;
    const notes: Tagged[] = [{ id: 0, t, dur }];

    expect(ids(new NoteCursor(notes).window(from, from + 1))).toEqual([0]);

    const stepping = new NoteCursor(notes);
    stepping.window(from - 2, from + 0.5);
    expect(ids(stepping.window(from, from + 1))).toEqual([0]);
  });

  it("answers an empty song", () => {
    expect(new NoteCursor<Tagged>([]).window(0, 10)).toEqual([]);
  });
});

const span = (t: number, dur: number) => ({ t, dur });

describe("TrackCursor", () => {
  it("has nothing current in an empty list", () => {
    expect(new TrackCursor([]).at(3)).toEqual({ current: -1, next: 0 });
  });

  it("follows a single span, both ends included", () => {
    const cursor = new TrackCursor([span(1, 1)]);
    expect(cursor.at(0)).toEqual({ current: -1, next: 0 });
    expect(cursor.at(1)).toEqual({ current: 0, next: 1 });
    expect(cursor.at(2)).toEqual({ current: 0, next: 1 });
    expect(cursor.at(2.01)).toEqual({ current: -1, next: 1 });
  });

  it("has nothing current in a gap", () => {
    expect(new TrackCursor([span(0, 1), span(2, 1)]).at(1.5)).toEqual({ current: -1, next: 1 });
  });

  it("gives a shared boundary to the later span", () => {
    expect(new TrackCursor([span(0, 1), span(1, 1)]).at(1)).toEqual({ current: 1, next: 2 });
  });

  it("takes the latest onset among overlapping spans, and the earlier once the later ends", () => {
    const cursor = new TrackCursor([span(0, 4), span(1, 1)]);
    expect(cursor.at(1.5)).toEqual({ current: 1, next: 2 });
    expect(cursor.at(3)).toEqual({ current: 0, next: 2 });
  });

  it("finds the earlier span after a backward jump", () => {
    const cursor = new TrackCursor([span(0, 10), span(10, 10), span(20, 10)]);
    expect(cursor.at(25).current).toBe(2);
    expect(cursor.at(5)).toEqual({ current: 0, next: 1 });
  });
});

describe("samePosition", () => {
  it("is true only when both the current and the next span match", () => {
    expect(samePosition({ current: 1, next: 2 }, { current: 1, next: 2 })).toBe(true);
    expect(samePosition({ current: 1, next: 2 }, { current: 0, next: 2 })).toBe(false);
    expect(samePosition({ current: 1, next: 2 }, { current: 1, next: 3 })).toBe(false);
  });
});
