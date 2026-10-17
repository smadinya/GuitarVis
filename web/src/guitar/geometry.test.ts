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
