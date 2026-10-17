# 3D Guitar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the second half of phase 5. A procedural three.js guitar neck replaces 007's SVG fretboard, seen square-on in 2D and turnable in 3D. Its strings swing by each note's loudness, which the worker measures from the stem.

**Architecture:** Two halves that meet at one new optional field, `Note.loudness`. In the worker, `loudness.py` measures each strum's level from the stem after transcription, and the field rides `NoteEvent` → `TabNote` → `Note`. In `web/src/guitar/`, four pure modules decide everything that is drawn: `sounding.ts` (what sounds now), `geometry.ts` (every position in millimetres), `vibration.ts` (how a string moves) and `camera.ts` (poses and limits). Two three.js modules build from them: `model.ts` (the scene graph) and `notes.ts` (the keyed dot updater). `stage.ts` owns the renderer and the frame loop, outside React. `Guitar.tsx` is the panel's chrome, and `Player` loads it lazily. 007's `fretboard/` is deleted.

**Tech Stack:** Python 3.12, Pydantic 2, stdlib `wave` · React 18.3, TypeScript 6.0, Vite 8.3, Vitest 5.0 with jsdom 29 · **new:** `three@^0.186.1`, `@types/three@^0.186.0`.

**Spec:** [spec.md](spec.md) · **Parent:** [001-guitarvis-design](../001-guitarvis-design/spec.md) · **Builds on:** [007-2d-fretboard](../007-2d-fretboard/spec.md) · **Reference look:** [spike.html](spike.html)

**Checked while writing**, in a scratch worktree of this branch:
- `three@0.186.1` (published 2026-09-24) and `@types/three@0.186.0` install cleanly. `tsc --noEmit` accepts `import { OrbitControls } from "three/addons/controls/OrbitControls.js"` under this repo's tsconfig.
- On vitest's `node` environment, three builds a scene graph with no WebGL: `ExtrudeGeometry`, `localToWorld`, `Vector3.project` and `Raycaster` all work. On jsdom, `OrbitControls` constructs on a `<canvas>`, and `new WebGLRenderer()` throws.
- `vite build` with three behind `React.lazy` gives a separate chunk of 584 kB (147 kB gzipped). The entry chunk grows by 0.6 kB gzipped, and Vite warns about the large chunk.
- In headless Chromium, `width: 100%; aspect-ratio: 2.8; min-height: 260px; max-height: 460px` keeps the full width and clamps the height: 368×260, 868×310, 1100×393.
- The geometry below gives a model 647 mm long and 232 mm tall, which is the spec's width / 2.8. At aspect 2.8, the 2D home pose's framing is limited equally by both axes (NDC 0.960 and 0.962).

**Not run:** this plan's code, which has not been assembled. Task 12 is a person's job.

## Global Constraints

Every task inherits these.

