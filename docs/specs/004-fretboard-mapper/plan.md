# Fretboard Mapper and Evaluation Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement stage 4 (`ViterbiFretboardMapper`) so the pipeline emits real tablature, and a GuitarSet evaluation harness that measures it — oracle mode by default, full mode on demand.

**Architecture:** `FretboardMapper.assign` returns a `FretboardResult(notes, warnings)`. The mapper groups notes into voicings, enumerates playable fingerings, and runs Viterbi over them in pure Python. The harness in `apps/eval` reads GuitarSet JAMS with the standard library, scores the mapper against ground-truth strings (oracle) or runs the real transcriber and analyzer on the mic audio (full), and writes one JSON file per run to `eval/results/`.

**Tech Stack:** Python 3.12, uv workspace, pytest, mypy, ruff. Full mode only: `mir_eval` 0.8, plus the worker's `ml` extra.

**Spec:** [spec.md](spec.md) · **Parent:** [001-guitarvis-design](../001-guitarvis-design/spec.md) · **Carried findings:** [003 review notes](../003-pipeline-skeleton/review-notes.md) · **ADRs:** [0003](../../decisions/0003-deterministic-fretboard.md), [0004](../../decisions/0004-evaluation-is-measured-not-gated.md)

## Global Constraints

Repo-wide rules from `CLAUDE.md` and `docs/CONVENTIONS.md`. Every task inherits them.

