# Tab Accuracy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** More notes on the right string and less noise. Stage 4's cost model
gets the fixes in spec 010, and stage 2 removes basic-pitch's harmonic
ghosts. Every change is tuned on `dev` and measured on `test` and on the
user's real songs.

**Architecture:**
- **Stage 4:** changes stay inside `apps/worker/src/guitarvis_worker/stages/fretboard.py`.
- **Stage 2:** changes stay inside `stages/transcription.py`.
- **Eval:** gains an overlap metric, records the transcription settings, and
  gets a dev-only sweep tool, `guitarvis_eval.sweep`.
- **Contracts:** no change to `contracts.py` or `tabdoc.py`.
- **Order:** stage 4 ships first and stage 2 second, each as separately
  revertible commits.

**Tech Stack:** Python 3.12, uv workspace, pytest, mypy, ruff; basic-pitch on
onnxruntime; mir_eval in eval-full; Node 22 for `web/scripts/confidence-report.ts`.

**Spec:** [spec.md](spec.md) · **Numbers:** [research.md](research.md) ·
**Deferred:** [future.md](future.md)

## Global Constraints

- **Branch `010-tab-accuracy`.** Never commit to `main`. Task 1 opens by
  committing this folder.
- **Test first.** Each behaviour starts with a test that fails for the right
  reason.
- **`make check` is the gate**, after `make services`. While iterating, the
  narrow checks are enough:
  - `uv run pytest apps/worker apps/eval`
  - `uv run ruff check . && uv run ruff format --check .`
  - `uv run mypy` on the touched package
- **Commit style:** `feat(worker): …`, `feat(eval): …`, `docs(eval): …`,
  `docs: …`, each with the attribution trailer.
- **Contracts and schema:** no change to `tabdoc.py`, `contracts.py` or
  `SCHEMA_VERSION`.
- **`CACHE_VERSION`** goes from 1 to 2 exactly once, in Task 11, which is
  the commit that changes stage 2's output.
- **Evaluation never gates CI.**
  - Nothing under `apps/eval/tests/` names `eval/results`.
  - `make sweep` is not reachable from `make check`.
  - The sweep never writes to `eval/results/`.
- **Splits.** Tuning uses `dev`. `test` is run three times, in Tasks 1, 9
  and 11, and each run's results file is committed. Task 11 runs again only
  if Task 12 sends stage 2 back.
- **Keep the halves separable.**
  - Tasks 3–6 and 9 touch stage 4 only.
  - Tasks 10–13 touch stage 2, its cache and its thresholds only.
  - Tasks 7–8 are eval infrastructure plus a settings object that does not
    change output.
- **Imports.** Heavy imports stay inside methods: `basic_pitch` only in
  `BasicPitchTranscriber._predict`.
- **Mapper determinism stays as it is.** Path totals are rounded to
  `COST_PLACES` before comparing. Ties break to the lower fret, then the
  lower string, deciding the latest voicing first. Every placed note passes
  `check_invariant`.
- **Real-song material** lives in the gitignored `tmp/`. Audio and documents
  from it are never committed; `real-songs.md` holds only numbers, job links
  and notes.
- **Stop for the user.**
  - At Task 12's sign-off.
  - At Task 13 if `HIDE` or `FULL` comes out as 0 or "not supported", or
    moves by more than 0.1.
  - Whenever a success condition in the spec's *When it is done* fails.

## Review Focus

1. **Tunings with a different lowest string.** In drop D the forced open
   note is D2. On a seven-string, E2 has two places, so its open string is
   not forced. The exemption must come from "only one candidate", never from
   "string 0". Test in Task 4.
2. **A note whose transcribed duration is absurdly long** (10 s, or longer
   than the song). The ringing penalty is a cost, so the notes after it must
   all still be placed. Test in Task 5.
3. **A chord wider than the hand box** (span 4, `hand_window` 4). The index
   finger lands on the lowest fret and the move is costed from there. Test in
   Task 3.
4. **Stacked octaves.** In E2–E3–E4 at equal confidence, none is a ghost. In
   a weak E4 over a weak E3 over a strong E2, both upper notes are ghosts,
   judged against the decoded notes, not the survivors. Test in Task 10.
5. **A sweep typo** (`--cost hand_widow=4`). It names the bad field and lists
   the valid ones, with no traceback. Test in Task 8.

---

### Task 1: Same-string overlaps in the eval, and the before-numbers

**Files:**
- Modify: `apps/eval/src/guitarvis_eval/metrics.py`,
  `apps/eval/src/guitarvis_eval/runner.py` (`ExcerptScore`, `score_oracle`,
  `score_full`, `_total`), `apps/eval/src/guitarvis_eval/__main__.py`
  (`_print_table`), `eval/results/README.md` (metric list)
- Test: `apps/eval/tests/test_oracle.py`, `apps/eval/tests/test_full.py`
- Create: `docs/specs/010-tab-accuracy/tuning.md`

