# Tuning record

**Spec:** [010 — Tab accuracy](spec.md)
**Date:** 2026-10-19

The record of 010's tuning on the dev split: the before-numbers, then each
sweep and the choice it led to.

## Dev before-numbers

Commit `99aa6a7`, clean tree. No code has changed since `6a3c1c3`, which added
the overlap count; the commits between are docs and results files. Dev runs go
to `~/.cache/guitarvis/010-before`, not to `eval/results/`.

```bash
make eval ARGS="--split dev --out $HOME/.cache/guitarvis/010-before"
make eval ARGS="--split dev --full --out $HOME/.cache/guitarvis/010-before"
```

Columns follow the sweep's names. Accuracy is a percentage; F1 and precision
are fractions; overlaps are per 1000 placed notes.

| oracle_comp | oracle_solo | full_comp | full_solo | f1_comp | f1_solo | prec_comp | prec_solo | oracle_ovl | full_ovl |
|---|---|---|---|---|---|---|---|---|---|
| 74.4% | 42.7% | 67.1% | 38.3% | 0.709 | 0.810 | 0.728 | 0.773 | 18.4 | 33.6 |

The oracle numbers match the research's (74.4% comp, 42.7% solo, and 542 and
446 overlaps). Overlaps by style:

| overlaps per 1000 | comp | solo | all |
|---|---|---|---|
| oracle | 13.9 | 30.4 | 18.4 |
| full | 30.7 | 40.4 | 33.6 |

The test split was committed first, at `3439361`:
[`2026-10-19-3439361-oracle-test.json`](../../../eval/results/2026-10-19-3439361-oracle-test.json)
and
[`2026-10-19-3439361-full-test.json`](../../../eval/results/2026-10-19-3439361-full-test.json).
Oracle string accuracy is 54.0% (62.0% comp, 30.2% solo) with 9.0 overlaps per
1000, against 100.1 for the lowest-fret baseline. Full-mode note F1 is 0.777,
string accuracy 50.3% and overlaps 30.7 per 1000.

## Timing baseline

Five minutes of dense strums: 1200 voicings of E, A, G and D chords
(`(40,47,52,56,59,64)`, `(45,52,57,61,64)`, `(43,47,50,55,59,67)`,
`(50,57,62,66)`), 0.25 s apart and 0.5 s long, 6300 notes, through
`ViterbiFretboardMapper().assign`. Five runs, run through `uv run python`:

```python
events = [
    NoteEvent(onset=0.25 * i, duration=0.5, midi=midi, confidence=1.0)
    for i in range(1200)
    for midi in CHORDS[i % 4]
]
mapper = ViterbiFretboardMapper()
mapper.assign(events, STANDARD_TUNING)  # timed with time.perf_counter()
```

| | seconds |
|---|---|
| before, five runs | 0.079 0.072 0.079 0.073 0.108 |
| before, median | 0.079 |

The limit later tasks must stay under is 2 s.

## Stage 4 sweeps

Commit `deca45e`, dev split, full mode. The transcriptions for the default
settings were cached first, so each row only re-maps.

In every row of every sweep, f1_comp is 0.709, f1_solo 0.810, prec_comp
0.728, prec_solo 0.773 and obj2 0.759. The mapper does not change what was
heard. Those columns equal their before-numbers and are left out of the
tables.

### The rule

- Maximise obj4, the mean of full_comp and full_solo.
- Reject a row below a before-number: oracle_comp 74.4, oracle_solo 42.7,
  full_comp 67.1, full_solo 38.3, f1_comp 0.709, f1_solo 0.810.
- Reject a row whose overlaps are not below the before-values: oracle_ovl
  18.4, full_ovl 33.6.
- A tie on obj4, to its printed tenth, goes to the row nearer the spec's
  starting values.
- A row that fails a musical test cannot ship. A musical test names a
  fingering, and that is never edited to fit the numbers. The best row that
  keeps them is taken instead, and the conflict is recorded below.