- **Never commit to `main`.** All work happens on branch `004-fretboard-mapper`. `.githooks/pre-commit` enforces it.
- **`make check` is the gate.** Run it before claiming any task is done: ruff, mypy, pytest, ESLint, `tsc`, `make schema-check`.
- **`pitch_of(string, fret, tuning) == note.midi`**, for every note, always. Every note leaving stage 4 must pass `guitarvis_core.fretboard.check_invariant`.
- **Seconds are authoritative.** Never store a note position as bar/beat.
- **Evaluation never gates CI.** `make eval` and `make eval-data` stay out of `make check`. No test under `apps/eval/tests/` may both mention the results directory path and read a file's contents — `apps/eval/tests/test_eval_never_gates_ci.py` fails the build if one does. Test files in this plan write results into `tmp_path` only and never spell that path.
- **Stage modules must not import** torch, demucs, basic_pitch, librosa, or numpy at module level. The mapper imports none of them at all.
- **`apps/api` must not import** torch, demucs, basic_pitch, librosa, or numpy. Not touched here.
- **No `tabdoc.py` change**, so no `make schema` run is needed. If you find yourself editing `tabdoc.py`, stop: the spec says the document does not change.
- **Test file basenames are unique across the repo** (the Makefile's mypy caveat). Worker mapper tests go in `test_fretboard_mapper.py` because `packages/core/tests/test_fretboard.py` exists. Do not add a `conftest.py` in `apps/eval/tests`.
- The worker's ML dependencies are opt-in: `uv sync --extra ml`. Full evaluation needs `uv sync --extra eval-full` (added in Task 7).
- Run `uv run ruff format . && uv run ruff check --fix .` before each commit; import order in these snippets is best-effort and ruff is authoritative.

## Review Focus

Inputs the spec implies but does not name, most likely first. Each has a test in the task that owns the code.

1. **The same pitch detected twice at one onset** (a transcriber double-hit). Expect one kept and one dropped with a warning when no hand can play both — never a crash, never two notes on one string. → Task 2, `test_duplicate_pitch_at_one_onset_keeps_one`.
2. **Notes arriving out of onset order.** Expect output sorted by onset, then string, with nothing lost. → Task 2, `test_unsorted_input_comes_out_sorted`.
3. **A tuning that is not six strings** (a 7-string with low B). Expect the mapper to use every string it is given. → Task 2, `test_seven_string_tuning_reaches_low_b`.
4. **An excerpt with no notes, or no in-vocabulary chords.** Expect rates of `None` (JSON `null`), not a `ZeroDivisionError`. → Task 4, `test_empty_excerpt_scores_none_not_zero_division`; Task 7, `test_chord_tally_skips_out_of_vocabulary_frames`.
5. **Running the harness outside a git checkout** (an exported tarball). Expect commit `"unknown"` and `dirty: true`, not a crash. → Task 5, `test_git_state_outside_a_repository`.

---

### Task 1: `FretboardResult` and stage 4's degradation

The contract change and the orchestrator change land together: changing the return type without the orchestrator reading `.notes` would break the pipeline between commits. The mapper is still the stub after this task; it now degrades through the general `except Exception` path, which is what 003's review notes asked for.

**Files:**
- Modify: `packages/core/src/guitarvis_core/contracts.py` (add `FretboardResult` after `TabNote`; change `FretboardMapper.assign`'s return type)
- Modify: `apps/worker/src/guitarvis_worker/stages/fretboard.py` (stub's return annotation only)
- Modify: `apps/worker/src/guitarvis_worker/pipeline.py` (stage 4 block)
- Modify: `packages/core/tests/test_contracts.py`
- Modify: `apps/worker/tests/test_pipeline.py`
- Modify: `apps/worker/tests/test_cli.py` (one assertion string)
- Modify: `docs/specs/001-guitarvis-design/spec.md:212`, `.claude/skills/pipeline-stage/SKILL.md:15` (the signature)

**Interfaces:**
- Consumes: nothing new.
- Produces: `guitarvis_core.contracts.FretboardResult(notes: list[TabNote], warnings: list[str] = [])`, frozen dataclass. `FretboardMapper.assign(self, notes: Sequence[NoteEvent], tuning: Sequence[str]) -> FretboardResult`. Pipeline warning text on mapper failure: `"Fretboard assignment failed ({ExceptionName}), so this document carries no notes."`

- [x] **Step 1: Write the failing contract test**

In `packages/core/tests/test_contracts.py`, add `FretboardResult` to the `guitarvis_core.contracts` import list, change `FakeMapper.assign` inside the protocol-conformance test to:

```python
    class FakeMapper:
        def assign(
            self, notes: Sequence[NoteEvent], tuning: Sequence[str]
        ) -> FretboardResult:
            return FretboardResult(notes=[])
```

and append:

```python
def test_fretboard_result_warnings_default_to_empty() -> None:
    """Stage 4 reports dropped notes the way stages 1 and 3 report theirs."""
    result = FretboardResult(notes=[TabNote(1.0, 0.5, 40, 0, 0, 0.9)])

    assert result.warnings == []
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.notes = []  # type: ignore[misc]
```

- [x] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/core/tests/test_contracts.py -v`
Expected: collection error, `ImportError: cannot import name 'FretboardResult'`.

- [x] **Step 3: Add `FretboardResult` and change the protocol**

In `contracts.py`, directly after the `TabNote` class:

```python
@dataclass(frozen=True)
class FretboardResult:
    """Stage 4 output. `warnings` carries degradation the client must show.

    The mapper drops a note it cannot place correctly rather than place it
    wrongly — the fretboard invariant forbids a wrong fret — and a silent drop
    is exactly the kind of loss the client is supposed to show.
    """

    notes: list[TabNote]
    warnings: list[str] = field(default_factory=list)
```

and change the protocol's method to:

```python
@runtime_checkable
class FretboardMapper(Protocol):
    """Stage 4: place pitches on the neck. Deterministic, never learned."""

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> FretboardResult: ...
```

In `apps/worker/src/guitarvis_worker/stages/fretboard.py`, change the import to `from guitarvis_core.contracts import FretboardResult, NoteEvent` and the stub's return annotation to `-> FretboardResult`. Leave the `raise NotImplementedError(...)` body; Task 2 replaces it.

- [x] **Step 4: Run the contract tests**

Run: `uv run pytest packages/core/tests/test_contracts.py -v`
Expected: all PASS.

- [x] **Step 5: Update the pipeline tests to the new contract (failing)**

In `apps/worker/tests/test_pipeline.py`:

Add `FretboardResult` to the `guitarvis_core.contracts` import. Replace `StubMapper` and `UnimplementedMapper` with:

```python
class StubMapper:
    def __init__(
        self, notes: Sequence[TabNote] = (), warnings: Sequence[str] = ()
    ) -> None:
        self.notes = list(notes)
        self.warnings = list(warnings)

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> FretboardResult:
        return FretboardResult(notes=list(self.notes), warnings=list(self.warnings))


class FailingMapper:
    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> FretboardResult:
        raise RuntimeError("no fingering search today")
```

Replace `test_unimplemented_fretboard_stage_degrades` with:

```python
def test_fretboard_failure_degrades_instead_of_failing(tmp_path: Path) -> None:
    doc = run(
        tmp_path,
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        mapper=FailingMapper(),
    )

    assert doc.notes == []
    assert any("fretboard assignment failed" in w.lower() for w in doc.warnings)
    # The fretboard warning must speak only about notes: stage 4 failing
    # says nothing about whether stage 3 (timing, chords) succeeded.
    assert not any("unaffected" in w.lower() for w in doc.warnings)


def test_a_mapper_raising_not_implemented_degrades_like_any_other_failure(
    tmp_path: Path,
) -> None:
    # 003's review notes: a real mapper may raise NotImplementedError for a
    # genuinely unsupported case. It must degrade, not be mistaken for a stub.
    class Unsupported:
        def assign(
            self, notes: Sequence[NoteEvent], tuning: Sequence[str]
        ) -> FretboardResult:
            raise NotImplementedError("exotic tuning")

    doc = run(
        tmp_path,
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        mapper=Unsupported(),
    )
    assert doc.notes == []
    assert any("NotImplementedError" in w for w in doc.warnings)


def test_fretboard_warnings_reach_the_document(tmp_path: Path) -> None:
    doc = run(
        tmp_path,
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        mapper=StubMapper(
            [TabNote(1.0, 0.5, 52, 2, 2, 0.8)],
            warnings=["1 note outside the guitar's range was dropped."],
        ),
    )

    assert len(doc.notes) == 1
    assert "1 note outside the guitar's range was dropped." in doc.warnings
```

Replace `test_transcribed_note_count_is_reported_even_though_notes_stays_empty` with:

```python
def test_transcribed_note_count_survives_a_fretboard_failure(
    tmp_path: Path,
) -> None:
    result = run_result(
        tmp_path,
        transcriber=StubTranscriber(
            [NoteEvent(1.0, 0.5, 52, 0.8), NoteEvent(2.0, 0.5, 55, 0.7)]
        ),
        mapper=FailingMapper(),
    )

    assert result.transcribed_note_count == 2
    assert result.document.notes == []
```

In `test_progress_still_reports_when_stages_degrade`, change `mapper=UnimplementedMapper()` to `mapper=FailingMapper()`.

In `apps/worker/tests/test_cli.py`, in `test_reports_the_fretboard_stage_is_not_implemented`, change the asserted string to `"Fretboard assignment failed (NotImplementedError)"`. (Task 2 replaces this test outright.)

- [x] **Step 6: Run them to verify they fail**

Run: `uv run pytest apps/worker/tests/test_pipeline.py apps/worker/tests/test_cli.py -v`
Expected: FAIL — `AttributeError: 'FretboardResult' object has no attribute 'onset'` (the pipeline still iterates the result as a list) and the degradation tests fail because `RuntimeError` is not caught.

- [x] **Step 7: Change the orchestrator's stage 4 block**

In `apps/worker/src/guitarvis_worker/pipeline.py`, replace everything from the `# Stage 4.` comment down to (not including) `_report(progress, "fretboard")` with:

```python
    # Stage 4. Optional like stages 2 and 3: a mapper that raises costs the
    # notes track, not the job — including NotImplementedError, which a real
    # mapper may raise for a genuinely unsupported case. Notes the mapper
    # could not place arrive as warnings on its result. A wrong fret is a
    # different matter: the invariant check below fails the job instead.
    tab_notes: list[TabNote] = []
    try:
        fretboard = mapper.assign(events, tuning)
    except Exception as exc:  # every mapper failure degrades alike
        warnings.append(
            f"Fretboard assignment failed ({exc.__class__.__name__}), so this "
            "document carries no notes."
        )
    else:
        tab_notes = fretboard.notes
        warnings.extend(fretboard.warnings)
```

- [x] **Step 8: Run the worker and core tests**

Run: `uv run pytest packages/core apps/worker -v`
Expected: all PASS (CLI tests needing `ffprobe` may SKIP).

- [x] **Step 9: Update the two docs that state the signature**

`docs/specs/001-guitarvis-design/spec.md` line 212 and `.claude/skills/pipeline-stage/SKILL.md` line 15: change `-> list[TabNote]` to `-> FretboardResult`.

- [x] **Step 10: Run `make check` and commit**

Run: `make check`
Expected: exit 0.

```bash
git add packages/core apps/worker docs/specs/001-guitarvis-design/spec.md .claude/skills/pipeline-stage/SKILL.md
git commit -m "feat: FretboardResult carries stage 4 warnings; mapper failure degrades

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `ViterbiFretboardMapper`

The deterministic core. Replaces the stub body. The algorithm is the spec's; the code below has been run against GuitarSet's dev split while this plan was written (see Task 8's expected numbers).

**Files:**
- Modify: `apps/worker/src/guitarvis_worker/stages/fretboard.py` (replace entirely)
- Create: `apps/worker/tests/test_fretboard_mapper.py`
- Modify: `apps/worker/tests/test_stages.py` (remove the not-implemented test, fix the module docstring)
- Modify: `apps/worker/tests/test_cli.py` (replace the not-implemented test)
- Modify: `apps/worker/src/guitarvis_worker/pipeline.py` (`PipelineResult` docstring only)

**Interfaces:**
- Consumes: `FretboardResult` from Task 1; `guitarvis_core.fretboard.parse_pitch(name: str) -> int`.
- Produces: `guitarvis_worker.stages.fretboard.MapperCosts` — frozen dataclass with fields `move_weight: float`, `span_weight: float`, `height_weight: float`, `open_bonus: float`, `max_fret: int = 20`, `max_span: int = 4`, `beam: int = 50`. `ViterbiFretboardMapper(costs: MapperCosts | None = None)` with attribute `.costs: MapperCosts` and `.assign(notes, tuning) -> FretboardResult`. Warning texts: `"{n} note(s) outside the guitar's range {was/were} dropped."` and `"{n} note(s) in chords no hand could play {was/were} dropped."` — singular form `"1 note ... was dropped."`.

- [x] **Step 1: Write the failing tests**

Create `apps/worker/tests/test_fretboard_mapper.py`:

```python
"""Stage 4 without audio: feed note sequences, assert fingerings.

Musical accuracy on real recordings is the evaluation harness's job. These
tests pin the mechanics — grouping, playability, the costs' intent, the drop
rules — and the one invariant that holds whatever the costs are.
"""

import random
from collections.abc import Sequence

from guitarvis_core.contracts import FretboardResult, NoteEvent
from guitarvis_core.fretboard import check_invariant
from guitarvis_core.tabdoc import STANDARD_TUNING, Note
from guitarvis_worker.stages.fretboard import MapperCosts, ViterbiFretboardMapper

DROP_D = ("D2", "A2", "D3", "G3", "B3", "E4")
SEVEN_STRING = ("B1", "E2", "A2", "D3", "G3", "B3", "E4")


def note(onset: float, midi: int, confidence: float = 0.9) -> NoteEvent:
    return NoteEvent(onset=onset, duration=0.5, midi=midi, confidence=confidence)


def chord(onset: float, *midis: int) -> list[NoteEvent]:
    return [note(onset, midi) for midi in midis]


def assign(
    notes: Sequence[NoteEvent],
    tuning: Sequence[str] = STANDARD_TUNING,
    costs: MapperCosts | None = None,
) -> FretboardResult:
    return ViterbiFretboardMapper(costs).assign(notes, tuning)


def places(result: FretboardResult) -> list[tuple[int, int, int]]:
    """(midi, string, fret) per placed note, in output order."""
    return [(tab.midi, tab.string, tab.fret) for tab in result.notes]


def assert_invariant(result: FretboardResult, tuning: Sequence[str]) -> None:
    for index, tab in enumerate(result.notes):
        check_invariant(
            Note(
                id=f"n_{index:04d}",
                t=tab.onset,
                dur=tab.duration,
                midi=tab.midi,
                string=tab.string,
                fret=tab.fret,
                confidence=tab.confidence,
            ),
            tuning,
        )


def test_low_e_is_the_open_sixth_string() -> None:
    assert places(assign([note(0.0, 40)])) == [(40, 0, 0)]


def test_empty_input_gives_an_empty_result() -> None:
    result = assign([])
    assert result.notes == []
    assert result.warnings == []


def test_open_c_chord_gets_the_open_shape() -> None:
    # x32010
    result = assign(chord(0.0, 48, 52, 55, 60, 64))
    assert places(result) == [
        (48, 1, 3),
        (52, 2, 2),
        (55, 3, 0),
        (60, 4, 1),
        (64, 5, 0),
    ]


def test_f_barre_chord_is_found() -> None:
    # 133211: three notes under the index-finger barre, three fingers above it
    result = assign(chord(0.0, 41, 48, 53, 57, 60, 65))
    assert places(result) == [
        (41, 0, 1),
        (48, 1, 3),
        (53, 2, 3),
        (57, 3, 2),
        (60, 4, 1),
        (65, 5, 1),
    ]


def test_a_note_after_a_barre_stays_in_position() -> None:
    # On its own, C#4 sits lowest at string 4 fret 2. After a 7th-position B
    # barre the hand is up the neck, so string 3 fret 6 is one fret away.
    assert places(assign([note(1.0, 61)])) == [(61, 4, 2)]

    b_barre = chord(0.0, 47, 54, 59, 63, 66, 71)
    result = assign([*b_barre, note(1.0, 61)])
    assert places(result)[-1] == (61, 3, 6)


def test_notes_inside_the_window_share_a_voicing() -> None:
    # E2 and F#2 both need the low string. 49ms apart they are one voicing
    # and cannot both sound; 51ms apart they are two and both fit.
    together = assign([note(0.0, 40), note(0.049, 42)])
    assert places(together) == [(40, 0, 0)]
    assert together.warnings == ["1 note in chords no hand could play was dropped."]

    apart = assign([note(0.0, 40), note(0.051, 42)])
    assert places(apart) == [(40, 0, 0), (42, 0, 2)]
    assert apart.warnings == []


def test_grouping_is_anchored_to_the_first_note() -> None:
    # 0.08s is within 50ms of 0.04 but not of 0.0: a new voicing, so F#2 is
    # free to use the low string E2 already used. Chaining would drop it.
    result = assign([note(0.0, 40), note(0.04, 45), note(0.08, 42)])
    assert places(result) == [(40, 0, 0), (45, 1, 0), (42, 0, 2)]
    assert result.warnings == []


def test_more_notes_than_strings_drops_the_least_confident() -> None:
    notes = [
        note(0.0, midi, confidence=0.9 - 0.01 * index)
        for index, midi in enumerate((40, 45, 50, 55, 59, 64, 69))
    ]
    result = assign(notes)

    assert 69 not in [tab.midi for tab in result.notes]  # confidence 0.84
    assert len(result.notes) == 6
    assert result.warnings == ["1 note in chords no hand could play was dropped."]


def test_an_impossible_stretch_drops_the_least_confident_note() -> None:
    # F2 exists only at string 0 fret 1; B4's nearest fret is 7. No hand
    # spans that, so the weaker note goes.
    result = assign([note(0.0, 41, confidence=0.9), note(0.0, 71, confidence=0.5)])
    assert places(result) == [(41, 0, 1)]
    assert result.warnings == ["1 note in chords no hand could play was dropped."]


def test_notes_outside_the_range_are_dropped_with_one_warning() -> None:
    result = assign([note(0.0, 30), note(1.0, 100), note(2.0, 45)])
    assert places(result) == [(45, 1, 0)]
    assert result.warnings == ["2 notes outside the guitar's range were dropped."]


def test_drop_d_tuning_reaches_low_d() -> None:
    assert places(assign([note(0.0, 38)], tuning=DROP_D)) == [(38, 0, 0)]
    assert assign([note(0.0, 38)]).notes == []  # below standard tuning's low E


def test_seven_string_tuning_reaches_low_b() -> None:
    assert places(assign([note(0.0, 35)], tuning=SEVEN_STRING)) == [(35, 0, 0)]


def test_max_fret_is_configurable() -> None:
    # A#4 (70) needs fret 6 or higher on every string.
    result = assign([note(0.0, 70)], costs=MapperCosts(max_fret=5))
    assert result.notes == []
    assert result.warnings == ["1 note outside the guitar's range was dropped."]


def test_duplicate_pitch_at_one_onset_keeps_one() -> None:
    # A transcriber double-hit. E3's other positions (string 1 fret 7,
    # string 0 fret 12) are all more than 4 frets from string 2 fret 2 and
    # from each other, so no hand plays two E3s at once: one is dropped, with
    # a warning, and the one kept is placed correctly.
    result = assign([note(0.0, 52), note(0.0, 52)])

    assert places(result) == [(52, 2, 2)]
    assert result.warnings == ["1 note in chords no hand could play was dropped."]
    assert_invariant(result, STANDARD_TUNING)


def test_unsorted_input_comes_out_sorted() -> None:
    forward = [note(0.0, 40), note(0.5, 45), note(1.0, 50), note(1.5, 55)]
    result = assign(list(reversed(forward)))

    assert [tab.onset for tab in result.notes] == [0.0, 0.5, 1.0, 1.5]
    assert places(result) == places(assign(forward))


def test_output_is_deterministic() -> None:
    notes = [*chord(0.0, 48, 52, 55, 60, 64), note(1.0, 62), note(1.25, 64)]
    assert assign(notes) == assign(notes)


def test_every_placed_note_satisfies_the_invariant() -> None:
    """Whatever the costs pick, the pitch must be right. Seeded, so a failure
    reproduces."""
    rng = random.Random(4)
    for tuning in (STANDARD_TUNING, DROP_D, SEVEN_STRING):
        for _ in range(100):
            notes = [
                note(
                    onset=round(rng.uniform(0.0, 5.0), 3),
                    midi=rng.randint(30, 95),
                    confidence=round(rng.uniform(0.1, 1.0), 2),
                )
                for _ in range(rng.randint(0, 25))
            ]
            result = assign(notes, tuning=tuning)

            assert len(result.notes) <= len(notes)
            placed = sorted((tab.onset, tab.midi) for tab in result.notes)
            available = sorted((n.onset, n.midi) for n in notes)
            remaining = list(available)
            for pair in placed:
                remaining.remove(pair)  # every output note came from the input
            assert_invariant(result, tuning)
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest apps/worker/tests/test_fretboard_mapper.py -v`
Expected: collection error — `ImportError: cannot import name 'MapperCosts'`.

- [x] **Step 3: Implement the mapper**

Replace `apps/worker/src/guitarvis_worker/stages/fretboard.py` entirely:

```python
"""Stage 4 — fretboard assignment. The deterministic core.

Notes within 50ms of a voicing's first note group into that voicing; each
voicing has a set of playable fingerings filtered by physical constraints; a
Viterbi pass minimises total cost, dominated by hand-position movement between
consecutive voicings because real players stay put.

Testable without audio: feed note sequences, assert fingerings. Every note it
emits must satisfy guitarvis_core.fretboard.check_invariant — a note that
cannot be placed correctly is dropped with a warning, never approximated.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from guitarvis_core.contracts import FretboardResult, NoteEvent, TabNote
from guitarvis_core.fretboard import parse_pitch

VOICING_WINDOW_SEC = 0.05
FINGERS_BEYOND_BARRE = 3  # the index finger holds the lowest fret; three remain


@dataclass(frozen=True)
class MapperCosts:
    """Every tunable number in the mapper. Tuned on the dev split, not by edit.

    Evaluation results record the values they ran with, so a change here shows
    up in the eval/results/ history next to the number it moved.
    """

    move_weight: float = 1.0
    span_weight: float = 0.5
    height_weight: float = 0.1
    open_bonus: float = 0.3
    max_fret: int = 20
    max_span: int = 4
    beam: int = 50


@dataclass(frozen=True)
class _Fingering:
    """One way to play one voicing: a (string, fret) per note, in note order."""

    places: tuple[tuple[int, int], ...]
    cost: float
    position: int | None  # lowest fretted fret; None when every string is open

    @property
    def order_key(self) -> tuple[float, int, tuple[int, ...]]:
        """Cheapest first, then lower frets, then lower strings: determinism."""
        frets = sum(fret for _, fret in self.places)
        strings = tuple(string for string, _ in self.places)
        return (self.cost, frets, strings)


class ViterbiFretboardMapper:
    """Implements guitarvis_core.contracts.FretboardMapper."""

    def __init__(self, costs: MapperCosts | None = None) -> None:
        self.costs = costs or MapperCosts()

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> FretboardResult:
        open_pitches = [parse_pitch(name) for name in tuning]

        placeable = [n for n in notes if self._candidates(n, open_pitches)]
        out_of_range = len(notes) - len(placeable)

        voicings: list[list[NoteEvent]] = []
        fingerings: list[list[_Fingering]] = []
        unplayable = 0
        for voicing in _group(placeable):
            options = self._fingerings(voicing, open_pitches)
            while not options:
                # Drop the least confident note (the latest, among equals)
                # until a fingering exists. A single placeable note is always
                # playable, so this ends.
                weakest = min(
                    range(len(voicing)), key=lambda i: (voicing[i].confidence, -i)
                )
                voicing = voicing[:weakest] + voicing[weakest + 1 :]
                unplayable += 1
                options = self._fingerings(voicing, open_pitches)
            voicings.append(voicing)
            fingerings.append(options)

        path = self._viterbi(fingerings)
        placed = [
            TabNote(
                onset=note.onset,
                duration=note.duration,
                midi=note.midi,
                string=string,
                fret=fret,
                confidence=note.confidence,
            )
            for voicing, choice in zip(voicings, path, strict=True)
            for note, (string, fret) in zip(voicing, choice.places, strict=True)
        ]
        placed.sort(key=lambda tab: (tab.onset, tab.string))

        warnings = []
        if out_of_range:
            warnings.append(
                f"{_notes(out_of_range)} outside the guitar's range "
                f"{_were(out_of_range)} dropped."
            )
        if unplayable:
            warnings.append(
                f"{_notes(unplayable)} in chords no hand could play "
                f"{_were(unplayable)} dropped."
            )
        return FretboardResult(notes=placed, warnings=warnings)

    def _candidates(
        self, note: NoteEvent, open_pitches: Sequence[int]
    ) -> list[tuple[int, int]]:
        """Every (string, fret) that sounds this note's pitch."""
        return [
            (string, note.midi - open_pitch)
            for string, open_pitch in enumerate(open_pitches)
            if 0 <= note.midi - open_pitch <= self.costs.max_fret
        ]

    def _fingerings(
        self, voicing: Sequence[NoteEvent], open_pitches: Sequence[int]
    ) -> list[_Fingering]:
        """The `beam` cheapest playable fingerings of one voicing."""
        if len(voicing) > len(open_pitches):
            return []  # more notes than strings: nothing to enumerate

        per_note = [self._candidates(note, open_pitches) for note in voicing]
        found: list[_Fingering] = []

        def extend(chosen: list[tuple[int, int]], used: set[int]) -> None:
            if len(chosen) == len(per_note):
                fingering = self._score(tuple(chosen))
                if fingering is not None:
                    found.append(fingering)
                return
            for string, fret in per_note[len(chosen)]:
                if string not in used:
                    chosen.append((string, fret))
                    used.add(string)
                    extend(chosen, used)
                    used.discard(string)
                    chosen.pop()

        extend([], set())
        found.sort(key=lambda fingering: fingering.order_key)
        return found[: self.costs.beam]

    def _score(self, places: tuple[tuple[int, int], ...]) -> _Fingering | None:
        """The cost of one fingering, or None when no hand can hold it."""
        fretted = [fret for _, fret in places if fret > 0]
        open_strings = len(places) - len(fretted)
        if not fretted:
            return _Fingering(places, -self.costs.open_bonus * open_strings, None)

        low, high = min(fretted), max(fretted)
        span = high - low
        if span > self.costs.max_span:
            return None
        # The index finger barres every note at the lowest fret; each other
        # fretted note needs a finger of its own.
        if sum(1 for fret in fretted if fret > low) > FINGERS_BEYOND_BARRE:
            return None

        cost = (
            self.costs.span_weight * span
            + self.costs.height_weight * low
            - self.costs.open_bonus * open_strings
        )
        return _Fingering(places, cost, low)

    def _move(self, before: _Fingering, after: _Fingering) -> float:
        """Hand movement. Open strings free the fretting hand, so moving into
        or out of an all-open voicing is free."""
        if before.position is None or after.position is None:
            return 0.0
        return self.costs.move_weight * abs(before.position - after.position)

    def _viterbi(self, fingerings: Sequence[Sequence[_Fingering]]) -> list[_Fingering]:
        """The cheapest fingering per voicing, over the whole sequence."""
        if not fingerings:
            return []

        totals = [fingering.cost for fingering in fingerings[0]]
        back: list[list[int]] = []
        for previous, current in zip(fingerings, fingerings[1:], strict=False):
            step_totals: list[float] = []
            step_back: list[int] = []
            for option in current:
                # `previous` is sorted by order_key, so strict `<` keeps the
                # first — lowest-fret — predecessor among equal costs.
                best, best_index = totals[0] + self._move(previous[0], option), 0
                for index in range(1, len(previous)):
                    total = totals[index] + self._move(previous[index], option)
                    if total < best:
                        best, best_index = total, index
                step_totals.append(best + option.cost)
                step_back.append(best_index)
            totals = step_totals
            back.append(step_back)

        index = min(range(len(totals)), key=lambda i: totals[i])
        path = [fingerings[-1][index]]
        for step in range(len(fingerings) - 2, -1, -1):
            index = back[step][index]
            path.append(fingerings[step][index])
        path.reverse()
        return path


def _group(notes: Sequence[NoteEvent]) -> list[list[NoteEvent]]:
    """Voicings: notes within VOICING_WINDOW_SEC of a voicing's first note.

    Anchored to the first note, not the latest, so a fast run cannot chain
    into one many-note chord.
    """
    voicings: list[list[NoteEvent]] = []
    for note in sorted(notes, key=lambda n: (n.onset, n.midi)):
        if voicings and note.onset - voicings[-1][0].onset <= VOICING_WINDOW_SEC:
            voicings[-1].append(note)
        else:
            voicings.append([note])
    return voicings


def _notes(count: int) -> str:
    return f"{count} note" if count == 1 else f"{count} notes"


def _were(count: int) -> str:
    return "was" if count == 1 else "were"


if TYPE_CHECKING:  # Static conformance: isinstance compares method names
    from guitarvis_core.contracts import FretboardMapper  # only, so this

    _conforms: FretboardMapper = ViterbiFretboardMapper()  # assignment is
    # what actually checks the signature.
```

Note on the backtrack: `back[k]` holds, for each fingering of voicing `k + 1`, the index of its best predecessor in voicing `k`. Walking `step` from `len - 2` down to `0` reads `back[step]` to go from voicing `step + 1` to voicing `step`.

- [x] **Step 4: Run the mapper tests**

Run: `uv run pytest apps/worker/tests/test_fretboard_mapper.py -v`
Expected: all PASS.

- [x] **Step 5: Retire the stub's tests and update the CLI test**

In `apps/worker/tests/test_stages.py`: delete `test_fretboard_is_not_implemented_yet`, remove the now-unused `import pytest` and `STANDARD_TUNING` import, and replace the module docstring with:

```python
"""Every stage satisfies its protocol, and no stage module drags in the ML
stack at import time."""
```

In `apps/worker/tests/test_cli.py`, add `NoteEvent` to the `guitarvis_core.contracts` import and replace `test_reports_the_fretboard_stage_is_not_implemented` with:

```python
@requires_ffprobe
def test_places_transcribed_notes_on_the_neck(
    tmp_path: Path,
    stub_stages: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class OneNote:
        def transcribe(self, stem_path: Path) -> list[NoteEvent]:
            return [NoteEvent(onset=0.1, duration=0.5, midi=40, confidence=0.9)]

    monkeypatch.setattr(cli, "BasicPitchTranscriber", lambda **kwargs: OneNote())
    out = tmp_path / "song.json"
    code = cli.main(["process", str(write_wav(tmp_path / "song.wav")), "-o", str(out)])

    assert code == 0
    notes = json.loads(out.read_text())["notes"]
    assert [(n["string"], n["fret"], n["midi"]) for n in notes] == [(0, 0, 40)]
    assert "1 notes placed" in capsys.readouterr().err
```

- [x] **Step 6: Update `PipelineResult`'s docstring**

In `pipeline.py`, replace the `PipelineResult` docstring with:

```python
    """What `run_pipeline` hands back: the document plus what stage 2 saw.

    `transcribed_note_count` is how many note events transcription produced,
    before stage 4 dropped any it could not place. Comparing it with
    `len(document.notes)` shows how much the fretboard stage lost. Returned
    as data rather than folded into a warning string so a caller gets it
    without parsing prose.
    """
```

- [x] **Step 7: Run the whole Python suite**

Run: `uv run pytest -v`
Expected: all PASS (ffprobe-dependent tests may SKIP if ffmpeg is absent; install it to run them — `sudo apt install ffmpeg`).

- [x] **Step 8: Add the degradation rows**

In `docs/specs/001-guitarvis-design/spec.md`'s *Failure handling* table and `.claude/skills/pipeline-stage/SKILL.md`'s *Degrade, do not fail* table, append:

```markdown
| Fretboard mapper raises | No notes; timing and chords unaffected by it; a warning says why |
| Notes no hand could play, or outside the neck's range | Those notes dropped, never approximated; a warning gives the count |
```

- [x] **Step 9: Run `make check` and commit**

Run: `make check`
Expected: exit 0.

```bash
git add apps/worker docs/specs/001-guitarvis-design/spec.md .claude/skills/pipeline-stage/SKILL.md
git commit -m "feat: Viterbi fretboard mapper for stage 4

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: GuitarSet reader and split

Standard-library JAMS reading, the player split, and where the data lives. No worker dependency yet.

**Files:**
- Create: `apps/eval/src/guitarvis_eval/dataset.py`
- Create: `apps/eval/tests/guitarset_fixture.py` (test helper, not a test module)
- Create: `apps/eval/tests/test_dataset.py`

**Interfaces:**
- Consumes: nothing.
- Produces, in `guitarvis_eval.dataset`: `Split = Literal["test", "dev"]`; `TEST_PLAYERS: frozenset[str]`; `DEFAULT_DATA_DIR: Path`; `ANNOTATION_DIR = "annotation"`; `MIC_AUDIO_DIR = "audio_mono-mic"`; `class DatasetMissing(Exception)`; frozen dataclasses `TruthNote(onset: float, duration: float, midi: int, string: int)`, `TruthChord(start: float, end: float, label: str)`, `Excerpt(name: str, player: str, style: str, duration: float, notes: list[TruthNote], chords: list[TruthChord])`; `data_dir() -> Path`; `excerpt_paths(root: Path, split: Split) -> list[Path]`; `mic_audio_path(root: Path, excerpt: Excerpt) -> Path`; `read_jams(path: Path) -> Excerpt`.
- Produces, in `apps/eval/tests/guitarset_fixture.py`: `write_jams(directory: Path, name: str, *, notes: Sequence[tuple[float, float, float, int]] = (), performed: Sequence[tuple[float, float, str]] = (), instructed: Sequence[tuple[float, float, str]] = (), duration: float = 10.0) -> Path` — notes are `(onset, duration, midi_float, string)`, chords are `(time, duration, label)`.

- [x] **Step 1: Write the fixture helper**

Create `apps/eval/tests/guitarset_fixture.py`:

```python
"""Tiny JAMS files shaped like GuitarSet's, for tests that need no dataset.

The real layout, as read from annotation.zip: six `note_midi` annotations
whose data_source is the string index, six `pitch_contour` annotations (which
the harness ignores), and two `chord` annotations — instructed (empty
data_source) then performed (non-empty data_source).
"""

import json
from collections.abc import Sequence
from pathlib import Path

PERFORMED_SOURCE = "Semi-automatic chord transcription with manual verification"


def _observations(rows: Sequence[tuple[float, float, object]]) -> list[dict]:
    return [
        {"time": t, "duration": d, "value": v, "confidence": None} for t, d, v in rows
    ]


def write_jams(
    directory: Path,
    name: str,
    *,
    notes: Sequence[tuple[float, float, float, int]] = (),
    performed: Sequence[tuple[float, float, str]] = (),
    instructed: Sequence[tuple[float, float, str]] = (),
    duration: float = 10.0,
) -> Path:
    annotations: list[dict] = []
    for string in range(6):
        annotations.append(
            {
                "namespace": "pitch_contour",
                "annotation_metadata": {"data_source": str(string)},
                "data": {"time": [], "duration": [], "value": [], "confidence": []},
            }
        )
        annotations.append(
            {
                "namespace": "note_midi",
                "annotation_metadata": {"data_source": str(string)},
                "data": _observations(
                    [(t, d, midi) for t, d, midi, s in notes if s == string]
                ),
            }
        )
    annotations.append(
        {
            "namespace": "chord",
            "annotation_metadata": {"data_source": ""},
            "data": _observations(instructed),
        }
    )
    annotations.append(
        {
            "namespace": "chord",
            "annotation_metadata": {"data_source": PERFORMED_SOURCE},
            "data": _observations(performed),
        }
    )

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.jams"
    path.write_text(
        json.dumps(
            {
                "annotations": annotations,
                "file_metadata": {"title": name, "duration": duration},
                "sandbox": {},
            }
        )
    )
    return path
```

- [x] **Step 2: Write the failing tests**

Create `apps/eval/tests/test_dataset.py`:

```python
"""Reading GuitarSet: strings, rounding, which chords count, and the split."""

from pathlib import Path

import pytest
from guitarset_fixture import write_jams
from guitarvis_eval.dataset import (
    DEFAULT_DATA_DIR,
    DatasetMissing,
    TruthChord,
    TruthNote,
    data_dir,
    excerpt_paths,
    mic_audio_path,
    read_jams,
)


def test_notes_take_their_string_from_the_annotation(tmp_path: Path) -> None:
    path = write_jams(
        tmp_path,
        "00_BN1-129-Eb_comp",
        notes=[(0.5, 0.4, 51.04, 1), (0.1, 0.3, 44.02, 0)],
    )
    excerpt = read_jams(path)

    # Rounded to MIDI, sorted by onset, string straight from data_source.
    assert excerpt.notes == [
        TruthNote(onset=0.1, duration=0.3, midi=44, string=0),
        TruthNote(onset=0.5, duration=0.4, midi=51, string=1),
    ]


def test_pitches_round_to_the_nearest_semitone(tmp_path: Path) -> None:
    path = write_jams(tmp_path, "00_x_solo", notes=[(0.0, 0.1, 58.51, 2)])
    assert read_jams(path).notes[0].midi == 59


def test_performed_chords_are_used_not_instructed(tmp_path: Path) -> None:
    path = write_jams(
        tmp_path,
        "00_x_comp",
        instructed=[(0.0, 4.0, "D#:maj")],
        performed=[(0.0, 4.0, "D#:sus2(7)/1"), (4.0, 2.0, "G#:maj6(*5)/1")],
    )
    assert read_jams(path).chords == [
        TruthChord(start=0.0, end=4.0, label="D#:sus2(7)/1"),
        TruthChord(start=4.0, end=6.0, label="G#:maj6(*5)/1"),
    ]


def test_excerpt_metadata_comes_from_the_name(tmp_path: Path) -> None:
    excerpt = read_jams(write_jams(tmp_path, "05_Rock2-85-F_solo", duration=21.5))

    assert excerpt.name == "05_Rock2-85-F_solo"
    assert excerpt.player == "05"
    assert excerpt.style == "solo"
    assert excerpt.duration == 21.5


def test_split_is_by_player(tmp_path: Path) -> None:
    annotations = tmp_path / "annotation"
    for name in ("05_b_solo", "00_a_comp", "05_a_comp", "04_a_solo"):
        write_jams(annotations, name)

    assert [p.stem for p in excerpt_paths(tmp_path, "test")] == [
        "05_a_comp",
        "05_b_solo",
    ]
    assert [p.stem for p in excerpt_paths(tmp_path, "dev")] == [
        "00_a_comp",
        "04_a_solo",
    ]


def test_missing_dataset_says_how_to_get_it(tmp_path: Path) -> None:
    with pytest.raises(DatasetMissing, match="make eval-data"):
        excerpt_paths(tmp_path, "test")


def test_data_dir_honours_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GUITARSET_DIR", str(tmp_path))
    assert data_dir() == tmp_path

    monkeypatch.delenv("GUITARSET_DIR")
    assert data_dir() == DEFAULT_DATA_DIR


def test_mic_audio_path_follows_the_archive_naming(tmp_path: Path) -> None:
    excerpt = read_jams(write_jams(tmp_path, "00_BN1-129-Eb_comp"))
    assert mic_audio_path(Path("/data"), excerpt) == Path(
        "/data/audio_mono-mic/00_BN1-129-Eb_comp_mic.wav"
    )
```

- [x] **Step 3: Run them to verify they fail**

Run: `uv run pytest apps/eval/tests/test_dataset.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'guitarvis_eval.dataset'`.

- [x] **Step 4: Implement the reader**

Create `apps/eval/src/guitarvis_eval/dataset.py`:

```python
"""GuitarSet on disk: where it lives, how its JAMS files read, how it splits.

A standard-library reader rather than `jams` or `mirdata`: an excerpt is six
note arrays and a chord array in one JSON file, and that is all the harness
needs from it.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Split = Literal["test", "dev"]

TEST_PLAYERS = frozenset({"05"})
DEFAULT_DATA_DIR = Path.home() / ".cache" / "guitarvis" / "guitarset"
ANNOTATION_DIR = "annotation"
MIC_AUDIO_DIR = "audio_mono-mic"


class DatasetMissing(Exception):
    """GuitarSet is not where the harness looked for it."""


@dataclass(frozen=True)
class TruthNote:
    onset: float
    duration: float
    midi: int
    string: int  # 0 is the lowest string, as in tabdoc.Note


@dataclass(frozen=True)
class TruthChord:
    start: float
    end: float
    label: str  # as annotated, e.g. "D#:sus2(7)/1"


@dataclass(frozen=True)
class Excerpt:
    name: str  # e.g. "05_BN1-129-Eb_comp"
    player: str  # "00".."05"
    style: str  # "comp" or "solo"
    duration: float
    notes: list[TruthNote]
    chords: list[TruthChord]


def data_dir() -> Path:
    """GUITARSET_DIR if set, else the cache `make eval-data` fills."""
    configured = os.environ.get("GUITARSET_DIR")
    return Path(configured) if configured else DEFAULT_DATA_DIR


def excerpt_paths(root: Path, split: Split) -> list[Path]:
    """The split's JAMS files, sorted. Split by player so one player's habits
    cannot leak between tuning and measurement."""
    annotations = root / ANNOTATION_DIR
    paths = sorted(annotations.glob("*.jams"))
    if not paths:
        raise DatasetMissing(
            f"no GuitarSet annotations under {annotations}. Run `make eval-data`, "
            "or point GUITARSET_DIR at an existing copy."
        )
    in_test = split == "test"
    return [p for p in paths if (p.name[:2] in TEST_PLAYERS) == in_test]


def mic_audio_path(root: Path, excerpt: Excerpt) -> Path:
    return root / MIC_AUDIO_DIR / f"{excerpt.name}_mic.wav"


def read_jams(path: Path) -> Excerpt:
    """One GuitarSet excerpt.

    Each of the six `note_midi` annotations is one string; its
    `annotation_metadata.data_source` is the string index with 0 as low E —
    the same convention as tabdoc.Note.string. Pitches are annotated as
    floats and rounded to the nearest MIDI number.

    There are two `chord` annotations: the instructed chords from the lead
    sheet (empty data_source) and the performed chords transcribed from what
    was actually played (non-empty data_source). The harness scores against
    what was played.
    """
    document = json.loads(path.read_text())
    name = document["file_metadata"]["title"]
    notes: list[TruthNote] = []
    chord_annotations = []

    for annotation in document["annotations"]:
        namespace = annotation["namespace"]
        if namespace == "note_midi":
            string = int(annotation["annotation_metadata"]["data_source"])
            notes.extend(
                TruthNote(
                    onset=float(obs["time"]),
                    duration=float(obs["duration"]),
                    midi=round(obs["value"]),
                    string=string,
                )
                for obs in annotation["data"]
            )
        elif namespace == "chord":
            chord_annotations.append(annotation)

    performed = [
        a for a in chord_annotations if a["annotation_metadata"].get("data_source")
    ]
    chords = [
        TruthChord(
            start=float(obs["time"]),
            end=float(obs["time"]) + float(obs["duration"]),
            label=str(obs["value"]),
        )
        for obs in (performed[0]["data"] if performed else [])
    ]

    notes.sort(key=lambda n: (n.onset, n.string))
    return Excerpt(
        name=name,
        player=name[:2],
        style=name.rsplit("_", 1)[-1],
        duration=float(document["file_metadata"]["duration"]),
        notes=notes,
        chords=chords,
    )
```

- [x] **Step 5: Run the tests**

Run: `uv run pytest apps/eval/tests/test_dataset.py -v`
Expected: all PASS.

- [x] **Step 6: Run `make check` and commit**

Run: `make check`
Expected: exit 0.

```bash
git add apps/eval
git commit -m "feat: GuitarSet JAMS reader and player split

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Baseline, oracle scoring, and totals

**Files:**
- Modify: `apps/eval/pyproject.toml` (depend on `guitarvis-worker`)
- Modify: `uv.lock` (regenerated by `uv lock`)
- Create: `apps/eval/src/guitarvis_eval/baseline.py`
- Create: `apps/eval/src/guitarvis_eval/metrics.py`
- Create: `apps/eval/src/guitarvis_eval/runner.py`
- Create: `apps/eval/tests/test_oracle.py`

**Interfaces:**
- Consumes: `guitarvis_eval.dataset.{Excerpt, TruthNote}` (Task 3); `ViterbiFretboardMapper`, `FretboardResult` (Tasks 1–2).
- Produces:
  - `guitarvis_eval.baseline.LowestFretMapper` — implements `FretboardMapper`; `MAX_FRET = 20`.
  - `guitarvis_eval.metrics.Tally(correct: int = 0, total: int = 0)` with `__add__` and `.rate -> float | None`; `NoteCounts(matched: int = 0, truth: int = 0, estimated: int = 0)` with `__add__`, `.precision`, `.recall`, `.f1` (each `float | None`); `oracle_string_tally(truth: Sequence[TruthNote], placed: Sequence[TabNote]) -> Tally`.
  - `guitarvis_eval.runner.ExcerptScore(name: str, style: str, strings: Tally, baseline_strings: Tally | None = None, notes: NoteCounts | None = None, chords: Tally | None = None)`; `score_oracle(excerpt: Excerpt, mapper: FretboardMapper, baseline: FretboardMapper) -> ExcerptScore`; `summarize(scores: Sequence[ExcerptScore]) -> dict[str, object]` keyed `"all"`, then each style; `score_to_dict(score: ExcerptScore) -> dict[str, object]`. Each group's dict: `{"excerpts": int, "string": {"correct", "total", "rate"}, ["baseline_string": {...}], ["note": {"matched","truth","estimated","precision","recall","f1"}], ["chord": {...}]}`.

- [x] **Step 1: Depend on the worker**

In `apps/eval/pyproject.toml` change `dependencies = ["guitarvis-core"]` to:

```toml
# The worker's base install is light (no ml extra): it supplies the mapper
# under test. The worker must never import this package in return.
dependencies = ["guitarvis-core", "guitarvis-worker"]
```

Run: `uv lock && uv sync`
Expected: lock updates; sync succeeds with no new third-party packages.

- [x] **Step 2: Write the failing tests**

Create `apps/eval/tests/test_oracle.py`:

```python
"""Oracle mode: ground-truth pitches into the mapper, strings compared.

Also the baseline, and the counting that makes totals honest.
"""

from pathlib import Path

from guitarset_fixture import write_jams
from guitarvis_core.contracts import FretboardMapper, NoteEvent, TabNote
from guitarvis_core.tabdoc import STANDARD_TUNING
from guitarvis_eval.baseline import LowestFretMapper
from guitarvis_eval.dataset import TruthNote, read_jams
from guitarvis_eval.metrics import NoteCounts, Tally, oracle_string_tally
from guitarvis_eval.runner import score_oracle, score_to_dict, summarize
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper

_baseline: FretboardMapper = LowestFretMapper()


def test_baseline_takes_the_lowest_fret() -> None:
    result = LowestFretMapper().assign(
        [NoteEvent(0.0, 0.5, 64, 0.9), NoteEvent(1.0, 0.5, 59, 0.9)],
        STANDARD_TUNING,
    )
    assert [(t.string, t.fret) for t in result.notes] == [(5, 0), (4, 0)]


def test_baseline_drops_out_of_range_notes() -> None:
    result = LowestFretMapper().assign([NoteEvent(0.0, 0.5, 30, 0.9)], STANDARD_TUNING)
    assert result.notes == []
    assert result.warnings == ["1 out-of-range notes dropped."]


def test_oracle_tally_pairs_by_onset_and_pitch() -> None:
    truth = [TruthNote(0.0, 0.5, 52, 1), TruthNote(1.0, 0.5, 57, 3)]
    placed = [
        TabNote(0.0, 0.5, 52, 1, 7, 1.0),  # right string
        TabNote(1.0, 0.5, 57, 2, 7, 1.0),  # wrong string
    ]
    assert oracle_string_tally(truth, placed) == Tally(correct=1, total=2)


def test_a_dropped_note_counts_as_wrong() -> None:
    truth = [TruthNote(0.0, 0.5, 52, 1)]
    assert oracle_string_tally(truth, []) == Tally(correct=0, total=1)


def test_the_same_pitch_twice_is_matched_once_each() -> None:
    truth = [TruthNote(0.0, 0.5, 52, 1), TruthNote(0.0, 0.5, 52, 2)]
    placed = [TabNote(0.0, 0.5, 52, 1, 7, 1.0), TabNote(0.0, 0.5, 52, 1, 7, 1.0)]
    assert oracle_string_tally(truth, placed) == Tally(correct=1, total=2)


def test_tallies_add_before_dividing() -> None:
    total = Tally(1, 4) + Tally(30, 40)
    assert total == Tally(31, 44)
    assert total.rate == 31 / 44
    assert Tally().rate is None


def test_note_counts_f1() -> None:
    counts = NoteCounts(matched=8, truth=10, estimated=16)
    assert counts.precision == 0.5
    assert counts.recall == 0.8
    assert counts.f1 == 2 * 8 / 26
    assert NoteCounts().f1 is None


def test_score_oracle_on_an_open_e_minor_chord(tmp_path: Path) -> None:
    # Em, 022000: both mapper and baseline should get every string right.
    notes = [
        (0.0, 1.0, float(m), s)
        for m, s in ((40, 0), (47, 1), (52, 2), (55, 3), (59, 4), (64, 5))
    ]
    excerpt = read_jams(write_jams(tmp_path, "05_x_comp", notes=notes))

    score = score_oracle(excerpt, ViterbiFretboardMapper(), LowestFretMapper())

    assert score.strings == Tally(6, 6)
    assert score.baseline_strings == Tally(6, 6)


def test_empty_excerpt_scores_none_not_zero_division(tmp_path: Path) -> None:
    excerpt = read_jams(write_jams(tmp_path, "05_empty_solo"))
    score = score_oracle(excerpt, ViterbiFretboardMapper(), LowestFretMapper())

    totals = summarize([score])
    assert totals["all"] == {
        "excerpts": 1,
        "string": {"correct": 0, "total": 0, "rate": None},
        "baseline_string": {"correct": 0, "total": 0, "rate": None},
    }


def test_summary_groups_by_style_and_weights_by_notes(tmp_path: Path) -> None:
    comp = read_jams(write_jams(tmp_path, "05_a_comp", notes=[(0.0, 1.0, 40.0, 0)]))
    solo = read_jams(
        write_jams(
            tmp_path,
            "05_a_solo",
            notes=[(t, 0.2, 64.0, 5) for t in (0.0, 1.0, 2.0)],
        )
    )
    mapper, baseline = ViterbiFretboardMapper(), LowestFretMapper()
    summary = summarize([score_oracle(e, mapper, baseline) for e in (comp, solo)])

    assert list(summary) == ["all", "comp", "solo"]
    assert summary["all"]["string"] == {"correct": 4, "total": 4, "rate": 1.0}  # type: ignore[index]
    assert summary["solo"]["excerpts"] == 1  # type: ignore[index]


def test_score_to_dict_names_the_excerpt(tmp_path: Path) -> None:
    excerpt = read_jams(write_jams(tmp_path, "05_a_comp", notes=[(0.0, 1.0, 40.0, 0)]))
    row = score_to_dict(
        score_oracle(excerpt, ViterbiFretboardMapper(), LowestFretMapper())
    )
    assert row["name"] == "05_a_comp"
    assert row["style"] == "comp"
    assert row["string"] == {"correct": 1, "total": 1, "rate": 1.0}
```

- [x] **Step 3: Run them to verify they fail**

Run: `uv run pytest apps/eval/tests/test_oracle.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'guitarvis_eval.baseline'`.

- [x] **Step 4: Implement the baseline**

Create `apps/eval/src/guitarvis_eval/baseline.py`:

```python
"""The number the mapper has to beat.

Every note at its lowest playable fret: no voicings, no search, no memory of
where the hand just was. It lives in the harness, never in the worker — it
is a reference point, and a plausible-looking wrong tab is exactly what the
pipeline must not ship.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from guitarvis_core.contracts import FretboardResult, NoteEvent, TabNote
from guitarvis_core.fretboard import parse_pitch

MAX_FRET = 20


class LowestFretMapper:
    """Implements guitarvis_core.contracts.FretboardMapper, naively."""

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> FretboardResult:
        open_pitches = [parse_pitch(name) for name in tuning]
        placed = []
        for note in notes:
            options = [
                (note.midi - open_pitch, string)
                for string, open_pitch in enumerate(open_pitches)
                if 0 <= note.midi - open_pitch <= MAX_FRET
            ]
            if not options:
                continue
            fret, string = min(options)
            placed.append(
                TabNote(
                    onset=note.onset,
                    duration=note.duration,
                    midi=note.midi,
                    string=string,
                    fret=fret,
                    confidence=note.confidence,
                )
            )
        dropped = len(notes) - len(placed)
        warnings = [f"{dropped} out-of-range notes dropped."] if dropped else []
        return FretboardResult(notes=placed, warnings=warnings)


if TYPE_CHECKING:
    from guitarvis_core.contracts import FretboardMapper

    _conforms: FretboardMapper = LowestFretMapper()
```

- [x] **Step 5: Implement the counting metrics**

Create `apps/eval/src/guitarvis_eval/metrics.py`:

```python
"""The three numbers, and nothing that decides whether they are good enough.

Everything here counts rather than averages, so excerpts add up before
anything is divided: a 4-note excerpt must not weigh as much as a 400-note
one.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from guitarvis_core.contracts import TabNote

from guitarvis_eval.dataset import TruthNote


@dataclass(frozen=True)
class Tally:
    correct: int = 0
    total: int = 0

    def __add__(self, other: "Tally") -> "Tally":
        return Tally(self.correct + other.correct, self.total + other.total)

    @property
    def rate(self) -> float | None:
        return self.correct / self.total if self.total else None


@dataclass(frozen=True)
class NoteCounts:
    matched: int = 0
    truth: int = 0
    estimated: int = 0

    def __add__(self, other: "NoteCounts") -> "NoteCounts":
        return NoteCounts(
            self.matched + other.matched,
            self.truth + other.truth,
            self.estimated + other.estimated,
        )

    @property
    def precision(self) -> float | None:
        return self.matched / self.estimated if self.estimated else None

    @property
    def recall(self) -> float | None:
        return self.matched / self.truth if self.truth else None

    @property
    def f1(self) -> float | None:
        if not self.truth and not self.estimated:
            return None
        return 2 * self.matched / (self.truth + self.estimated)


def oracle_string_tally(truth: Sequence[TruthNote], placed: Sequence[TabNote]) -> Tally:
    """Oracle mode: the mapper saw exactly the truth's onsets and pitches.

    Pair by (onset, pitch). A truth note the mapper dropped has no partner
    and counts as wrong: dropping a note is not a way to score better.
    """
    strings: dict[tuple[float, int], list[int]] = defaultdict(list)
    for tab in placed:
        strings[(tab.onset, tab.midi)].append(tab.string)

    correct = 0
    for note in truth:
        candidates = strings.get((note.onset, note.midi), [])
        if note.string in candidates:
            candidates.remove(note.string)
            correct += 1
    return Tally(correct, len(truth))
```

- [x] **Step 6: Implement the runner (oracle half)**

Create `apps/eval/src/guitarvis_eval/runner.py`:

```python
"""Scores one excerpt at a time and adds the scores up.

Stages arrive by injection, as they do in the worker's pipeline, so every
path through here is testable with stubs and no audio.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from guitarvis_core.contracts import FretboardMapper, NoteEvent
from guitarvis_core.tabdoc import STANDARD_TUNING

from guitarvis_eval.dataset import Excerpt
from guitarvis_eval.metrics import NoteCounts, Tally, oracle_string_tally


@dataclass(frozen=True)
class ExcerptScore:
    name: str
    style: str
    strings: Tally  # the mapper's string accuracy
    baseline_strings: Tally | None = None  # oracle mode only
    notes: NoteCounts | None = None  # full mode only
    chords: Tally | None = None  # full mode only


def score_oracle(
    excerpt: Excerpt, mapper: FretboardMapper, baseline: FretboardMapper
) -> ExcerptScore:
    """Ground-truth pitches in, so string accuracy measures stage 4 alone."""
    events = [
        NoteEvent(onset=n.onset, duration=n.duration, midi=n.midi, confidence=1.0)
        for n in excerpt.notes
    ]
    return ExcerptScore(
        name=excerpt.name,
        style=excerpt.style,
        strings=oracle_string_tally(
            excerpt.notes, mapper.assign(events, STANDARD_TUNING).notes
        ),
        baseline_strings=oracle_string_tally(
            excerpt.notes, baseline.assign(events, STANDARD_TUNING).notes
        ),
    )


def summarize(scores: Sequence[ExcerptScore]) -> dict[str, object]:
    """Totals overall ("all") and per style ("comp", "solo"). Counts are
    summed before dividing, so long excerpts weigh more than short ones."""
    groups: dict[str, list[ExcerptScore]] = {"all": list(scores)}
    for score in scores:
        groups.setdefault(score.style, []).append(score)
    return {group: _total(members) for group, members in sorted(groups.items())}


def score_to_dict(score: ExcerptScore) -> dict[str, object]:
    return {"name": score.name, "style": score.style, **_total([score])}


def _total(scores: Sequence[ExcerptScore]) -> dict[str, object]:
    out: dict[str, object] = {
        "excerpts": len(scores),
        "string": _tally(sum((s.strings for s in scores), Tally())),
    }
    baselines = [s.baseline_strings for s in scores if s.baseline_strings is not None]
    if baselines:
        out["baseline_string"] = _tally(sum(baselines, Tally()))
    counts = [s.notes for s in scores if s.notes is not None]
    if counts:
        notes = sum(counts, NoteCounts())
        out["note"] = {
            "matched": notes.matched,
            "truth": notes.truth,
            "estimated": notes.estimated,
            "precision": notes.precision,
            "recall": notes.recall,
            "f1": notes.f1,
        }
    chords = [s.chords for s in scores if s.chords is not None]
    if chords:
        out["chord"] = _tally(sum(chords, Tally()))
    return out


def _tally(tally: Tally) -> dict[str, object]:
    return {"correct": tally.correct, "total": tally.total, "rate": tally.rate}
```

`sorted(groups.items())` puts `"all"` before `"comp"` and `"solo"` alphabetically, which is the order `test_summary_groups_by_style_and_weights_by_notes` asserts.

- [x] **Step 7: Run the tests**

Run: `uv run pytest apps/eval/tests/test_oracle.py -v`
Expected: all PASS.

- [x] **Step 8: Run `make check` and commit**

Run: `make check`
Expected: exit 0.

```bash
git add apps/eval uv.lock
git commit -m "feat: oracle scoring and the lowest-fret baseline

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Results file and `make eval`

**Files:**
- Create: `apps/eval/src/guitarvis_eval/results.py`
- Modify: `apps/eval/src/guitarvis_eval/__main__.py` (replace entirely)
- Modify: `Makefile` (`eval` passes `ARGS`)
- Create: `apps/eval/tests/test_results.py`
- Modify: `apps/eval/tests/test_eval.py` (the entry-point test)

**Interfaces:**
- Consumes: Tasks 3–4 (`excerpt_paths`, `read_jams`, `data_dir`, `DatasetMissing`, `LowestFretMapper`, `score_oracle`, `summarize`, `score_to_dict`); `ViterbiFretboardMapper`, `MapperCosts` (Task 2).
- Produces: `guitarvis_eval.results.REPO_ROOT: Path`, `RESULTS_DIR: Path`, `git_state(repo: Path = REPO_ROOT) -> tuple[str, bool]`, `write_results(*, mode: str, split: str, costs: MapperCosts, summary: dict[str, object], excerpts: list[dict[str, object]], out_dir: Path = RESULTS_DIR, today: date | None = None, repo: Path = REPO_ROOT) -> Path`. File name `<YYYY-MM-DD>-<sha>-<mode>-<split>.json`; top-level keys `date, commit, dirty, mode, split, mapper_costs, summary, excerpts`. `guitarvis_eval.__main__.main(argv: list[str] | None = None) -> int` with flags `--split {test,dev}` (default `test`), `--data-dir PATH`, `--out PATH`, and `--full` (added in Task 7).

- [x] **Step 1: Write the failing tests**

Create `apps/eval/tests/test_results.py`. It writes only into `tmp_path` and must never spell the tracked results directory's path (see Global Constraints):

```python
"""What a run leaves behind, and the command that produces it."""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from guitarset_fixture import write_jams
from guitarvis_eval.__main__ import main
from guitarvis_eval.results import REPO_ROOT, git_state, write_results
from guitarvis_worker.stages.fretboard import MapperCosts


def test_results_file_is_named_and_shaped(tmp_path: Path) -> None:
    written = write_results(
        mode="oracle",
        split="test",
        costs=MapperCosts(),
        summary={"all": {"excerpts": 0}},
        excerpts=[],
        out_dir=tmp_path,
        today=date(2026, 9, 29),
    )
    sha, _ = git_state()

    assert written == tmp_path / f"2026-09-29-{sha}-oracle-test.json"
    payload = json.loads(written.read_text())
    assert set(payload) == {
        "date",
        "commit",
        "dirty",
        "mode",
        "split",
        "mapper_costs",
        "summary",
        "excerpts",
    }
    assert payload["mapper_costs"]["max_fret"] == MapperCosts().max_fret


def test_git_state_inside_the_repository() -> None:
    sha, dirty = git_state(REPO_ROOT)
    assert len(sha) >= 7
    assert isinstance(dirty, bool)


def test_git_state_outside_a_repository(tmp_path: Path) -> None:
    assert git_state(tmp_path) == ("unknown", True)


def test_main_scores_the_test_split(tmp_path: Path) -> None:
    data = tmp_path / "guitarset"
    write_jams(data / "annotation", "05_a_comp", notes=[(0.0, 1.0, 40.0, 0)])
    write_jams(data / "annotation", "00_a_comp", notes=[(0.0, 1.0, 45.0, 1)])
    out = tmp_path / "out"

    assert main(["--data-dir", str(data), "--out", str(out)]) == 0

    [written] = list(out.glob("*.json"))
    payload = json.loads(written.read_text())
    assert payload["mode"] == "oracle"
    assert payload["split"] == "test"
    assert [e["name"] for e in payload["excerpts"]] == ["05_a_comp"]
    assert payload["summary"]["all"]["string"]["total"] == 1


def test_main_without_data_says_how_to_get_it(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "guitarvis_eval", "--data-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 1
    assert "make eval-data" in result.stderr
```

In `apps/eval/tests/test_eval.py`, delete `test_harness_entry_point_exists_and_reports_its_status` (superseded by the two `main` tests above), remove the now-unused `sys` import, and change the module docstring's last sentence to: `These tests hold the one rule that must never be relaxed.`

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest apps/eval/tests/test_results.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'guitarvis_eval.results'`.

- [x] **Step 3: Implement the results writer**

Create `apps/eval/src/guitarvis_eval/results.py`:

```python
"""One run, one file in eval/results/. Committing it is a human decision.

The file records enough to reproduce the number: the commit, whether the
tree had uncommitted changes (a dirty run measures code that is not in git),
the mode, the split, and every mapper cost it ran with.
"""

import dataclasses
import json
import subprocess
from datetime import date
from pathlib import Path

from guitarvis_worker.stages.fretboard import MapperCosts

REPO_ROOT = Path(__file__).resolve().parents[4]
RESULTS_DIR = REPO_ROOT / "eval" / "results"


def git_state(repo: Path = REPO_ROOT) -> tuple[str, bool]:
    """(short sha, dirty). ("unknown", True) when there is no repository: an
    evaluation must not fail because it ran from an exported tree."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True
    return sha, bool(status.strip())


def write_results(
    *,
    mode: str,
    split: str,
    costs: MapperCosts,
    summary: dict[str, object],
    excerpts: list[dict[str, object]],
    out_dir: Path = RESULTS_DIR,
    today: date | None = None,
    repo: Path = REPO_ROOT,
) -> Path:
    sha, dirty = git_state(repo)
    day = (today or date.today()).isoformat()
    path = out_dir / f"{day}-{sha}-{mode}-{split}.json"
    payload = {
        "date": day,
        "commit": sha,
        "dirty": dirty,
        "mode": mode,
        "split": split,
        "mapper_costs": dataclasses.asdict(costs),
        "summary": summary,
        "excerpts": excerpts,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path
```

`parents[4]` walks `results.py → guitarvis_eval → src → eval → apps → repo root`; the workspace installs `guitarvis-eval` editable, so `__file__` is the source file.

- [x] **Step 4: Replace the entry point**

Replace `apps/eval/src/guitarvis_eval/__main__.py`:

```python
"""Entry point for `make eval`.

Deliberately outside `make check`. If you find yourself wiring this into CI,
read the module docstring in __init__.py first.
"""

import argparse
import sys
from pathlib import Path

from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper

from guitarvis_eval.baseline import LowestFretMapper
from guitarvis_eval.dataset import DatasetMissing, data_dir, excerpt_paths, read_jams
from guitarvis_eval.results import RESULTS_DIR, write_results
from guitarvis_eval.runner import ExcerptScore, score_oracle, score_to_dict, summarize


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m guitarvis_eval",
        description="GuitarSet evaluation. Measured, never gated.",
    )
    parser.add_argument(
        "--split",
        choices=("test", "dev"),
        default="test",
        help="test is player 05 and is what gets committed; dev is players "
        "00-04, for tuning MapperCosts (default: test)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="GuitarSet root (default: $GUITARSET_DIR, else the eval-data cache)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=RESULTS_DIR,
        help="where the results file goes (default: eval/results/)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = args.data_dir or data_dir()

    try:
        paths = excerpt_paths(root, args.split)
    except DatasetMissing as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    mapper = ViterbiFretboardMapper()
    baseline = LowestFretMapper()
    scores: list[ExcerptScore] = [
        score_oracle(read_jams(path), mapper, baseline) for path in paths
    ]

    summary = summarize(scores)
    written = write_results(
        mode="oracle",
        split=args.split,
        costs=mapper.costs,
        summary=summary,
        excerpts=[score_to_dict(score) for score in scores],
        out_dir=args.out,
    )
    _print_table(summary)
    print(f"wrote {written}", file=sys.stderr)
    return 0


def _print_table(summary: dict[str, object]) -> None:
    rows = (
        ("string", "string accuracy"),
        ("baseline_string", "baseline string accuracy"),
        ("chord", "chord accuracy"),
    )
    for group, totals in summary.items():
        assert isinstance(totals, dict)
        print(f"{group} ({totals['excerpts']} excerpts)")
        note = totals.get("note")
        if isinstance(note, dict):
            print(f"  {'note F1':<26} {_percent(note['f1'])}")
        for key, label in rows:
            tally = totals.get(key)
            if isinstance(tally, dict):
                print(f"  {label:<26} {_percent(tally['rate'])}")


def _percent(value: object) -> str:
    return f"{value:6.1%}" if isinstance(value, float) else "     —"


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 5: Pass arguments through `make eval`**

In `Makefile`, add below `UV_SYNC_FLAGS ?=`:

```makefile
# Extra arguments for `make eval` / `make eval-data`, e.g.
# `make eval ARGS="--split dev"`.
ARGS ?=
```

and change the `eval` recipe to:

```makefile
eval: ## GuitarSet evaluation. Measured, never gated — not part of `check`.
	$(UV) run python -m guitarvis_eval $(ARGS)
```

- [x] **Step 6: Run the eval tests**

Run: `uv run pytest apps/eval -v`
Expected: all PASS, including `test_eval_never_gates_ci.py` (proves the new test file does not trip the tripwire).

- [x] **Step 7: Run `make check` and commit**

Run: `make check`
Expected: exit 0.

```bash
git add apps/eval Makefile
git commit -m "feat: make eval runs oracle mode and writes a results file

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `make eval-data`

**Files:**
- Create: `apps/eval/src/guitarvis_eval/download.py`
- Modify: `Makefile` (`eval-data` target, `.PHONY`)
- Create: `apps/eval/tests/test_download.py`

**Interfaces:**
- Consumes: `guitarvis_eval.dataset.{ANNOTATION_DIR, MIC_AUDIO_DIR, data_dir}`.
- Produces: `guitarvis_eval.download.Archive(filename: str, md5: str, unpack_to: str)` with `.url`; constants `ANNOTATIONS`, `MIC_AUDIO`; `class ChecksumMismatch(Exception)`; `md5_of(path: Path) -> str`; `fetch(archive: Archive, root: Path, url: str | None = None) -> Path`; `main(argv) -> int` with `--audio`.

- [x] **Step 1: Write the failing tests**

Create `apps/eval/tests/test_download.py`:

```python
"""Fetching GuitarSet: verified before unpacked, skipped when present."""

import hashlib
import zipfile
from pathlib import Path

import pytest
from guitarvis_eval.download import (
    ANNOTATIONS,
    MIC_AUDIO,
    Archive,
    ChecksumMismatch,
    fetch,
)


def make_zip(path: Path) -> str:
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("00_a_comp.jams", "{}")
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_fetch_verifies_and_unpacks(tmp_path: Path) -> None:
    source = tmp_path / "annotation.zip"
    archive = Archive("annotation.zip", make_zip(source), "annotation")
    root = tmp_path / "data"

    target = fetch(archive, root, url=source.as_uri())

    assert target == root / "annotation"
    assert (target / "00_a_comp.jams").read_text() == "{}"
    assert not list(root.glob("*.part"))  # no leftovers


def test_a_bad_checksum_unpacks_nothing(tmp_path: Path) -> None:
    source = tmp_path / "annotation.zip"
    make_zip(source)
    archive = Archive("annotation.zip", "0" * 32, "annotation")
    root = tmp_path / "data"

    with pytest.raises(ChecksumMismatch):
        fetch(archive, root, url=source.as_uri())
    assert not (root / "annotation").exists()
    assert not list(root.glob("*.part"))


def test_an_unpacked_archive_is_not_fetched_again(tmp_path: Path) -> None:
    root = tmp_path / "data"
    (root / "annotation").mkdir(parents=True)
    (root / "annotation" / "existing.jams").write_text("{}")
    archive = Archive("annotation.zip", "0" * 32, "annotation")

    # The URL does not exist; reaching for it would raise.
    assert (
        fetch(archive, root, url=(tmp_path / "nope.zip").as_uri())
        == root / "annotation"
    )


def test_archives_point_at_the_zenodo_record() -> None:
    assert ANNOTATIONS.url == (
        "https://zenodo.org/api/records/3371780/files/annotation.zip/content"
    )
    assert ANNOTATIONS.md5 == "b39b78e63d3446f2e54ddb7a54df9b10"
    assert MIC_AUDIO.md5 == "275966d6610ac34999b58426beb119c3"
```

- [x] **Step 2: Run them to verify they fail**

Run: `uv run pytest apps/eval/tests/test_download.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'guitarvis_eval.download'`.

- [x] **Step 3: Implement the downloader**

Create `apps/eval/src/guitarvis_eval/download.py`:

```python
"""`make eval-data`: fetch GuitarSet from Zenodo, verify it, unpack it.

Into a cache outside the repo, never into git. Each archive is checked
against the MD5 Zenodo publishes before anything is unpacked, and an archive
already unpacked is skipped, so rerunning is cheap.
"""

import argparse
import hashlib
import shutil
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from guitarvis_eval.dataset import ANNOTATION_DIR, MIC_AUDIO_DIR, data_dir

ZENODO_RECORD = "https://zenodo.org/api/records/3371780/files"
CHUNK = 1 << 20


@dataclass(frozen=True)
class Archive:
    filename: str
    md5: str
    unpack_to: str  # directory under the data root

    @property
    def url(self) -> str:
        return f"{ZENODO_RECORD}/{self.filename}/content"


# Checksums as published on the Zenodo record, verified against a download
# on 2026-09-29.
ANNOTATIONS = Archive(
    "annotation.zip", "b39b78e63d3446f2e54ddb7a54df9b10", ANNOTATION_DIR
)
MIC_AUDIO = Archive(
    "audio_mono-mic.zip", "275966d6610ac34999b58426beb119c3", MIC_AUDIO_DIR
)


class ChecksumMismatch(Exception):
    """A downloaded archive is not the one Zenodo published."""


def md5_of(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(archive: Archive, root: Path, url: str | None = None) -> Path:
    """Download, verify, unpack. Returns the unpacked directory.

    `url` overrides the Zenodo URL; tests pass a file:// URL.
    """
    target = root / archive.unpack_to
    if target.is_dir() and any(target.iterdir()):
        return target

    root.mkdir(parents=True, exist_ok=True)
    partial = root / f"{archive.filename}.part"
    with (
        urllib.request.urlopen(url or archive.url) as response,
        partial.open("wb") as out,
    ):
        shutil.copyfileobj(response, out, CHUNK)

    actual = md5_of(partial)
    if actual != archive.md5:
        partial.unlink()
        raise ChecksumMismatch(
            f"{archive.filename}: expected MD5 {archive.md5}, got {actual}"
        )

    # Unpack beside the target and rename, so an interrupted unpack never
    # leaves a half-filled directory that the skip check above would trust.
    staging = root / f"{archive.unpack_to}.part"
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(partial) as bundle:
        bundle.extractall(staging)
    staging.replace(target)
    partial.unlink()
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m guitarvis_eval.download")
    parser.add_argument(
        "--audio",
        action="store_true",
        help="also fetch the mic audio (about 650 MB), needed only for --full",
    )
    args = parser.parse_args(argv)

    root = data_dir()
    archives = [ANNOTATIONS, MIC_AUDIO] if args.audio else [ANNOTATIONS]
    for archive in archives:
        print(f"{archive.filename} → {root / archive.unpack_to}", file=sys.stderr)
        try:
            fetch(archive, root)
        except (OSError, ChecksumMismatch) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Add the Makefile target**

Add `eval-data` to the `.PHONY` list, and below the `eval` target:

```makefile
eval-data: ## Download GuitarSet into ~/.cache (ARGS=--audio for full mode's audio)
	$(UV) run python -m guitarvis_eval.download $(ARGS)
```

- [x] **Step 5: Run the tests**

Run: `uv run pytest apps/eval/tests/test_download.py -v`
Expected: all PASS.

- [x] **Step 6: Fetch the real annotations once**

Run: `make eval-data`
Expected: prints `annotation.zip → ~/.cache/guitarvis/guitarset/annotation`, exits 0; `ls ~/.cache/guitarvis/guitarset/annotation | wc -l` prints `360`.

- [x] **Step 7: Run `make check` and commit**

Run: `make check`
Expected: exit 0.

```bash
git add apps/eval Makefile
git commit -m "feat: make eval-data fetches and verifies GuitarSet

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Full mode

Note F1 via `mir_eval`, string accuracy over matched notes, chord accuracy against the analyzer's vocabulary, and the `--full` flag. `mir_eval` and numpy are not installed under `make check`, so tests of `match_notes` skip there; everything else runs.

**Files:**
- Modify: `apps/eval/pyproject.toml` (`full` extra)
- Modify: `pyproject.toml` (root `eval-full` extra)
- Modify: `uv.lock`
- Modify: `mypy.ini` (`mir_eval` sections)
- Modify: `apps/eval/src/guitarvis_eval/metrics.py` (append)
- Modify: `apps/eval/src/guitarvis_eval/runner.py` (append `score_full`)
- Modify: `apps/eval/src/guitarvis_eval/__main__.py` (`--full`)
- Create: `apps/eval/tests/test_full.py`

**Interfaces:**
- Consumes: Tasks 3–5; the worker's `BasicPitchTranscriber`, `LibrosaStructureAnalyzer`; `guitarvis_core.tabdoc.Chord(t, dur, symbol, confidence)`.
- Produces: in `metrics`: `ONSET_TOLERANCE_SEC = 0.05`, `CHORD_HOP_SEC = 0.1`, `NO_CHORD = "N"`, `match_notes(truth: Sequence[TruthNote], estimated: Sequence[TabNote]) -> list[tuple[int, int]]`, `reduce_chord(label: str) -> str | None`, `chord_tally(truth: Sequence[TruthChord], predicted: Sequence[Chord], duration: float, hop: float = CHORD_HOP_SEC) -> Tally`. In `runner`: `score_full(excerpt: Excerpt, audio: Path, *, transcriber: Transcriber, analyzer: StructureAnalyzer, mapper: FretboardMapper) -> ExcerptScore`.

- [x] **Step 1: Add the extras and mypy sections**

`apps/eval/pyproject.toml`, below `dependencies`:

```toml
# Full mode runs the real transcriber and structure analyzer on GuitarSet's
# audio, and scores notes with mir_eval so the number is comparable with
# published results. Oracle mode — the default — needs none of it.
[project.optional-dependencies]
full = ["guitarvis-worker[ml]", "mir_eval>=0.8"]
```

Root `pyproject.toml`, in `[project.optional-dependencies]` below `ml`:

```toml
# Forwards to the eval member, as `ml` forwards to the worker:
# `uv sync --extra eval-full`, then `make eval ARGS=--full`.
eval-full = ["guitarvis-eval[full]"]
```

`mypy.ini`, append:

```ini
; mir_eval lives behind the eval `full` extra and is genuinely absent under
; the default `uv sync` that CI and `make check` run.
[mypy-mir_eval]
ignore_missing_imports = True

[mypy-mir_eval.*]
ignore_missing_imports = True
```

Run: `uv lock && uv sync`
Expected: lock updates; the default sync does not install `mir_eval`.

- [x] **Step 2: Write the failing tests**

Create `apps/eval/tests/test_full.py`:

```python
"""Full mode: matching estimated notes to truth, chord scoring, and the
end-to-end scorer with stub stages."""

from pathlib import Path

import pytest
from guitarset_fixture import write_jams
from guitarvis_core.contracts import NoteEvent, StructureResult, TabNote
from guitarvis_core.tabdoc import Chord, Timing
from guitarvis_eval.dataset import TruthChord, TruthNote, read_jams
from guitarvis_eval.metrics import (
    NoteCounts,
    Tally,
    chord_tally,
    match_notes,
    reduce_chord,
)
from guitarvis_eval.runner import score_full, summarize
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper


@pytest.mark.parametrize(
    ("label", "reduced"),
    [
        ("D#:maj", "D#"),
        ("G#:maj6(*5)/1", "G#"),
        ("A:7", "A"),
        ("C:maj7/3", "C"),
        ("F#:min7", "F#m"),
        ("Bb:min", "A#m"),  # flats spelled as the analyzer's sharps
        ("E", "E"),  # Harte shorthand: a bare root is major
        ("N", "N"),
        ("D#:sus2(7)/1", None),  # no third: out of vocabulary
        ("B:hdim7", None),
        ("G:(1,5)/1", None),  # power chord
        ("X", None),
    ],
)
def test_reduce_chord_to_the_analyzer_vocabulary(
    label: str, reduced: str | None
) -> None:
    assert reduce_chord(label) == reduced


def test_chord_tally_is_frame_wise() -> None:
    truth = [TruthChord(0.0, 1.0, "A:min"), TruthChord(1.0, 2.0, "C:maj")]
    predicted = [Chord(t=0.0, dur=1.5, symbol="Am", confidence=0.9)]

    # 20 frames: 0.0–0.9 Am right, 1.0–1.4 predicted Am vs C wrong,
    # 1.5–1.9 predicted nothing vs C wrong.
    assert chord_tally(truth, predicted, duration=2.0) == Tally(correct=10, total=20)


def test_chord_tally_skips_out_of_vocabulary_frames() -> None:
    truth = [TruthChord(0.0, 1.0, "D:sus4")]
    assert chord_tally(truth, [], duration=1.0) == Tally(0, 0)
    assert Tally(0, 0).rate is None


def test_no_chord_frames_count_when_nothing_is_predicted() -> None:
    assert chord_tally([], [], duration=0.5) == Tally(correct=5, total=5)


def test_match_notes_needs_onset_within_50ms_and_the_exact_pitch() -> None:
    pytest.importorskip("mir_eval")
    truth = [TruthNote(0.0, 0.5, 60, 4), TruthNote(1.0, 0.5, 62, 4)]
    estimated = [
        TabNote(0.04, 0.3, 60, 4, 1, 0.9),  # 40ms late: a hit
        TabNote(1.0, 0.3, 63, 4, 4, 0.9),  # a semitone off: a miss
    ]
    assert match_notes(truth, estimated) == [(0, 0)]


def test_match_notes_with_nothing_to_match() -> None:
    assert match_notes([], [TabNote(0.0, 0.5, 60, 4, 1, 0.9)]) == []
    assert match_notes([TruthNote(0.0, 0.5, 60, 4)], []) == []


class EchoTranscriber:
    """Returns fixed notes, as if transcription were perfect or not."""

    def __init__(self, events: list[NoteEvent]) -> None:
        self.events = events
        self.seen: list[Path] = []

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        self.seen.append(stem_path)
        return list(self.events)


class FixedAnalyzer:
    def __init__(self, chords: list[Chord]) -> None:
        self.chords = chords

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        assert stem_path == mix_path  # no separation: the recording is both
        return StructureResult(timing=Timing(), chords=self.chords, sections=[])


def test_score_full_with_stub_stages(tmp_path: Path) -> None:
    pytest.importorskip("mir_eval")
    excerpt = read_jams(
        write_jams(
            tmp_path,
            "05_a_comp",
            notes=[(0.0, 0.5, 40.0, 0), (1.0, 0.5, 45.0, 1)],
            performed=[(0.0, 1.0, "E:min")],
            duration=1.0,
        )
    )
    audio = tmp_path / "05_a_comp_mic.wav"
    transcriber = EchoTranscriber(
        [NoteEvent(0.01, 0.5, 40, 0.9), NoteEvent(0.5, 0.5, 70, 0.9)]
    )

    score = score_full(
        excerpt,
        audio,
        transcriber=transcriber,
        analyzer=FixedAnalyzer([Chord(t=0.0, dur=1.0, symbol="Em", confidence=0.9)]),
        mapper=ViterbiFretboardMapper(),
    )

    assert transcriber.seen == [audio]
    assert score.notes == NoteCounts(matched=1, truth=2, estimated=2)
    assert score.strings == Tally(1, 1)  # E2 on the low string
    assert score.chords == Tally(10, 10)
    assert "note" in summarize([score])["all"]  # type: ignore[operator]
```

- [x] **Step 3: Run them to verify they fail**

Run: `uv run pytest apps/eval/tests/test_full.py -v`
Expected: collection error — `ImportError: cannot import name 'chord_tally'`.

- [x] **Step 4: Append the full-mode metrics**

At the top of `apps/eval/src/guitarvis_eval/metrics.py`, change the imports to:

```python
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from guitarvis_core.contracts import TabNote
from guitarvis_core.tabdoc import Chord

from guitarvis_eval.dataset import TruthChord, TruthNote

ONSET_TOLERANCE_SEC = 0.05
CHORD_HOP_SEC = 0.1
NO_CHORD = "N"

_PITCH_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_LETTERS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# Harte qualities whose third is major or minor. Everything else — sus,
# diminished, augmented, power chords, bare interval lists — has no answer in
# the analyzer's major/minor vocabulary and is left out of the score.
_MAJOR = frozenset({"maj", "maj6", "maj7", "maj9", "7", "9", "11", "13"})
_MINOR = frozenset({"min", "min6", "min7", "min9", "min11", "minmaj7"})
```

and append to the end of the file:

```python
def match_notes(
    truth: Sequence[TruthNote], estimated: Sequence[TabNote]
) -> list[tuple[int, int]]:
    """(truth index, estimate index) pairs: onset within 50ms, exact pitch,
    each note matched at most once, offsets ignored.

    mir_eval does the matching so the number is comparable with published
    transcription results. Imported here, not at module level: it is in the
    `full` extra, and oracle mode must run without it.
    """
    if not truth or not estimated:
        return []

    import mir_eval
    import numpy as np

    def intervals(notes: Sequence[TruthNote] | Sequence[TabNote]) -> object:
        # mir_eval rejects zero-length intervals; offsets are ignored anyway.
        return np.array([[n.onset, n.onset + max(n.duration, 1e-3)] for n in notes])

    def hertz(notes: Sequence[TruthNote] | Sequence[TabNote]) -> object:
        return 440.0 * 2.0 ** ((np.array([n.midi for n in notes]) - 69) / 12)

    pairs = mir_eval.transcription.match_notes(
        intervals(truth),
        hertz(truth),
        intervals(estimated),
        hertz(estimated),
        onset_tolerance=ONSET_TOLERANCE_SEC,
        pitch_tolerance=50.0,  # cents: under a semitone, so pitch must be exact
        offset_ratio=None,
    )
    return [(int(t), int(e)) for t, e in pairs]


def reduce_chord(label: str) -> str | None:
    """A Harte label in the analyzer's vocabulary — "C#", "C#m", or NO_CHORD.

    None means the chord has no major/minor reading and is excluded from the
    score, rather than counted against an analyzer that cannot express it.
    """
    if label == NO_CHORD:
        return NO_CHORD
    if label == "X":
        return None
    root, _, rest = label.partition(":")
    quality = rest.split("(")[0].split("/")[0] if rest else "maj"
    if quality in _MAJOR:
        suffix = ""
    elif quality in _MINOR:
        suffix = "m"
    else:
        return None

    pitch_class = _LETTERS[root[0]] + root[1:].count("#") - root[1:].count("b")
    return _PITCH_NAMES[pitch_class % 12] + suffix


def chord_tally(
    truth: Sequence[TruthChord],
    predicted: Sequence[Chord],
    duration: float,
    hop: float = CHORD_HOP_SEC,
) -> Tally:
    """Frame-wise agreement on a `hop` grid, over the frames whose truth is in
    the analyzer's vocabulary. Frames with no chord on either side agree."""
    correct = total = 0
    for frame in range(round(duration / hop)):
        t = frame * hop
        expected = reduce_chord(_label_at(truth, t))
        if expected is None:
            continue
        actual = next((c.symbol for c in predicted if c.t <= t < c.t + c.dur), NO_CHORD)
        total += 1
        correct += actual == expected
    return Tally(correct, total)


def _label_at(chords: Sequence[TruthChord], t: float) -> str:
    return next((c.label for c in chords if c.start <= t < c.end), NO_CHORD)
```

`round(duration / hop)` rather than `int(...)`: `2.0 / 0.1` is `19.999…` in floating point, and `int` would lose the last frame.

- [x] **Step 5: Append `score_full`**

In `apps/eval/src/guitarvis_eval/runner.py`, change the imports to:

```python
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from guitarvis_core.contracts import (
    FretboardMapper,
    NoteEvent,
    StructureAnalyzer,
    Transcriber,
)
from guitarvis_core.tabdoc import STANDARD_TUNING

from guitarvis_eval.dataset import Excerpt
from guitarvis_eval.metrics import (
    NoteCounts,
    Tally,
    chord_tally,
    match_notes,
    oracle_string_tally,
)
```

and add after `score_oracle`:

```python
def score_full(
    excerpt: Excerpt,
    audio: Path,
    *,
    transcriber: Transcriber,
    analyzer: StructureAnalyzer,
    mapper: FretboardMapper,
) -> ExcerptScore:
    """Audio in. Separation is skipped — GuitarSet is already solo guitar —
    so the recording is passed as both stem and mix."""
    placed = mapper.assign(transcriber.transcribe(audio), STANDARD_TUNING).notes
    pairs = match_notes(excerpt.notes, placed)
    structure = analyzer.analyze(audio, audio)
    return ExcerptScore(
        name=excerpt.name,
        style=excerpt.style,
        strings=Tally(
            correct=sum(excerpt.notes[t].string == placed[e].string for t, e in pairs),
            total=len(pairs),
        ),
        notes=NoteCounts(
            matched=len(pairs), truth=len(excerpt.notes), estimated=len(placed)
        ),
        chords=chord_tally(excerpt.chords, structure.chords, excerpt.duration),
    )
```

- [x] **Step 6: Add `--full` to the entry point**

In `__main__.py`: add `mic_audio_path` to the `guitarvis_eval.dataset` import and `score_full` to the `guitarvis_eval.runner` import. In `_build_parser`, add as the first argument:

```python
    parser.add_argument(
        "--full",
        action="store_true",
        help="run transcription and structure on the audio too "
        "(needs `uv sync --extra eval-full` and `make eval-data ARGS=--audio`)",
    )
```

In `main`, replace the lines from `mapper = ViterbiFretboardMapper()` through the `scores: list[ExcerptScore] = [...]` statement with:

```python
    mapper = ViterbiFretboardMapper()
    mode = "full" if args.full else "oracle"
    scores: list[ExcerptScore] = []

    if args.full:
        try:
            import mir_eval  # noqa: F401  (fail now, not after minutes of audio)
            from guitarvis_worker.stages.structure import LibrosaStructureAnalyzer
            from guitarvis_worker.stages.transcription import BasicPitchTranscriber
        except ImportError as error:
            print(
                f"error: full mode needs the ML stack ({error}). "
                "Run `uv sync --extra eval-full`.",
                file=sys.stderr,
            )
            return 1
        transcriber = BasicPitchTranscriber()
        analyzer = LibrosaStructureAnalyzer()
        for index, path in enumerate(paths, 1):
            excerpt = read_jams(path)
            audio = mic_audio_path(root, excerpt)
            if not audio.is_file():
                print(
                    f"error: missing {audio}. Run `make eval-data ARGS=--audio`.",
                    file=sys.stderr,
                )
                return 1
            print(f"[{index}/{len(paths)}] {excerpt.name}", file=sys.stderr)
            scores.append(
                score_full(
                    excerpt,
                    audio,
                    transcriber=transcriber,
                    analyzer=analyzer,
                    mapper=mapper,
                )
            )
    else:
        baseline = LowestFretMapper()
        scores = [score_oracle(read_jams(path), mapper, baseline) for path in paths]
```

and in the `write_results(...)` call change `mode="oracle"` to `mode=mode`.

The stage imports stay inside the `if`: the worker's stage modules import cleanly without the `ml` extra, but `mir_eval` does not, and the check must fail before any excerpt runs.

- [x] **Step 7: Add a test for the missing-extra message**

Append to `apps/eval/tests/test_full.py`:

```python
def test_full_mode_without_mir_eval_says_what_to_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import builtins
    from typing import Any

    from guitarvis_eval.__main__ import main

    real_import = builtins.__import__

    def no_mir_eval(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "mir_eval":
            raise ImportError("No module named 'mir_eval'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_mir_eval)
    write_jams(tmp_path / "annotation", "05_a_comp")

    code = main(["--full", "--data-dir", str(tmp_path), "--out", str(tmp_path / "out")])

    assert code == 1
    assert "uv sync --extra eval-full" in capsys.readouterr().err
```

- [x] **Step 8: Run the eval tests**

Run: `uv run pytest apps/eval -v`
Expected: all PASS; `test_match_notes_needs_onset_within_50ms_and_the_exact_pitch` and `test_score_full_with_stub_stages` SKIP (no `mir_eval` in the default environment).

Then with the extra: `uv sync --extra eval-full && uv run pytest apps/eval -v`
Expected: all PASS, nothing skipped. Then `uv sync` to return to the default environment before `make check`.

- [x] **Step 9: Run `make check` and commit**

Run: `make check`
Expected: exit 0.

```bash
git add apps/eval pyproject.toml uv.lock mypy.ini
git commit -m "feat: full evaluation mode — note F1, matched string accuracy, chord accuracy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Docs, the first committed result, and closing 003's findings

**Files:**
- Modify: `README.md` (status line; the CLI paragraph about empty `notes`)
- Modify: `CLAUDE.md` (build-phase marker; eval commands)
- Modify: `CONTRIBUTING.md` (command table)
- Modify: `.claude/skills/eval-harness/SKILL.md` (commands, modes, split)
- Modify: `eval/results/README.md` (file naming, modes)
- Modify: `docs/specs/003-pipeline-skeleton/review-notes.md` (mark the two stage-4 findings resolved)
- Create: `eval/results/<date>-<sha>-oracle-test.json` (generated)

**Interfaces:**
- Consumes: everything above.
- Produces: documentation and the first tracked before-number.

- [x] **Step 1: README**

Replace the status paragraph (lines 7–9) with:

```markdown
**Status: phase 2 of 6 done.** The pipeline runs end to end and emits real
tablature: stage 4 places every transcribed note on the neck, and a GuitarSet
evaluation harness measures how well (`make eval`). Phase 3 (the API and job
queue) is next.
```

Replace the paragraph beginning "This needs `ffmpeg`" with:

```markdown
This needs `ffmpeg` (for duration probing) and, the first time, a download of
the Demucs and basic-pitch model weights. Notes stage 4 cannot place — outside
the neck's range, or in a chord no hand could play — are dropped rather than
given a wrong fret, and the document's warnings say how many.
```

- [x] **Step 2: CLAUDE.md and CONTRIBUTING.md**

`CLAUDE.md`, *Build phases*: move `← **next**` from phase 2 to phase 3. *Commands*: change the line to
`` `make install` · `make check` · `make test` · `make schema` · `make eval-data` · `make eval` · `make help` ``.
*Things that will bite you*: add

```markdown
- `make eval` needs GuitarSet: run `make eval-data` once (annotations only,
  ~40 MB, into `~/.cache/guitarvis/guitarset`). Full mode needs
  `uv sync --extra eval-full` and `make eval-data ARGS=--audio` (~650 MB).
```

`CONTRIBUTING.md` command table: add above `make eval`:

```markdown
| `make eval-data` | Download GuitarSet into `~/.cache` (`ARGS=--audio` for full mode) |
```

and change the `make eval` row's description to `GuitarSet evaluation — measured, never gated (`ARGS="--full"`, `ARGS="--split dev"`)`.

- [x] **Step 3: The eval-harness skill and the results README**

In `.claude/skills/eval-harness/SKILL.md`, replace the opening code block with:

````markdown
```bash
make eval-data                    # once: GuitarSet annotations into ~/.cache
make eval                         # oracle mode, test split (player 05)
make eval ARGS="--split dev"      # players 00–04: tune MapperCosts here
uv sync --extra eval-full && make eval-data ARGS=--audio
make eval ARGS=--full             # transcription + structure + mapper
```

**Oracle mode** feeds ground-truth pitches to the mapper, so its string
accuracy measures stage 4 alone, next to a lowest-fret baseline. **Full mode**
runs the real transcriber and analyzer on the mic audio and reports note F1,
string accuracy over matched notes, and chord accuracy. Tune on `dev`; commit
`test`.
````

In `eval/results/README.md`, after the first paragraph add:

```markdown
One file per run: `<date>-<commit>-<mode>-<split>.json`, where mode is
`oracle` or `full` and split is `test` or `dev`. Only `test` results belong
here; `dev` runs are for tuning and are not committed. A file whose `dirty`
field is `true` measured uncommitted code — rerun from a clean tree before
committing it.
```

- [x] **Step 4: Close 003's findings**

In `docs/specs/003-pipeline-skeleton/review-notes.md`, append to the *Stage 4's narrow `except NotImplementedError`* bullet and the *`--tuning` validation* bullet, respectively:

```markdown
  **Resolved in 004:** the pipeline now catches `Exception` for stage 4;
  `test_a_mapper_raising_not_implemented_degrades_like_any_other_failure`
  pins it.
```

```markdown
  **Resolved in 004:** unchanged by design — `check_invariant` still runs on
  every note stage 4 returns, whatever tuning it was handed.
```

- [x] **Step 5: Commit the docs, then produce the before-number from a clean tree**

```bash
git add README.md CLAUDE.md CONTRIBUTING.md .claude/skills/eval-harness/SKILL.md eval/results/README.md docs/specs/003-pipeline-skeleton/review-notes.md
git commit -m "docs: phase 2 status, eval commands, 003 findings resolved

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Run: `make eval`
Expected: a table like the following (the dev split measured 65.1% / 46.7% while this plan was written; the test split's numbers are not known in advance and must not be tuned toward), and `wrote …/eval/results/<date>-<sha>-oracle-test.json`:

```
all (60 excerpts)
  string accuracy              ~65%
  baseline string accuracy     ~47%
comp (30 excerpts)
  …
solo (30 excerpts)
  …
```

Check: the JSON's `"dirty"` is `false`. If it is `true`, something is uncommitted — commit or stash it and rerun.

- [x] **Step 6: Run `make check` and commit the result**

Run: `make check`
Expected: exit 0.

```bash
git add eval/results/
git commit -m "eval: first oracle result on the test split

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Full mode, if the ML stack is available**

Optional for this branch — it takes tens of minutes on CPU. If run: `uv sync --extra eval-full && make eval-data ARGS=--audio && make eval ARGS=--full`, then `uv sync`, and commit the `full-test` result file on its own. If not run, say so in the PR description rather than implying it was.

## Deviations

- **Open voicings carry the hand position** (a3dfec3). Task 4's `_viterbi`
  made a move into or out of an all-open voicing free, so one open note
  excused any jump. The Viterbi state is now a fingering plus the hand
  position. The spec's *Transition cost* paragraph was updated to match.
  String accuracy on test went from 52.7% to 54.0%.
- **Full mode not yet run** (Task 8, Step 7). The harness is built and tested
  with stubs, but no `full-test` result is committed.
