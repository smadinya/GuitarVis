import { describe, expect, it } from "vitest";

import { buildSong, canRead } from "./song";
import firstSongJson from "./test/fixtures/first-song.tabdoc.json";
import minimalJson from "../../packages/core/tests/fixtures/minimal.tabdoc.json";
import type { TabDocument } from "./types/tabDocument";

const FIRST_SONG: TabDocument = firstSongJson;
const MINIMAL: TabDocument = minimalJson;

describe("buildSong", () => {
  it("sorts every track by onset", () => {
    const doc = structuredClone(FIRST_SONG);
    doc.notes = [...(doc.notes ?? [])].reverse();

    const song = buildSong(doc);

    const onsets = song.notes.map((n) => n.t);
    expect(onsets).toEqual([...onsets].sort((a, b) => a - b));
    expect(song.notes).toHaveLength(FIRST_SONG.notes?.length ?? -1);
  });

  it("reads the real first song: notes, chords, beats, and no sections", () => {
    const song = buildSong(FIRST_SONG);

    expect(song.notes.length).toBeGreaterThan(0);
    expect(song.chords.length).toBeGreaterThan(0);
    expect(song.beats.length).toBeGreaterThan(0);
    expect(song.sections).toEqual([]);
    expect(song.duration).toBeCloseTo(13.871);
  });

  it("fills omitted optional tracks with empty lists and standard tuning", () => {
    const doc: TabDocument = {
      source: MINIMAL.source,
      instrument: {},
      timing: {},
    };

    const song = buildSong(doc);

    expect(song.notes).toEqual([]);
    expect(song.chords).toEqual([]);
    expect(song.sections).toEqual([]);
    expect(song.beats).toEqual([]);
    expect(song.warnings).toEqual([]);
    expect(song.hidden).toEqual([]);
    expect(song.tuning).toEqual(["E2", "A2", "D3", "G3", "B3", "E4"]);
  });
});

describe("canRead", () => {
  it("reads version 1, and a document with no version", () => {
    expect(canRead(MINIMAL)).toBe(true);
    const unversioned: TabDocument = { ...MINIMAL };
    delete unversioned.schema_version;
    expect(canRead(unversioned)).toBe(true);
  });

  it("refuses any other version", () => {
    expect(canRead({ ...MINIMAL, schema_version: 2 })).toBe(false);
  });
});
