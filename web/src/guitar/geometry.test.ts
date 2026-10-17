import { describe, expect, it } from "vitest";

import { buildSong } from "../song";
import type { Note, TabDocument } from "../types/tabDocument";
import { GAUGES, LIFT, OPEN_X, geometryOf, type Vec3 } from "./geometry";

const STANDARD = ["E2", "A2", "D3", "G3", "B3", "E4"];

let ids = 0;
function note(fret: number): Note {
  ids += 1;
  return { id: `n${ids}`, t: ids, dur: 0.5, midi: 40 + fret, string: 0, fret, confidence: 0.95 };
}

function doc(fields: Partial<TabDocument> = {}): TabDocument {
  return {
    source: { title: "t", duration_sec: 60, audio_url: "/jobs/x/audio/mix" },
    instrument: {},
    timing: {},
    ...fields,
  };
}

function songWith(frets: number[], tuning = STANDARD) {
  return buildSong(doc({ notes: frets.map(note), instrument: { tuning } }));
}

const g = geometryOf(songWith([0, 5]));

describe("frets", () => {
  it("has twenty frets, or as many as the song's highest", () => {
    expect([[], [0, 5], [20], [22]].map((f) => geometryOf(songWith(f)).frets)).toEqual([20, 20, 20, 22]);
  });

  it("spaces the wires as on a 650 mm scale", () => {
    expect(g.wireX[0]).toBe(0);
    expect(g.wireX[12]).toBeCloseTo(-325, 9);
    for (let n = 1; n <= g.frets; n++) expect(g.wireX[n]).toBeCloseTo(-650 * (1 - 2 ** (-n / 12)), 9);
  });

  it("ends the fingerboard 10 mm past the last wire", () => {
    expect(g.boardEnd).toBeCloseTo(g.wireX[20] - 10, 9);
    expect(g.boardEnd).toBeCloseTo(-455.26, 2);
  });

  it("ignores a negative fret, and counts from the highest of the rest", () => {
    expect(geometryOf(songWith([-3])).frets).toBe(20);
    expect(geometryOf(songWith([-3, 22])).frets).toBe(22);
  });

  it("runs `along` from 0 at the nut to 1 at the end, and holds there past either", () => {
    expect(g.along(0)).toBe(0);
    expect(g.along(g.boardEnd / 2)).toBeCloseTo(0.5, 9);
    expect(g.along(g.boardEnd)).toBe(1);
    expect(g.along(1)).toBe(0);
    expect(g.along(100)).toBe(0);
    expect(g.along(2 * g.boardEnd)).toBe(1);
    expect(g.along(-1000)).toBe(1);
  });

  it("makes the fingerboard 1.7 × (22 + 6.5a) mm either side of the centre", () => {
    expect(g.halfWidth(0)).toBeCloseTo(37.4, 9);
    expect(g.halfWidth(g.boardEnd / 2)).toBeCloseTo(42.925, 9);
    expect(g.halfWidth(g.boardEnd)).toBeCloseTo(48.45, 9);
    expect(g.halfWidth(100)).toBeCloseTo(37.4, 9);
    expect(g.halfWidth(2 * g.boardEnd)).toBeCloseTo(48.45, 9);
  });
});

describe("marks", () => {
  it("puts a fretted note between its two wires, on its string, just above it", () => {
    for (let f = 1; f <= g.frets; f++) {
      for (let s = 0; s < 6; s++) {
        const { at, open } = g.mark(s, f);
        expect(at.x).toBeCloseTo((g.wireX[f - 1] + g.wireX[f]) / 2, 9);
        expect(at.y).toBeCloseTo(g.stringY(s, at.x), 9);
        expect(at.z).toBeCloseTo(g.stringZ(at.x) + LIFT, 9);
        expect(open).toBe(false);
      }
    }
  });

  it("puts an open note 12 mm past the nut, on its string's way to its post", () => {
    for (let s = 0; s < 6; s++) {
      const { at, open } = g.mark(s, 0);
      const { top } = g.tuners[s];
      const y0 = g.stringY(s, 0);
      expect(at.x).toBe(OPEN_X);
      expect((at.y - y0) / (top.y - y0)).toBeCloseTo(OPEN_X / top.x, 9);
      expect(open).toBe(true);
    }
  });

  it("lifts an open ring 1 mm off the line from the nut, 2.8 mm up, to its post's top", () => {
    for (let s = 0; s < 6; s++) {
      const { at } = g.mark(s, 0);
      const { top } = g.tuners[s];
      expect((at.z - LIFT - 2.8) / (top.z - 2.8)).toBeCloseTo(OPEN_X / top.x, 9);
    }
  });

  it("makes neighbouring dots almost touch, and never overlap, at fret 1 and at fret F", () => {
    for (const f of [1, g.frets]) {
      for (let s = 0; s < 5; s++) {
        const [a, b] = [g.mark(s, f), g.mark(s + 1, f)];
        const apart = Math.abs(a.at.y - b.at.y);
        expect(a.r + b.r).toBeLessThan(apart);
        expect(a.r + b.r).toBeGreaterThanOrEqual(0.97 * apart);
      }
    }
  });
});