The musical tests that fail somewhere in the sweeps, all in
`apps/worker/tests/test_fretboard_mapper.py`:

| short name | test |
|---|---|
| box | `test_a_phrase_inside_one_box_does_not_move_the_hand` |
| scale | `test_a_scale_in_fifth_position_uses_no_open_strings` |
| barre | `test_a_note_after_a_barre_stays_in_position` |
| tie-move | `test_a_tie_after_a_move_goes_to_the_lower_frets` |
| tie-open | `test_a_tie_with_an_open_string_goes_to_the_lower_frets` |
| ring | `test_a_note_still_ringing_keeps_its_string` |
| power | `test_a_power_chord_keeps_to_adjacent_strings` |

Five more tests check the cost arithmetic at the default weights
(`_transition`, `_ring`, `_score`). They are not musical: a row that changes
a weight they read fails them by construction. They are left out of the verdicts. One of
them meets a weight that changed; see *Conflicts*.

### Sweep 1: the hand and open strings

```bash
make sweep ARGS="--full --cost hand_window=3,4,5 --cost open_weight=0.1,0.2,0.4 --cost open_reach=3,4,5"
```

| hand_window | open_weight | open_reach | oracle_comp | oracle_solo | oracle_ovl | full_comp | full_solo | full_ovl | obj4 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| defaults |  |  | 82.1 | 50.8 | 7.2 | 76.7 | 40.0 | 17.6 | 58.3 | admissible |
| 3 | 0.1 | 3 | 83.4 | 51.9 | 5.8 | 76.7 | 40.9 | 17.6 | 58.8 | tests fail: box, scale, tie-open |
| 3 | 0.1 | 4 | 83.2 | 51.7 | 6.4 | 76.3 | 40.7 | 17.9 | 58.5 | tests fail: box, scale, tie-open |
| 3 | 0.1 | 5 | 83.3 | 51.6 | 6.4 | 76.0 | 40.1 | 18.0 | 58.1 | tests fail: box, scale, tie-open |
| 3 | 0.2 | 3 | 83.6 | 51.7 | 5.9 | 77.2 | 42.9 | 17.8 | 60.1 | rule's best; tests fail: box, scale |
| 3 | 0.2 | 4 | 83.6 | 51.6 | 6.4 | 76.9 | 42.8 | 18.0 | 59.9 | tests fail: box, scale |
| 3 | 0.2 | 5 | 83.5 | 52.7 | 6.5 | 76.7 | 41.4 | 18.2 | 59.0 | tests fail: box, scale, tie-open |
| 3 | 0.4 | 3 | 83.8 | 51.8 | 5.9 | 77.3 | 41.9 | 17.9 | 59.6 | tests fail: box, scale |
| 3 | 0.4 | 4 | 83.7 | 52.3 | 6.4 | 77.3 | 42.3 | 18.3 | 59.8 | tests fail: box, scale |
| 3 | 0.4 | 5 | 83.8 | 52.5 | 6.4 | 76.9 | 43.0 | 18.2 | 60.0 | tests fail: box, scale |
| 4 | 0.1 | 3 | 81.8 | 51.0 | 7.2 | 76.5 | 39.2 | 17.0 | 57.9 | tests fail: tie-open |
| 4 | 0.1 | 4 | 81.7 | 50.2 | 7.4 | 76.1 | 39.6 | 17.7 | 57.9 | tests fail: tie-open |
| 4 | 0.1 | 5 | 81.7 | 49.7 | 7.4 | 75.9 | 38.8 | 17.8 | 57.4 | tests fail: scale, tie-open |
| 4 | 0.2 | 3 | 82.6 | 51.5 | 7.0 | 76.8 | 39.8 | 16.7 | 58.3 | admissible |
| 4 | 0.2 | 4 | 82.1 | 50.8 | 7.2 | 76.7 | 40.0 | 17.6 | 58.3 | **chosen** |
| 4 | 0.2 | 5 | 81.8 | 50.0 | 7.3 | 76.6 | 40.0 | 17.7 | 58.3 | tests fail: scale, tie-open |
| 4 | 0.4 | 3 | 82.6 | 52.2 | 6.7 | 76.8 | 38.5 | 17.0 | 57.6 | admissible |
| 4 | 0.4 | 4 | 82.7 | 51.2 | 6.9 | 76.8 | 38.5 | 17.4 | 57.6 | admissible |
| 4 | 0.4 | 5 | 82.1 | 51.1 | 7.0 | 76.6 | 38.8 | 17.5 | 57.7 | tests fail: scale |
| 5 | 0.1 | 3 | 81.5 | 52.4 | 8.1 | 76.0 | 37.3 | 17.6 | 56.7 | rejected: full_solo below 38.3 |
| 5 | 0.1 | 4 | 81.4 | 51.4 | 8.3 | 75.9 | 37.0 | 17.9 | 56.5 | rejected: full_solo below 38.3 |
| 5 | 0.1 | 5 | 81.4 | 50.5 | 8.4 | 76.0 | 36.4 | 17.7 | 56.2 | rejected: full_solo below 38.3 |
| 5 | 0.2 | 3 | 81.9 | 53.6 | 8.1 | 76.2 | 37.0 | 17.2 | 56.6 | rejected: full_solo below 38.3 |
| 5 | 0.2 | 4 | 81.7 | 52.7 | 8.3 | 76.4 | 37.4 | 17.5 | 56.9 | rejected: full_solo below 38.3 |
| 5 | 0.2 | 5 | 81.4 | 52.6 | 8.4 | 76.2 | 37.2 | 17.5 | 56.7 | rejected: full_solo below 38.3 |
| 5 | 0.4 | 3 | 82.2 | 52.5 | 7.9 | 76.3 | 38.0 | 17.2 | 57.2 | rejected: full_solo below 38.3 |
| 5 | 0.4 | 4 | 82.0 | 51.8 | 8.3 | 76.4 | 37.1 | 17.4 | 56.8 | rejected: full_solo below 38.3 |
| 5 | 0.4 | 5 | 81.6 | 52.4 | 8.3 | 76.3 | 37.5 | 17.4 | 56.9 | rejected: full_solo below 38.3 |

