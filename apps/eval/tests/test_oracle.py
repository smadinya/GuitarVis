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
