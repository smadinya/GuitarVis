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
