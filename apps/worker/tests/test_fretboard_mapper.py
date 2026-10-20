"""Stage 4 without audio: feed note sequences, assert fingerings.

Musical accuracy on real recordings is the evaluation harness's job. These
tests pin the mechanics — grouping, playability, the costs' intent, the drop
rules — and the one invariant that holds whatever the costs are.
"""

import math
import random
from collections.abc import Sequence

import pytest
from guitarvis_core.contracts import FretboardResult, NoteEvent
from guitarvis_core.fretboard import check_invariant, parse_pitch
from guitarvis_core.tabdoc import STANDARD_TUNING, Note
from guitarvis_worker.stages.fretboard import (
    MapperCosts,
    ViterbiFretboardMapper,
    _Fingering,
)

DROP_D = ("D2", "A2", "D3", "G3", "B3", "E4")
SEVEN_STRING = ("B1", "E2", "A2", "D3", "G3", "B3", "E4")


def note(
    onset: float, midi: int, confidence: float = 0.9, duration: float = 0.5
) -> NoteEvent:
    return NoteEvent(onset=onset, duration=duration, midi=midi, confidence=confidence)


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
    # A phrase at frets 12-16 stays there. Swapping one note for an open low E
    # must not make the jump down to 7th position free: the hand is still up
    # the neck when the open string rings, so every other note is placed
    # exactly as it was.
    phrase = [77, 71, 72, 71, 72, 74]
    with_open = [77, 71, 40, 71, 72, 74]

    def run(midis: list[int]) -> list[tuple[int, int, int]]:
        return places(assign([note(i * 0.5, m) for i, m in enumerate(midis)]))

    baseline = run(phrase)
    assert all(12 <= fret <= 16 for _, _, fret in baseline)

    result = run(with_open)
    assert result[2] == (40, 0, 0)
    assert [p for i, p in enumerate(result) if i != 2] == [
        p for i, p in enumerate(baseline) if i != 2
    ]


def test_a_phrase_inside_one_box_does_not_move_the_hand() -> None:
    # The fifth-position A minor pentatonic box. Every note sits within four
    # frets of the index finger on the 5th, so the hand never moves; pulled
    # toward the nut, the same phrase went to B1, B3 and so on.
    midis = [60, 62, 67, 69, 72]
    result = assign([note(i * 0.25, m, duration=0.25) for i, m in enumerate(midis)])
    assert places(result) == [
        (60, 3, 5),
        (62, 3, 7),
        (67, 4, 8),
        (69, 5, 5),
        (72, 5, 8),
    ]


def quarter_notes(midis: list[int]) -> list[NoteEvent]:
    """`midis` 0.25 s apart, each 0.25 s long."""
    return [note(i * 0.25, m, duration=0.25) for i, m in enumerate(midis)]


def test_a_scale_in_fifth_position_uses_no_open_strings() -> None:
    # E4 is an open string, but the hand is at the 5th fret, and an open
    # string up the neck costs something. Free, it would be played open.
    result = assign(quarter_notes([60, 62, 64, 67, 69, 72]))
    assert places(result) == [
        (60, 3, 5),
        (62, 3, 7),
        (64, 4, 5),
        (67, 4, 8),
        (69, 5, 5),
        (72, 5, 8),
    ]


def test_twelfth_position_stays_up_the_neck() -> None:
    # A descent that ends on E4. Nothing pulls the hand to the nut, and the
    # open e string costs 0.2 a fret above the fourth, so the phrase stays
    # at the 12th fret instead of sliding down to it.
    result = assign(quarter_notes([76, 74, 71, 69, 67, 64]))
    assert places(result) == [
        (76, 5, 12),
        (74, 4, 15),
        (71, 4, 12),
        (69, 3, 14),
        (67, 3, 12),
        (64, 2, 14),
    ]


def test_an_open_low_e_pedal_does_not_drag_the_riff_down() -> None:
    # E2 has one place, the open low string, wherever the hand is, so it is
    # exempt from the open-string cost. Charged, the pedal pulled the hand to
    # the nut: D4 landed on B3 and E4 on the open e string.
    riff = [62, 64, 66, 67, 69, 71]
    alone = [note((2 * i + 1) * 0.25, m, duration=0.25) for i, m in enumerate(riff)]
    pedal = quarter_notes([m for riff_note in riff for m in (40, riff_note)])

    with_pedal = places(assign(pedal))
    assert [p for p in with_pedal if p[0] != 40] == places(assign(alone))
    assert all(
        string == 0 and fret == 0 for midi, string, fret in with_pedal if midi == 40
    )


