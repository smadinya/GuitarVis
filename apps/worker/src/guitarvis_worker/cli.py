"""Command line entry point for the pipeline.

Stage construction happens here, not inside run_pipeline, so the CLI can be
tested end to end without loading a model: the names below are what tests
patch. It is also the seam the future job worker replaces.
"""

import argparse
import sys
from pathlib import Path

from guitarvis_core.contracts import FailureReason, PipelineError
from guitarvis_core.tabdoc import STANDARD_TUNING

from guitarvis_worker.ingest import MAX_DURATION_SEC, UploadSource
from guitarvis_worker.pipeline import StageProgress, run_pipeline
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper
from guitarvis_worker.stages.separation import DemucsSeparator
from guitarvis_worker.stages.structure import LibrosaStructureAnalyzer
from guitarvis_worker.stages.transcription import BasicPitchTranscriber


def _print_progress(update: StageProgress) -> None:
    print(f"  {update.stage:<14} {update.percent:>3}%", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="guitarvis-worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("process", help="turn an audio file into tablature")
    run.add_argument("audio", help="path to an audio file")
    run.add_argument(
        "-o", "--output", required=True, help="where to write the document"
    )
    run.add_argument(
        "--tuning",
        default=",".join(STANDARD_TUNING),
        help="comma-separated open strings, lowest first",
    )
    run.add_argument(
        "--max-duration",
        type=float,
        default=MAX_DURATION_SEC,
        help="reject inputs longer than this many seconds",
    )
    run.add_argument("--device", default=None, help="torch device, e.g. cuda")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        audio = UploadSource(args.audio, max_duration_sec=args.max_duration).fetch()
        result = run_pipeline(
            audio,
            separator=DemucsSeparator(device=args.device),
            transcriber=BasicPitchTranscriber(),
            analyzer=LibrosaStructureAnalyzer(),
            mapper=ViterbiFretboardMapper(),
            tuning=args.tuning.split(","),
            progress=_print_progress,
        )
    except PipelineError as error:
        print(f"error [{error.reason.value}]: {error}", file=sys.stderr)
        return 2

    document = result.document
    try:
        Path(args.output).write_text(document.model_dump_json(indent=2))
    except OSError as error:
        print(
            f"error [{FailureReason.INTERNAL.value}]: could not write "
            f"{args.output}: {error}",
            file=sys.stderr,
        )
        return 2

    print(
        f"wrote {args.output}: {result.transcribed_note_count} note events "
        f"transcribed, {len(document.notes)} notes placed, "
        f"{len(document.chords)} chords, {len(document.timing.beats)} beats",
        file=sys.stderr,
    )
    for warning in document.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