**Interfaces:**
- Produces:
  - `OVERLAP_TOLERANCE_SEC = 0.03`;
  - `@dataclass(frozen=True) class Overlaps: count: int = 0; notes: int = 0`,
    with `__add__` and `per_thousand -> float | None`, which is None when
    `notes == 0`;
  - `same_string_overlaps(notes: Sequence[TabNote], tolerance: float = OVERLAP_TOLERANCE_SEC) -> Overlaps`;
  - new fields `ExcerptScore.overlaps: Overlaps | None = None` and
    `ExcerptScore.baseline_overlaps: Overlaps | None = None`;
  - summary keys `"overlaps"` and `"baseline_overlaps"`, each
    `{"count", "notes", "per_1000"}`.

- [ ] **Step 0: Commit the spec folder.**
  `git add docs/specs/010-tab-accuracy && git commit -m "docs: 010 spec, research, future notes and plan"`
- [ ] **Step 1: Write the failing tests** in `test_oracle.py`. The helper
  builds `TabNote(onset, duration, midi=60, string=s, fret=0, confidence=1.0)`.
  - `test_a_note_on_a_string_still_sounding_is_an_overlap`: string 3 at
    (0.0, 1.0) and (0.5, 0.5) gives `Overlaps(count=1, notes=2)`.
  - `test_overlaps_allow_30ms_of_slop`: the first note lasts 0.52 s, so the
    count is 0.
  - `test_overlaps_are_per_string`: the second note is on string 2, so the
    count is 0.
  - `test_overlaps_ignore_input_order`: reversed input gives the same result.
  - `test_overlaps_per_thousand`: `Overlaps(3, 1500).per_thousand == 2.0` and
    `Overlaps().per_thousand is None`.
  - `test_score_oracle_reports_overlaps_for_mapper_and_baseline`:
    - The excerpt is G3 (55) on string 3 at 0.0 for 1.0 s, then A3 (57) on
      string 2 at 0.5.
    - The baseline puts both on string 3, so
      `score.baseline_overlaps == Overlaps(1, 2)`.
    - `score.overlaps.notes == 2`.
  - `test_summary_reports_overlaps_per_thousand`:
    - Two `ExcerptScore`s with `overlaps=Overlaps(1, 2)` and `Overlaps(0, 2)`.
    - `summarize(...)["all"]["overlaps"] == {"count": 1, "notes": 4, "per_1000": 250.0}`.

  In `test_full.py`, extend `test_score_full_with_stub_stages`: it now asserts
  `score.overlaps is not None` and `score.baseline_overlaps is None`.
- [ ] **Step 2: Run and watch them fail.**
  `uv run pytest apps/eval/tests/test_oracle.py apps/eval/tests/test_full.py -q`
  fails with ImportError on `Overlaps`.
- [ ] **Step 3: Implement.**
  - `same_string_overlaps` sorts by `(onset, string)` and keeps each
    string's last end. A note counts when its onset is earlier than that end
    minus `tolerance`.
  - `score_oracle` fills `overlaps` and `baseline_overlaps`; `score_full`
    fills `overlaps`.
  - `_print_table` prints `same-string overlaps /1000` and
    `baseline overlaps /1000` rows.
  - The README gains one bullet: placed notes starting on a string whose
    previous note still sounds more than 30 ms later, per 1000 placed notes.
    The truth scores zero.
- [ ] **Step 4: Run** the two test files (they pass), then `make check`
  (passes).
- [ ] **Step 5: Commit** `feat(eval): count notes placed on a string still sounding`
- [ ] **Step 6: Before-numbers on `test`.**
  - The tree must be clean. Run `uv sync --extra eval-full`, then
    `make eval` and `make eval ARGS=--full`.
  - Expected: two new files in `eval/results/`, `-oracle-test.json` and
    `-full-test.json`, both with `"dirty": false`. Oracle string accuracy
    should match the committed 54.0%. Full-mode note F1 should be 0.777.
  - Commit both: `docs(eval): 010's before-numbers on test`
- [ ] **Step 7: Before-numbers on `dev`, and the timing baseline.**
  - Run `make eval ARGS="--split dev --out $HOME/.cache/guitarvis/010-before"`,
    then the same with `--full`.
  - Create `tuning.md` with a *Dev before-numbers* table. Its columns are:
    - oracle string accuracy (comp, solo);
    - full string accuracy (comp, solo);
    - full note F1 (comp, solo);
    - full note precision (comp, solo);
    - overlaps per 1000 (oracle, full).

    For reference, the research's oracle dev numbers were 74.4% comp and
    42.7% solo.
  - Time the mapper on five minutes of dense strums. 1200 voicings of the
    E, A, G and D chords (`(40,47,52,56,59,64)`, `(45,52,57,61,64)`,
    `(43,47,50,55,59,67)`, `(50,57,62,66)`), 0.25 s apart and 0.5 s long,
    through `ViterbiFretboardMapper().assign`. It is about 0.1 s today.
    Record it in `tuning.md`.
  - Commit `docs: 010's dev before-numbers`

### Task 2: Real-song baseline

**Files:** Create `docs/specs/010-tab-accuracy/real-songs.md`. Local only:
`tmp/010/before/`.

**Interfaces:**
- Produces: *the round procedure*, which Tasks 9 and 12 rerun with
  `R=stage4` and `R=stage2`.