The rule alone picks `hand_window=3, open_weight=0.2, open_reach=3`, at 60.1.
Every `hand_window=3` row fails box and scale: a three-fret hand cannot hold
the fifth-position pentatonic box, frets 5 to 8, without moving. Every
`hand_window=5` row is below full_solo's before-number.

Of the rows that keep the tests, two tie at 58.3: `open_weight=0.2` with
`open_reach` 3 and 4. The `open_reach=5` row ties on the number but fails
scale and tie-open: an open string is free with the hand at the 5th fret, so
the scale plays its E4 open, and the open G under a hand at the 9th costs 0.8
instead of 1.0, which beats the first-position shape's 1.5. The tie goes to
the starting values, `hand_window=4, open_weight=0.2, open_reach=4`.

### Sweep 2: ringing strings

The rule's pick from sweep 1 was carried forward first, before its test
failures were known:

```bash
make sweep ARGS="--full --cost hand_window=3 --cost open_weight=0.2 --cost open_reach=3 --cost ring_weight=0,1,2,4 --cost ring_tolerance=0.05,0.1,0.15,0.2"
```

| ring_weight | ring_tolerance | oracle_comp | oracle_solo | oracle_ovl | full_comp | full_solo | full_ovl | obj4 | verdict |
|---|---|---|---|---|---|---|---|---|---|
| defaults |  | 82.1 | 50.8 | 7.2 | 76.7 | 40.0 | 17.6 | 58.3 | admissible |
| 0 | 0.05 | 83.3 | 50.4 | 10.4 | 77.2 | 42.0 | 25.9 | 59.6 | tests fail: box, scale, ring |
| 0 | 0.1 | 83.3 | 50.4 | 10.4 | 77.2 | 42.0 | 25.9 | 59.6 | tests fail: box, scale, ring |
| 0 | 0.15 | 83.3 | 50.4 | 10.4 | 77.2 | 42.0 | 25.9 | 59.6 | tests fail: box, scale, ring |
| 0 | 0.2 | 83.3 | 50.4 | 10.4 | 77.2 | 42.0 | 25.9 | 59.6 | tests fail: box, scale, ring |
| 1 | 0.05 | 83.8 | 52.1 | 5.4 | 77.4 | 42.4 | 18.2 | 59.9 | tests fail: box, scale |
| 1 | 0.1 | 83.7 | 51.4 | 6.7 | 77.3 | 42.6 | 19.8 | 59.9 | tests fail: box, scale |
| 1 | 0.15 | 83.7 | 51.2 | 7.5 | 77.2 | 42.3 | 21.8 | 59.7 | tests fail: box, scale |
| 1 | 0.2 | 83.7 | 51.0 | 8.0 | 77.2 | 42.2 | 23.1 | 59.7 | tests fail: box, scale |
| 2 | 0.05 | 83.8 | 52.5 | 4.2 | 77.1 | 43.2 | 15.4 | 60.2 | tests fail: box, scale |
| 2 | 0.1 | 83.6 | 51.7 | 5.9 | 77.2 | 42.9 | 17.8 | 60.1 | tests fail: box, scale |
| 2 | 0.15 | 83.6 | 51.3 | 6.8 | 77.2 | 42.8 | 20.4 | 60.0 | tests fail: box, scale |
| 2 | 0.2 | 83.7 | 51.1 | 7.4 | 77.1 | 42.6 | 22.3 | 59.9 | tests fail: box, scale |
| 4 | 0.05 | 83.8 | 53.2 | 3.3 | 77.0 | 43.3 | 12.8 | 60.2 | tests fail: box, scale |
| 4 | 0.1 | 83.7 | 52.2 | 5.3 | 77.0 | 43.3 | 15.9 | 60.2 | tests fail: box, scale |
| 4 | 0.15 | 83.6 | 51.3 | 6.5 | 77.0 | 43.5 | 19.4 | 60.3 | rule's best; tests fail: box, scale |
| 4 | 0.2 | 83.7 | 51.2 | 7.1 | 77.1 | 42.9 | 21.6 | 60.0 | tests fail: box, scale |

