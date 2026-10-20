"""Entry point for `make sweep`: tune MapperCosts and the transcriber's settings.

A dev-only tool. It always runs on the dev split, prints a table and writes no
results file, so nothing it measures can be committed by accident. Like
`make eval` it is deliberately outside `make check`: see __init__.py.

    make sweep ARGS="--cost gap_weight=0,0.3,0.6 --cost hand_window=4,5"
    make sweep ARGS="--full --transcription onset_threshold=0.4,0.5,0.6"

One row per combination, defaults first, tab-separated so it pastes into a
spreadsheet. The grids multiply: two values of one setting and three of
another is six rows.

In full mode each distinct set of transcription settings is transcribed once,
and its notes are cached under `--cache` so later runs and later cost sweeps
only re-map. The cache is keyed by the settings, the worker's CACHE_VERSION
and the transcriber's module constants. A change to the transcriber's code
that leaves all of those alone still needs a fresh `--cache`.
"""

import argparse
import dataclasses
import hashlib
import itertools
import json
import sys
import types
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args, get_type_hints

from guitarvis_core.contracts import NoteEvent, Transcriber
from guitarvis_worker import caching
from guitarvis_worker.stages import transcription
from guitarvis_worker.stages.fretboard import MapperCosts, ViterbiFretboardMapper
from guitarvis_worker.stages.transcription import TranscriptionSettings

from guitarvis_eval.baseline import LowestFretMapper
from guitarvis_eval.dataset import (
    DatasetMissing,
    data_dir,
    excerpt_paths,
    mic_audio_path,
    read_jams,
)
from guitarvis_eval.runner import score_full, score_oracle, summarize

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "guitarvis" / "sweep"

# Columns follow docs/specs/010-tab-accuracy/tuning.md.
ORACLE_COLUMNS = ("oracle_comp", "oracle_solo", "oracle_ovl")
FULL_COLUMNS = (
    "full_comp",
    "full_solo",
    "f1_comp",
    "f1_solo",
    "prec_comp",
    "prec_solo",
    "full_ovl",
    "obj4",
    "obj2",
)


class SweepError(Exception):
    """A command-line mistake. Reported on one line, with no traceback."""


def parse_grid(specs: Sequence[str]) -> dict[str, list[str]]:
    """["gap_weight=0,0.3", "hand_window=5"] to {"gap_weight": ["0", "0.3"], ...}."""
    grid: dict[str, list[str]] = {}
    for spec in specs:
        name, _, values = spec.partition("=")
        if not name or not values:
            raise SweepError(f"expected NAME=V1,V2…, not {spec!r}")
        if name in grid:
            raise SweepError(f"{name} is given twice; list its values in one spec")
        grid[name] = values.split(",")
    return grid


def combinations(grid: dict[str, list[str]]) -> list[dict[str, str]]:
    """The Cartesian product, with the last name varying fastest. An empty
    grid is one combination with nothing overridden."""
    return [
        dict(zip(grid, values, strict=True))
        for values in itertools.product(*grid.values())
    ]


def build[T](cls: type[T], overrides: dict[str, str]) -> T:
    """`cls` with each override coerced to its field's type.

    `none` stands for None on an optional field. The dataclass's own
    validation reports an out-of-range value, as a SweepError.
    """
    hints = get_type_hints(cls)
    for name in overrides:
        if name not in hints:
            raise SweepError(
                f"{cls.__name__} has no field {name!r}. "
                f"Valid fields: {', '.join(hints)}"
            )
    values = {
        name: _coerce(name, text, hints[name]) for name, text in overrides.items()
    }
    try:
        return cls(**values)
    except ValueError as error:
        raise SweepError(str(error)) from error


def _coerce(name: str, text: str, hint: Any) -> object:
    if types.NoneType in get_args(hint):
        if text == "none":
            return None
        hint = next(arg for arg in get_args(hint) if arg is not types.NoneType)
    if hint is bool:
        if text in ("true", "false"):
            return text == "true"
        raise SweepError(f"{name} takes true or false, not {text!r}")
    if hint is int or hint is float:
        try:
            return hint(text)
        except ValueError:
            raise SweepError(f"{name} takes {hint.__name__}, not {text!r}") from None
    raise SweepError(f"{name} cannot be set from the command line")