- [ ] **Step 1: Bring the stack up.**
  - Run `uv sync --extra eval-full`, which includes `ml`. Syncing `ml`
    alone would remove `mir_eval`.
  - Run `make services` and `make migrate`, then `make api`, `make worker`
    and `make web`, each in the background.
  - Check `curl -sf localhost:8000/health` returns 200.
- [ ] **Step 2: Run the round.** Run it in the background. Each job takes
  minutes, because separation dominates.

  Jobs dedupe on the file's content hash, so each round uploads a copy whose
  metadata names the round. Uploading the original twice would just return
  the old job.

  ```bash
  R=before; mkdir -p tmp/010/$R
  for song in tmp/*.mp3; do
    name=$(basename "$song" .mp3); copy=tmp/010/$R/$name-$R.mp3
    ffmpeg -loglevel error -y -i "$song" -c copy -metadata comment="010 $R" "$copy"
    id=$(curl -sf -F "file=@$copy" localhost:8000/jobs | jq -r .id)
    until s=$(curl -sf localhost:8000/jobs/$id | jq -r .status); [ "$s" = succeeded ] || [ "$s" = failed ]; do sleep 15; done
    echo "$name $id $s" | tee -a tmp/010/$R/jobs.txt
    [ "$s" = succeeded ] && curl -sf localhost:8000/jobs/$id/document -o tmp/010/$R/$name.json
  done
  node web/scripts/confidence-report.ts tmp/010/$R/*.json
  ```
- [ ] **Step 3: Write `real-songs.md`.**
  - What it is: spec 010's review, songs in the gitignored `tmp/`, nothing
    committed but numbers.
  - A *Before* table, one row per song:
    - the job link, `http://localhost:5173/songs/<id>`;
    - note count;
    - % at or below `HIDE`, % partly faded, % hidden, passages (from the
      report);
    - median confidence
      (`jq '[.notes[].confidence] | sort | .[length/2|floor]'`);
    - the document's `warnings`.

  A failed job is recorded with its failure reason. Commit
  `docs: 010's real-song before-numbers`.

### Task 3: The hand covers a box

**Files:**
- Modify: `apps/worker/src/guitarvis_worker/stages/fretboard.py`
- Test: `apps/worker/tests/test_fretboard_mapper.py`

**Interfaces:**
- Produces:
  - `MapperCosts.hand_window: int = 4`, refused below 1;
  - `_Fingering.top: int | None`, the highest fretted fret, None when all
    open;
  - `ViterbiFretboardMapper._transition(self, hand: int | None, after: _Fingering) -> tuple[float, int | None]`,
    which returns the transition cost and where the hand lands. It replaces
    `_move`. `_viterbi` keys states on the landing it returns.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_phrase_inside_one_box_does_not_move_the_hand`:
    - MIDI `[60, 62, 67, 69, 72]`, 0.25 s apart, each `note()` 0.25 s long.
    - Output: `[(60,3,5), (62,3,7), (67,4,8), (69,5,5), (72,5,8)]`, the
      fifth-position A minor pentatonic box.
    - Today it gives B1, B3 and so on, toward the nut.
  - `test_the_hand_moves_only_as_far_as_the_shape_needs`:
    - A unit test on `_transition` with hand-built `_Fingering`s.
    - Hand 5 into a shape at frets 6–8: cost 0, lands on 5.
    - Hand 5 into frets 7–9: cost 1.0, lands on 6.
    - Hand 9 into frets 5–6: cost 4.0, lands on 5.
    - Hand None into frets 7–9: cost 0, lands on 7.
    - An all-open shape: cost 0, the hand stays where it was.
  - `test_a_shape_wider_than_the_box_puts_the_index_finger_on_its_lowest_fret`
    (Review Focus 3): hand 3 into frets 5–9 lands on 5 at cost 2.0; hand 7
    lands on 5 at cost 2.0.
  - **Rewrite `test_an_open_string_does_not_reset_the_hand_position`.**
    - Keep its intent: with the open low E, every other note is placed
      exactly as without it, and the open E is `(40, 0, 0)`.
    - Replace the pinned baseline frets with an assertion that every fretted
      note sits between frets 12 and 16.
    - The box now puts B4 at G16, not B12. That is a debatable choice,
      recorded in future.md's *A cost for changing strings*.
- [ ] **Step 2: Run and watch them fail.**
  `uv run pytest apps/worker/tests/test_fretboard_mapper.py -q`: the new
  tests fail; the rewritten one passes.
- [ ] **Step 3: Implement `_transition`.** The landing rule is the spec's:

  ```python
  if after.position is None:
      return 0.0, hand                       # all open: the hand stays
  low, high = after.position, after.top
  if hand is None:
      return 0.0, low                        # arriving from nowhere is free
  landing = min(max(hand, min(high - (self.costs.hand_window - 1), low)), low)
  return self.costs.move_weight * abs(hand - landing), landing
  ```

  Validate `hand_window >= 1` in `__post_init__`. Update the module and
  `_viterbi` docstrings: the hand is the index finger's fret.
- [ ] **Step 4: Run.** The whole mapper test file and `uv run pytest apps/worker`
  pass. Today's other tests are unaffected, as checked against the spike.
- [ ] **Step 5: Commit** `feat(worker): the fretting hand covers a box of frets`

### Task 4: Open strings cost something up the neck

**Files:** `stages/fretboard.py`, `apps/worker/tests/test_fretboard_mapper.py`

**Interfaces:**
- Consumes: `_transition` from Task 3.
- Produces:
  - `MapperCosts.open_reach: int = 4` and `MapperCosts.open_weight: float = 0.2`;
  - `open_bonus` removed;
  - `height_weight` default 0.0;
  - `_Fingering.charged_opens: int`, the open strings whose note has another
    candidate;
  - `_score(self, places, forced: tuple[bool, ...]) -> _Fingering | None`,
    where `forced[i]` means note *i* has exactly one candidate;
  - `_transition` adds `open_weight * charged_opens * max(0, landing - open_reach)`.
    For an all-open fingering that is `max(0, hand - open_reach)` with
    `hand or 0`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_scale_in_fifth_position_uses_no_open_strings`:
    - MIDI `[60, 62, 64, 67, 69, 72]`, 0.25 s apart, 0.25 s long.
    - Output: `[(60,3,5), (62,3,7), (64,4,5), (67,4,8), (69,5,5), (72,5,8)]`.
    - Task 3's code still plays E4 on the open e string.
  - `test_twelfth_position_stays_up_the_neck`:
    - MIDI `[76, 74, 71, 69, 67, 64]`, 0.25 s apart, 0.25 s long.
    - Output: `[(76,5,12), (74,4,15), (71,4,12), (69,3,14), (67,3,12), (64,2,14)]`.
    - Today it slides down to the open e string.
  - `test_an_open_low_e_pedal_does_not_drag_the_riff_down`:
    - MIDI `[40, 62, 40, 64, 40, 66, 40, 67, 40, 69, 40, 71]`, 0.25 s apart.
    - With the pedal, the non-pedal notes are placed as the riff alone is.
    - This test already passes today, because nothing charges for open
      strings yet. It pins the exemption against the cost added here; the
      spike without the exemption put D4 at B3 and E4 on the open e.
  - `test_only_a_note_with_no_other_place_is_exempt` (Review Focus 1):
    - Through `_fingerings`, E2 (40) in standard tuning is open with
      `charged_opens == 0`.
    - D2 (38) in `DROP_D` is too.
    - In `SEVEN_STRING`, E2's open fingering (string 1) has
      `charged_opens == 1`.
  - Update `test_costs_that_could_never_place_a_note_are_refused`: drop
    `open_bonus`, and add `{"open_weight": -0.1}`, `{"open_reach": -1}` and
    `{"hand_window": 0}`.
