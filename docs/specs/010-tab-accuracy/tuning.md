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
scale and tie-open. For the scale, an open string is free with the hand at
the 5th fret, so it plays its E4 open. For tie-open (F#3, G3, C4), the
9th-fret shape totals 1.3 at `open_reach=5`: 0.5 for the span and 0.8 for the
open G (four frets above the reach, at 0.2 each). That beats the
first-position shape's 1.5. At `open_reach=4` the open charge is 1.0 (five
frets), the totals tie at 1.5, and the lower frets win. The tie goes to the starting
values, `hand_window=4, open_weight=0.2, open_reach=4`.

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

The plan's benchmark met its 2 s limit but does not exercise the extra
hand-position states. Its chords have one to three fingerings each, so a
transition has little to multiply. The worst case is a voicing with many
fingerings played over and over. It was measured at the end of 010, at
`cc86137` (the mapper is as at `ebf0cb1`), against `ff1bce4`, the last commit
before 010. It is the same script on the same machine, five runs each, with a
worker process running in the background. Five minutes at four voicings a
second is 1200 voicings:

| 1200 voicings, 0.25 s apart | `ff1bce4` | `cc86137` |
|---|---|---|
| D3 G3 B3 E4 (27 fingerings) every time | 1.21 s | 8.05 s |
| four mixed 4-note chords in turn | 0.33 s | 1.36 s |
| random 3-note voicings | 0.13 s | 0.31 s |
| Task 1's strums | 0.10 s | 0.18 s |

Medians. The worst case is about six and a half times slower than before 010,
and the only row over 2 s. The final review measured the same case at 6.85 s
against 1.01 s at `ff1bce4`, about the same ratio. It is small next
to separation, which alone takes tens of seconds to minutes for a song
(`docs/specs/001-guitarvis-design/spec.md`), and a real song does not repeat
one 27-fingering voicing for five minutes. No mapper code changed for it.

A follow-up, if it ever matters: `_ring` depends on the previous voicing's
fingering and the new fingering, not on where the hand lands. `_viterbi`
calls it once per hand-position state, so caching it per (previous fingering,
fingering) pair would cut the repeated work.

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

## Stage 2 sweeps

Commit `6b2136b`, dev split, full mode, with stage 4's tuned costs. Each
distinct set of transcription settings is one basic-pitch pass over the 300
dev excerpts, about three minutes, cached under `~/.cache/guitarvis/sweep`.

In every row of every sweep, oracle_comp is 83.0, oracle_solo 50.8 and
oracle_ovl 7.4. Oracle mode never hears the audio. Those columns are left out
of the tables.

The `defaults` row is stage 4 as shipped with basic-pitch's own decoding:
onset 0.5, frame 0.3, 127.7 ms, melodia on, no ghost rule. It gives the
before-numbers for every rule below, and it is stage 4's chosen row to the
digit. Task 10 added two settings fields, so its transcriptions were made
again under a new cache key. All 300 are byte-identical to the ones stage 4's
sweeps used.

### The rule

- Maximise obj2, the mean of f1_comp and f1_solo.
- Precision must rise: prec_comp above 0.728, prec_solo above 0.773.
- Reject a row below a before-number: oracle_comp 83.0, oracle_solo 50.8,
  full_comp 77.0, full_solo 39.9, f1_comp 0.709, f1_solo 0.810, prec_comp
  0.728, prec_solo 0.773.
- Reject a row whose full_ovl is above 17.7.
- Rows are compared as printed. A printed tie on obj2 that decides a choice
  is settled on the unrounded obj2. Only an exact tie goes to the row nearer
  basic-pitch's defaults.
- Between the two ghost forms, each at its own best ratio, take the higher
  full_solo. Within 0.5 points, take the plain rule,
  `ghost_alone_only=false`. No rule, `ghost_ratio=none`, stays a candidate.

### Sweep 1: decoding

```bash
make sweep ARGS="--full --transcription melodia_trick=true,false --transcription frame_threshold=0.3,0.35,0.4 --transcription minimum_note_length_ms=58,93,127.7"
```

