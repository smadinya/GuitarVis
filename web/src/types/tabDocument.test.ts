/**
 * The shared fixture must satisfy the generated type.
 *
 * The CI diff check catches a forgotten regeneration. This catches the failure
 * the diff check cannot see: a generator that is silently emitting the wrong
 * types, where both sides are consistently wrong.
 *
 * The fixture is imported directly as a JSON module (`resolveJsonModule` is
 * on in tsconfig.json) and assigned to a `TabDocument`-typed constant below,
 * with no cast in between. `tsc --noEmit` structurally checks the fixture's
 * actual SHAPE against the generated type this way — a cast such as `as
 * TabDocument` would instead just tell the compiler to trust the assertion,
 * which checks nothing. `vitest run` alone still only checks the fixture's
 * runtime VALUES (the asserted numbers/strings/lengths); the SHAPE half is
 * verified only by `tsc --noEmit`. Do not run this suite by itself as proof
 * the contract holds; run it alongside typechecking (`npm test` does both —
 * see package.json — and so does `make check`).
 */
import { describe, expect, it } from "vitest";

import fixtureJson from "../../../packages/core/tests/fixtures/minimal.tabdoc.json";
import type { TabDocument } from "./tabDocument";

// The direct assignment (no `as TabDocument`) is the actual shape check:
// tsc rejects this line if the JSON module's inferred type no longer
// structurally matches TabDocument.
const FIXTURE: TabDocument = fixtureJson;

function loadFixture(): TabDocument {
  // Return a fresh copy per call so tests that mutate their own copy (see
  // the "omitted optional track" test below) cannot affect one another.
  return structuredClone(FIXTURE);
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