- [ ] **Step 2: Run and watch them fail.** The fifth- and twelfth-position
  tests fail on the open e.
- [ ] **Step 3: Implement.**
  - `_fingerings` computes `forced` from each note's candidate count and
    passes it to `_score`.
  - `_score` drops the open-bonus term.
  - `_transition` adds the open cost on the landing hand.
  - `MapperCosts` docstring and validation are updated.
- [ ] **Step 4: Run** the mapper tests and `uv run pytest apps/eval`. The
  eval's oracle tests use the mapper, and `test_score_oracle_on_an_open_e_minor_chord`
  must still pass.
- [ ] **Step 5: Commit** `feat(worker): open strings cost something up the neck`

### Task 5: Ringing strings

**Files:** `stages/fretboard.py`, `apps/worker/tests/test_fretboard_mapper.py`

**Interfaces:**
- Produces:
  - `MapperCosts.ring_weight: float = 2.0` and
    `MapperCosts.ring_tolerance: float = 0.1` (seconds), both non-negative;
  - `_viterbi(self, voicings: Sequence[Sequence[NoteEvent]], fingerings: Sequence[Sequence[_Fingering]]) -> list[_Fingering]`;
  - `_ring(self, before: Sequence[NoteEvent], held: _Fingering, onset: float, after: _Fingering) -> float`.
    It returns `ring_weight` × the number of strings in `after` whose note in
    `before` ends later than `onset + ring_tolerance`.

- [ ] **Step 1: Write the failing tests.** Use `NoteEvent` directly, since
  `note()` fixes the duration at 0.5.
  - `test_a_note_still_ringing_keeps_its_string`: G3 (55) at 0.0 lasting
    1.0 s, then A3 (57) at 0.5 lasting 0.5 s, gives `[(55,3,0), (57,2,7)]`.
    Today A3 takes G2.
  - `test_a_note_that_has_stopped_frees_its_string`: G3 lasting 0.3 s gives
    `[(55,3,0), (57,3,2)]`.
  - `test_ringing_allows_100ms_of_slop`: G3 lasting 0.55 s gives
    `[(55,3,0), (57,3,2)]`.
  - `test_a_note_ringing_for_ever_never_blocks_the_notes_after_it` (Review
    Focus 2):
    - G3 at 0.0 lasting 10 s, then 55, 57, 59, 60 at 0.5, 1.0, 1.5 and 2.0,
      each 0.4 s.
    - All five notes are placed, and `assert_invariant` holds.