No ring setting rescues `hand_window=3`: box and scale fail in every row, so
that line stops here. The sweep was run again from the row that keeps the
tests:

```bash
make sweep ARGS="--full --cost hand_window=4 --cost open_weight=0.2 --cost open_reach=4 --cost ring_weight=0,1,2,4 --cost ring_tolerance=0.05,0.1,0.15,0.2"
```

| ring_weight | ring_tolerance | oracle_comp | oracle_solo | oracle_ovl | full_comp | full_solo | full_ovl | obj4 | verdict |
|---|---|---|---|---|---|---|---|---|---|
| defaults |  | 82.1 | 50.8 | 7.2 | 76.7 | 40.0 | 17.6 | 58.3 | admissible |
| 0 | 0.05 | 81.5 | 48.9 | 13.8 | 76.5 | 38.5 | 28.4 | 57.5 | tests fail: ring |
| 0 | 0.1 | 81.5 | 48.9 | 13.8 | 76.5 | 38.5 | 28.4 | 57.5 | tests fail: ring |
| 0 | 0.15 | 81.5 | 48.9 | 13.8 | 76.5 | 38.5 | 28.4 | 57.5 | tests fail: ring |
| 0 | 0.2 | 81.5 | 48.9 | 13.8 | 76.5 | 38.5 | 28.4 | 57.5 | tests fail: ring |
| 1 | 0.05 | 82.2 | 49.9 | 5.8 | 77.0 | 39.6 | 17.0 | 58.3 | admissible |
| 1 | 0.1 | 82.2 | 50.8 | 8.5 | 76.8 | 39.6 | 19.6 | 58.2 | admissible |
| 1 | 0.15 | 82.1 | 49.6 | 9.6 | 76.6 | 39.4 | 22.5 | 58.0 | admissible |
| 1 | 0.2 | 82.0 | 49.6 | 10.3 | 76.7 | 38.6 | 24.2 | 57.7 | admissible |
| 2 | 0.05 | 82.2 | 51.0 | 4.4 | 76.8 | 39.8 | 14.4 | 58.3 | admissible |
| 2 | 0.1 | 82.1 | 50.8 | 7.2 | 76.7 | 40.0 | 17.6 | 58.3 | **chosen** |
| 2 | 0.15 | 82.1 | 50.4 | 8.7 | 76.4 | 40.0 | 21.1 | 58.2 | admissible |
| 2 | 0.2 | 82.1 | 49.7 | 9.6 | 76.7 | 39.2 | 23.4 | 57.9 | admissible |
| 4 | 0.05 | 82.3 | 50.7 | 3.7 | 76.2 | 40.4 | 12.2 | 58.3 | admissible |
| 4 | 0.1 | 82.2 | 50.6 | 6.7 | 76.2 | 39.9 | 15.9 | 58.1 | admissible |
| 4 | 0.15 | 82.1 | 50.3 | 8.4 | 76.1 | 40.2 | 20.3 | 58.1 | admissible |
| 4 | 0.2 | 82.1 | 49.5 | 9.2 | 76.5 | 39.3 | 22.8 | 57.9 | admissible |