- **Never commit to `main`.** Work on `008-3d-guitar`, which already holds the spec. `.githooks/pre-commit` refuses `main`.
- **`make check` is the gate.** Run `make services` first, or the integration tests skip locally and fail in CI.
- **No change to the api, `SCHEMA_VERSION` (stays 1), or `CACHE_VERSION` (stays 1).**
- **After changing `tabdoc.py`, run `make schema` and commit `schema/` and `web/src/types/` with it** (invariant 5). Never hand-edit `web/src/types/tabDocument.ts` or `api.ts`.
- **`loudness.py` is not a stage and imports no stage.** It is stdlib only, like `measure_rms`, so it runs in CI without the `ml` extra.
- **Degrade, never fail.** A loudness failure leaves every `loudness` as `None` and logs a warning. It adds nothing to the document's `warnings`, and the job carries on. Catch `Exception`, never `BaseException`: `JobTimedOut` must pass through.
- **`web/src/confidence.ts` is imported unchanged.** Opacity comes from `emphasis(...)` and means nothing else.
- **A view never imports another view.** Text comes from `web/src/labels.ts`.
- **React never renders at frame rate.** Frames go through `Stage`. React renders the chrome on mount, on a view toggle, and when WebGL is lost or comes back.
- **The guitar never calls `engine.redraw()`.** It requests its own animation frames for camera moves and pulses.
- **Never call `OrbitControls.listenToKeyEvents`.** The arrow keys seek (`player/keys.ts`). Keyboard control of the camera is out of scope.
- **three.js is reached only through `React.lazy`.** Nothing outside `web/src/guitar/` imports `three` or a `guitar/` module, except `Player.tsx`'s lazy import and the tests.
- **Seconds are authoritative.** Vibration runs on song time, so pausing freezes it and 0.5× slows it. The pulse and camera transitions run on wall-clock time.
- **Exact values from the spec:**
  - mm throughout. The nut is at x = 0 and the neck runs toward −x. The headstock is at +x, the fingerboard faces +z, and the lowest string is on top (+y).
  - wire n at x = −650 · (1 − 2^(−n/12)). F = max(20, the song's highest fret). The fingerboard ends 10 mm past wire F.
  - `WIDE` = 1.7. `a` runs from 0 at the nut to 1 at the fingerboard's end. The board's half-width is `WIDE · (22 + 6.5a)`. The outer strings sit `WIDE · (17.5 + 7a)` from the centre, the others evenly between, and all of them `2.8 + 1.6a` above the board.
  - inlays at 3, 5, 7, 9, 15, 17, 19 and 21, with a pair at 12, and only up to F. The headstock is tilted back 13°.
  - tuners: ⌈n/2⌉ on the upper side, the rest on the lower, with the outermost string's post nearest the nut on each side.
  - a dot's radius is 0.49 × the gap between strings at its fret. An open string's ring sits on the string, 12 mm past the nut.
  - pulse: 1.5× → 1× over 220 ms, ease-out.
  - vibration: `y(u, t) = A · sin(πu) · sin(2πf(t − onset))` with `A = amplitude(loudness) · e^(−(t − onset)/0.7) · fade`. `fade` goes 1 → 0 over the last 80 ms before dark. `f = 7 Hz · 2^((midi − 40)/24)`. `amplitude` runs linearly from 0.6 mm at loudness 0 to 3.2 mm at 1, and is 2.0 mm for `null`.
  - the blur spans `±(A · sin(πu) + radius)`, at 0.3 × emphasis opacity. Each vibrating string is a tube of 160 segments × 6 sides.
  - camera: perspective, 22° field of view. The 2D home pose frames the whole model with a 4% margin. The 3D home pose is the spike's, position (−560, −150, 390) and target (−110, 0, 0). A double-click ends 260 mm in front (2D) or 190 mm along the view (3D). Transitions take 700 ms, eased in and out. Distance stays within 35–1800 mm, and the target stays over the model.
  - panel: full width, aspect 2.8, height clamped to 260–460 px. One `localStorage` key, and a first visit gets 3D.
  - message fonts: 15 px system-ui. A chord is bold 32 px monospace. The halo is a `text-shadow` in the background colour.
  - canvas: `role="img"`, `aria-label="Guitar"`. No-WebGL text: "The guitar needs WebGL, which this browser has turned off."
  - loudness: a note joins its group when its onset is ≤ 50 ms after the previous note's. A group's window runs from its first onset to 50 ms after its last. Its level is the window's RMS in dB, relative to the 95th percentile of the song's group levels. −30…0 dB maps onto 0…1, clipped.
  - `Note.loudness` description: "How loud the note is, relative to the song's loud notes. Not confidence."
- **Running tests:** `uv run pytest <path>` for Python. `npm --prefix web test -- <path>` runs `tsc --noEmit` and then `vitest run <path>` inside `web/`, with paths relative to `web/`. While a module does not exist yet, `tsc` is what fails.
- **jsdom:** a test that needs the DOM begins with `// @vitest-environment jsdom`. Everything else runs on `node`.
- **Style:** TypeScript uses double quotes, semicolons and two-space indents, and `npm --prefix web run lint` is authoritative. Python follows `ruff`.
- End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

Inputs the spec implies but its test list never exercises, most likely first. Each one is pinned by a test in the task named.

1. **The camera settles, and its loop stops.** A camera move while paused must draw its own frames until the camera arrives, then stop. A loop that never stops burns a laptop's battery on every song page. One that never starts leaves the camera frozen until play. → Task 9: `draws its own frames while the camera moves, and stops once it arrives`.
2. **A panel with no size yet.** jsdom always has one, and so does a browser's first layout. An aspect of 0/0 is `NaN`, and a `NaN` camera draws nothing ever after. Expected: a finite pose, as if the panel had its CSS aspect. → Task 7: `stays finite before the panel is measured`.
3. **Storage that throws, or holds junk.** Private windows and blocked site data make `localStorage` throw, and an old build may have left another value. Expected: 3D, a working toggle, no error. → Task 9: `opens in 3D when the browser's storage throws, and still switches` and `ignores a stored view it does not know`.
4. **A note whose window runs past the stem's end.** A transcriber's onset can land in the last 50 ms, or a cached stem can be a hair shorter than the mix. Expected: that group reads silent (0.0), and the rest of the song is measured. A bad seek must not cost the whole song's loudness. → Task 2: `test_a_note_past_the_end_of_the_stem_reads_silent`.
5. **A stem silent under every note.** The reference level is then 0, and dB relative to 0 is undefined. Expected: the measurement fails, so every note is `None` at the default swing. Not a crash, and not every note at full swing. → Task 2: `test_a_stem_silent_under_every_note_cannot_be_measured`.

## File map

| Path | Responsibility | Task |
|---|---|---|
| `packages/core/src/guitarvis_core/tabdoc.py`, `contracts.py` | `loudness` on `Note`, `NoteEvent`, `TabNote` | 1 |
| `schema/tab-document.schema.json`, `web/src/types/tabDocument.ts` | regenerated | 1 |
| `apps/worker/src/guitarvis_worker/stages/fretboard.py` | the mapper copies `loudness` | 1 |
| `apps/worker/src/guitarvis_worker/loudness.py` | `measure_loudness(stem, events)` | 2 |
| `apps/worker/src/guitarvis_worker/pipeline.py` | measures after stage 2, logs a failure; copies `TabNote.loudness` to `Note` | 1, 2 |
| `apps/worker/tests/stem_fixture.py` | `write_stem`: a wav of plucks, for tests | 2 |
| `web/src/guitar/sounding.ts` | `sounding(song, cursors, t)`: lit notes and the message | 3 |
| `web/src/guitar/geometry.ts` | `geometryOf(song)`: every dimension and position | 4 |
| `web/src/guitar/vibration.ts` | `envelope`, `swing`, `displacement`, `amplitude`, `frequency` | 5 |
| `web/src/guitar/model.ts` | `buildModel(geometry, paintText)`: the scene graph; `VibratingString` | 6 |
| `web/src/guitar/camera.ts` | home and focus poses, the target clamp, easing | 7 |
| `web/src/guitar/notes.ts` | `NoteLayer`: dots and rings by key, with the pulse | 8 |
| `web/src/guitar/textures.ts` | canvas-painted dot and text textures; `readPalette` | 9 |
| `web/src/guitar/stage.ts` | `Stage`: renderer, camera, controls, frames, overlay | 9 |
| `web/src/guitar/Guitar.tsx` | the panel: canvas, toggle, reset, WebGL message | 9 |
| `web/src/styles.css` | `--guitar-*` tokens and `.guitar*` classes; `--fret-*` removed | 9, 10 |
| `web/src/player/Player.tsx`, `Player.test.tsx` | lazy `<Guitar>` above the tab strip | 10 |
| `web/src/views.test.ts` | the strip and `sounding()` pinned to one hidden-note rule | 3, 10 |
| `web/src/fretboard/` | deleted | 10 |
| `web/vite.config.ts` | the chunk-size warning limit | 10 |
| `docs/decisions/0009-procedural-guitar-model.md`, `docs/decisions/README.md`, parent spec, `docs/CONVENTIONS.md`, `CLAUDE.md`, `.claude/skills/pipeline-stage/SKILL.md` | the records | 2, 11 |
| `docs/specs/008-3d-guitar/acceptance.md` | the manual record | 11, 12 |

---

### Task 1: Loudness in the contract

A note's loudness travels from transcription to the document. Nothing measures it yet: every value is `None` until Task 2.

**Files:**
- Modify: `packages/core/src/guitarvis_core/tabdoc.py` (`Note`)
- Modify: `packages/core/src/guitarvis_core/contracts.py` (`NoteEvent`, `TabNote`)
- Modify: `apps/worker/src/guitarvis_worker/stages/fretboard.py:111-118` (the `TabNote(...)` in `assign`)
- Modify: `apps/worker/src/guitarvis_worker/pipeline.py` (the `Note(...)` in the invariant loop)
- Regenerate: `schema/tab-document.schema.json`, `web/src/types/tabDocument.ts`
- Test: `packages/core/tests/test_tabdoc.py`, `apps/worker/tests/test_fretboard_mapper.py`, `apps/worker/tests/test_pipeline.py`, `apps/worker/tests/test_caching.py`

**Interfaces:**
- Produces:
  - `Note.loudness: float | None = Field(default=None, ge=0, le=1, description="How loud the note is, relative to the song's loud notes. Not confidence.")`, declared after `confidence`.
  - `NoteEvent.loudness: float | None = None` and `TabNote.loudness: float | None = None`, each the **last** field, so the positional constructions in the eval tests still work. Each docstring gains one line: "`loudness` is measured from the stem after transcription (`guitarvis_worker.loudness`); it is not confidence."
  - Generated TypeScript: `Note.loudness?: number | null`, with the description as its doc comment.
- Not touched: eval's `LowestFretMapper`, which never carries loudness, because evaluation does not read it.

- [x] **Step 1: Write the failing tests**

In `packages/core/tests/test_tabdoc.py`:

```python
def test_loudness_is_optional() -> None:
    assert TabDocument.model_validate(load_fixture()).notes[0].loudness is None


def test_loudness_round_trips() -> None:
    raw = load_fixture()
    raw["notes"][0]["loudness"] = 0.42

    assert TabDocument.model_validate(raw).notes[0].loudness == 0.42


@pytest.mark.parametrize("value", [-0.1, 1.2])
def test_loudness_outside_zero_to_one_is_rejected(value: float) -> None:
    raw = load_fixture()
    raw["notes"][0]["loudness"] = value

    with pytest.raises(ValidationError):
        TabDocument.model_validate(raw)
```

In `apps/worker/tests/test_fretboard_mapper.py`:

```python
def test_loudness_travels_with_each_note() -> None:
    notes = [
        NoteEvent(onset=0.0, duration=0.5, midi=48, confidence=0.9, loudness=0.2),
        NoteEvent(onset=0.0, duration=0.5, midi=52, confidence=0.9, loudness=0.9),
        NoteEvent(onset=1.0, duration=0.5, midi=55, confidence=0.9),
    ]

    result = assign(notes)

    assert {tab.midi: tab.loudness for tab in result.notes} == {
        48: 0.2,
        52: 0.9,
        55: None,
    }
```

In `apps/worker/tests/test_pipeline.py`:

```python
def test_loudness_reaches_the_document(tmp_path: Path) -> None:
    doc = run(
        tmp_path,
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        mapper=StubMapper([TabNote(1.0, 0.5, 52, 2, 2, 0.8, loudness=0.4)]),
    )

    assert doc.notes[0].loudness == 0.4
```

In `apps/worker/tests/test_caching.py`:

```python
def test_a_transcription_cached_before_loudness_still_loads(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    old = [{"onset": 1.0, "duration": 0.5, "midi": 52, "confidence": 0.8}]
    blobs.put_bytes(KEYS.transcription, json.dumps(old).encode())
    inner = CountingTranscriber()

    events = CachedTranscriber(inner, blobs, KEYS).transcribe(tmp_path)

    assert events == EVENTS
    assert events[0].loudness is None
    assert inner.calls == 0
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/core/tests/test_tabdoc.py apps/worker/tests/test_fretboard_mapper.py apps/worker/tests/test_pipeline.py apps/worker/tests/test_caching.py`
Expected: FAIL. `test_loudness_is_optional` fails with `AttributeError`, the round-trip with `extra_forbidden`, and the others with `TypeError: ... unexpected keyword argument 'loudness'`.

- [x] **Step 3: Add the fields, and copy them along**

Add the three fields as the Interfaces block states. In the mapper's `TabNote(...)`, add `loudness=note.loudness`. In `run_pipeline`'s `Note(...)`, add `loudness=tab.loudness`.

- [x] **Step 4: Regenerate the contract artifacts**

Run: `make schema && git status --short schema web/src/types`
Expected: `schema/tab-document.schema.json` and `web/src/types/tabDocument.ts` modified, and nothing else. `api.schema.json` does not embed the tab document. The new TypeScript reads:

```typescript
  /**
   * How loud the note is, relative to the song's loud notes. Not confidence.
   */
  loudness?: number | null;
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages apps/worker apps/eval && npm --prefix web test -- src/types`
Expected: PASS. Evaluation's positional `TabNote(...)` and `NoteEvent(...)` calls are untouched and still pass, and so does the fixture contract test on both sides.

- [x] **Step 6: Commit**

```bash
git add packages/core/src/guitarvis_core/tabdoc.py packages/core/src/guitarvis_core/contracts.py \
  apps/worker/src/guitarvis_worker/stages/fretboard.py apps/worker/src/guitarvis_worker/pipeline.py \
  schema web/src/types packages/core/tests/test_tabdoc.py apps/worker/tests/test_fretboard_mapper.py \
  apps/worker/tests/test_pipeline.py apps/worker/tests/test_caching.py
git commit -m "feat: carry each note's loudness from transcription to the document

Note gains an optional loudness in [0, 1], and NoteEvent and TabNote
carry it there. Additive, so SCHEMA_VERSION stays 1, though a client
validating raw JSON against a bundled v1 schema would reject it.
Transcription entries cached before this load with loudness None.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Measuring loudness from the stem

The worker measures each strum's level from the guitar stem, between transcription and the mapper. A stem it cannot read costs only the swing's size.

**Files:**
- Create: `apps/worker/src/guitarvis_worker/loudness.py`, `apps/worker/tests/test_loudness.py`, `apps/worker/tests/stem_fixture.py`
- Modify: `apps/worker/src/guitarvis_worker/pipeline.py` (a module logger, and the call after stage 2)
- Modify: `apps/worker/tests/test_pipeline.py`
- Modify: `.claude/skills/pipeline-stage/SKILL.md` and `docs/specs/001-guitarvis-design/spec.md:313-320` (the degradation tables)

**Interfaces:**
- Consumes: `NoteEvent.loudness` (Task 1).
- Produces, from `guitarvis_worker.loudness`:
  - `STRUM_WINDOW_SEC = 0.05`, with a comment saying it restates the mapper's `VOICING_WINDOW_SEC` because a helper may not import a stage. Also `FLOOR_DB = -30.0` and `REFERENCE_PERCENTILE = 0.95`.
  - `measure_loudness(stem_path: Path, events: Sequence[NoteEvent]) -> list[NoteEvent]`. It returns the events in their given order, each a `dataclasses.replace` with `loudness` set and rounded to 3 places. With no events it returns `[]` without opening the file. When the stem cannot be measured it raises, with whatever `wave` and the file system raise (`EOFError`, `wave.Error`, `OSError`), or with `ValueError` for a sample width other than 16-bit or a reference level of 0.
- From `apps/worker/tests/stem_fixture.py`: `write_stem(path: Path, plucks: Sequence[tuple[float, float, int]], *, seconds: float = 4.0, rate: int = 8000, channels: int = 2) -> Path`. It writes a 16-bit wav of silence plus square-wave plucks, each `(onset, length, amplitude)`. A square wave's RMS is its amplitude. Other tests import it as `from stem_fixture import write_stem`, as eval's tests import `guitarset_fixture`.

- [x] **Step 1: Write the fixture and the failing tests**

`write_stem` fills an `array.array("h")` of zeros, `int(seconds * rate) * channels` long. For each pluck, every frame from `int(onset * rate)` up to `min(int((onset + length) * rate), the frame count)` gets `+amplitude` on even frames and `-amplitude` on odd ones, in every channel. It writes the array with `wave` at sample width 2.

Create `apps/worker/tests/test_loudness.py`:

```python
"""Loudness from the stem: a stdlib measurement, so no audio stack needed."""

import wave
from dataclasses import replace
from pathlib import Path

import pytest
from guitarvis_core.contracts import NoteEvent
from guitarvis_worker.loudness import measure_loudness
from stem_fixture import write_stem


def event(onset: float, midi: int = 52) -> NoteEvent:
    return NoteEvent(onset=onset, duration=0.3, midi=midi, confidence=0.9)


def test_a_loud_pluck_reads_louder_than_a_quiet_one(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(1.0, 0.3, 16000), (2.0, 0.3, 2000)])

    loud, quiet = measure_loudness(stem, [event(1.0), event(2.0)])

    assert loud.loudness == 1.0
    # 2000 / 16000 is -18.06 dB, so (30 - 18.06) / 30.
    assert quiet.loudness == pytest.approx(0.398, abs=0.001)


def test_a_strums_notes_share_one_level(tmp_path: Path) -> None:
    # Quiet under the first string, loud from the third: measured note by
    # note, the later strings would read louder.
    stem = write_stem(
        tmp_path / "stem.wav",
        [(1.0, 0.04, 1000), (1.04, 0.3, 16000), (3.0, 0.3, 16000)],
    )

    measured = measure_loudness(
        stem, [event(1.0, 40), event(1.02, 45), event(1.04, 50), event(3.0)]
    )

    assert measured[0].loudness == measured[1].loudness == measured[2].loudness
    assert measured[0].loudness < measured[3].loudness


def test_notes_more_than_50ms_apart_are_measured_apart(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(1.0, 0.1, 2000), (1.1, 0.3, 16000)])

    first, second = measure_loudness(stem, [event(1.0), event(1.1)])

    assert first.loudness < second.loudness