def test_an_open_dyad_under_a_riff_does_not_drag_it_down() -> None:
    # A2 alone could be fretted on the low string, but beside E2, which holds
    # that string, it can only be played open. Every way to play the dyad
    # plays it open, so it is exempt like the pedal above. Charged, it pulled
    # the riff toward the nut: D4 went to the B string and E4 to the open e.
    riff = [62, 64, 66, 67, 69, 71]
    alone = [note(0.25 + 0.5 * i, m, duration=0.25) for i, m in enumerate(riff)]
    dyads = [
        note(0.5 * i, midi, duration=0.25)
        for i in range(len(riff))
        for midi in (40, 45)
    ]

    with_dyads = places(assign([*dyads, *alone]))
    assert [p for p in with_dyads if p[0] not in (40, 45)] == places(assign(alone))
    assert [p for p in with_dyads if p[0] in (40, 45)] == [
        (40, 0, 0),
        (45, 1, 0),
    ] * len(riff)


def test_a_note_open_in_every_fingering_of_its_chord_is_exempt() -> None:
    # Judged per voicing: E2 holds the low string, so A2 beside it has only
    # the open A string. In A2 and E3, A2 can be fretted at the 5th when E3
    # takes the D string, so where it is open it is charged.
    mapper = ViterbiFretboardMapper()
    pitches = [parse_pitch(name) for name in STANDARD_TUNING]

    (dyad,) = mapper._fingerings([note(0.0, 40), note(0.0, 45)], pitches)
    assert (dyad.places, dyad.charged_opens) == (((0, 0), (1, 0)), 0)

    options = mapper._fingerings([note(0.0, 45), note(0.0, 52)], pitches)
    assert {o.places: o.charged_opens for o in options} == {
        ((1, 0), (2, 2)): 1,
        ((1, 0), (0, 12)): 1,
        ((0, 5), (1, 7)): 0,
        ((0, 5), (2, 2)): 0,
    }


def test_the_exemption_is_judged_before_the_beam() -> None:
    # A beam of one keeps only the open A, but the note can still be fretted
    # on the low string, so its open string is charged.
    mapper = ViterbiFretboardMapper(MapperCosts(beam=1))
    pitches = [parse_pitch(name) for name in STANDARD_TUNING]
    (kept,) = mapper._fingerings([note(0.0, 45)], pitches)
    assert (kept.places, kept.charged_opens) == (((1, 0),), 1)


def test_only_a_note_with_no_other_place_is_exempt() -> None:
    # Alone, a note is exempt only when it has exactly one candidate, not
    # because it is on the lowest string. Low D in drop D has no other place;
    # on a seven-string the open E2 does, so it is charged like any open
    # string.
    def open_fingering(tuning: Sequence[str], midi: int) -> _Fingering:
        mapper = ViterbiFretboardMapper()
        pitches = [parse_pitch(name) for name in tuning]
        options = mapper._fingerings([note(0.0, midi)], pitches)
        (found,) = [o for o in options if all(fret == 0 for _, fret in o.places)]
        return found

    standard_e2 = open_fingering(STANDARD_TUNING, 40)
    assert (standard_e2.places, standard_e2.charged_opens) == (((0, 0),), 0)
    drop_d_d2 = open_fingering(DROP_D, 38)
    assert (drop_d_d2.places, drop_d_d2.charged_opens) == (((0, 0),), 0)
    seven_e2 = open_fingering(SEVEN_STRING, 40)
    assert (seven_e2.places, seven_e2.charged_opens) == (((1, 0),), 1)


def test_the_first_voicing_pays_for_its_open_strings_too() -> None:
    # E4 open with C5 at the 13th fret costs nothing but the open string, which
    # sits nine frets above the reach. Charged, the chord is held in the box at
    # the 8th fret instead. The hand arriving for free is no reason to let the
    # first voicing's open strings off.
    assert places(assign(chord(0.0, 64, 72))) == [(64, 3, 9), (72, 5, 8)]


def test_a_tie_after_a_move_goes_to_the_lower_frets() -> None:
    # G#2 and C4 after F2: C4 at the 5th fret moves the hand one fret (0.5 + 1),
    # and at the 1st fret stretches the hand three (1.5). Both total 1.5, and
    # the lower frets win.
    result = assign([note(0.0, 41), *chord(1.0, 44, 60)])
    assert places(result) == [(41, 0, 1), (44, 0, 4), (60, 4, 1)]


def test_a_tie_with_an_open_string_goes_to_the_lower_frets() -> None:
    # F#3, G3 and C4: the open G with the hand at the 9th fret costs 0.5 for
    # the span and 1.0 for the open string; the first-position shape costs 1.5
    # for its stretch. Equal totals: the lower frets win, and the open string
    # up the neck does not.
    result = assign(chord(0.0, 54, 55, 60))
    assert places(result) == [(54, 2, 4), (55, 3, 0), (60, 4, 1)]