Four rows tie at 58.3: `ring_weight=1` and 4 at `ring_tolerance=0.05`, and
`ring_weight=2` at 0.05 and at 0.1. The `defaults` row and `ring_weight=2,
ring_tolerance=0.1` are the same costs, so they count once. The starting
values stay. `ring_weight=0` fails ring: with no cost, A3 takes the G string
while G3 still sounds.

### Sweep 3: gaps, height and span

```bash
make sweep ARGS="--full --cost hand_window=4 --cost open_weight=0.2 --cost open_reach=4 --cost ring_weight=2 --cost ring_tolerance=0.1 --cost gap_weight=0,0.15,0.3,0.6 --cost height_weight=0,0.05 --cost span_weight=0.25,0.5,1"
```

| gap_weight | height_weight | span_weight | oracle_comp | oracle_solo | oracle_ovl | full_comp | full_solo | full_ovl | obj4 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| defaults |  |  | 82.1 | 50.8 | 7.2 | 76.7 | 40.0 | 17.6 | 58.3 | admissible |
| 0 | 0 | 0.25 | 79.0 | 50.5 | 7.3 | 74.0 | 39.0 | 17.1 | 56.5 | tests fail: power |
| 0 | 0 | 0.5 | 81.1 | 51.0 | 7.3 | 75.6 | 39.9 | 17.6 | 57.7 | tests fail: power |
| 0 | 0 | 1 | 82.3 | 51.1 | 8.0 | 75.9 | 41.9 | 18.9 | 58.9 | tests fail: tie-move, tie-open, power |
| 0 | 0.05 | 0.25 | 75.8 | 45.6 | 8.3 | 70.4 | 40.2 | 18.5 | 55.3 | tests fail: scale, power |
| 0 | 0.05 | 0.5 | 78.5 | 45.7 | 8.2 | 72.0 | 40.8 | 18.5 | 56.4 | tests fail: scale, power |
| 0 | 0.05 | 1 | 80.5 | 46.0 | 8.9 | 74.0 | 40.9 | 19.7 | 57.5 | tests fail: scale, tie-move, tie-open, power |
| 0.15 | 0 | 0.25 | 79.7 | 50.7 | 7.2 | 74.7 | 39.1 | 16.8 | 56.9 | admissible |
| 0.15 | 0 | 0.5 | 81.9 | 50.8 | 7.2 | 76.3 | 40.0 | 17.5 | 58.1 | admissible |
| 0.15 | 0 | 1 | 82.7 | 51.1 | 7.8 | 76.5 | 41.7 | 18.8 | 59.1 | rule's best; tests fail: tie-move, tie-open |
| 0.15 | 0.05 | 0.25 | 76.9 | 45.6 | 8.2 | 71.6 | 40.4 | 18.3 | 56.0 | tests fail: scale |
| 0.15 | 0.05 | 0.5 | 79.3 | 45.7 | 8.1 | 72.7 | 40.8 | 18.5 | 56.7 | tests fail: scale |
| 0.15 | 0.05 | 1 | 81.0 | 46.0 | 8.8 | 74.9 | 40.9 | 19.5 | 57.9 | tests fail: scale, tie-move, tie-open |
| 0.3 | 0 | 0.25 | 80.3 | 50.7 | 7.2 | 75.3 | 38.9 | 16.9 | 57.1 | admissible |
| 0.3 | 0 | 0.5 | 82.1 | 50.8 | 7.2 | 76.7 | 40.0 | 17.6 | 58.3 | admissible |
| 0.3 | 0 | 1 | 82.6 | 51.1 | 7.9 | 76.5 | 41.4 | 18.8 | 58.9 | tests fail: tie-move, tie-open |
| 0.3 | 0.05 | 0.25 | 77.3 | 45.6 | 8.2 | 71.8 | 40.3 | 18.4 | 56.1 | tests fail: scale |
| 0.3 | 0.05 | 0.5 | 79.2 | 45.8 | 8.1 | 73.0 | 40.8 | 18.5 | 56.9 | tests fail: scale |
| 0.3 | 0.05 | 1 | 81.1 | 46.0 | 8.7 | 74.8 | 40.9 | 19.4 | 57.9 | tests fail: scale, tie-move, tie-open |
| 0.6 | 0 | 0.25 | 81.1 | 50.7 | 7.3 | 76.0 | 38.4 | 17.6 | 57.2 | admissible |
| 0.6 | 0 | 0.5 | 83.0 | 50.8 | 7.4 | 77.0 | 39.9 | 17.7 | 58.5 | **chosen** |
| 0.6 | 0 | 1 | 82.7 | 51.1 | 7.9 | 76.6 | 40.8 | 19.0 | 58.7 | tests fail: tie-move, tie-open |
| 0.6 | 0.05 | 0.25 | 78.0 | 45.7 | 8.1 | 72.1 | 40.7 | 18.9 | 56.4 | tests fail: scale |
| 0.6 | 0.05 | 0.5 | 79.3 | 45.8 | 8.1 | 73.5 | 40.9 | 18.8 | 57.2 | tests fail: scale |
| 0.6 | 0.05 | 1 | 81.3 | 46.0 | 8.6 | 74.7 | 41.2 | 19.5 | 58.0 | tests fail: scale, tie-move, tie-open |