- [ ] **Step 2: Run and watch them fail.** The first test fails, with A3 at
  G2.
- [ ] **Step 3: Implement.** `assign` passes the kept voicings to `_viterbi`.
  The transition adds `_ring(voicings[k-1], <the state's previous fingering>, voicings[k][0].onset, option)`.
  The previous fingering is the state's fingering index, so no new state is
  needed.
- [ ] **Step 4: Run** the mapper tests and `uv run pytest apps/worker apps/eval`.
- [ ] **Step 5: Commit** `feat(worker): a string still ringing is busy`

### Task 6: Skipped strings in a chord

**Files:** `stages/fretboard.py`, `apps/worker/tests/test_fretboard_mapper.py`

**Interfaces:**
- Produces: `MapperCosts.gap_weight: float = 0.3`, non-negative. For three or
  more notes, `_score` adds
  `gap_weight * (max(strings) - min(strings) + 1 - len(places))`.

- [ ] **Step 1: Write the failing test.**
  `test_a_power_chord_keeps_to_adjacent_strings`: C3, G3 and C4
  (48, 55, 60) at one onset give `[(48,1,3), (55,2,5), (60,3,5)]`, the C5
  shape. Today it is A3, open G and B1, skipping the D string.
- [ ] **Step 2: Run and watch it fail.**
- [ ] **Step 3: Implement**, and add `gap_weight` to the validation test's
  parameters as `{"gap_weight": -0.1}`.
- [ ] **Step 4: Run** `uv run pytest apps/worker apps/eval`, then `make check`.
- [ ] **Step 5: Commit** `feat(worker): chords prefer adjacent strings`

### Task 7: The transcriber's settings, made explicit

Output does not change, so `CACHE_VERSION` stays where it is.

**Files:**
- Modify: `apps/worker/src/guitarvis_worker/stages/transcription.py`,
  `apps/eval/src/guitarvis_eval/results.py` (`write_results`),
  `apps/eval/src/guitarvis_eval/__main__.py`
- Test: `apps/worker/tests/test_transcription.py`,
  `apps/eval/tests/test_results.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class TranscriptionSettings`, with fields
    `onset_threshold: float = 0.5`, `frame_threshold: float = 0.3`,
    `minimum_note_length_ms: float = 127.7` and `melodia_trick: bool = True`.
    It refuses thresholds outside (0, 1] and negative lengths.
  - `BasicPitchTranscriber(min_confidence: float = MIN_CONFIDENCE, settings: TranscriptionSettings | None = None)`,
    exposing `.settings`.
  - `write_results(..., transcription: TranscriptionSettings | None = None)`,
    which writes `"transcription_settings"` only when given.

- [ ] **Step 1: Write the failing tests.**
  - `test_default_settings_are_basic_pitchs_own`:
    `TranscriptionSettings() == TranscriptionSettings(0.5, 0.3, 127.7, True)`.
  - `test_settings_reach_predict`:
    - Monkeypatch `sys.modules["basic_pitch"]` and
      `["basic_pitch.inference"]` with fakes. The fake `basic_pitch` needs
      `ICASSP_2022_MODEL_PATH`.
    - The fake `predict` records its kwargs and returns `({}, None, [])`.
    - Assert `onset_threshold=0.6`, `frame_threshold=0.4`,
      `minimum_note_length=58.0` and `melodia_trick=False` arrive.
  - `test_settings_refuse_impossible_values`, parametrised over
    `frame_threshold=0`, `onset_threshold=1.5` and
    `minimum_note_length_ms=-1`.
  - In `test_results.py`: a full-mode `write_results` call with
    `transcription=TranscriptionSettings()` writes
    `payload["transcription_settings"]["frame_threshold"] == 0.3`. The
    oracle-mode payload has no such key.
- [ ] **Step 2: Run and watch them fail** with an ImportError.
- [ ] **Step 3: Implement.**
  - `_predict` passes the four settings to `predict()`.
  - `__main__` passes `transcriber.settings` in full mode.
- [ ] **Step 4: Run** `uv run pytest apps/worker apps/eval`, then `make check`.
- [ ] **Step 5: Commit** `feat(worker): transcription settings are explicit and recorded`

### Task 8: The sweep

**Files:**
- Create: `apps/eval/src/guitarvis_eval/sweep.py`
- Modify: `apps/eval/src/guitarvis_eval/runner.py`, where `score_full` gains
  `analyzer: StructureAnalyzer | None` and leaves `chords` and
  `chord_confidence` None when it is None
- Modify: `Makefile`, adding
  `sweep: ## Tune MapperCosts and transcription settings on dev. Never gated.`,
  which runs `$(UV) run python -m guitarvis_eval.sweep $(ARGS)`
- Modify: `.claude/skills/eval-harness/SKILL.md`, adding a `make sweep`
  line and the overlaps metric row
- Test: `apps/eval/tests/test_sweep.py`, `apps/eval/tests/test_full.py`