describe("strings", () => {
  const topDown = (tuning: string[]) => {
    const geometry = geometryOf(songWith([], tuning));
    return geometry.labels.map((label, s) => ({ label, y: geometry.stringY(s, 0) }))
      .sort((a, b) => b.y - a.y).map((s) => s.label);
  };

  it("puts the lowest string on top: E A D G B e, and D A D G B E in drop D", () => {
    expect(topDown(STANDARD)).toEqual(["E", "A", "D", "G", "B", "e"]);
    expect(topDown(["D2", "A2", "D3", "G3", "B3", "E4"])).toEqual(["D", "A", "D", "G", "B", "E"]);
  });

  it("spreads the outer strings 1.7 × (17.5 + 7a) mm from the centre", () => {
    expect(g.stringY(0, 0)).toBeCloseTo(29.75, 9);
    expect(g.stringY(5, g.boardEnd)).toBeCloseTo(-41.65, 9);
  });

  it("holds the strings 2.8 + 1.6a mm above the board, whatever the string", () => {
    expect(g.stringZ(0)).toBeCloseTo(2.8, 9);
    expect(g.stringZ(g.boardEnd / 2)).toBeCloseTo(3.6, 9);
    expect(g.stringZ(g.boardEnd)).toBeCloseTo(4.4, 9);
    expect(g.stringZ(100)).toBeCloseTo(2.8, 9);
    expect(g.stringZ(2 * g.boardEnd)).toBeCloseTo(4.4, 9);
    expect(g.stringY(0, g.boardEnd / 2)).toBeCloseTo(35.7, 9);
    expect(g.stringY(2, 0)).toBeCloseTo(29.75 / 5, 9);
  });

  it("puts a lone string on the centreline, with a post, a dot and a gauge", () => {
    const one = geometryOf(songWith([], ["E2"]));
    expect(one.strings).toBe(1);
    expect(one.stringY(0, 0)).toBe(0);
    expect(one.stringY(0, one.boardEnd)).toBe(0);
    expect(one.tuners.map((t) => [t.side, t.post.x])).toEqual([[1, 50]]);
    expect(one.mark(0, 3).r).toBeGreaterThan(0);
    expect(Number.isFinite(one.mark(0, 3).r)).toBe(true);
    expect(one.mark(0, 0).r).toBeCloseTo(29.155, 9);
    expect(one.gauges).toEqual([0.26]);
    expect(one.wound).toEqual([true]);
  });

  it("repeats the thickest gauge below the sixth string from the top", () => {
    const seven = geometryOf(songWith([], ["B1", "E2", "A2", "D3", "G3", "B3", "E4"]));
    expect(seven.gauges).toEqual([0.62, 0.62, 0.52, 0.43, 0.36, 0.3, 0.26]);
    expect(seven.wound).toEqual([true, true, true, true, false, false, false]);
    const eight = geometryOf(songWith([], ["F#1", "B1", "E2", "A2", "D3", "G3", "B3", "E4"]));
    expect(eight.gauges).toEqual([0.62, 0.62, 0.62, 0.52, 0.43, 0.36, 0.3, 0.26]);
    expect(eight.wound).toEqual([true, true, true, true, false, false, false, false]);
  });

  it("winds the lower half, and makes each string thinner than the one below", () => {
    expect(g.wound).toEqual([true, true, true, false, false, false]);
    expect(g.gauges).toEqual(GAUGES);
  });
});

describe("tuners", () => {
  it("puts 3 + 3 on six strings, the outer strings nearest the nut", () => {
    expect(g.tuners.map((t) => t.side)).toEqual([1, 1, 1, -1, -1, -1]);
    expect(g.tuners.map((t) => t.post.x)).toEqual([50, 98, 146, 146, 98, 50]);
  });

  it("puts an odd count's extra string on the upper side, every post on the headstock", () => {
    const seven = geometryOf(songWith([], ["B1", "E2", "A2", "D3", "G3", "B3", "E4"]));
    expect(seven.tuners.map((t) => t.side)).toEqual([1, 1, 1, 1, -1, -1, -1]);
    expect(seven.tuners.map((t) => t.post.x)).toEqual([50, 82, 114, 146, 146, 98, 50]);
  });

  it("tilts the headstock back, so a post further from the nut sits lower", () => {
    expect(g.tuners[2].top.z).toBeLessThan(g.tuners[0].top.z);
    expect(g.tuners[0].top.z).toBeLessThan(0);
  });

  it("has no tuners, gauges or winding on a song with no strings", () => {
    const none = geometryOf(songWith([], []));
    expect(none.strings).toBe(0);
    expect([none.labels, none.tuners, none.gauges, none.wound]).toEqual([[], [], [], []]);
  });
});

describe("inlays", () => {
  it("marks 3 to 19, with a pair at 12, on a twenty-fret neck", () => {
    expect(g.inlays).toHaveLength(9);
    const twelve = g.inlays.filter((i) => i.x === g.noteX(12));
    expect(twelve).toHaveLength(2);
    expect(twelve[0].y).toBeCloseTo(-twelve[1].y, 9);
  });

  it("adds 21 only when the neck reaches it", () => {
    expect(geometryOf(songWith([21])).inlays).toHaveLength(10);
  });
});

describe("bounds", () => {
  it("contains every mark, post top and inlay", () => {
    const inside = (p: Vec3) =>
      (["x", "y", "z"] as const).every((k) => g.bounds.min[k] <= p[k] && p[k] <= g.bounds.max[k]);
    const points = [
      ...g.inlays,
      ...g.tuners.map((t) => t.top),
      ...Array.from({ length: 6 * (g.frets + 1) }, (_, i) => g.mark(i % 6, Math.floor(i / 6)).at),
    ];
    for (const p of points) expect(inside(p), JSON.stringify(p)).toBe(true);
  });
});