| melodia_trick | frame_threshold | minimum_note_length_ms | full_comp | full_solo | f1_comp | f1_solo | prec_comp | prec_solo | full_ovl | obj4 | obj2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| defaults |  |  | 77.0 | 39.9 | 0.709 | 0.810 | 0.728 | 0.773 | 17.7 | 58.5 | 0.759 | before-numbers |
| true | 0.3 | 58 | 75.0 | 37.4 | 0.717 | 0.767 | 0.657 | 0.658 | 19.4 | 56.2 | 0.742 | rejected: full_comp, full_solo, f1_solo, prec_comp, prec_solo below; full_ovl above |
| true | 0.3 | 93 | 76.7 | 39.1 | 0.727 | 0.806 | 0.700 | 0.729 | 18.5 | 57.9 | 0.766 | rejected: full_comp, full_solo, f1_solo, prec_comp, prec_solo below; full_ovl above |
| true | 0.3 | 127.7 | 77.0 | 39.9 | 0.709 | 0.810 | 0.728 | 0.773 | 17.7 | 58.5 | 0.759 | the defaults again |
| true | 0.35 | 58 | 76.9 | 35.3 | 0.731 | 0.801 | 0.693 | 0.711 | 14.2 | 56.1 | 0.766 | rejected: full_comp, full_solo, f1_solo, prec_comp, prec_solo below |
| true | 0.35 | 93 | 78.5 | 40.0 | 0.732 | 0.832 | 0.732 | 0.777 | 13.7 | 59.2 | 0.782 | admissible |
| true | 0.35 | 127.7 | 78.3 | 42.5 | 0.705 | 0.823 | 0.755 | 0.811 | 12.7 | 60.4 | 0.764 | rejected: f1_comp below |
| true | 0.4 | 58 | 79.4 | 37.3 | 0.738 | 0.825 | 0.721 | 0.753 | 9.6 | 58.3 | 0.781 | rejected: full_solo, prec_comp, prec_solo below |
| true | 0.4 | 93 | 79.9 | 40.5 | 0.730 | 0.846 | 0.756 | 0.809 | 8.8 | 60.2 | 0.788 | admissible |
| true | 0.4 | 127.7 | 78.3 | 40.1 | 0.695 | 0.827 | 0.775 | 0.836 | 8.8 | 59.2 | 0.761 | rejected: f1_comp below |
| false | 0.3 | 58 | 75.6 | 31.4 | 0.727 | 0.795 | 0.691 | 0.705 | 15.9 | 53.5 | 0.761 | rejected: full_comp, full_solo, f1_solo, prec_comp, prec_solo below |
| false | 0.3 | 93 | 77.2 | 35.5 | 0.731 | 0.827 | 0.728 | 0.772 | 15.3 | 56.3 | 0.779 | rejected: full_solo, prec_solo below; prec_comp not above |
| false | 0.3 | 127.7 | 77.1 | 36.0 | 0.705 | 0.818 | 0.750 | 0.807 | 14.7 | 56.5 | 0.762 | rejected: full_solo, f1_comp below |
| false | 0.35 | 58 | 77.7 | 32.7 | 0.738 | 0.820 | 0.721 | 0.746 | 11.9 | 55.2 | 0.779 | rejected: full_solo, prec_comp, prec_solo below |
| false | 0.35 | 93 | 79.2 | 39.4 | 0.735 | 0.844 | 0.755 | 0.807 | 11.8 | 59.3 | 0.789 | rejected: full_solo below |
| false | 0.35 | 127.7 | 78.3 | 40.0 | 0.701 | 0.825 | 0.773 | 0.835 | 11.1 | 59.1 | 0.763 | rejected: f1_comp below |
| false | 0.4 | 58 | 78.8 | 37.4 | 0.743 | 0.838 | 0.745 | 0.779 | 8.7 | 58.1 | 0.790 | rejected: full_solo below |
| false | 0.4 | 93 | 79.4 | 41.2 | 0.732 | 0.853 | 0.776 | 0.831 | 8.1 | 60.3 | 0.793 | **chosen** |
| false | 0.4 | 127.7 | 78.2 | 41.1 | 0.692 | 0.826 | 0.792 | 0.853 | 8.1 | 59.7 | 0.759 | rejected: f1_comp below |

