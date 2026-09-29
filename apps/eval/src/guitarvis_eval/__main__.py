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