def settings_key(settings: TranscriptionSettings) -> str:
    """Names a settings object's cache directory.

    Every field goes in, and so does what changes the notes under the same
    settings: the worker's CACHE_VERSION, which is bumped when a stage's
    output changes, and the constants the transcriber reads.
    """
    material = {
        "settings": dataclasses.asdict(settings),
        "cache_version": caching.CACHE_VERSION,
        "min_confidence": transcription.MIN_CONFIDENCE,
        "ghost_intervals": list(transcription.GHOST_INTERVALS),
        "ghost_lead_sec": transcription.GHOST_LEAD_SEC,
    }
    text = json.dumps(material, sort_keys=True)
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()[:12]


class CachedTranscriptions:
    """Implements guitarvis_core.contracts.Transcriber, remembering what the
    transcriber heard. An entry is the audio file's stem plus `.json`, holding
    [onset, duration, midi, confidence] rows."""

    def __init__(self, inner: Transcriber, directory: Path) -> None:
        self.inner = inner
        self.directory = directory

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        entry = self.directory / f"{stem_path.stem}.json"
        if entry.is_file():
            return [NoteEvent(*row) for row in json.loads(entry.read_text())]
        events = self.inner.transcribe(stem_path)
        rows = [[e.onset, e.duration, e.midi, e.confidence] for e in events]
        self.directory.mkdir(parents=True, exist_ok=True)
        # Through a temporary name, so an interrupted run never leaves half an
        # entry for the next one to trip on.
        partial = entry.with_suffix(".partial")
        partial.write_text(json.dumps(rows))
        partial.replace(entry)
        return events


@dataclass(frozen=True)
class _Run:
    label: str  # the overrides as written, or "defaults"
    costs: MapperCosts
    settings: TranscriptionSettings


def _plan(cost_specs: Sequence[str], transcription_specs: Sequence[str]) -> list[_Run]:
    """Defaults, then every combination of both grids. Everything is built
    here, so a typo in the last value fails before any excerpt is scored."""
    cost_grid = parse_grid(cost_specs)
    transcription_grid = parse_grid(transcription_specs)
    runs = [_Run("defaults", MapperCosts(), TranscriptionSettings())]
    if not cost_grid and not transcription_grid:
        return runs
    for settings_overrides in combinations(transcription_grid):
        settings = build(TranscriptionSettings, settings_overrides)
        for cost_overrides in combinations(cost_grid):
            overrides = {**cost_overrides, **settings_overrides}
            label = ",".join(f"{name}={value}" for name, value in overrides.items())
            runs.append(_Run(label, build(MapperCosts, cost_overrides), settings))
    return runs


def _dig(summary: dict[str, object], *path: str) -> float | None:
    value: object = summary
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if isinstance(value, float) else None