Three rows are admissible. The rule picks `melodia_trick=false,
frame_threshold=0.4, minimum_note_length_ms=93`, at 0.793. The next is the
same row with melodia on, at 0.788.

- Every 58 ms row is below full_solo's before-number. That includes the
  spec's starting point, melodia off at 0.4 and 58 ms, which scores 0.790
  with full_solo at 37.4.
- Every 127.7 ms row but the defaults is below f1_comp's before-number.
  Precision rises in those rows while F1 falls, so comp recall falls.
- No row at frame 0.3 is admissible.

### Sweep 2: onset

The winner's other three values, fixed:

```bash
make sweep ARGS="--full --transcription melodia_trick=false --transcription frame_threshold=0.4 --transcription minimum_note_length_ms=93 --transcription onset_threshold=0.4,0.5,0.6"
```

| onset_threshold | full_comp | full_solo | f1_comp | f1_solo | prec_comp | prec_solo | full_ovl | obj4 | obj2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| defaults | 77.0 | 39.9 | 0.709 | 0.810 | 0.728 | 0.773 | 17.7 | 58.5 | 0.759 | before-numbers |
| 0.4 | 80.2 | 43.6 | 0.708 | 0.823 | 0.698 | 0.775 | 9.2 | 61.9 | 0.766 | rejected: f1_comp, prec_comp below |
| 0.5 | 79.4 | 41.2 | 0.732 | 0.853 | 0.776 | 0.831 | 8.1 | 60.3 | 0.793 | **chosen** |
| 0.6 | 77.5 | 37.2 | 0.724 | 0.872 | 0.833 | 0.873 | 8.3 | 57.4 | 0.798 | rejected: full_solo below |

0.6 has the best obj2, 0.798, but solo string accuracy falls to 37.2. 0.4
is below f1_comp and prec_comp. `onset_threshold` stays at 0.5. Its row
repeats sweep 1's to the digit.

### Sweep 3: harmonic ghosts

All four decoding values, fixed:

```bash
make sweep ARGS="--full --transcription melodia_trick=false --transcription frame_threshold=0.4 --transcription minimum_note_length_ms=93 --transcription onset_threshold=0.5 --transcription ghost_ratio=none,0.5,0.6,0.7,0.8 --transcription ghost_alone_only=false,true"
```

| ghost_ratio | ghost_alone_only | full_comp | full_solo | f1_comp | f1_solo | prec_comp | prec_solo | full_ovl | obj4 | obj2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| defaults |  | 77.0 | 39.9 | 0.709 | 0.810 | 0.728 | 0.773 | 17.7 | 58.5 | 0.759 | before-numbers |
| none | false | 79.4 | 41.2 | 0.732 | 0.853 | 0.776 | 0.831 | 8.1 | 60.3 | 0.793 | admissible |
| none | true | 79.4 | 41.2 | 0.732 | 0.853 | 0.776 | 0.831 | 8.1 | 60.3 | 0.793 | admissible |
| 0.5 | false | 79.1 | 41.6 | 0.732 | 0.854 | 0.777 | 0.833 | 8.1 | 60.3 | 0.793 | admissible |
| 0.5 | true | 79.4 | 41.6 | 0.732 | 0.854 | 0.776 | 0.833 | 8.1 | 60.5 | 0.793 | admissible |
| 0.6 | false | 79.0 | 43.5 | 0.732 | 0.857 | 0.782 | 0.839 | 7.9 | 61.2 | 0.795 | admissible |
| 0.6 | true | 79.4 | 42.9 | 0.733 | 0.857 | 0.777 | 0.838 | 8.0 | 61.1 | 0.795 | admissible |
| 0.7 | false | 77.8 | 50.3 | 0.728 | 0.862 | 0.790 | 0.849 | 7.6 | 64.0 | 0.795 | **dev rule's pick**: plain rule's best |
| 0.7 | true | 79.1 | 47.7 | 0.733 | 0.861 | 0.779 | 0.846 | 8.1 | 63.4 | 0.797 | admissible |
| 0.8 | false | 75.7 | 51.7 | 0.719 | 0.864 | 0.796 | 0.854 | 7.5 | 63.7 | 0.792 | rejected: full_comp below |
| 0.8 | true | 79.2 | 48.5 | 0.733 | 0.862 | 0.781 | 0.850 | 8.1 | 63.8 | 0.798 | **shipped**: alone-only rule's best |