def shape(frets: tuple[int, int] | None, charged_opens: int = 0) -> _Fingering:
    """A fingering whose fretted notes run over `frets` (lowest, highest), or
    one with every string open when `frets` is None. Only its position, top
    and charged opens matter to the hand."""
    if frets is None:
        return _Fingering(
            places=((0, 0),),
            cost=0.0,
            position=None,
            top=None,
            charged_opens=charged_opens,
        )
    low, high = frets
    return _Fingering(
        places=((0, low), (1, high)),
        cost=0.0,
        position=low,
        top=high,
        charged_opens=charged_opens,
    )


@pytest.mark.parametrize(
    ("hand", "frets", "cost", "landing"),
    [
        (5, (6, 8), 0.0, 5),  # inside the box 5-8: stays
        (5, (7, 9), 1.0, 6),  # one fret short: moves one
        (9, (5, 6), 4.0, 5),  # below the box: down to the lowest fret
        (None, (7, 9), 0.0, 7),  # from nowhere: free, on the lowest fret
        (5, None, 0.0, 5),  # all open: the hand stays
        (None, None, 0.0, None),  # all open before any fretting
    ],
)
def test_the_hand_moves_only_as_far_as_the_shape_needs(
    hand: int | None,
    frets: tuple[int, int] | None,
    cost: float,
    landing: int | None,
) -> None:
    assert ViterbiFretboardMapper()._transition(hand, shape(frets)) == (cost, landing)


@pytest.mark.parametrize("hand", [3, 7])
def test_a_shape_wider_than_the_box_puts_the_index_finger_on_its_lowest_fret(
    hand: int,
) -> None:
    # Frets 5-9 are five wide, one more than the box. The index finger holds
    # the lowest fret whichever side the hand came from, and the move is
    # costed to there.
    assert ViterbiFretboardMapper()._transition(hand, shape((5, 9))) == (2.0, 5)


@pytest.mark.parametrize(
    ("hand", "frets", "charged", "cost", "landing"),
    [
        (4, None, 2, 0.0, 4),  # all open at the reach: free
        (5, None, 1, 0.2, 5),  # one fret above it: 0.2 an open string
        (9, None, 2, 2.0, 9),  # five frets above, two open strings
        (9, None, 0, 0.0, 9),  # nothing charged: free anywhere
        (None, None, 2, 0.0, None),  # all open before any fretting: the nut
        (5, (6, 8), 1, 0.2, 5),  # charged on the hand after it stays
        (5, (7, 9), 1, 1.4, 6),  # ...and after it moves: 1.0 + 0.2 * 2
        (None, (7, 9), 1, 0.6, 7),  # ...and where it first lands
    ],
)
def test_an_open_string_costs_by_how_far_up_the_neck_the_hand_lands(
    hand: int | None,
    frets: tuple[int, int] | None,
    charged: int,
    cost: float,
    landing: int | None,
) -> None:
    got_cost, got_landing = ViterbiFretboardMapper()._transition(
        hand, shape(frets, charged)
    )
    assert got_cost == pytest.approx(cost)
    assert got_landing == landing


def held_note(onset: float, midi: int, duration: float) -> NoteEvent:
    return NoteEvent(onset=onset, duration=duration, midi=midi, confidence=0.9)


def test_a_note_still_ringing_keeps_its_string() -> None:
    # G3 rings for a second, so A3 half a second later does not take the G
    # string at the 2nd fret. The open G has left the hand nowhere, so the D
    # string at the 7th is reached for free.
    notes = [held_note(0.0, 55, 1.0), held_note(0.5, 57, 0.5)]
    assert places(assign(notes)) == [(55, 3, 0), (57, 2, 7)]


def test_a_note_that_has_stopped_frees_its_string() -> None:
    notes = [held_note(0.0, 55, 0.3), held_note(0.5, 57, 0.5)]
    assert places(assign(notes)) == [(55, 3, 0), (57, 3, 2)]


def test_ringing_allows_100ms_of_slop() -> None:
    # G3 ends at 0.55 s, 50 ms into A3's onset at 0.5 s: inside the tolerance.
    notes = [held_note(0.0, 55, 0.55), held_note(0.5, 57, 0.5)]
    assert places(assign(notes)) == [(55, 3, 0), (57, 3, 2)]