**Interfaces:**
- Consumes: `Overlaps` (Task 1), the `MapperCosts` fields (Tasks 3–6) and
  `TranscriptionSettings` (Task 7).
- Produces:
  - `parse_grid(specs: Sequence[str]) -> dict[str, list[str]]`, from
    `"name=v1,v2"`;
  - `combinations(grid: dict[str, list[str]]) -> list[dict[str, str]]`, a
    Cartesian product in the order given;
  - `build[T](cls: type[T], overrides: dict[str, str]) -> T`, which coerces
    each value by the field's type:
    - int and float as written;
    - bool from `true` or `false`;
    - `float | None` also from `none`.

    An unknown field raises `SweepError` naming the field and listing the
    valid ones.
  - `CachedTranscriptions(inner: Transcriber, directory: Path)`, which
    implements `Transcriber`. Its key is the audio file's stem, and an entry
    is JSON `[onset, duration, midi, confidence]` rows.
  - `settings_key(settings: TranscriptionSettings) -> str`, the first 12 hex
    characters of a SHA-1 over the sorted JSON of its fields.
  - `main(argv: list[str] | None = None) -> int`. Its options:
    - `--cost NAME=V1,V2…` and `--transcription NAME=V1,V2…`, both
      repeatable;
    - `--full`;
    - `--data-dir`;
    - `--cache DIR`, defaulting to `~/.cache/guitarvis/sweep`.

    There is no `--split`: it always runs on `dev`. It prints one
    tab-separated row per combination, and the first row is always the
    defaults. The columns:
    - the overrides;
    - `oracle_comp` and `oracle_solo` string accuracy;
    - `oracle_ovl` (per 1000);
    - with `--full`:
      - `full_comp` and `full_solo` string accuracy;
      - `f1_comp` and `f1_solo`;
      - `prec_comp` and `prec_solo`;
      - `full_ovl`;
      - `obj4`, the mean of `full_comp` and `full_solo`;
      - `obj2`, the mean of `f1_comp` and `f1_solo`.

    Transcriptions are cached under `<cache>/<settings_key>/`.

- [ ] **Step 1: Write the failing tests** in `test_sweep.py`.
  - The JAMS files come from `guitarset_fixture.write_jams`.
  - Full mode uses `EchoTranscriber` from `test_full.py`; move it to a
    shared helper if importing it is awkward.
  - Full-mode tests start with `pytest.importorskip("mir_eval")`, as in
    `test_full.py`.

  The tests:
  - `test_parse_grid_splits_names_and_values`
  - `test_combinations_are_the_product_in_order`: `{"a": ["1","2"], "b": ["x"]}`
    gives `[{"a":"1","b":"x"}, {"a":"2","b":"x"}]`.
  - `test_build_coerces_by_field_type`: `hand_window="5"` becomes 5 (an int),
    `ring_weight="0.5"` becomes 0.5, and `melodia_trick="false"` becomes
    False.
  - `test_a_misspelled_field_is_named` (Review Focus 5): `main(["--cost", "hand_widow=4", ...])`
    returns 2. Its stderr names `hand_widow` and lists `hand_window`, with no
    traceback.
  - `test_the_cache_transcribes_each_file_once`: a counting stub is called
    once across two `transcribe` calls on the same path.
  - `test_settings_key_is_stable_and_distinguishes`
  - `test_main_prints_defaults_first_then_each_combination`: oracle mode,
    `--cost gap_weight=0,0.6`, three data rows.
  - `test_main_never_writes_results`: the out tree is unchanged after a run.
  - In `test_full.py`: `test_score_full_without_an_analyzer_scores_no_chords`.
- [ ] **Step 2: Run and watch them fail.**
- [ ] **Step 3: Implement.**
  - Reuse `score_oracle`, with `LowestFretMapper` as the baseline.
  - Reuse `score_full(analyzer=None)` and `summarize`.
  - The sweep reads columns out of `summarize`'s `comp` and `solo` groups.
- [ ] **Step 4: Run** `uv run pytest apps/eval`, then `make check`. Confirm
  `make -n check` does not mention `sweep`.
- [ ] **Step 5: Commit** `feat(eval): a dev-only sweep for tuning`

### Task 9: Tune and measure stage 4

**Files:** `stages/fretboard.py` (the `MapperCosts` defaults),
`docs/specs/010-tab-accuracy/tuning.md` and `real-songs.md`, and a
committed results file pair.

- [ ] **Step 1: Coarse sweep.** Run it in full mode, so the transcriptions
  cache once:

  ```bash
  make sweep ARGS="--full --cost hand_window=3,4,5 --cost open_weight=0.1,0.2,0.4 --cost open_reach=3,4,5"
  ```
- [ ] **Step 2: Fix the winners and sweep the rest.**
  - `--cost ring_weight=0,1,2,4 --cost ring_tolerance=0.05,0.1,0.15,0.2`
  - Then `--cost gap_weight=0,0.15,0.3,0.6 --cost height_weight=0,0.05 --cost span_weight=0.25,0.5,1`
