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


def test_an_open_string_does_not_reset_the_hand_position() -> None:
    # A phrase at frets 12-15 stays there. Swapping one note for an open low E
    # must not make the jump down to 7th position free: the hand is still at
    # the 12th fret when the open string rings.
    phrase = [77, 71, 72, 71, 72, 74]
    with_open = [77, 71, 40, 71, 72, 74]

    def run(midis: list[int]) -> list[tuple[int, int, int]]:
        return places(assign([note(i * 0.5, m) for i, m in enumerate(midis)]))

    baseline = run(phrase)
    assert [fret for _, _, fret in baseline] == [13, 12, 13, 12, 13, 15]

    result = run(with_open)
    assert result[2] == (40, 0, 0)
    assert [p for i, p in enumerate(result) if i != 2] == [
        p for i, p in enumerate(baseline) if i != 2
    ]


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