The rule alone picks `gap_weight=0.15, height_weight=0, span_weight=1`, at
59.1. Every `span_weight=1` row fails tie-move and tie-open. In tie-open,
F#3, G3 and C4 leave the first-position shape for an open G under a hand at
the 9th fret. Every `height_weight=0.05` row fails scale and loses about five
points of oracle solo. Every `gap_weight=0` row fails power.

The best row that keeps the tests is `gap_weight=0.6, height_weight=0,
span_weight=0.5`, at 58.5. 0.6 is the top of the grid; nothing above it was
tried.

### The chosen values

| field | starting | chosen |
|---|---|---|
| `move_weight` | 1.0 | 1.0, not swept |
| `span_weight` | 0.5 | 0.5 |
| `height_weight` | 0 | 0 |
| `hand_window` | 4 | 4 |
| `open_reach` | 4 | 4 |
| `open_weight` | 0.2 | 0.2 |
| `ring_weight` | 2.0 | 2.0 |
| `ring_tolerance` | 0.1 | 0.1 |
| `gap_weight` | 0.3 | **0.6** |

On dev, against the before-numbers:

| | oracle_comp | oracle_solo | full_comp | full_solo | f1_comp | f1_solo | oracle_ovl | full_ovl | obj4 |
|---|---|---|---|---|---|---|---|---|---|
| before, old mapper | 74.4 | 42.7 | 67.1 | 38.3 | 0.709 | 0.810 | 18.4 | 33.6 | 52.7 |
| starting values | 82.1 | 50.8 | 76.7 | 40.0 | 0.709 | 0.810 | 7.2 | 17.6 | 58.3 |
| chosen | 83.0 | 50.8 | 77.0 | 39.9 | 0.709 | 0.810 | 7.4 | 17.7 | 58.5 |