def test_a_note_ringing_for_ever_never_blocks_the_notes_after_it() -> None:
    # The ring is a cost, and only the next voicing is checked against it. A
    # transcribed duration of 10 s must not stop any later note being placed.
    notes = [
        held_note(0.0, 55, 10.0),
        *(
            held_note(onset, midi, 0.4)
            for onset, midi in [(0.5, 55), (1.0, 57), (1.5, 59), (2.0, 60)]
        ),
    ]
    result = assign(notes)
    assert [tab.midi for tab in result.notes] == [55, 55, 57, 59, 60]
    assert result.warnings == []
    assert_invariant(result, STANDARD_TUNING)


@pytest.mark.parametrize(
    ("after_strings", "cost"),
    [
        ((3,), 2.0),  # the G string rings
        ((3, 2), 4.0),  # the G and D strings ring
        ((3, 2, 1), 4.0),  # the A string was never played
        ((1,), 0.0),  # nothing it uses rings
        ((4,), 0.0),  # the B string's note has ended
    ],
)
def test_a_ring_costs_the_weight_for_each_string_still_sounding(
    after_strings: tuple[int, ...], cost: float
) -> None:
    before = [
        held_note(0.0, 55, 1.0),  # G3 on string 3, until 1.0 s
        held_note(0.0, 62, 1.0),  # D4 on string 2, until 1.0 s
        held_note(0.0, 59, 0.5),  # B3 on string 4, until 0.5 s
    ]
    held = _Fingering(
        places=((3, 0), (2, 7), (4, 0)),
        cost=0.0,
        position=7,
        top=7,
        charged_opens=0,
    )
    after = _Fingering(
        places=tuple((string, 1) for string in after_strings),
        cost=0.0,
        position=1,
        top=1,
        charged_opens=0,
    )
    assert ViterbiFretboardMapper()._ring(before, held, 0.5, after) == cost


def test_a_power_chord_keeps_to_adjacent_strings() -> None:
    # C3, G3, C4. A3, open G and B1 sounds the same pitches but skips the D
    # string; the C5 shape is the one a strum would hit.
    result = assign(chord(0.0, 48, 55, 60))
    assert places(result) == [(48, 1, 3), (55, 2, 5), (60, 3, 5)]
    assert_invariant(result, STANDARD_TUNING)


@pytest.mark.parametrize(
    ("string_places", "cost"),
    [
        (((0, 3), (2, 5)), 1.0),  # two notes: a skipped string is free
        (((1, 3), (2, 5), (3, 5)), 1.0),  # adjacent: span 2 only
        (((1, 3), (3, 5), (4, 5)), 1.3),  # one string skipped
        (((0, 3), (2, 5), (5, 5)), 1.9),  # span 2, three strings skipped
        (((0, 0), (2, 0), (3, 0)), 0.3),  # all open: the gap is still charged
    ],
)
def test_a_chord_pays_for_each_unused_string_between_its_outer_strings(
    string_places: tuple[tuple[int, int], ...], cost: float
) -> None:
    # The costs above are worked out at 0.5 a fret of span and 0.3 a skipped
    # string, so the weights are named here rather than read from the defaults.
    costs = MapperCosts(span_weight=0.5, gap_weight=0.3)
    exempt = (False,) * len(string_places)
    fingering = ViterbiFretboardMapper(costs)._score(string_places, exempt)
    assert fingering is not None
    assert fingering.cost == pytest.approx(cost)


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


def test_an_exact_tie_goes_to_the_lower_frets() -> None:
    # Two paths cost exactly 4.2. Summed in floating point they differ in the
    # last bit; the tie must still break toward the lower frets, not the bit.
    notes = [note(0.0, 47), *chord(0.5, 49, 55), *chord(1.0, 57, 59)]
    assert places(assign(notes))[-2:] == [(57, 3, 2), (59, 4, 0)]


@pytest.mark.parametrize(
    "bad",
    [
        {"beam": 0},
        {"max_span": -1},
        {"max_fret": -1},
        {"hand_window": 0},
        {"open_reach": -1},
        {"move_weight": -1.0},
        {"span_weight": -0.5},
        {"height_weight": -0.1},
        {"open_weight": -0.1},
        {"ring_weight": -0.1},
        {"ring_tolerance": -0.1},
        {"gap_weight": -0.1},
        # Not finite: inf * 0 is nan, and a nan poisons every total it meets.
        *(
            {name: value}
            for name in (
                "move_weight",
                "span_weight",
                "height_weight",
                "open_weight",
                "ring_weight",
                "gap_weight",
                "ring_tolerance",
            )
            for value in (math.inf, math.nan)
        ),
    ],
)
def test_costs_that_could_never_place_a_note_are_refused(
    bad: dict[str, float],
) -> None:
    with pytest.raises(ValueError):
        MapperCosts(**bad)  # type: ignore[arg-type]