- [ ] **Step 3: Choose by the spec's rule.**
  - Maximise `obj4`.
  - Reject any row where a column falls below the dev before-numbers from
    Task 1: oracle comp and solo, full comp and solo, f1 comp and solo.
  - `oracle_ovl` and `full_ovl` must be below their before-values.
  - Record each sweep's table and the choice in `tuning.md`.
- [ ] **Step 4: Set the defaults** to the chosen values, then run
  `uv run pytest apps/worker apps/eval`.
  - A musical test that fails at the chosen values is a conflict. Prefer the
    best row that keeps it.
  - If none does, record the conflict in `tuning.md` and stop for the user.
  - Never edit a test's expected fingering to fit the numbers.
- [ ] **Step 5: Time** the Task 1 benchmark again and record it. It must be
  under 2 s.
- [ ] **Step 6: Commit** `feat(worker): tuned mapper costs`, then on a clean
  tree run `make eval` and `make eval ARGS=--full` on `test`.
  - Check conditions 1–3 and 8 of the spec's *When it is done* against
    Task 1's files: string accuracy rises in comp and in solo in both modes,
    and overlaps fall in both.
  - Write the verdict table into `tuning.md`.
  - Commit both results and `tuning.md`:
    `docs(eval): 010 stage 4 on test`
  - If a condition fails, stop for the user. Stage 2 can still proceed.
- [ ] **Step 7: Real-song round `R=stage4`.** Run Task 2's procedure. Stage 4
  isn't cached, so a new upload re-maps it.
  - Add a *Stage 4* table to `real-songs.md`, with the same columns plus a
    *Before* link per song.
  - Commit `docs: 010's real songs after stage 4`.
  - The user's look at this round is informational.

### Task 10: Harmonic ghosts

Off by default: output is unchanged until Task 11 sets it.

**Files:** `stages/transcription.py`, `apps/worker/tests/test_transcription.py`

**Interfaces:**
- Produces:
  - Two new fields, `TranscriptionSettings.ghost_ratio: float | None = None`
    and `TranscriptionSettings.ghost_alone_only: bool = False`. The ratio is
    refused outside (0, 1].
  - `GHOST_INTERVALS = (12, 19, 24)` and `GHOST_LEAD_SEC = 0.05`.
  - `drop_ghosts(events: Sequence[NoteEvent], ratio: float, *, alone_only: bool) -> list[NoteEvent]`.
    Note *g* is dropped when some other decoded note *b* meets three
    conditions:
    - `g.midi - b.midi in GHOST_INTERVALS`;
    - `b.onset - GHOST_LEAD_SEC <= g.onset <= b.onset + b.duration`;
    - `g.confidence < ratio * b.confidence`.

    With `alone_only`, there is a fourth: every other note whose onset is
    within `VOICING_WINDOW_SEC` of `g.onset` must be such a base of *g*.
    Bases are judged against all decoded notes, never against the survivors.
  - `transcribe` applies the rule after the `MIN_CONFIDENCE` filter, when
    `ghost_ratio` is not None.

- [ ] **Step 1: Write the failing tests.** Each test calls `drop_ghosts`
  directly, with the base E3 (52) at 1.0 lasting 0.5 s at confidence 0.8.
  - `test_a_weak_octave_above_a_sounding_note_is_dropped`: E4 (64) at 1.0 with
    confidence 0.4, ratio 0.6: dropped.
  - `test_twelfths_and_double_octaves_are_ghosts_but_fifths_are_not`: 71 and
    76 are dropped; 59 is kept.
  - `test_a_strong_octave_is_kept`: confidence 0.6 is at least 0.48, so kept.
  - `test_a_ghost_may_lead_its_base_by_50ms`: onset 0.96 is dropped; 0.94 is
    kept.
  - `test_a_ghost_needs_its_base_still_sounding`: onset 1.6 is kept.
  - `test_alone_only_spares_a_chord`: add G3 (55) at 1.0. The E4 is kept with
    `alone_only=True` and dropped with False.
  - `test_ghost_rule_judges_against_decoded_notes` (Review Focus 4):
    - E2 at 0.9, E3 at 0.5 and E4 at 0.25: both upper notes are dropped.
    - E2, E3 and E4 all at 0.8: none is dropped.
  - `test_ghosts_are_kept_by_default`: `StubTranscriber` with the default
    settings returns both notes.
  - Validation: `ghost_ratio=0` and `1.5` are refused.
- [ ] **Step 2: Run and watch them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest apps/worker apps/eval`, then `make check`.
- [ ] **Step 5: Commit** `feat(worker): an optional rule against basic-pitch's harmonic ghosts`

### Task 11: Tune and measure stage 2

**Files:** `stages/transcription.py` (the `TranscriptionSettings` defaults),
`apps/worker/src/guitarvis_worker/caching.py` (`CACHE_VERSION = 2`),
`tuning.md`, and a committed results file pair.

- [ ] **Step 1: Decoding sweep.**

  ```bash
  make sweep ARGS="--full --transcription melodia_trick=true,false --transcription frame_threshold=0.3,0.35,0.4 --transcription minimum_note_length_ms=58,93,127.7"
  ```

  Then add `--transcription onset_threshold=0.4,0.5,0.6` around the winner.