The two `ghost_ratio=none` rows are the same settings under two cache keys,
transcribed separately. Their 300 transcriptions are byte-identical, and
both repeat sweep 2's chosen row.

The plain rule's 0.6 and 0.7 tie on obj2 as printed, and that tie decides the
form. It is settled on the unrounded numbers. A tie at float precision would
have gone to 0.6, the spec's value for this form, but there is none. The same
cached transcriptions were scored again through the sweep's own code
(`CachedTranscriptions`, `score_full` without an analyzer, `summarize`), at
six decimals:

| ghost_ratio | ghost_alone_only | full_comp | full_solo | f1_comp | f1_solo | obj2 |
|---|---|---|---|---|---|---|
| defaults | | 76.961021 | 39.945522 | 0.709049 | 0.809705 | 0.759377 |
| none | either | 79.355697 | 41.172360 | 0.732226 | 0.853489 | 0.792857 |
| 0.5 | false | 79.125065 | 41.574779 | 0.732335 | 0.854234 | 0.793284 |
| 0.5 | true | 79.357866 | 41.574779 | 0.732340 | 0.854234 | 0.793287 |
| 0.6 | false | 78.969111 | 43.469816 | 0.732081 | 0.857352 | 0.794717 |
| 0.6 | true | 79.357629 | 42.892652 | 0.732674 | 0.856867 | 0.794771 |
| 0.7 | false | 77.804739 | 50.276157 | 0.728203 | 0.862173 | 0.795188 |
| 0.7 | true | 79.106522 | 47.745997 | 0.733094 | 0.860948 | 0.797021 |
| 0.8 | false | 75.675043 | 51.729241 | 0.719258 | 0.863959 | 0.791609 |
| 0.8 | true | 79.165121 | 48.521631 | 0.732919 | 0.862492 | 0.797706 |

Every value rounds to its printed cell. The unrounded numbers leave every
verdict's admissibility as it was.

- **The plain rule.** At 0.8 it is below full_comp, at 75.7: chords hold
  real octaves, as the research found. Its best is 0.7, at 0.795188 against
  0.6's 0.794717. Its full_solo is 50.28.
- **The alone-only rule.** Its best is 0.8, at 0.797706, the best obj2 in the
  sweep. Its full_solo is 48.52.
- **Between the forms.** 50.28 against 48.52 is 1.75 points, so the plain
  rule at 0.7 is the dev rule's pick. It beats no rule on obj2, 0.795188
  against 0.792857.

A first pass broke the printed tie toward 0.6 and so chose the alone-only
rule at 0.8. That is commit `fa69e14` and its test pair, below.

The plain rule at 0.7 is the dev rule's pick. It is not what ships. Its test
run failed condition 6 in comp, and on 2026-10-19 the user chose the
alone-only rule at 0.8. See *Stage 2 on test*.

### The chosen values

| field | basic-pitch's default | spec's starting point | dev rule's pick | shipped |
|---|---|---|---|---|
| `onset_threshold` | 0.5 | 0.5 | 0.5 | 0.5 |
| `frame_threshold` | 0.3 | 0.4 | 0.4 | **0.4** |
| `minimum_note_length_ms` | 127.7 | about 58 | 93 | **93** |
| `melodia_trick` | on | off | off | **off** |
| `ghost_ratio` | no rule | 0.6 plain, or 0.8 alone-only | 0.7 | **0.8** |
| `ghost_alone_only` | — | | false | **true** |

The two ghost rows differ between the last two columns. The dev rule picked the
plain rule at 0.7. It failed condition 6 in comp on test, and the user chose
the alone-only rule at 0.8 instead (*Stage 2 on test*, below). The other four
settings are the same in both.

On dev, against the before-numbers:

| | full_comp | full_solo | f1_comp | f1_solo | prec_comp | prec_solo | full_ovl | obj2 |
|---|---|---|---|---|---|---|---|---|
| before, stage 4 and basic-pitch's decoding | 77.0 | 39.9 | 0.709 | 0.810 | 0.728 | 0.773 | 17.7 | 0.759 |
| tuned decoding, no ghost rule | 79.4 | 41.2 | 0.732 | 0.853 | 0.776 | 0.831 | 8.1 | 0.793 |
| dev rule's pick: plain rule at 0.7 | 77.8 | 50.3 | 0.728 | 0.862 | 0.790 | 0.849 | 7.6 | 0.795 |
| shipped: alone-only rule at 0.8 | 79.2 | 48.5 | 0.733 | 0.862 | 0.781 | 0.850 | 8.1 | 0.798 |

The shipped row is sweep 3's `0.8, true` row. The sweep was not run again
after the revert. `CACHE_VERSION` goes from 1 to 2. It stayed at 2 through the
move to the plain rule and stays at 2 on the move back: the branch has not
shipped, and relative to `main` it is still one bump. 2 already sets aside
every entry from before 010.

**The choice is provisional.** `frame_threshold` and `melodia_trick` reach
production only through the real-song review (spec, *Stage 2 · decoding*),
so this choice waits on Task 12's sign-off. A setting the review rejects goes
back to basic-pitch's default. Without the ghost rule, sweep 1 shows what
that would cost on dev. Melodia back on (`true, 0.4, 93`) is still
admissible, at 0.788. Frame back at 0.3 (`false, 0.3, 93`) is not: full_solo
falls to 35.5, and precision does not rise.

### Tests that read the old defaults

- `test_default_settings_are_basic_pitchs_own` is now
  `test_default_settings_are_010s_tuned_values`, and pins the chosen values.
- `test_keys_are_versioned_and_per_upload` pins `CACHE_VERSION` at 2. Its
  other-version probe uses version 1.
- Four tests name the values they run with instead of reading the defaults.
  Their expectations are unchanged.
  - `test_ghosts_are_kept_by_default` is now
    `test_ghosts_are_kept_when_the_rule_is_off`, with `ghost_ratio=None`.
  - The eval's `EchoTranscriber` names basic-pitch's own settings, which
    `test_full_mode_prints_and_records_precision_by_confidence` checks are
    recorded.
  - `test_full_results_record_the_transcription_settings` passes
    `frame_threshold=0.3`, the value it checks.
  - `test_settings_key_is_stable_and_distinguishes` probes
    `melodia_trick=True`, now the non-default value.

## Stage 2 on test

The current pair is at `fa69e14`, with the alone-only rule at 0.8. The pair at
`5624075`, with the plain rule at 0.7, is history. Both pairs' files stay in
`eval/results/`.

### The decision

On 2026-10-19 the user chose to ship the alone-only ghost rule at 0.8.

- The plain rule at 0.7 was the dev rule's pick on the unrounded values. On
  test it failed condition 6 in comp: string accuracy fell from 64.6% to
  63.8%, which is 0.80 points against a tolerance of 0.5.
- The alone-only rule at 0.8 met conditions 4, 5, 6 and 8 on test.
- The user chose it with both test results in view. The plan's dev and test
  discipline normally avoids that: the test split decided between two
  candidates. The choice is not a dev result.
- Commit `2a347e3` reverts `5624075`. The stage-2 code is identical to
  `fa69e14`'s: at `ebf0cb1`, `git diff fa69e14 ebf0cb1 -- apps packages` is
  empty, and `-- web` differs only in comments in `web/src/confidence.ts` (the
  recalibration in `5a621e7`). No further test run was made. The code is the
  same, so the `fa69e14` results stand.
- `CACHE_VERSION` stays at 2.
- The real-song round for stage 2 (`real-songs.md`) ran at `dc315bd` with the
  plain rule at 0.7. Round `stage2b`, in the same file, was made afterwards at
  `679ce9e`, which has the reverted code and the alone-only rule at 0.8.

### `fa69e14`: the alone-only rule at 0.8 (current)

This is the first choice, made when the plain rule's printed tie went to
0.6. It is current again by the user's decision, above. The decoding settings
are the same as the plain rule's.
[`2026-10-19-fa69e14-full-test.json`](../../../eval/results/2026-10-19-fa69e14-full-test.json)
and
[`2026-10-19-fa69e14-oracle-test.json`](../../../eval/results/2026-10-19-fa69e14-oracle-test.json),
against Task 9's pair:

| condition | mode | style | before | after | change | met |
|---|---|---|---|---|---|---|
| 4. note precision rises | full | comp | 0.700 | 0.765 | +6.5 | yes |
| | full | solo | 0.845 | 0.899 | +5.4 | yes |
| 5. note F1 holds | full | comp | 0.745 | 0.772 | +2.7 | yes |
| | full | solo | 0.874 | 0.912 | +3.8 | yes |
| 6. string accuracy holds | full | comp | 64.6% | 65.5% | +0.9 | yes |
| | full | solo | 41.9% | 42.2% | +0.3 | yes |

- Overall, precision went from 0.734 to 0.799 and note F1 from 0.777 to
  0.807, with 8910 notes reported.
- Full-mode string accuracy went from 58.3% to 58.9%, and overlaps per 1000
  from 16.8 to 5.1.
- The run printed `HIDE` 0.5 and `FULL` 0.6.
- Condition 8 held: 8870 placements from 8910 notes, the same SHA-256 in two
  processes, and every one with `pitch_of(string, fret) == midi`.

That pair met conditions 4, 5, 6 and 8. Condition 7, the real-song review,
is Task 12's.

### `5624075`: the plain rule at 0.7 (history)

Commit `5624075`, clean tree:

```bash
make eval ARGS=--full
make eval
```

Before is Task 9's pair, at `354c2c8`. After is
[`2026-10-19-5624075-full-test.json`](../../../eval/results/2026-10-19-5624075-full-test.json)
and
[`2026-10-19-5624075-oracle-test.json`](../../../eval/results/2026-10-19-5624075-oracle-test.json).
Changes are taken from the unrounded rates, in points.

| condition | mode | style | before | after | change | met |
|---|---|---|---|---|---|---|
| 4. note precision rises | full | comp | 0.700 | 0.771 | +7.2 | yes |
| | full | solo | 0.845 | 0.898 | +5.3 | yes |
| 5. note F1 holds | full | comp | 0.745 | 0.767 | +2.3 | yes |
| | full | solo | 0.874 | 0.912 | +3.7 | yes |
| 6. string accuracy holds | full | comp | 64.6% | 63.8% | −0.8 | **no** |
| | full | solo | 41.9% | 42.2% | +0.4 | yes |

**Condition 6 fails in comp.**
- Full-mode comp string accuracy falls from 64.6% to 63.8%: 3179 of 4983
  matched notes on the right string, against 3353 of 5191. That is 0.80
  points, and the tolerance is 0.5.
- On dev the same setting held comp, at 77.80 against 76.96.
- The alone-only rule at 0.8, measured first, held comp on test, at 65.5%
  (+0.9).
- In comp the plain rule leaves 6472 notes, against the alone-only rule's
  6666, and 4991 matched, against 5098.
- Following the spec, stage 2 waited for an explicit decision. It is below.

Overall, precision goes from 0.734 to 0.804 and note F1 from 0.777 to 0.804.
The transcriber reports 8721 notes, against 9778. Recall falls in comp, from
0.796 to 0.764, and rises in solo, from 0.906 to 0.927. Full-mode string
accuracy goes from 58.3% to 57.6%. Overlaps per 1000 fall from 16.8 to 5.5:
17.2 to 5.3 in comp, 15.5 to 6.2 in solo. Chord accuracy (33.5%) does not
move. The oracle file matches Task 9's in summary and in every excerpt.

The run printed `HIDE` 0.5 and `FULL` 0.6, the values `confidence.ts` holds
now. Task 13 re-derives them.

**Condition 8 is met.**
- All 70 mapper tests and 29 transcription tests pass. Among them,
  `test_every_placed_note_satisfies_the_invariant` checks 300 random inputs
  in three tunings.
- The 60 test excerpts, transcribed with these settings and mapped in two
  separate processes, give the same 8692 placements from 8721 notes, by
  SHA-256. Every one has `pitch_of(string, fret) == midi`.
- The second oracle run gives Task 9's summary and per-excerpt results
  exactly.
