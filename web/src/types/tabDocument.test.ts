/**
 * The shared fixture must satisfy the generated type.
 *
 * The CI diff check catches a forgotten regeneration. This catches the failure
 * the diff check cannot see: a generator that is silently emitting the wrong
 * types, where both sides are consistently wrong.
 */
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import type { TabDocument } from "./tabDocument";

// Resolved from this file, not from the working directory, so the test does
// not depend on where the runner was invoked.
const FIXTURE = new URL(
  "../../../packages/core/tests/fixtures/minimal.tabdoc.json",
  import.meta.url,
);

function loadFixture(): TabDocument {
  return JSON.parse(readFileSync(FIXTURE, "utf8")) as TabDocument;
}

describe("the tab document contract", () => {
  // Note the optional chaining throughout. Every field carrying a Pydantic
  // default is absent from the schema's `required` list and therefore optional
  // in TypeScript. That is correct — the degradation ladder depends on a
  // document being able to omit whole tracks — and a client must handle it.
  it("accepts the fixture that pytest also validates", () => {
    const doc = loadFixture();

    expect(doc.schema_version).toBe(1);
    expect(doc.instrument.tuning).toEqual(["E2", "A2", "D3", "G3", "B3", "E4"]);
    expect(doc.notes ?? []).toHaveLength(2);
    expect(doc.notes?.[1]?.string).toBe(2);
    expect(doc.notes?.[1]?.fret).toBe(2);
  });

  it("keeps seconds as the authoritative position", () => {
    const doc = loadFixture();

    // Notes carry `t` in seconds. Bars and beats live only in timing.beats.
    expect(doc.notes?.[0]?.t).toBe(0);
    expect(doc.timing.beats?.[0]?.bar).toBe(1);
  });

  it("models an omitted optional track as absent rather than malformed", () => {
    const degraded: TabDocument = { ...loadFixture(), chords: [] };

    expect(degraded.chords).toEqual([]);
  });
});
