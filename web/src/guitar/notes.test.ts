import { Group, type Mesh, type MeshBasicMaterial, type PlaneGeometry, Texture } from "three";
import { describe, expect, it, vi } from "vitest";

import { buildSong } from "../song";
import type { Note, TabDocument } from "../types/tabDocument";
import { geometryOf } from "./geometry";
import { NoteLayer, PULSE_SCALE, type DotPainter } from "./notes";
import type { SoundingNote } from "./sounding";

const STANDARD = ["E2", "A2", "D3", "G3", "B3", "E4"];

function note(fret: number): Note {
  return { id: `n${fret}`, t: 1, dur: 0.5, midi: 40 + fret, string: 0, fret, confidence: 0.95 };
}

function doc(fields: Partial<TabDocument> = {}): TabDocument {
  return {
    source: { title: "t", duration_sec: 60, audio_url: "/jobs/x/audio/mix" },
    instrument: { tuning: STANDARD },
    timing: {},
    notes: [note(0), note(5)],
    ...fields,
  };
}

const g = geometryOf(buildSong(doc()));
const sounding = (fields: Partial<SoundingNote> = {}): SoundingNote => ({
  key: "dot:a",
  string: 0,
  fret: 3,
  midi: 43,
  name: "G",
  opacity: 1,
  onset: 1,
  until: 2,
  loudness: null,
  ...fields,
});
function layer() {
  const parent = new Group();
  const paint = vi.fn<DotPainter>(() => new Texture());
  return { parent, paint, notes: new NoteLayer(parent, g, paint) };
}
const mesh = (parent: Group) => parent.children[0] as Mesh<PlaneGeometry, MeshBasicMaterial>;

describe("the notes on the neck", () => {
  it("makes a mesh for a new key, at its mark", () => {
    const { parent, notes } = layer();
    notes.apply([sounding()], 0, true);
    expect(parent.children).toHaveLength(1);
    expect(mesh(parent).position.toArray()).toEqual(Object.values(g.mark(0, 3).at));
  });

  it("keeps the mesh while its key lasts, and follows its opacity", () => {
    const { parent, notes } = layer();
    notes.apply([sounding()], 0, true);
    const first = mesh(parent);
    notes.apply([sounding({ opacity: 0.35 })], 16, true);
    expect(mesh(parent)).toBe(first);
    expect(first.material.opacity).toBe(0.35);
  });

  it("removes and disposes the mesh once its key is gone", () => {
    const { parent, notes } = layer();
    notes.apply([sounding()], 0, true);
    const dispose = vi.spyOn(mesh(parent).material, "dispose");
    notes.apply([], 32, true);
    expect(parent.children).toHaveLength(0);
    expect(dispose).toHaveBeenCalled();
  });

  it("gives each pluck of a repeated note its own mesh, so each one pulses", () => {
    const { parent, notes } = layer();
    notes.apply([sounding({ key: "dot:first" })], 0, true);
    const first = mesh(parent);
    notes.apply([sounding({ key: "dot:again" })], 300, true);
    expect(mesh(parent)).not.toBe(first);
    expect(mesh(parent).scale.x).toBeCloseTo(PULSE_SCALE * g.mark(0, 3).r, 9);
  });

  it("rings an open string and dots a fretted note", () => {
    const { parent, notes } = layer();
    notes.apply([sounding({ key: "dot:o", fret: 0, name: "E" }), sounding({ key: "dot:f", string: 1 })], 0, true);
    expect(parent.children.map((c) => c.name).sort()).toEqual(["dot", "ring"]);
  });

  it("pulses a new mark from 1.5 times its size down to it over 220 ms", () => {
    const { parent, notes } = layer();
    const r = g.mark(0, 3).r;
    expect(notes.apply([sounding()], 1000, true)).toBe(true);
    expect(mesh(parent).scale.x).toBeCloseTo(1.5 * r, 9);
    notes.apply([sounding()], 1110, true);
    expect(mesh(parent).scale.x).toBeCloseTo(r * (1 + 0.5 * 0.25), 9);
    expect(notes.apply([sounding()], 1220, true)).toBe(false);
    expect(mesh(parent).scale.x).toBeCloseTo(r, 9);
  });

  it("does not pulse under reduced motion", () => {
    const { parent, notes } = layer();
    expect(notes.apply([sounding()], 0, false)).toBe(false);
    expect(mesh(parent).scale.x).toBeCloseTo(g.mark(0, 3).r, 9);
  });

  it("paints each name once, and again on repaint", () => {
    const { parent, notes, paint } = layer();
    notes.apply([sounding({ key: "dot:a" }), sounding({ key: "dot:b", string: 1 })], 0, true);
    expect(paint).toHaveBeenCalledTimes(1); // both named G, both fretted
    const old = mesh(parent).material.map as Texture;
    const dispose = vi.spyOn(old, "dispose");

    notes.repaint();

    expect(paint).toHaveBeenCalledTimes(2);
    expect(dispose).toHaveBeenCalled();
    expect(mesh(parent).material.map).not.toBe(old);
  });
});