- [ ] **Step 2: Ghost sweep** on the best decoding:
  `--transcription ghost_ratio=none,0.5,0.6,0.7,0.8 --transcription ghost_alone_only=false,true`.
- [ ] **Step 3: Choose by the spec's rule.**
  - Maximise `obj2`, with `prec_comp` and `prec_solo` above the defaults
    row.
  - No column may fall below the defaults row, which is stage 4 shipped and
    today's decoding.
  - `full_ovl` must not rise.
  - Between the two ghost forms, take the higher `full_solo`. Within 0.5
    points, take `ghost_alone_only=false`.
  - Record the tables and the choice in `tuning.md`.
- [ ] **Step 4: Set the defaults and bump the cache.** Set the
  `TranscriptionSettings` defaults, and bump `CACHE_VERSION` to 2 with a
  comment naming 010.
  - Update `test_default_settings_are_basic_pitchs_own`: rename it
    `test_default_settings_are_010s_tuned_values` and pin the new values.
  - Run `uv run pytest apps/worker apps/eval`.
  - Commit `feat(worker): tuned transcription settings`.
- [ ] **Step 5: Measure on `test`.** On a clean tree, run `make eval ARGS=--full`
  and `make eval`.
  - Check conditions 4–6 and 8 against Task 9's files, or Task 1's if
    stage 4 did not ship: precision rises,
    and note F1 and string accuracy hold within 0.5 points, in comp and in
    solo.
  - Write the verdict into `tuning.md`.
  - Commit `docs(eval): 010 stage 2 on test`.
  - If a condition fails, stop for the user.

### Task 12: Real-song review of stage 2: the user's sign-off

**Files:** `real-songs.md`

- [ ] **Step 1: Round `R=stage2`.** Run Task 2's procedure. The
  `CACHE_VERSION` bump forces a fresh transcription.
- [ ] **Step 2: Write the comparison.** Add a *Stage 2* table, linking all
  three rounds per song. Flag any song whose note count fell by more than a
  third from the stage-4 round, or whose share of hidden notes rose by more
  than 10 points. Those are the frame-threshold risk the spec names.
- [ ] **Step 3: Stop and ask the user** to open the three links per song and
  sign off.
  - **If they reject a setting:** revert that field's default to
    basic-pitch's, re-run Task 11's Steps 4–5 for the reduced change, and
    repeat this task.
  - **If they sign off:** record their words and the date in
    `real-songs.md`.
  - Commit `docs: 010's real songs after stage 2, signed off`.

### Task 13: Recalibrate the note thresholds

**Files:** `web/src/confidence.ts`,
`docs/specs/006-tab-view-sync/calibration.md`

- [ ] **Step 1: Read the thresholds** that Task 11's full-mode `make eval`
  printed: `HIDE` and `FULL` under the 006 rule.
  - **If either is 0 or "not supported", or differs from today's 0.5 / 0.6
    by more than 0.1:** stop, show the user the bands table, and apply what
    they decide.
- [ ] **Step 2: Add *After 010*** to `calibration.md`.
  - The bands table from Task 11's `-full-test.json`, cited by file name.
  - The chosen values, with the rule column as in *Chosen values*.
  - The real-song report from Task 12, run under the new thresholds with
    `node web/scripts/confidence-report.ts tmp/010/stage2/*.json`.
- [ ] **Step 3: Update `confidence.ts`.** Set `HIDE` and `FULL` (even if
  unchanged), and point their doc comments at the new section.
- [ ] **Step 4: Run** `cd web && npm run test && npm run typecheck && npm run lint`,
  then `make check`.
- [ ] **Step 5: Commit** `docs(eval): recalibrate the note thresholds after 010`

### Task 14: Docs and the PR

**Files:**
- `docs/specs/001-guitarvis-design/spec.md` (stage 4's cost list)
- `docs/specs/004-fretboard-mapper/spec.md` (*Fingering cost*, *Transition
  cost*)
- `docs/specs/010-tab-accuracy/spec.md` (Status)
- `CLAUDE.md` (Commands)

- [ ] **Step 1: Update 001's stage 4 bullet list.** The terms become:
  - fret span;
  - hand movement out of a four-fret box;
  - open strings up the neck;
  - reusing a string still ringing;
  - skipped strings in a chord.

  Add "Amended by [010](../010-tab-accuracy/spec.md)".
- [ ] **Step 2: Annotate 004.** Its two cost sections each get one line,
  "Amended by 010: …", naming what changed. 004's text stays as written,
  since it is history.
- [ ] **Step 3: Update the Commands.** Add `make sweep` to the Commands line
  in `CLAUDE.md`. Set 010's Status to `Implemented`.
- [ ] **Step 4: Run** `make check`, after `make services`.
- [ ] **Step 5: Commit** `docs: 010 in the design spec, 004 and CLAUDE.md`.
  Then push with `git push -u origin 010-tab-accuracy` and open the PR from
  `.github/pull_request_template.md`.
  - **Spec:** `docs/specs/010-tab-accuracy/spec.md`.
  - The body gives the before and after tables for `test` (oracle and full),
    links `real-songs.md`, and states the sign-off.
