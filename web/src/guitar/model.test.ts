import { type BufferAttribute, BufferGeometry, Material, Mesh, MeshBasicMaterial, Texture } from "three";
import { describe, expect, it, vi } from "vitest";

import { buildSong } from "../song";
import type { Note, TabDocument } from "../types/tabDocument";
import { geometryOf } from "./geometry";
import { SEGMENTS, SIDES, buildModel, type Model, type TextPainter } from "./model";

const STANDARD = ["E2", "A2", "D3", "G3", "B3", "E4"];
const SEVEN = ["B1", "E2", "A2", "D3", "G3", "B3", "E4"];

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

const blank: TextPainter = () => ({ texture: new Texture(), aspect: 1 });
const named = (model: Model, name: string) => model.root.getObjectsByProperty("name", name);

describe("the model", () => {
  it("has one fret wire per fret", () => {
    for (const frets of [[5], [22]]) {
      const g = geometryOf(songWith(frets));
      expect(named(buildModel(g, blank), "wire")).toHaveLength(g.frets);
    }
  });

  it("has one string and one tuner per tuning entry", () => {
    for (const tuning of [STANDARD, SEVEN]) {
      const model = buildModel(geometryOf(songWith([], tuning)), blank);
      expect(named(model, "string")).toHaveLength(tuning.length);
      expect(named(model, "tuner")).toHaveLength(tuning.length);
      expect(model.strings).toHaveLength(tuning.length);
    }
  });

  it("labels every string at its tuner, and numbers every fret", () => {
    const g = geometryOf(songWith([]));
    const model = buildModel(g, blank);
    expect(named(model, "label")).toHaveLength(6);
    expect(named(model, "fret-number")).toHaveLength(g.frets);
  });

  it("lets a double-click land on the fingerboard and the neck, and nothing else", () => {
    expect(buildModel(geometryOf(songWith([])), blank).pickable.map((o) => o.name)).toEqual(["board", "neck"]);
  });

  it("bends a string at its middle, not its ends, and blurs it only while it moves", () => {
    const g = geometryOf(songWith([]));
    const string = buildModel(g, blank).strings[0];
    const ringY = (i: number) => {
      const position = string.tube.geometry.getAttribute("position");
      let sum = 0;
      for (let k = 0; k < SIDES; k++) sum += position.getY(i * SIDES + k);
      return sum / SIDES;
    };
    const rest = [0, SEGMENTS / 2, SEGMENTS].map(ringY);

    string.shape(2, 1, 1);
    expect(ringY(0) - rest[0]).toBeCloseTo(0, 6);
    expect(ringY(SEGMENTS / 2) - rest[1]).toBeCloseTo(2, 6);
    expect(ringY(SEGMENTS) - rest[2]).toBeCloseTo(0, 6);
    expect(string.blur.visible).toBe(true);

    string.shape(0, 0, 1);
    expect(ringY(SEGMENTS / 2)).toBeCloseTo(rest[1], 6);
    expect(string.blur.visible).toBe(false);
  });

  it("makes the blur as wide as the swing and the string, at 0.3 × the string's emphasis", () => {
    const g = geometryOf(songWith([]));
    const string = buildModel(g, blank).strings[0];
    const blur = string.blur.geometry.getAttribute("position");
    const half = (i: number) => (blur.getY(2 * i + 1) - blur.getY(2 * i)) / 2;

    string.shape(2, 1, 0.5);

    expect(half(SEGMENTS / 2)).toBeCloseTo(2 + g.gauges[0], 5);
    expect(half(0)).toBeCloseTo(g.gauges[0], 5);
    expect((string.blur.material as MeshBasicMaterial).opacity).toBeCloseTo(0.15, 9);
  });

  it("leaves its buffers alone when it is still and stays still", () => {
    const string = buildModel(geometryOf(songWith([])), blank).strings[0];
    const position = string.tube.geometry.getAttribute("position") as BufferAttribute;

    string.shape(2, 1, 1);
    const moving = position.version;
    string.shape(0, 0, 1);
    const settled = position.version;
    string.shape(0, 1, 1);

    expect(settled).toBeGreaterThan(moving);
    expect(position.version).toBe(settled);
  });

  it("disposes every geometry and material it made", () => {
    const model = buildModel(geometryOf(songWith([])), blank);
    const spies = new Set<{ dispose: () => void }>();
    model.root.traverse((o) => {
      if (o instanceof Mesh) for (const part of [o.geometry as BufferGeometry, o.material as Material]) spies.add(part);
    });
    const calls = [...spies].map((part) => vi.spyOn(part, "dispose"));

    model.dispose();

    for (const call of calls) expect(call).toHaveBeenCalled();
  });
});