def test_the_notes_come_back_in_order_with_nothing_else_changed(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(1.0, 0.3, 16000), (2.0, 0.3, 2000)])
    events = [event(2.0, 60), event(1.0, 40)]

    measured = measure_loudness(stem, events)

    assert [replace(m, loudness=None) for m in measured] == events
    assert measured[0].loudness < measured[1].loudness


def test_a_note_past_the_end_of_the_stem_reads_silent(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(1.0, 0.3, 16000)], seconds=2.0)

    inside, past = measure_loudness(stem, [event(1.0), event(5.0)])

    assert (inside.loudness, past.loudness) == (1.0, 0.0)


def test_a_stem_silent_under_every_note_cannot_be_measured(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(3.0, 0.5, 16000)])

    with pytest.raises(ValueError):
        measure_loudness(stem, [event(1.0), event(2.0)])


def test_an_unreadable_stem_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")

    with pytest.raises((EOFError, wave.Error)):
        measure_loudness(empty, [event(1.0)])


def test_a_stem_that_is_not_16_bit_raises(tmp_path: Path) -> None:
    stem = tmp_path / "24bit.wav"
    with wave.open(str(stem), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(3)
        handle.setframerate(8000)
        handle.writeframes(b"\0" * 3 * 8000)

    with pytest.raises(ValueError):
        measure_loudness(stem, [event(0.5)])


def test_no_notes_need_no_stem(tmp_path: Path) -> None:
    assert measure_loudness(tmp_path / "missing.wav", []) == []
```

In `apps/worker/tests/test_pipeline.py`, add `import logging`, `from stem_fixture import write_stem` and `from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper`, then:

```python
def test_loudness_is_measured_from_the_stem(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "song.wav", [(1.0, 0.3, 16000)])

    result = run_pipeline(
        IngestedAudio(path=stem, title="song", duration_sec=4.0),
        separator=StubSeparator(),  # returns the input as the stem
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        analyzer=StubAnalyzer(),
        mapper=ViterbiFretboardMapper(),
    )

    assert [note.loudness for note in result.document.notes] == [1.0]


def test_an_unreadable_stem_costs_loudness_and_nothing_else(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="guitarvis_worker.pipeline"):
        doc = run(  # audio() writes an empty file, which is no wav
            tmp_path,
            transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
            mapper=ViterbiFretboardMapper(),
        )

    assert [note.loudness for note in doc.notes] == [None]
    assert doc.warnings == []
    assert "loudness" in caplog.text
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest apps/worker/tests/test_loudness.py apps/worker/tests/test_pipeline.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'guitarvis_worker.loudness'`.

- [x] **Step 3: Write `measure_loudness` in `apps/worker/src/guitarvis_worker/loudness.py`**

The module docstring says why loudness is measured here and is not confidence. Point it at spec 008's *Loudness*. The algorithm:

1. **Groups.** Walk the event indices sorted by onset (a stable sort). A note joins the current group when its onset minus the *previous note's* onset is ≤ `STRUM_WINDOW_SEC`. This chains, as the spec says, where the mapper anchors to a group's first note.
2. **Levels.** Each group's window runs from its first onset to its last onset + `STRUM_WINDOW_SEC`. Convert it to frames with `int(seconds * rate)`, and clamp both ends to `[0, nframes]`. Read it with `setpos` and `readframes` from one open `wave` handle. Its level is the RMS of every sample, all channels together, using `array.array("h")` as `measure_rms` does. An empty window reads 0. Refuse a sample width other than 2 with `ValueError`, as `measure_rms` does.
3. **Reference.** Take the nearest-rank 95th percentile of the group levels: `sorted(levels)[math.ceil(REFERENCE_PERCENTILE * len(levels)) - 1]`. Not `statistics.quantiles`, which on Python 3.12 refuses a single value. A reference of 0 raises `ValueError("the stem is silent under every note")`.
4. **Loudness.** `min(1, max(0, (20 * log10(level / reference) - FLOOR_DB) / -FLOOR_DB))`, and 0.0 for a level of 0. Round to 3 places.

- [x] **Step 4: Call it from `run_pipeline`**

Import `logging` and `from guitarvis_worker.loudness import measure_loudness`, and add `log = logging.getLogger(__name__)` below the imports. After stage 2's `try/except/else`, and before stage 3:

```python
# Loudness, for how far the guitar's strings swing. Not a stage: it reads
# the stem stage 1 left, so any transcriber gets it. Its failure costs
# only the size of the swing, so it is logged, not warned about: the
# document's warnings say whether the tab can be trusted, and this does
# not touch the tab.
if events:
    try:
        events = measure_loudness(separation.stem_path, events)
    except Exception:  # degrade, as every stage after separation does
        log.warning(
            "could not measure loudness from %s; strings will swing at the default",
            separation.stem_path,
            exc_info=True,
        )
```

`transcribed_note_count=len(events)` is unchanged, since measuring neither adds nor drops a note.

- [x] **Step 5: Add the degradation row to both tables**

In `.claude/skills/pipeline-stage/SKILL.md`'s *Degrade, do not fail* table and the parent spec's table (lines 313–320), after the *Fretboard mapper raises* row:

```markdown
| Loudness cannot be measured from the stem | Every note's `loudness` is null, and strings swing at the default amplitude; the worker logs it, and the document carries no warning |
```

- [x] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest apps/worker && uv run ruff check apps/worker && uv run mypy apps/worker/src apps/worker/tests`
Expected: PASS, and both linters clean. Every older pipeline test now logs a loudness warning, since `audio()` writes an empty file. They still pass, because none of them asserts on the log.

- [x] **Step 7: Commit**

```bash
git add apps/worker/src/guitarvis_worker/loudness.py apps/worker/src/guitarvis_worker/pipeline.py \
  apps/worker/tests/test_loudness.py apps/worker/tests/stem_fixture.py apps/worker/tests/test_pipeline.py \
  .claude/skills/pipeline-stage/SKILL.md docs/specs/001-guitarvis-design/spec.md
git commit -m "feat(worker): measure each strum's loudness from the stem

Notes within 50 ms of the previous one share a window, so a strum's
later strings do not read louder for the earlier ones still ringing.
RMS in dB against the song's 95th-percentile group, -30..0 dB onto
0..1. Stdlib only. A stem it cannot read leaves loudness None and is
logged; the job carries on and the document gets no warning.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: What sounds

The deciding half of 007's `fretboard/layout.ts` moves to `guitar/sounding.ts`, unchanged, and the pixels stay behind. `fretboard/` keeps working until Task 10 deletes it.

**Files:**
- Create: `web/src/guitar/sounding.ts`, `web/src/guitar/sounding.test.ts`
- Modify: `web/src/views.test.ts` (a third case; Task 10 removes the fretboard's)

**Interfaces:**
- Consumes: `Song`, `buildSong` (`song.ts`); `emphasis`, `isHidden`, `CHORD_THRESHOLDS` (`confidence.ts`); `EMPTY_MESSAGE`, `UNCLEAR_LABEL`, `noteName` (`labels.ts`); `NoteCursor`, `inWindow` (`playback/cursor.ts`). All exist.
- Produces, from `web/src/guitar/sounding.ts`:
  - `MIN_LIT = 0.15`, `interface Cursors`, `cursorsOf(song: Song): Cursors`, `litUntil(notes: readonly Note[]): Map<Note, number>`, all as in `fretboard/layout.ts`.
  - `interface SoundingNote { key: string; string: number; fret: number; midi: number; name: string; opacity: number; onset: number; until: number; loudness: number | null }`. `key` is `` `dot:${note.id}` ``, `until` is when it goes dark (from `cursors.until`), and `loudness` is `note.loudness ?? null`.
  - `interface Message { text: string; chord: boolean; opacity: number }`.
  - `interface Sounding { notes: SoundingNote[]; message: Message | null }`.
  - `sounding(song: Song, cursors: Cursors, now: number): Sounding`. `notes` holds at most one entry per string. A note on a string outside `song.tuning`, or with a negative fret, is skipped.

- [x] **Step 1: Write the failing tests**

Port `web/src/fretboard/layout.test.ts` to `web/src/guitar/sounding.test.ts` one test for one, keeping every name and timing assertion. Drop `neckOf`, `DOT_R` and `WIDTH`. The `board(song)` helper becomes:

```typescript
function board(song: Song) {
  const cursors = cursorsOf(song);
  const at = (now: number) => sounding(song, cursors, now);
  return {
    at,
    notes: (now: number) => at(now).notes,
    message: (now: number) => at(now).message,
  };
}
```

`fretboard.dots(t)` becomes `fretboard.notes(t)`. Tests that compared whole outputs with `toEqual([])` now compare `notes` with `[]`, or the whole `Sounding` with `{ notes: [], message: null }`. The changed assertions:

| Test | Becomes |
|---|---|
| lights a note across [t, t + dur], at its string and fret, named by pitch | `toMatchObject({ string: 2, fret: 2, name: "E", onset: 1, until: 1.5 })` |
| draws an open string in the column left of the nut | renamed `lights an open string as fret 0`: `notes(1)[0].fret === 0` |
| does not light a long note again after a shorter one on its string has ended it | adds `expect(fretboard.notes(0.5)[0].until).toBe(1)` |
| skips a note on a string or fret the neck does not have | `expect(fretboard.at(1)).toEqual({ notes: [], message: null })` |
| draws nothing for a note until it sounds | `at(t)` → `{ notes: [], message: null }`; at 2, one note |
| centres the message on the fingerboard | dropped: the overlay centres it in CSS |
| draws the minimal fixture | `notes(0.1)` equals `[expect.objectContaining({ key: "dot:n_0000", name: "E", string: 0, fret: 0 })]` |
| shows the message, and nothing else, for a document with no notes | `toEqual({ notes: [], message: { text: EMPTY_MESSAGE, chord: false, opacity: 1 } })` |

The message tests assert on `message(t)` with the same objects, minus `x` and `y`. Add:

```typescript
describe("loudness", () => {
  it("passes a note's loudness through", () => {
    expect(boardOf([note(1, { loudness: 0.7 })]).notes(1)[0].loudness).toBe(0.7);
  });

  it("gives null for a note without one, as in every document made before it", () => {
    expect(boardOf([note(1)]).notes(1)[0].loudness).toBeNull();
  });
});
```

In `web/src/views.test.ts`, import `{ cursorsOf as soundingCursors, sounding } from "./guitar/sounding"` and add:

```typescript
  it("sounding() lights every note that isHidden leaves shown, and no other", () => {
    const cursors = soundingCursors(song);
    const lit = new Set<string>();

    for (const now of [...song.notes.map((n) => n.t), ...grid]) {
      for (const note of sounding(song, cursors, now).notes) lit.add(note.key);
    }

    expect([...lit].sort()).toEqual(song.notes.filter(shown).map((n) => `dot:${n.id}`).sort());
  });
```

- [x] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/guitar/sounding.test.ts src/views.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './sounding'`.

- [x] **Step 3: Write `sounding.ts`**

Copy `MIN_LIT`, `Cursors`, `cursorsOf` and `litUntil` from `fretboard/layout.ts` verbatim. `sounding()` is `layout()`'s body with three changes:
- the neck lookups become the skip rule: `note.string < 0 || note.string >= song.tuning.length || note.fret < 0`;
- a lit note becomes a `SoundingNote`, using the `until` that `layout` already computes;
- `message(...)` returns a `Message`, without coordinates.

Keep `layout`'s comments on the window and on reading the passages back to the earliest onset. The module comment says this decides *what* sounds, and that what is coming is the tab strip's to show.

- [x] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/guitar/sounding.test.ts src/views.test.ts`
Expected: PASS. Ported one for one, that is 22 tests in `sounding.test.ts` and 4 in `views.test.ts`.

- [x] **Step 5: Commit**

```bash
git add web/src/guitar/sounding.ts web/src/guitar/sounding.test.ts web/src/views.test.ts
git commit -m "feat(web): decide what sounds, without pixels, for the guitar

007's note-selection rules, unchanged: MIN_LIT, the latest onset per
string, emphasis, hidden passages and their message. Each lit note
carries its onset, when it goes dark, and its loudness, for the
vibration. Pinned to isHidden with the tab strip in views.test.ts.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The model's geometry

Every dimension and position on the guitar, in millimetres, as a pure function of the song. This holds the spike's numbers and the spec's rules, with no three.js.

**Files:**
- Create: `web/src/guitar/geometry.ts`, `web/src/guitar/geometry.test.ts`

**Interfaces:**
- Consumes: `Song`, `buildSong`; `stringLabels` (`labels.ts`).
- Produces, from `web/src/guitar/geometry.ts`:
  - `SCALE = 650`, `WIDE = 1.7`, `MIN_FRETS = 20`, `BOARD_TAIL = 10`, `OPEN_X = 12`, `DOT_FILL = 0.49`, `LIFT = 1` (mm a mark sits above its string), `INLAY_FRETS = [3, 5, 7, 9, 12, 15, 17, 19, 21]`, `HEAD_TILT_DEG = 13`, `HEAD_ORIGIN: Vec3 = { x: 5, y: 0, z: -3.5 }`, `HEAD_LENGTH = 192`, `HEAD_DEPTH = 14.2` (the outline's far end and the head's back, with its bevel), `GAUGES = [0.62, 0.52, 0.43, 0.36, 0.3, 0.26]` (string radii, lowest of six first), `REACH = WIDE * 64 + 7` (the tuner buttons' outer edge).
  - `interface Vec3 { x: number; y: number; z: number }` and `interface Box { min: Vec3; max: Vec3 }`. Both are plain objects, which three's `Vector3.copy` accepts as `Vector3Like`.
  - `interface Tuner { string: number; side: 1 | -1; post: Vec3; top: Vec3 }`. `post` is head-local, on the face. `top` is the post's top in world coordinates.
  - `interface Mark { at: Vec3; r: number; open: boolean }`.
  - `interface Geometry { frets; strings; labels: string[]; wireX: number[]; boardEnd: number; along(x): number; halfWidth(x): number; stringY(string, x): number; stringZ(x): number; noteX(fret): number; mark(string, fret): Mark; inlays: Vec3[]; tuners: Tuner[]; gauges: number[]; wound: boolean[]; headToWorld(p: Vec3): Vec3; bounds: Box }`. `frets` is F. `wireX` has F + 1 entries, the nut first. `tuners`, `gauges` and `wound` are indexed by string.
  - `geometryOf(song: Song): Geometry`.

The rules the signatures do not fix:
- `along(x) = clamp(x / boardEnd, 0, 1)`. `stringY(s, x) = spread(x) · (1 − 2s / (n − 1))`, where `spread = WIDE · (17.5 + 7a)`, and 0 when n = 1. `gap(x) = 2 · spread(x) / max(1, n − 1)`.
- `noteX(f)` is the midpoint of wires f − 1 and f, and `OPEN_X` for f = 0.
- `mark(s, f)` for f ≥ 1 is at `(noteX(f), stringY(s, x), stringZ(x) + LIFT)` with `r = DOT_FILL · gap(x)`. For f = 0, it is the point at x = `OPEN_X` on the straight line from the nut, `(0, stringY(s, 0), stringZ(0))`, to `tuners[s].top`, plus `LIFT` in z, with `r = DOT_FILL · gap(0)` and `open: true`.
- `headToWorld(p) = HEAD_ORIGIN + (p.x·cos θ + p.z·sin θ, p.y, −p.x·sin θ + p.z·cos θ)`, with θ = 13°. This is three's `rotation.y`, as the spike sets it, so the head tilts back.
- Tuners: strings 0 … ⌈n/2⌉ − 1 go on side 1 (+y) and the rest on side −1. On a side with m posts, the i-th from the nut is at head-local x = `50 + 96 · i / (m − 1)` (50 when m = 1), y = `side · WIDE · 33`, z = 0. Side 1 runs string 0 first; side −1 runs string n − 1 first. `top = headToWorld({ x, y, z: 10.5 })`. For six strings that gives the spike's 50, 98 and 146.
- `gauges`: count from the highest string, giving it 0.26, the next 0.3, and so on up `GAUGES`. A string below the sixth from the top repeats 0.62. `wound[s] = s < n / 2`.
- Inlays: for each `f` in `INLAY_FRETS` with f ≤ F, at `(noteX(f), 0, 0.05)`. Fret 12 gives two, at y = ±0.6 · spread.
- `bounds`: `min = (boardEnd, −REACH, headToWorld({x: HEAD_LENGTH, y: 0, z: −HEAD_DEPTH}).z)` and `max = (headToWorld({x: HEAD_LENGTH, y: 0, z: 0}).x, REACH, stringZ(boardEnd) + LIFT)`.

- [x] **Step 1: Write the failing tests**

Create `web/src/guitar/geometry.test.ts`. Its helpers follow `fretboard/neck.test.ts`: `note(fret)`, `doc(fields)`, and `songWith(frets: number[], tuning = STANDARD)`, which builds a song from those frets. `const g = geometryOf(songWith([0, 5]))`. The tests:

```typescript
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
```

- [x] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/guitar/geometry.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './geometry'`.

- [x] **Step 3: Write `geometryOf` by the rules above**

F is `Math.max(MIN_FRETS, ...song.notes.map((n) => n.fret))`, ignoring negative frets. `labels` is `stringLabels(song.tuning)`. The module comment says: dimensions in mm, axes as in the spec's *The model*, and [spike.html](spike.html) as the reference for every number.

- [x] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/guitar/geometry.test.ts`
Expected: PASS, 15 tests.

- [x] **Step 5: Commit**

```bash
git add web/src/guitar/geometry.ts web/src/guitar/geometry.test.ts
git commit -m "feat(web): lay out the guitar's neck in millimetres

A 650 mm scale with at least twenty frets, 1.7 times wide, the lowest
string on top, a headstock tilted back 13 degrees with 3 + 3 tuners.
Dots fill 0.49 of the gap between strings; an open string's ring sits
on the string, 12 mm past the nut. Pure, so every rule is tested.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: How a string moves

The vibration as pure functions of the note and song time.

**Files:**
- Create: `web/src/guitar/vibration.ts`, `web/src/guitar/vibration.test.ts`

**Interfaces:**
- Consumes: `SoundingNote` (Task 3).
- Produces, from `web/src/guitar/vibration.ts`:
  - `DECAY_SEC = 0.7`, `FADE_SEC = 0.08`, `BASE_HZ = 7`, `QUIET_MM = 0.6`, `LOUD_MM = 3.2`, `UNKNOWN_MM = 2.0`, `BLUR_OPACITY = 0.3`, and `STILL_MM = 0.05` (below this, a string is drawn still).
  - `type Plucked = Pick<SoundingNote, "onset" | "until" | "midi" | "loudness">`.
  - `amplitude(loudness: number | null): number`. Linear from `QUIET_MM` to `LOUD_MM`, with loudness clamped to [0, 1]; `UNKNOWN_MM` for `null`.
  - `frequency(midi: number): number`, which is `BASE_HZ · 2^((midi − 40) / 24)`.
  - `profile(u: number): number`, which is `sin(πu)`.
  - `envelope(note: Plucked, t: number): number`, the spec's A. It is 0 for t < onset or t ≥ until. The fade is `clamp((until − t) / FADE_SEC, 0, 1)`.
  - `swing(note: Plucked, t: number): number`, which is `sin(2π · frequency(midi) · (t − onset))`.
  - `displacement(note: Plucked, t: number, u: number): number`, which is `envelope · profile(u) · swing`.

- [x] **Step 1: Write the failing tests**

```typescript
import { describe, expect, it } from "vitest";

import { amplitude, displacement, envelope, frequency, swing, type Plucked } from "./vibration";

const plucked = (fields: Partial<Plucked> = {}): Plucked => ({ onset: 1, until: 3, midi: 40, loudness: 0.5, ...fields });
const times = Array.from({ length: 200 }, (_, i) => 1 + i / 100);

describe("the shape along the string", () => {
  it("is still at the nut and at the fingerboard's end", () => {
    for (const t of times) {
      expect(displacement(plucked(), t, 0)).toBe(0);
      expect(Math.abs(displacement(plucked(), t, 1))).toBeLessThan(1e-12);
    }
  });

  it("is widest mid-string", () => {
    const middle = Math.abs(displacement(plucked(), 1.03, 0.5));
    for (let u = 0; u <= 1; u += 0.05) expect(Math.abs(displacement(plucked(), 1.03, u))).toBeLessThanOrEqual(middle);
  });
});

describe("over time", () => {
  it("dies away", () => {
    const note = plucked();
    expect(envelope(note, 1.1)).toBeGreaterThan(envelope(note, 1.5));
    expect(envelope(note, 1.5)).toBeGreaterThan(envelope(note, 2.5));
  });

  it("comes to rest over the last 80 ms, and is still once the note is dark", () => {
    const note = plucked();
    const unfaded = amplitude(0.5) * Math.exp(-(2.96 - 1) / 0.7);
    expect(envelope(note, 2.96)).toBeCloseTo(unfaded / 2, 9);
    expect(envelope(note, 3)).toBe(0);
    expect(envelope(note, 4)).toBe(0);
    expect(envelope(note, 0.5)).toBe(0);
  });

  it("starts each pluck from rest", () => {
    expect(swing(plucked({ onset: 2.25 }), 2.25)).toBe(0);
  });
});

describe("loudness and pitch", () => {
  it("swings a louder note wider: 0.6 mm at 0, 3.2 mm at 1", () => {
    expect([amplitude(0), amplitude(0.5), amplitude(1), amplitude(2)]).toEqual([0.6, 1.9, 3.2, 3.2]);
    expect(envelope(plucked({ loudness: 1 }), 1.2)).toBeGreaterThan(envelope(plucked({ loudness: 0.1 }), 1.2));
  });

  it("swings a note without loudness 2 mm", () => {
    expect(amplitude(null)).toBe(2);
  });

  it("wobbles a higher note faster: 7 Hz for the low E, 14 Hz two octaves up", () => {
    expect(frequency(40)).toBe(7);
    expect(frequency(64)).toBeCloseTo(14, 9);
    expect(frequency(52)).toBeGreaterThan(frequency(40));
  });
});
```

`toEqual` on `amplitude(0.5)` relies on 0.6 + 0.5 × 2.6 being exactly 1.9 in floating point. If it is not, use `toBeCloseTo` for that one value.

- [x] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/guitar/vibration.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './vibration'`.

- [x] **Step 3: Write the module by the Interfaces block**

The module comment says the motion is drawn slowed down, because a real string moves too fast to see. It also says time is song time, so a pause freezes the string.

- [x] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/guitar/vibration.test.ts`
Expected: PASS, 8 tests.

- [x] **Step 5: Commit**

```bash
git add web/src/guitar/vibration.ts web/src/guitar/vibration.test.ts
git commit -m "feat(web): shape a sounding string's swing by its loudness

Half a sine along the string, decaying over 0.7 s and coming to rest
over the last 80 ms. 0.6 to 3.2 mm by loudness, 2 mm without one. A
7 Hz wobble for the low E, faster for higher notes, in song time.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: three.js, and the model

The scene graph, built from a `Geometry`. It is ported from the spike, and it runs on `node`, because nothing in it needs WebGL. Text textures are injected.

**Files:**
- Modify: `web/package.json`, `web/package-lock.json`
- Create: `web/src/guitar/model.ts`, `web/src/guitar/model.test.ts`

**Interfaces:**
- Consumes: `Geometry`, `Vec3` (Task 4); `profile`, `STILL_MM`, `BLUR_OPACITY` (Task 5).
- Produces, from `web/src/guitar/model.ts`:
  - `type TextPainter = (text: string, colour: string) => { texture: Texture; aspect: number }`, where `aspect` is width over height.
  - `SEGMENTS = 160`, `SIDES = 6`, `LABEL_MM = 9`, `NUMBER_MM = 7`, `NUMBER_GAP = 5`, `LABEL_PAST_POST = 11`, `LABEL_COLOUR = "#f4efe2"`, and `NUMBER_COLOUR = "#8a8478"`, a grey readable on both themes' backgrounds. The sizes are starting points for the acceptance run.
  - `class VibratingString { readonly tube: Mesh; readonly blur: Mesh; constructor(nut: Vec3, end: Vec3, radius: number, material: Material, blurColour: number); shape(amplitude: number, swing: number, opacity: number): void }`. `u` runs from 0 at `nut` to 1 at `end`. `shape` moves ring i's centre by `amplitude · profile(i / SEGMENTS) · swing` in y. It sets the blur's half-width to `amplitude · profile(u) + radius`, makes the blur visible only when `amplitude > STILL_MM`, and sets its opacity to `BLUR_OPACITY · opacity`. When `amplitude` is 0 and the string is already still, it returns without touching a buffer.
  - `interface Model { root: Group; pickable: Object3D[]; strings: VibratingString[]; dispose(): void }`. `pickable` is the fingerboard and the neck's back. `strings` is indexed by string.
  - `buildModel(g: Geometry, paintText: TextPainter): Model`.
  - Object names, which the tests use: `board`, `neck`, `nut`, `wire`, `inlay`, `headstock` (a Group), `tuner` (a Group per string), `string` (the tube), `string-blur`, `string-head`, `label`, and `fret-number`.

- [x] **Step 1: Add three**

```bash
npm --prefix web install three@^0.186.1
npm --prefix web install --save-dev @types/three@^0.186.0
```

Check: `git diff web/package.json` shows `three` under `dependencies` and `@types/three` under `devDependencies`, and nothing else.

- [x] **Step 2: Write the failing tests**

```typescript
import { BufferGeometry, Material, Mesh, Texture } from "three";
// ...
const blank: TextPainter = () => ({ texture: new Texture(), aspect: 1 });
const named = (model: Model, name: string) => model.root.getObjectsByProperty("name", name);
const SEVEN = ["B1", "E2", "A2", "D3", "G3", "B3", "E4"];

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
```

`songWith` and `STANDARD` are as in `geometry.test.ts`. Copy them in, since a test file does not import another.

- [x] **Step 3: Run them to verify they fail**

Run: `npm --prefix web test -- src/guitar/model.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './model'`.

- [x] **Step 4: Port the spike into `buildModel`**

Port [spike.html](spike.html) lines 88–243 (the lights, materials, board, neck back, frets, nut, inlays, headstock and tuners, and strings), with these substitutions:

| Spike | Here |
|---|---|
| `wire(n)`, `LAST_WIRE` | `g.wireX[n]`, `g.frets` |
| `BOARD_END`, `LEN` | `g.boardEnd`, `-g.boardEnd` |
| `halfWidth`, `stringY(s, x)`, `stringZ` | `g.halfWidth`, `g.stringY`, `g.stringZ` |
| the inlay loop | one `CircleGeometry(3.6, 32)` mesh per `g.inlays` point |
| the head group's position and `rotation.y` | `HEAD_ORIGIN` and `HEAD_TILT_DEG`, imported from `geometry.ts` |
| the `[s, x, side]` tuner table | `g.tuners`: a `tuner` Group per string, its bushing, post, shaft and button at `tuner.post` |
| `postTop[s]` | `g.tuners[s].top`, already in world coordinates |
| `GAUGE`, `s < 3`, `COLOURS` | `g.gauges`, `g.wound[s]`, the wound or plain colour |
| the tube, ribbon and `shapeString` | `VibratingString`, from the nut `(0, stringY(s, 0), stringZ(0))` to the end `(boardEnd, …)`; its rest shape is set in the constructor by `shape`'s own loop at amplitude 0 |
| the static rod over the headstock | a `string-head` mesh from the nut to `g.tuners[s].top` |

Then add what the spike lacks:
- **Labels.** In the head group, one plane per string: `LABEL_MM` tall and `LABEL_MM · aspect` wide, textured with `paintText(g.labels[s], LABEL_COLOUR)`. It sits at `(post.x + LABEL_PAST_POST, post.y, 1.5)`, facing +z.
- **Fret numbers.** In the root, one plane per fret 1 … F: `NUMBER_MM` tall, centred at `(g.noteX(n), −(g.halfWidth(x) + NUMBER_GAP + NUMBER_MM / 2), 0)`, textured with `paintText(String(n), NUMBER_COLOUR)`.
- **Text materials:** `MeshBasicMaterial({ map, transparent: true, depthWrite: false })`.
- **`dispose()`** traverses `root` and disposes every mesh's geometry and material, plus every texture `paintText` returned.

- [x] **Step 5: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/guitar/model.test.ts && npm --prefix web run lint`
Expected: PASS, 6 tests, and lint clean.

- [x] **Step 6: Commit**

```bash
git add web/package.json web/package-lock.json web/src/guitar/model.ts web/src/guitar/model.test.ts
git commit -m "feat(web): build the guitar's neck and headstock in three.js

After the spike: rosewood board, maple neck, nickel frets, bone nut,
a dark headstock tilted back with 3 + 3 tuners, wound and plain
strings. Each string over the board is a tube that bends in place,
with a blur for the eye. String labels at the tuners, fret numbers
under the neck. Builds on node; only the renderer needs WebGL.

Adds three@0.186 and @types/three.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The camera's poses

Home poses, double-click focus, the pan clamp and the easing, as pure functions. Three's math types appear only in the test.

**Files:**
- Create: `web/src/guitar/camera.ts`, `web/src/guitar/camera.test.ts`

**Interfaces:**
- Consumes: `Geometry`, `Vec3`, `geometryOf` (Task 4).
- Produces, from `web/src/guitar/camera.ts`:
  - `type View = "2d" | "3d"`, `interface Pose { position: Vec3; target: Vec3 }`.
  - `FOV = 22`, `NEAR = 1`, `FAR = 6000`, `MARGIN = 0.04`, `MIN_DISTANCE = 35`, `MAX_DISTANCE = 1800`, `FOCUS_MM: Record<View, number> = { "2d": 260, "3d": 190 }`, `TRANSITION_MS = 700`, `PANEL_ASPECT = 2.8` (with a comment pointing at `.guitar` in `styles.css`), and `HOME_3D: Pose`, the spike's (−560, −150, 390) → (−110, 0, 0).
  - `homePose(view: View, g: Geometry, aspect: number): Pose`. For 3D it returns `HOME_3D`. For 2D it centres on `g.bounds` in x and y, at z = 0. It sets the camera at `+z` by `max(halfWidth / (tan(FOV/2) · aspect), halfHeight / tan(FOV/2)) · (1 + MARGIN)`. An aspect that is not a positive finite number is read as `PANEL_ASPECT`.
  - `focusPose(view: View, hit: Vec3, current: Pose, g: Geometry): Pose`. The target is `hit` moved onto the fingerboard: x clamped to `[g.boardEnd, 0]`, then |y| ≤ `g.halfWidth(x)`, and z = 0. The position is the target plus `FOCUS_MM[view]` along `(0, 0, 1)` in 2D, or along `current.position − current.target`, normalised, in 3D. A zero-length view direction falls back to `(0, 0, 1)`.
  - `clampTarget(target: Vec3, g: Geometry): Vec3`, each coordinate clamped into `g.bounds`.
  - `easeInOut(k: number): number`, the spike's: `k < 0.5 ? 2k² : 1 − (−2k + 2)² / 2`.
  - `between(a: Pose, b: Pose, k: number): Pose`, linear in both points.

- [x] **Step 1: Write the failing tests**

```typescript
import { PerspectiveCamera, Vector3 } from "three";
// ...
const g = geometryOf(buildSong(doc()));

/** Where `p` lands on screen, in normalised device coordinates. */
function project(pose: Pose, aspect: number, p: Vec3): Vector3 {
  const camera = new PerspectiveCamera(FOV, aspect, NEAR, FAR);
  camera.position.copy(pose.position);
  camera.lookAt(pose.target.x, pose.target.y, pose.target.z);
  camera.updateMatrixWorld();
  return new Vector3(p.x, p.y, p.z).project(camera);
}

const corners = (z: number) =>
  [g.bounds.min, g.bounds.max].flatMap((a) => [g.bounds.min, g.bounds.max].map((b) => ({ x: a.x, y: b.y, z })));

it("frames the whole model in 2D, edge to edge, at wide and narrow aspects", () => {
  for (const aspect of [1.4, 2.8, 4]) {
    const pose = homePose("2d", g, aspect);
    const front = corners(0).map((c) => project(pose, aspect, c));
    for (const p of [...front, ...corners(g.bounds.min.z).map((c) => project(pose, aspect, c))]) {
      expect(Math.abs(p.x)).toBeLessThanOrEqual(1);
      expect(Math.abs(p.y)).toBeLessThanOrEqual(1);
    }
    const fill = Math.max(...front.flatMap((p) => [Math.abs(p.x), Math.abs(p.y)]));
    expect(fill).toBeCloseTo(1 / (1 + MARGIN), 2);
  }
});

it("always looks along −z in 2D", () => {
  const poses = [homePose("2d", g, 2.8), focusPose("2d", { x: -200, y: 10, z: 0 }, HOME_3D, g)];
  for (const { position, target } of poses) {
    expect([position.x, position.y]).toEqual([target.x, target.y]);
    expect(position.z).toBeGreaterThan(target.z);
  }
});

it("stays finite before the panel is measured", () => {
  for (const aspect of [0, Number.NaN, Number.POSITIVE_INFINITY]) {
    expect(homePose("2d", g, aspect)).toEqual(homePose("2d", g, PANEL_ASPECT));
  }
});

it("opens 3D on the spike's three-quarter view", () => {
  expect(homePose("3d", g, 2.8)).toEqual(HOME_3D);
});

it("keeps a panned target over the model", () => {
  expect(clampTarget({ x: -2000, y: 500, z: 80 }, g)).toEqual({ x: g.bounds.min.x, y: g.bounds.max.y, z: g.bounds.max.z });
  expect(clampTarget({ x: -100, y: 5, z: 0 }, g)).toEqual({ x: -100, y: 5, z: 0 });
});

it("focuses on the fingerboard: 260 mm in front in 2D, 190 mm back along the view in 3D", () => {
  const onTheNeckBack = { x: -200, y: 60, z: -8 };
  const flat = focusPose("2d", onTheNeckBack, HOME_3D, g);
  expect(flat.target).toEqual({ x: -200, y: g.halfWidth(-200), z: 0 });
  expect(flat.position).toEqual({ x: -200, y: g.halfWidth(-200), z: 260 });

  const turned = focusPose("3d", onTheNeckBack, HOME_3D, g);
  const away = new Vector3().subVectors(turned.position, turned.target);
  const before = new Vector3().subVectors(HOME_3D.position, HOME_3D.target);
  expect(away.length()).toBeCloseTo(190, 9);
  expect(away.normalize().dot(before.normalize())).toBeCloseTo(1, 9);
});

it("eases in and out, from one pose to the other", () => {
  expect([0, 0.5, 1].map(easeInOut)).toEqual([0, 0.5, 1]);
  expect(easeInOut(0.25)).toBeLessThan(0.25);
  expect(easeInOut(0.75)).toBeGreaterThan(0.75);
  const home = homePose("2d", g, 2.8);
  expect(between(home, HOME_3D, 0)).toEqual(home);
  expect(between(home, HOME_3D, 1)).toEqual(HOME_3D);
});
```

three's `subVectors` and `copy` take a `Vector3Like`, so the plain `Vec3` objects need no cast.

- [x] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/guitar/camera.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './camera'`.

- [x] **Step 3: Write the module by the Interfaces block**

- [x] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/guitar/camera.test.ts`
Expected: PASS, 7 tests.

- [x] **Step 5: Commit**

```bash
git add web/src/guitar/camera.ts web/src/guitar/camera.test.ts
git commit -m "feat(web): pose the guitar's camera, for 2D and 3D

2D frames the whole model square-on with a 4% margin, at any aspect,
and an unmeasured panel reads as the CSS aspect rather than NaN. 3D
opens on the spike's three-quarter view. Double-click focus lands on
the fingerboard; panning keeps the target over the model.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The notes on the neck

The keyed updater. Each frame's sounding notes become dot and ring meshes, one per note id, each pulsing once as it appears.

**Files:**
- Create: `web/src/guitar/notes.ts`, `web/src/guitar/notes.test.ts`

**Interfaces:**
- Consumes: `SoundingNote` (Task 3); `Geometry` (Task 4).
- Produces, from `web/src/guitar/notes.ts`:
  - `PULSE_SCALE = 1.5`, `PULSE_MS = 220`.
  - `type DotPainter = (name: string, open: boolean) => Texture`.
  - `class NoteLayer { constructor(parent: Object3D, g: Geometry, paint: DotPainter); apply(notes: readonly SoundingNote[], wallMs: number, pulse: boolean): boolean; repaint(): void; dispose(): void }`. `apply` returns whether a pulse is still running.
- The rules:
  - Every mark shares one `PlaneGeometry(2, 2)`, so a mesh's scale is its radius.
  - Each mesh has its own `MeshBasicMaterial({ map, transparent: true, depthWrite: false })`, because opacity differs per note. Textures are shared, cached by `` `${name}|${open}` ``.
  - The mesh's `name` is `"ring"` for fret 0 and `"dot"` otherwise. Its `userData` holds `{ name, open }`. Its position is `g.mark(string, fret).at`, its `renderOrder` is 2, and `material.opacity` is the note's.
  - Scale is `r · (1 + (PULSE_SCALE − 1) · (1 − k)²)`, with `k = min(1, (wallMs − born) / PULSE_MS)`; with `pulse` false, it is `r`.
  - A gone key's mesh is removed and its material disposed, but not the shared texture.
  - `repaint()` disposes the cached textures, clears the cache, and gives each live mesh a fresh map.
  - `dispose()` removes every mesh and disposes the materials, the textures and the shared plane.

- [x] **Step 1: Write the failing tests**

```typescript
const g = geometryOf(buildSong(doc()));
const sounding = (fields: Partial<SoundingNote> = {}): SoundingNote => ({
  key: "dot:a", string: 0, fret: 3, midi: 43, name: "G", opacity: 1, onset: 1, until: 2, loudness: null, ...fields,
});
function layer() {
  const parent = new Group();
  const paint = vi.fn<DotPainter>(() => new Texture());
  return { parent, paint, notes: new NoteLayer(parent, g, paint) };
}
const mesh = (parent: Group) => parent.children[0] as Mesh<PlaneGeometry, MeshBasicMaterial>;

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
```

- [x] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/guitar/notes.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './notes'`.

- [x] **Step 3: Write `NoteLayer` by the Interfaces block**

Its comment says this is 007's `MarkLayer` for three.js: a key is stable across frames, so its mesh is made once, updated while the key lasts, and removed when it is gone. Every onset has its own key, which is what makes each pluck pulse.

- [x] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test -- src/guitar/notes.test.ts`
Expected: PASS, 8 tests.

- [x] **Step 5: Commit**

```bash
git add web/src/guitar/notes.ts web/src/guitar/notes.test.ts
git commit -m "feat(web): put each sounding note on the neck, keyed by id

A filled dot on its fret, or a ring for an open string, lying on the
board. One mesh per onset, so each pluck swells from 1.5x over 220 ms,
on wall-clock time; none under reduced motion. Textures are shared by
name, and repainted when the colour scheme changes.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The guitar panel

The renderer, the frame loop and the chrome, not yet mounted. `fretboard/` is still what `Player` shows.

**Files:**
- Create: `web/src/guitar/textures.ts`, `web/src/guitar/stage.ts`, `web/src/guitar/stage.test.ts`, `web/src/guitar/Guitar.tsx`, `web/src/guitar/Guitar.test.tsx`
- Modify: `web/src/styles.css` (add the `--guitar-*` tokens, light and dark, and the `.guitar*` classes)

**Interfaces:**
- Consumes: Tasks 3–8. `PlaybackEngine` (`playback/engine.ts`). `FakeMedia`, `FakeFrames` (`test/fakeMedia.ts`). `JOB_ID` (`test/jobs.ts`).
- Produces, from `web/src/guitar/textures.ts` (browser-only, not unit-tested):
  - `interface Palette { background: string; dot: string; dotText: string }`.
  - `readPalette(element: Element): Palette`. It reads `--guitar-background`, `--guitar-dot` and `--guitar-dot-text`, as `TabStrip`'s `readPalette` does, with `"#888"` when one is unset.
  - `dotPainter(palette: () => Palette): DotPainter`. The spike's `dotTexture` (lines 309–342) on a 128 px canvas. A dot is filled with `dot`, edged `rgba(255,255,255,0.92)`, with its name in `dotText`. A ring is stroked in `dot`, with its name in `RING_TEXT = "#f4efe2"`, since the headstock is dark in both themes. `colorSpace` is `SRGBColorSpace`.
  - `paintText: TextPainter`, on a 64 px-tall canvas as wide as the text, in `600 48px system-ui, sans-serif`.
  - With no 2D context (jsdom), both return a blank `Texture` and aspect 1, and never throw.
- Produces, from `web/src/guitar/stage.ts`:
  - `type Renderer = Pick<WebGLRenderer, "setPixelRatio" | "setSize" | "render" | "dispose">`.
  - `interface StageOptions { canvas: HTMLCanvasElement; overlay: HTMLElement; song: Song; engine: PlaybackEngine; renderer: Renderer; view: View; onLost: (lost: boolean) => void; now?: () => number; requestFrame?: (callback: () => void) => number; cancelFrame?: (id: number) => void }`. The last three default to `performance.now` and the window's animation frames.
  - `class Stage { constructor(options: StageOptions); setView(view: View): void; resetView(): void; dispose(): void }`.
- Produces, from `web/src/guitar/Guitar.tsx`:
  - `NO_WEBGL = "The guitar needs WebGL, which this browser has turned off."` and `VIEW_KEY = "guitarvis.guitar-view"`.
  - `interface GuitarProps { song: Song; engine: PlaybackEngine; createRenderer?: (canvas: HTMLCanvasElement) => Renderer }`. The default is `(canvas) => new WebGLRenderer({ canvas, antialias: true })`.
  - `function Guitar(props: GuitarProps)`, a named export.

**What `Stage` does.** This is the spec's *Rendering*, *The two views* and *The other cases*, made concrete. The spike's lines 372–481 are the model for the controls and the tween.

- **Construction.**
  - `geometryOf(song)`, `buildModel(g, paintText)`, a `Scene` holding `model.root`, and a `NoteLayer(scene, g, dotPainter(() => palette))`.
  - `cursorsOf(song)`.
  - A `PerspectiveCamera(FOV, PANEL_ASPECT, NEAR, FAR)` set at once to `homePose(view, g, aspect)`.
  - `OrbitControls(camera, canvas)` with `enableDamping` on, `dampingFactor` 0.08, `zoomToCursor` on, and `MIN_DISTANCE`/`MAX_DISTANCE`.
  - Pixel ratio `min(devicePixelRatio || 1, 2)`.
  - A `ResizeObserver` on `canvas.parentElement`, if the browser has one. `matchMedia` listeners for `(prefers-color-scheme: dark)` and `(prefers-reduced-motion: reduce)`, if it has those.
  - Canvas listeners for `dblclick`, `webglcontextlost` and `webglcontextrestored`.
  - Last, `engine.onFrame((t) => { this.t = t; if (this.draw(t)) this.wake(); })`.
- **The views.**
  - 2D: `enableRotate = false`, `mouseButtons = { LEFT: PAN, MIDDLE: DOLLY, RIGHT: PAN }`, `touches = { ONE: PAN, TWO: DOLLY_PAN }`.
  - 3D: `enableRotate = true`, `{ LEFT: ROTATE, MIDDLE: DOLLY, RIGHT: PAN }`, `{ ONE: ROTATE, TWO: DOLLY_PAN }`.
  - `setView(view)` does nothing for the current view. Otherwise it applies the settings, clears `touched`, and moves to the new view's home.
  - `resetView()` clears `touched` and moves to the current view's home.
- **Moving the camera.**
  - `goTo(pose)` starts a tween `{ from: current pose, to: pose, start: now() }` and wakes.
  - Each frame's camera step runs the tween if there is one: `k = still ? 1 : min(1, elapsed / TRANSITION_MS)`, the pose set to `between(from, to, easeInOut(k))`, then `camera.lookAt(target)`. The tween ends at k = 1.
  - With no tween, the step runs `controls.update()` and then `clampTarget`. If the clamp moved the target, the camera moves by the same offset, so the view does not swing.
  - The step returns whether the camera is still moving.
  - The controls' `start` event sets `touched`, drops any tween, and wakes. Their `change` event wakes.
- **Double-click.** Compute NDC from `getBoundingClientRect`, and do nothing if it has zero width. Raycast `model.pickable`. On a hit, set `touched` and `goTo(focusPose(view, hit.point, current, g))`.
- **Resize.** Read the box's `clientWidth`/`clientHeight`, and ignore either being 0. Then `renderer.setSize(w, h, false)`, set the camera's aspect and update its projection. If the camera is not `touched` and no tween runs, jump to `homePose`. Then wake.
- **One frame**, `draw(t)`: steps 1–5 of the spec's *Rendering*:

  ```typescript
  const now = this.now();
  const moving = this.stepCamera(now);
  const { notes, message } = sounding(this.song, this.cursors, t);
  const pulsing = this.notes.apply(notes, now, !this.still);
  const byString = new Map(notes.map((note) => [note.string, note]));
  this.model.strings.forEach((string, s) => {
    const note = byString.get(s);
    const a = note === undefined || this.still ? 0 : envelope(note, t);
    string.shape(a, note === undefined ? 0 : swing(note, t), note?.opacity ?? 1);
  });
  this.show(message); // hidden when null; text, class and opacity set only when changed
  this.renderer.render(this.scene, this.camera);
  return moving || pulsing;
  ```

  `show` sets `overlay.className` to `"guitar-message chord"` for a chord and `"guitar-message"` otherwise, and `overlay.style.opacity` to the message's opacity.
- **Own frames.** `wake()` returns if the stage is disposed, a frame is already pending, or `engine.getState().playing` is true, because the engine draws every frame then. Otherwise it requests one frame, which runs `if (this.draw(this.t)) this.wake()`. It never calls `engine.redraw()`.
- **Colour scheme change.** Re-read the palette, set `scene.background`, call `notes.repaint()`, and wake.
- **Reduced motion.** `still` follows the media query: no vibration, no pulse, and camera moves jump.
- **Context loss.** `webglcontextlost` calls `onLost(true)` and `webglcontextrestored` calls `onLost(false)`. three's own handler already calls `preventDefault`, so a browser may restore the context.
- **`dispose()`.** Stop the engine listener, cancel the pending frame, remove every listener and observer, then `controls.dispose()`, `notes.dispose()`, `model.dispose()` and `renderer.dispose()`.

**What `Guitar` renders:**

```tsx
<div className="guitar">
  <canvas ref={canvasRef} role="img" aria-label="Guitar" />
  <div ref={overlayRef} className="guitar-message" hidden />
  {unavailable ? (
    <p className="guitar-unavailable">{NO_WEBGL}</p>
  ) : (
    <>
      <div className="guitar-views" role="group" aria-label="View">
        {/* 2D, 3D: type="button", aria-pressed, onMouseDown={keepFocus} */}
      </div>
      <button type="button" className="guitar-reset" onMouseDown={keepFocus} onClick={reset}>Reset view</button>
    </>
  )}
</div>
```

- `keepFocus` is `Controls.tsx`'s one-liner, restated with its comment, because a click must not leave Space on a button.
- `view` is React state, initialised by `readView()`. That returns `"2d"` or `"3d"` from `localStorage[VIEW_KEY]`, and `"3d"` for anything else or if storage throws. `writeView` writes inside `try`/`catch`.
- One effect, keyed on `[song, engine, createRenderer]`, calls `createRenderer(canvas)`. If that throws, it sets `unavailable`. Otherwise it makes a `Stage` with the current view and `onLost: setUnavailable`, and returns `stage.dispose`.
- A second effect, keyed on `[view]`, calls `stage.setView(view)` and `writeView(view)`.

**Styles** (light / dark):
- tokens:
  - `--guitar-background: #fbfaf7 / #171614`
  - `--guitar-dot: #c2410c / #fb923c`
  - `--guitar-dot-text: #ffffff / #171614`
  - `--guitar-text: #7a7469 / #a39d91`
  - `--guitar-chord: #1f1d1a / #ece8df`
- `.guitar`: `position: relative; width: 100%; aspect-ratio: 2.8; min-height: 260px; max-height: 460px; margin-bottom: 12px; border-radius: 8px; overflow: hidden; background: var(--guitar-background); box-shadow: 0 0 0 1px var(--border)`.
- `.guitar canvas`: `display: block; width: 100%; height: 100%; cursor: grab`.
- `.guitar-message`: `position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; pointer-events: none; color: var(--guitar-text); font: 15px system-ui, sans-serif`, with `text-shadow: 0 0 3px var(--guitar-background)` four times over.
- `.guitar-message[hidden]`: `display: none`, because the `display: flex` above would beat the attribute.
- `.guitar-message.chord`: `color: var(--guitar-chord); font: bold 32px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`.
- `.guitar-views`: absolute, `top: 8px; left: 8px`. `.guitar-reset`: absolute, `top: 8px; right: 8px`.
- `.guitar button`: as `.controls button`, including `[aria-pressed="true"]`.
- `.guitar-unavailable`: absolute, inset 0, centred, `margin: 0; padding: 16px; color: var(--muted); text-align: center`.
- The comment at the top of `styles.css` gains: "the guitar's three.js scene reads the --guitar-* ones."

- [x] **Step 1: Write the failing tests**

`web/src/guitar/Guitar.test.tsx`:

```tsx
// @vitest-environment jsdom
// Each test: getContext stubbed to null (jsdom has no canvas), localStorage cleared.

function fakeRenderer() {
  return { setPixelRatio: vi.fn(), setSize: vi.fn(), render: vi.fn(), dispose: vi.fn() };
}

function mount(doc: TabDocument = FIRST_SONG, renderer: Renderer = fakeRenderer(), createRenderer = () => renderer) {
  // engine with FakeMedia and FakeFrames, as Fretboard.test.tsx's engineFor; render <Guitar ... />;
  // returns { engine, renderer, view, at(t) }, where at seeks and flushes the engine's frames.
  // The WebGL tests pass a createRenderer that throws.
}

it("draws each engine frame, and on unmount unsubscribes and disposes the renderer", ...);
// spy on engine.onFrame as Fretboard.test.tsx does; at(1) → renderer.render called;
// unmount → the stop function called once, renderer.dispose called once.

it("opens in 3D on a first visit", ...);            // "3D" aria-pressed "true", "2D" "false"

it("switches views from the toggle, and remembers the choice", ...);
// click "2D" → pressed; localStorage.getItem(VIEW_KEY) === "2d"; unmount; mount again → "2D" pressed.

it("opens in 3D when the browser's storage throws, and still switches", ...);
// vi.spyOn(Storage.prototype, "getItem" and "setItem").mockImplementation(() => { throw new DOMException("denied", "SecurityError"); })

it("ignores a stored view it does not know", ...);  // localStorage.setItem(VIEW_KEY, "4d") → 3D

it("keeps a mouse click on the toggle from taking focus", ...);
// expect(fireEvent.mouseDown(screen.getByRole("button", { name: "2D" }))).toBe(false)

it("says the guitar needs WebGL when the renderer cannot be made, and offers no camera buttons", ...);
// createRenderer throws → getByText(NO_WEBGL); queryByRole("button", { name: "Reset view" }) is null; no throw

it("says so while the WebGL context is lost, and clears it once restored", ...);
// fireEvent(canvas, new Event("webglcontextlost")) → NO_WEBGL shown; "webglcontextrestored" → gone

it("shows a hidden passage's chord in the overlay, and nothing outside it", ...);
// three weak notes at 1, 1.3, 1.6 and an Am chord over them; at(1.2) → overlay text "Am", class contains "chord";
// at(5) → overlay hidden

it("shows the empty message for a document with no notes", ...);  // at(0) → "No notes to show"
```

`web/src/guitar/stage.test.ts` (`// @vitest-environment jsdom`, `getContext` stubbed to null as above) builds a `Stage` directly. It uses a fake renderer, a canvas inside a div, its own `FakeFrames`, and a `now` that the test advances:

```typescript
it("draws its own frames while the camera moves, and stops once it arrives", () => {
  const { stage, own, renderer, tick } = setUp({ view: "3d" }); // engine paused
  const before = renderer.render.mock.calls.length;

  stage.setView("2d");
  expect(own.pending).toBe(1);
  for (let i = 0; i < 10; i++) tick(100); // advance now by 100 ms, flush own frames

  expect(own.pending).toBe(0);
  expect(renderer.render.mock.calls.length - before).toBeGreaterThanOrEqual(7);
});

it("leaves the drawing to the engine's frames while the song plays", () => {
  const { stage, own, engine } = setUp({ view: "3d" });
  engine.play();
  stage.setView("2d");
  expect(own.pending).toBe(0);
});

it("jumps instead of animating under reduced motion", () => {
  // vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), addEventListener() {}, removeEventListener() {} }))
  const { stage, own, tick } = setUp({ view: "3d" });
  stage.setView("2d");
  tick(16);
  expect(own.pending).toBe(0);
});

it("stops drawing once disposed", () => {
  const { stage, renderer, at } = setUp({ view: "3d" });
  stage.dispose();
  const calls = renderer.render.mock.calls.length;
  at(2); // engine seeks and flushes its frames
  expect(renderer.render.mock.calls.length).toBe(calls);
  expect(renderer.dispose).toHaveBeenCalledTimes(1);
});
```

`setUp` returns `{ stage, own, engine, renderer, tick(ms), at(t) }`. The engine has its own `FakeFrames`, separate from the stage's `own`.

- [x] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/guitar/Guitar.test.tsx src/guitar/stage.test.ts`
Expected: FAIL. `tsc` reports `Cannot find module './Guitar'` and `'./stage'`.

- [x] **Step 3: Write `textures.ts`, `stage.ts`, `Guitar.tsx` and the styles, as described above**

- [x] **Step 4: Run the tests to verify they pass**

Run: `npm --prefix web test && npm --prefix web run lint`
Expected: PASS: all of `web/`'s tests, including 10 in `Guitar.test.tsx` and 4 in `stage.test.ts`, and lint clean. jsdom may print "Not implemented: HTMLCanvasElement's getContext()" for canvases the stub misses. That is noise, not a failure.

- [x] **Step 5: Commit**

```bash
git add web/src/guitar/textures.ts web/src/guitar/stage.ts web/src/guitar/stage.test.ts \
  web/src/guitar/Guitar.tsx web/src/guitar/Guitar.test.tsx web/src/styles.css
git commit -m "feat(web): draw the guitar from the engine's frames, in 2D or 3D

A Stage owns the renderer, camera and controls outside React: each
engine frame lights the notes, swings the strings and sets the
overlay. Its own frames run only while the camera moves or a dot
pulses, and never while the song plays. 2D pans and zooms and never
tilts; 3D rotates. The choice is remembered. Without WebGL the panel
says so, and the rest of the player carries on.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The guitar replaces the fretboard

`Player` loads the guitar lazily above the tab strip, and 007's SVG fretboard is deleted.

**Files:**
- Modify: `web/src/player/Player.tsx`, `web/src/player/Player.test.tsx`, `web/src/views.test.ts`, `web/src/styles.css`, `web/vite.config.ts`, `web/src/confidence.ts:3` and `web/src/tab/layout.ts:145` (comments only)
- Delete: `web/src/fretboard/Fretboard.tsx`, `Fretboard.test.tsx`, `layout.ts`, `layout.test.ts`, `marks.ts`, `marks.test.ts`, `neck.ts`, `neck.test.ts`

**Interfaces:**
- Consumes: `Guitar` (Task 9).
- Produces: nothing new. `web/src/fretboard/` no longer exists.

- [x] **Step 1: Update the tests**

In `web/src/player/Player.test.tsx`, replace `shows the fretboard above the tab strip` with:

```tsx
  it("shows the guitar above the tab strip", async () => {
    mount();

    const guitar = await screen.findByRole("img", { name: "Guitar" });
    const strip = screen.getByLabelText("Tab");

    expect(guitar.compareDocumentPosition(strip) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps playing from its controls when the guitar has no WebGL", async () => {
    const media = mount();

    await screen.findByText(NO_WEBGL); // jsdom has none

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(media.paused).toBe(false);
  });
```

In `web/src/views.test.ts`:
- remove the fretboard's case, and the `fretboard/layout` and `fretboard/neck` imports;
- rename the imports `soundingCursors` → `cursorsOf`;
- reword the header: "The tab strip and the guitar each read the hidden passages for their own window, by the same rule written twice."

- [x] **Step 2: Run them to verify they fail**

Run: `npm --prefix web test -- src/player/Player.test.tsx`
Expected: FAIL. `findByRole("img", { name: "Guitar" })` times out, because the player still shows the fretboard.

- [x] **Step 3: Mount the guitar lazily, and delete the fretboard**

In `Player.tsx`:

```tsx
import { lazy, Suspense, useEffect, useState } from "react";
// ...
/** three.js is about 150 kB gzipped, so the guitar is its own chunk, fetched
 * when a song first shows: the upload page never downloads it. */
const Guitar = lazy(() => import("../guitar/Guitar").then((module) => ({ default: module.Guitar })));
```

Replace `<Fretboard … />` with:

```tsx
      <Suspense fallback={<div className="guitar" />}>
        <Guitar song={song} engine={engine} />
      </Suspense>
```

The fallback has the panel's class, so it takes the panel's final height while it loads. Reword the component comment: "The guitar sits above the tab strip; each is one more onFrame listener."

Delete `web/src/fretboard/`.

In `styles.css`, delete every `--fret-*` token (light and dark), the `.fretboard` and `.fret-*` rules, and the `fret-pluck` keyframes with their reduced-motion block. The top comment then names only `--tab-*` and `--guitar-*`.

In `web/src/confidence.ts:3`, change "Phase 5's fretboards" to "The guitar". In `web/src/tab/layout.ts:145`, change "as on the fretboard" to "as on the guitar".

In `web/vite.config.ts`:

```typescript
  build: {
    // three.js ships in the guitar's lazy chunk, about 585 kB before gzip
    // and 150 kB after. Vite's 500 kB default would warn on every build.
    chunkSizeWarningLimit: 650,
  },
```

- [x] **Step 4: Verify**

Run: `npm --prefix web test && npm --prefix web run lint`
Expected: PASS, lint clean.

Run: `grep -rn "fretboard/\|--fret-\|\.fret-\|Fretboard" web/src`
Expected: no matches. (`progress.ts`'s `fretboard:` is the pipeline stage's name, and the grep's patterns skip it.)

Run: `npm --prefix web run build`
Expected: no warning. `dist/assets/` holds a `Guitar-*.js` of about 590 kB (about 150 kB gzipped). The `index-*.js` entry is no larger than before this branch, 170.6 kB (56.6 kB gzipped), because the fretboard has left it.

Run: `make services && make check`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add -A web/src/fretboard web/src/player/Player.tsx web/src/player/Player.test.tsx web/src/views.test.ts \
  web/src/styles.css web/vite.config.ts web/src/confidence.ts web/src/tab/layout.ts
git commit -m "feat(web): show the guitar above the tab strip, in place of the fretboard

Loaded with React.lazy, so three.js stays out of the upload page's
bundle. 007's SVG fretboard and its --fret-* tokens go: its rules live
on in guitar/sounding.ts, pinned to the tab strip in views.test.ts.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: The records

Close the parent spec's open decision 8, point the docs at the guitar, and commit a blank acceptance record for Task 12.

**Files:**
- Create: `docs/decisions/0009-procedural-guitar-model.md`, `docs/specs/008-3d-guitar/acceptance.md`
- Modify: `docs/decisions/README.md`, `docs/specs/001-guitarvis-design/spec.md` (lines 268–272 and 407–409), `docs/CONVENTIONS.md`, `CLAUDE.md`

- [x] **Step 1: Write ADR 0009 from `docs/decisions/template.md`**

- Title: "0009. The guitar is built in code, not loaded from a model file".
- Status: "Accepted". Date: the commit date. Spec: `[008-3d-guitar](../specs/008-3d-guitar/spec.md#the-model)`.
- **Context:** open decision 8: procedural geometry against a sourced glTF model. A glTF would look better for less modelling work, but brings licensing and file size to manage. Its proportions also could not stretch to `WIDE`, the 1.7× width that makes the dots large enough to name.
- **Decision:** a procedural neck and headstock, built with plain three.js from `guitar/geometry.ts`, after spike.html.
- **Consequences:** every dimension is a tested constant, and any song's fret range fits. No asset pipeline or licence. The body, bridge and sound hole are not drawn. A sourced model would need the geometry module's positions mapped onto it, which is the work to revisit.

- [x] **Step 2: Update the indexes and the parent spec**

- `docs/decisions/README.md`: add 0009's row to *Accepted*, and delete the "3D guitar asset: procedural or sourced glTF" row from *Still open*.
- Parent spec, under *Rendering*:
  - the **2D fretboard** bullet gains: "Superseded by [008](../008-3d-guitar/spec.md): the 3D model seen square-on is the 2D view."
  - the **3D guitar** bullet reads: "plain three.js, not react-three-fiber ([008](../008-3d-guitar/spec.md#rejected-alternatives))."
- Parent spec, under open decision 8: append "**Resolved by [ADR 0009](../../decisions/0009-procedural-guitar-model.md):** procedural."
- `docs/CONVENTIONS.md`: replace "Canvas for the tab strip, SVG for the 2D fretboard." with "Canvas for the tab strip, and three.js for the guitar, which draws both the 2D and the 3D view and is loaded lazily."
- `CLAUDE.md`:
  - move "← **next**" from phase 5 to phase 6;
  - under *Things that will bite you*, add: "The guitar's tests run without WebGL. Pure modules in `web/src/guitar/` run on `node`, three.js included. `Guitar` and `Stage` take a fake renderer under jsdom."

- [x] **Step 3: Write `docs/specs/008-3d-guitar/acceptance.md`**

Use 007's `acceptance.md` layout: a **Spec:** link to the spec's *Manual acceptance*, a sentence on what it is for, and *Setup* (commit; machine, OS and browser; songs, with title, length and the frets they reach). Then one checkbox per item in the spec's *Manual acceptance*, under its own headings: *End to end*, *The views*, *Readability*, *Frame rate*, *Dark mode, reduced motion, resizing, WebGL off*, and *The string orders*. Each section ends with "Notes: …". Add three free-text lines:
- "Readable without zoom down to a panel width of: … px"
- "Frame rate: browser … , about … fps, playing with the 3D view moving"
- "Constants changed in this run, from → to, and why: …", for the amplitudes, the pulse, `WIDE`, the panel height or the pixel ratio.

State at the top: "Filled in before the PR is merged. 007's record was committed blank and merged without the run."

- [x] **Step 4: Verify**

Run: `grep -n "react-three-fiber" docs/specs/001-guitarvis-design/spec.md docs/CONVENTIONS.md CLAUDE.md`
Expected: only the parent spec's line that now says "not react-three-fiber".

- [x] **Step 5: Commit**

```bash
git add docs/decisions docs/specs/001-guitarvis-design/spec.md docs/CONVENTIONS.md CLAUDE.md \
  docs/specs/008-3d-guitar/acceptance.md
git commit -m "docs: record the procedural guitar, and the acceptance run to come

ADR 0009 closes open decision 8. The parent spec, conventions and
CLAUDE.md point at three.js and the guitar; phase 6 is next. The
acceptance record is committed blank, to be filled in before merge.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: The acceptance run, then the PR

**A person runs this task.** It needs real services, a real song, a browser, and judgement about how the result looks and sounds. An agent executing this plan stops at Step 1 and hands over.

**Files:**
- Modify: `docs/specs/008-3d-guitar/acceptance.md`, `docs/specs/008-3d-guitar/plan.md` (checkboxes)
- Maybe modify: the constants the run judges (`vibration.ts`, `notes.ts`, `geometry.ts`'s `WIDE`, `styles.css`'s panel height, and `Stage`'s pixel-ratio cap)

- [ ] **Step 1: Run every check in `acceptance.md`**

Run `make services`, `make migrate`, `make api`, `make worker` and `make web`. `make worker` needs `uv sync --extra ml`. Upload a real song, then work through the record and fill in each line.

- [ ] **Step 2: Change only what the run calls for**

If a constant changes, re-run `npm --prefix web test`, since some tests pin these values, and note the change in the record's last line. The spec's *Risks* name the levers: cap the pixel ratio at 1.5, then reshape strings every other frame for frame rate; a taller panel or a larger `WIDE` for text size; the amplitude constants for distraction; the loudness window and range for loudness.

After changing the loudness constants, delete the song's job row (or use a new song) before re-uploading, or the api returns the old document and the change never reaches the browser.

- [ ] **Step 3: Commit the record**

```bash
git add docs/specs/008-3d-guitar/acceptance.md
git commit -m "docs: 008's acceptance record

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Run the gate once more, and tick this plan's checkboxes**

Run: `make services && make check`
Expected: PASS. Then tick every checkbox in this plan, and commit as "docs: tick 008's plan checkboxes".

- [ ] **Step 5: Open the PR**

Use `.github/pull_request_template.md`, with **Spec:** `docs/specs/008-3d-guitar/spec.md`. Under *What changed*, state the tab-document skill's caveat: `Note.loudness` is additive for in-repo clients, but a client validating raw JSON against a bundled v1 schema would reject a document carrying it. List every constant the acceptance run changed under *Deviations from the spec*. End the description with:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