def _mean(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else (a + b) / 2


def _percent(rate: float | None) -> str:
    return "—" if rate is None else f"{100 * rate:.1f}"


def _fraction(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def _per_thousand(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def _oracle_cells(summary: dict[str, object]) -> list[str]:
    return [
        _percent(_dig(summary, "comp", "string", "rate")),
        _percent(_dig(summary, "solo", "string", "rate")),
        _per_thousand(_dig(summary, "all", "overlaps", "per_1000")),
    ]


def _full_cells(summary: dict[str, object]) -> list[str]:
    full_comp = _dig(summary, "comp", "string", "rate")
    full_solo = _dig(summary, "solo", "string", "rate")
    f1_comp = _dig(summary, "comp", "note", "f1")
    f1_solo = _dig(summary, "solo", "note", "f1")
    return [
        _percent(full_comp),
        _percent(full_solo),
        _fraction(f1_comp),
        _fraction(f1_solo),
        _fraction(_dig(summary, "comp", "note", "precision")),
        _fraction(_dig(summary, "solo", "note", "precision")),
        _per_thousand(_dig(summary, "all", "overlaps", "per_1000")),
        _percent(_mean(full_comp, full_solo)),  # stage 4's objective
        _fraction(_mean(f1_comp, f1_solo)),  # stage 2's objective
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m guitarvis_eval.sweep",
        description="Tune MapperCosts and the transcriber's settings on the dev "
        "split. Prints a table, writes no results. Measured, never gated.",
    )
    parser.add_argument(
        "--cost",
        action="append",
        default=[],
        metavar="NAME=V1,V2",
        help="a MapperCosts field and the values to try; repeatable",
    )
    parser.add_argument(
        "--transcription",
        action="append",
        default=[],
        metavar="NAME=V1,V2",
        help="a TranscriptionSettings field and the values to try; repeatable; "
        "needs --full",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="transcribe the audio too, adding the full-mode columns "
        "(needs `uv sync --extra eval-full` and `make eval-data ARGS=--audio`)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="GuitarSet root (default: $GUITARSET_DIR, else the eval-data cache)",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="where transcriptions are kept, one directory per settings "
        f"(default: {DEFAULT_CACHE_DIR})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.transcription and not args.full:
        print("error: --transcription needs --full", file=sys.stderr)
        return 2
    try:
        runs = _plan(args.cost, args.transcription)
    except SweepError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    root = args.data_dir or data_dir()
    try:
        excerpts = [read_jams(path) for path in excerpt_paths(root, "dev")]
    except DatasetMissing as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    transcribers: dict[TranscriptionSettings, Transcriber] = {}
    if args.full:
        # As in __main__: find a missing file now, not at excerpt 40.
        missing = [
            audio
            for audio in (mic_audio_path(root, excerpt) for excerpt in excerpts)
            if not audio.is_file()
        ]
        if missing:
            print(
                f"error: {len(missing)} audio file(s) missing, first {missing[0]}. "
                "Run `make eval-data ARGS=--audio`.",
                file=sys.stderr,
            )
            return 1
        try:
            import mir_eval  # noqa: F401  (fail now, not after minutes of audio)
            from guitarvis_worker.stages.transcription import BasicPitchTranscriber
        except ImportError as error:
            return _needs_the_ml_stack(error)
        # One transcriber per distinct settings, however many cost
        # combinations share them.
        for settings in dict.fromkeys(run.settings for run in runs):
            transcribers[settings] = CachedTranscriptions(
                BasicPitchTranscriber(settings=settings),
                args.cache / settings_key(settings),
            )

    columns = ["overrides", *ORACLE_COLUMNS, *(FULL_COLUMNS if args.full else ())]
    print("\t".join(columns), flush=True)
    baseline = LowestFretMapper()
    oracle: dict[MapperCosts, list[str]] = {}  # oracle ignores the settings
    try:
        for index, run in enumerate(runs, 1):
            print(f"[{index}/{len(runs)}] {run.label}", file=sys.stderr)
            mapper = ViterbiFretboardMapper(run.costs)
            if run.costs not in oracle:
                scores = [score_oracle(e, mapper, baseline) for e in excerpts]
                oracle[run.costs] = _oracle_cells(summarize(scores))
            cells = [run.label, *oracle[run.costs]]
            if args.full:
                heard = [
                    score_full(
                        excerpt,
                        mic_audio_path(root, excerpt),
                        transcriber=transcribers[run.settings],
                        analyzer=None,  # chords are not tuned here
                        mapper=mapper,
                    )
                    for excerpt in excerpts
                ]
                cells += _full_cells(summarize(heard))
            print("\t".join(cells), flush=True)
    except ImportError as error:  # basic-pitch loads on the first file heard
        return _needs_the_ml_stack(error)
    return 0


def _needs_the_ml_stack(error: ImportError) -> int:
    print(
        f"error: full mode needs the ML stack ({error}). "
        "Run `uv sync --extra eval-full`.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