With the new defaults, `make sweep ARGS=--full` prints the chosen row again,
to the digit.

### Conflicts

- **The hand window.** `hand_window=3` scores up to 60.3, against 58.5. It
  fails box and scale. The tests stand, and `hand_window` stays at 4.
- **Span.** `span_weight=1` scores up to 59.1. It fails tie-move and
  tie-open. The tests stand, and `span_weight` stays at 0.5.
- **The gap arithmetic test.**
  `test_a_chord_pays_for_each_unused_string_between_its_outer_strings` works
  its costs out at 0.3 a skipped string. It now names
  `MapperCosts(span_weight=0.5, gap_weight=0.3)` instead of reading the
  defaults. Its expected costs are unchanged.

## Timing after tuning

Task 1's benchmark, unchanged, with the chosen values. Five runs, run through
`uv run python`:

| | seconds |
|---|---|
| after, five runs | 0.143 0.134 0.199 0.227 0.137 |
| after, median | 0.143 |

Under the 2 s limit.

## Stage 4 on test

Commit `354c2c8`, clean tree, the tuned costs:

```bash
make eval
make eval ARGS=--full
```

Before is Task 1's pair, at `3439361`. After is
[`2026-10-19-354c2c8-oracle-test.json`](../../../eval/results/2026-10-19-354c2c8-oracle-test.json)
and
[`2026-10-19-354c2c8-full-test.json`](../../../eval/results/2026-10-19-354c2c8-full-test.json).
Changes are taken from the unrounded rates.

| condition | mode | style | before | after | change | met |
|---|---|---|---|---|---|---|
| 1. string accuracy rises | oracle | comp | 62.0% | 74.0% | +11.9 | yes |
| | oracle | solo | 30.2% | 45.5% | +15.3 | yes |
| 2. string accuracy rises | full | comp | 57.8% | 64.6% | +6.8 | yes |
| | full | solo | 30.8% | 41.9% | +11.0 | yes |
| 3. overlaps fall, per 1000 | oracle | all | 9.0 | 3.9 | −5.1 | yes |
| | full | all | 30.7 | 16.8 | −13.9 | yes |

Overlaps also fall in each style: oracle 6.4 to 1.8 in comp and 16.6 to 10.1
in solo; full 31.7 to 17.2 in comp and 27.2 to 15.5 in solo. Overall, oracle
string accuracy goes from 54.0% to 66.8% (the spike reached 65.5%), and full
from 50.3% to 58.3%. Note F1 (0.777) and precision (0.734) do not move: stage
2 is untouched.

**Condition 8 is met.**
- All 70 mapper tests pass. Among them,
  `test_every_placed_note_satisfies_the_invariant` checks 300 random inputs
  in three tunings.
- The 60 test excerpts' true pitches, mapped in two separate processes, give
  the same 8698 placements, by SHA-256. Every one has
  `pitch_of(string, fret) == midi`.
- A second oracle run, into a scratch directory, gives the same summary and
  the same per-excerpt results.
- The defaults row is the same in all four sweeps. The chosen row comes back
  to the digit with the new defaults.

Stage 4 meets conditions 1, 2, 3 and 8 on test.
