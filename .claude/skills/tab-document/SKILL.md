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

Every model refuses unknown fields. That is deliberate: a client sending a
field this version does not know about should be told, not silently ignored.

## Check before you push

```bash
uv run pytest packages/core/tests/test_tabdoc.py packages/core/tests/test_schema_export.py
cd web && npm test; cd ..
```

The shared fixture `packages/core/tests/fixtures/minimal.tabdoc.json` is
validated by pytest and vitest both. If you add a required field, update the
fixture or both suites fail — which is the intended behaviour, not an
inconvenience.

`npm test` is `tsc --noEmit && vitest run` — both halves matter. The contract
check in `web/src/types/tabDocument.test.ts` is split across them: esbuild
erases `import type` before vitest ever runs, so `vitest run` alone only
checks the fixture's runtime values and cannot see whether its shape still
matches the generated `TabDocument` type. Only `tsc --noEmit` checks the
shape. Running `npx vitest run` by itself is not sufficient proof the contract
holds — always run (or let `npm test` / `make check` run) both.
