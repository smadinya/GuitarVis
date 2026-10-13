/**
 * The real pipeline output the web tests draw on: the first song run
 * through the api. Assigned uncast below, so `tsc --noEmit` checks its shape
 * against the generated TabDocument, as types/tabDocument.test.ts does for
 * the minimal fixture.
 */
import { describe, expect, it } from "vitest";

import type { TabDocument } from "../types/tabDocument";
import firstSongJson from "./fixtures/first-song.tabdoc.json";

const FIRST_SONG: TabDocument = firstSongJson;

describe("the first-song fixture", () => {
  it("is real output: low confidence throughout, and no sections", () => {
    const confidences = (FIRST_SONG.notes ?? []).map((n) => n.confidence).sort((a, b) => a - b);

    expect(FIRST_SONG.schema_version).toBe(1);
    expect(confidences).toHaveLength(32);
    expect(confidences[16]).toBeLessThan(0.5);
    expect(confidences.at(-1)).toBeLessThan(0.9);
    expect(FIRST_SONG.sections).toEqual([]);
    expect(FIRST_SONG.chords?.length).toBeGreaterThan(0);
    expect(FIRST_SONG.timing.beats?.length).toBeGreaterThan(0);
  });
});
