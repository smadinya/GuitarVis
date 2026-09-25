---
name: tab-document
description: Use when editing packages/core tabdoc.py, the generated schema/ or web/src/types/, or when adding, removing, or retyping any tab document field. The document is the contract between the pipeline and every client, and changing it wrong breaks clients silently.
---

# The tab document

The contract between the pipeline and every client, present and future.
Defined once in `packages/core/src/guitarvis_core/tabdoc.py`.

## After any change, regenerate

```bash
make schema
git add schema web/src/types
```

`schema/tab-document.schema.json` and `web/src/types/tabDocument.ts` are
generated from the Pydantic models and committed. CI runs `make schema` and
fails on any diff. Never hand-edit either file.

## When to bump `SCHEMA_VERSION`

**Additive, no bump:** a new optional field with a default; a widened
constraint; a new enum member that old clients can ignore.

**Breaking, bump required:** removing a field; renaming one; retyping one;
making an optional field required; narrowing a constraint.

This "additive, no bump" rule is true only for a client that reads the
document in-repo, through the generated TypeScript types or by calling
`TabDocument.model_validate`. It is **false** for anything that validates the
raw JSON against the *committed JSON Schema* independently — a future iOS
client bundling `schema/tab-document.schema.json`, for instance. Because every
model uses `extra="forbid"` (`additionalProperties: false` on the root and all
eight `$defs`) and `Technique` is a closed enum, a v2 document with a new
optional field, or a new `Technique` member, fails whole-document validation
against a bundled v1 schema. A schema-validating client must still update to
accept a v1-additive change, even though a `model_validate`-based client does
not. State this when documenting a "safe" additive change to anyone building
an external validator.

Bumping means every client must be updated to accept the new version.
`schema_version` exists so a client can refuse a document it does not
understand rather than render it wrong.

## Rules that are not negotiable

**Seconds are authoritative.** Every note carries `t`, a wall-clock onset. Bars
and beats live only in `timing.beats`. Never add a bar/beat field to `Note`:
beat tracking is the most error-prone stage, and a tempo error would then
desynchronise playback from audio — the one failure a play-along app cannot
have. A bad beat grid should yield ugly bar lines over correctly synced notes.

**The note list stays flat.** Measures are computed from the beat grid at
render time. Nesting notes inside measures would make a timing correction
rewrite the note data and force the fretboard views to parse structure they do
not need.

**The fingering invariant.** `pitch_of(string, fret, tuning) == note.midi`, for
every note, always. `guitarvis_core.fretboard.check_invariant` is the single
implementation; call it rather than reimplementing the arithmetic.

**Confidence is first-class** and required on every note and chord. With no
editing in v1, the interface's honesty depends entirely on this field. A
beginner cannot distinguish a wrong tab from a hard passage, and will conclude
they are bad at guitar.

**Optional tracks are omittable.** `chords`, `sections`, and `timing.beats`
default to empty. A job that loses chord detection omits the track; it does not
send empty scaffolding.

## `extra="forbid"`

Every model refuses unknown fields. Clients consume tab documents; they never
produce them — the pipeline is the only writer. This is deliberate so that an
old client parsing a newer document (produced by a later pipeline version)
raises a validation error instead of silently dropping the field it does not
recognise and rendering an incomplete or wrong tab.

This also closes every model's generated JSON Schema
(`additionalProperties: false` at the root and in all eight `$defs`, plus
`Technique` as a closed enum). See "When to bump `SCHEMA_VERSION`" above for
why that makes "additive, no bump" false for a client validating against the
committed schema file rather than through `TabDocument.model_validate`.

## Check before you push

```bash
uv run pytest packages/core/tests/test_tabdoc.py packages/core/tests/test_schema_export.py
npm --prefix web test
```

The shared fixture `packages/core/tests/fixtures/minimal.tabdoc.json` is
validated by pytest and vitest both. If you add a required field, update the
fixture or both suites fail — which is the intended behaviour, not an
inconvenience.

`npm test` is `tsc --noEmit && vitest run` — both halves matter. The contract
check in `web/src/types/tabDocument.test.ts` is split across them: the fixture
JSON is imported directly and assigned, with no cast, to a `TabDocument`-typed
constant, so `tsc --noEmit` structurally checks the fixture's shape against the
generated type. esbuild erases that type-only checking machinery before vitest
ever runs, so `vitest run` alone only checks the fixture's runtime values and
cannot see whether its shape still matches `TabDocument`. Only `tsc --noEmit`
checks the shape. Running `npx vitest run` by itself is not sufficient proof
the contract holds — always run (or let `npm test` / `make check` run) both.