- On dev, two separate transcription passes of the same settings give
  byte-identical notes for all 300 excerpts, twice over: the defaults (Task
  9's pass and this one), and the two `ghost_ratio=none` rows of sweep 3.
- With the defaults at `5624075`, the sweep printed the dev rule's pick again,
  to the digit.

At `5624075`, stage 2 met conditions 4, 5 and 8 on test. It failed
condition 6 in comp. This pair is history. Condition 7, the real-song review,
is Task 12's.

## After the PR review

**Date:** 2026-10-20

The code review of PR #26 led to four fixes:

- **`29f1f80`: open notes in a chord.** A note is exempt from the open-string
  cost when every playable fingering of its voicing plays it open, judged
  before the beam. A2 beside E2, which holds the low string, no longer drags
  a riff toward the nut.
- **`a7c350e`: alone-only ghosts.** The alone-only ghost rule now needs at
  least one other note starting with the ghost, and every such note must be a
  base. A melody note over a held bass an octave below is no longer deleted.
- **`793dc96`: the sweep's cache key.** It now also covers the worker's
  `CACHE_VERSION`, `MIN_CONFIDENCE`, `GHOST_INTERVALS` and `GHOST_LEAD_SEC`.
- **`7c8641c`: the ring cost.** It is worked out once per fingering pair,
  not once per hand state. The output is identical.

F1 is deferred to an issue. That is the first landing: letting a hand that
arrives from nowhere land anywhere its box covers the shape. Its fix flips
four pinned musical tests:
- `test_an_open_string_does_not_reset_the_hand_position`
- `test_twelfth_position_stays_up_the_neck`
- `test_a_tie_with_an_open_string_goes_to_the_lower_frets`
- `test_a_note_still_ringing_keeps_its_string`

`CACHE_VERSION` stays at 2. The ghost fix changes stage 2's output, but the
branch has not shipped, and 2 is one bump from `main`.

### Dev

Commit `7c8641c`, clean tree. The cache is a fresh directory, because the
ghost fix changes the notes without changing a setting:

```bash
make sweep ARGS="--full --cache <fresh directory>"
```

| | oracle_comp | oracle_solo | full_comp | full_solo | f1_comp | f1_solo | prec_comp | prec_solo | oracle_ovl | full_ovl |
|---|---|---|---|---|---|---|---|---|---|---|
| before-numbers | 74.4 | 42.7 | 67.1 | 38.3 | 0.709 | 0.810 | 0.728 | 0.773 | 18.4 | 33.6 |
| shipped, before the review | 83.0 | 50.8 | 79.2 | 48.5 | 0.733 | 0.862 | 0.781 | 0.850 | 7.4 | 8.1 |
| after the review | 83.0 | 50.8 | 79.3 | 48.8 | 0.733 | 0.862 | 0.781 | 0.850 | 7.4 | 8.2 |

No column is below its before-number, and both overlap columns are below
theirs. obj4 is 64.0 and obj2 0.798.

The whole change on dev comes from the ghost fix. The mapper at `9b49746` and
the mapper at `7c8641c` place the 300 dev transcriptions identically.

### Test

Commit `7c8641c`, clean tree, `make eval` and `make eval ARGS=--full`:
[`2026-10-20-7c8641c-oracle-test.json`](../../../eval/results/2026-10-20-7c8641c-oracle-test.json)
and
[`2026-10-20-7c8641c-full-test.json`](../../../eval/results/2026-10-20-7c8641c-full-test.json).
Conditions 1–3 are measured against `3439361`, and 4–5 against `354c2c8`.
The last column is `fa69e14`, the pair before the review. Changes are taken
from the unrounded rates.

| condition | mode | style | before | after | change | met | `fa69e14` |
|---|---|---|---|---|---|---|---|
| 1. string accuracy rises | oracle | comp | 62.0% | 74.0% | +11.95 | yes | 74.0% |
| | oracle | solo | 30.2% | 45.5% | +15.33 | yes | 45.5% |
| 2. string accuracy rises | full | comp | 57.8% | 65.4% | +7.69 | yes | 65.5% |
| | full | solo | 30.8% | 42.2% | +11.36 | yes | 42.2% |
| 3. overlaps fall, per 1000 | oracle | all | 9.0 | 3.9 | −5.06 | yes | 3.9 |
| | full | all | 30.7 | 5.4 | −25.25 | yes | 5.1 |
| 4. note precision rises | full | comp | 0.700 | 0.764 | +6.42 | yes | 0.765 |
| | full | solo | 0.845 | 0.899 | +5.41 | yes | 0.899 |
| 5. note F1 holds | full | comp | 0.745 | 0.772 | +2.75 | yes | 0.772 |
| | full | solo | 0.874 | 0.912 | +3.76 | yes | 0.912 |

**Oracle.** The oracle file matches `fa69e14`'s in its summary and in every
excerpt.

**Full mode.** Solo does not move. In comp, the ghost fix keeps 18 more notes
(6684, against 6666), and 7 more of them match the truth (5105, against
5098). Comp precision falls from 0.7648 to 0.7638, and F1 is flat. Full-mode
comp string accuracy is 3335 of 5096 matched notes, against 3333 of 5089.

**The open-note fix on test.** The shipped transcriptions, mapped by
`9b49746`'s mapper, give 3340 of 5096 in comp (65.54%), against 3335 now.
Comp overlaps are 4.82 per 1000, against 5.12 now. Solo is identical. So the
open-note fix costs 5 comp notes on test and none on dev.

**Condition 6.** Full-mode string accuracy holds against the same mapper with
basic-pitch's default decoding. The comparison rows were computed on test at
`7c8641c` with a throwaway script, `score_full(..., analyzer=None)` and
`summarize`, and are not committed.

| decoding, mapper at `7c8641c` | comp | solo | met |
|---|---|---|---|
| shipped (the results file) | 65.44% (3335/5096) | 42.19% (851/2017) | |
| basic-pitch's own: onset 0.5, frame 0.3, 127.7 ms, melodia on, no ghost rule | 64.21% (3333/5191) | 41.87% (827/1975) | yes: +1.24, +0.32 |
| basic-pitch's decoding with the ghost rule at its default (alone-only, 0.8) | 63.87% (3311/5184) | 47.21% (929/1968) | in solo, no: −5.01 |

The second row is the comparison condition 6 means. It is stage 2 switched
off: basic-pitch's predict() has no ghost rule, and it is the decoding behind
`354c2c8`'s pair. The same transcriptions there gave 3353 of 5191 in comp;
the open-note fix moves 20 of them.

The third row is a different setup: the brief's constructor, which leaves
`ghost_ratio` at its default. That combination was never a dev candidate,
because sweep 3 fixed the decoding before trying ghost rules. On test, its
solo string accuracy is 5.0 points above the shipped decoding. Its precision
(0.716 comp, 0.859 solo) and F1 (0.754, 0.880) are below the shipped
decoding's. It is recorded here and not acted on, since acting on it would
mean tuning on test.

**Condition 8 is met.**
- `make check` passes, with `GUITARVIS_REQUIRE_SERVICES=1`: 682 Python tests
  and 330 web tests.
- A second oracle run and a second full run, into a scratch directory, give
  the committed files' summaries and every excerpt exactly.
- Two separate processes map the 60 test excerpts' transcriptions to the
  same 8888 placements from 8928 notes, by SHA-256. All 8888 have
  `pitch_of(string, fret) == midi`.

**Thresholds.** The run printed `HIDE` 0.5 and `FULL` 0.6, and `CHORD_HIDE`
0.7 and `CHORD_FULL` 0.8. These are the values `web/src/confidence.ts`
holds.

**The current pair** is `7c8641c`'s. `fa69e14`'s is history.

### Timing

The plan's benchmark and the worst case from *Timing after tuning*, five runs
each, with a worker process running in the background. Times are medians, in
seconds:

| 1200 voicings, 0.25 s apart | `9b49746` | `793dc96` (before the ring fix) | `7c8641c` (after it) |
|---|---|---|---|
| D3 G3 B3 E4 (27 fingerings) every time | 7.80 | 6.90 | 4.92 |
| Task 1's strums | 0.169 | 0.156 | 0.169 |

- The search is the same at `9b49746` and `793dc96`, so the difference
  between those two columns is noise.
- The ring fix cuts the worst case by 29%.
- The ring fix's output was checked against the code before it on 3000
  random inputs. They cover three tunings, and half of them use random ring,
  hand and open-string costs. Placements and warnings are identical in every
  one, and the same check catches a ring weight changed by 0.5 in 302 of
  them.
