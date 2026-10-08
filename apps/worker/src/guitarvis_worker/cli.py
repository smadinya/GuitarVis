"""Command line entry point for the pipeline.

Stage construction happens here, not inside run_pipeline, so the CLI can be
tested end to end without loading a model: the names below are what tests
patch. `serve` hands the same stages to the queue worker in runner.py.
"""

import argparse
import contextlib
import os
import sys
import tempfile
from pathlib import Path

from guitarvis_core.audio import MAX_DURATION_SEC
from guitarvis_core.contracts import FailureReason, PipelineError
from guitarvis_core.fretboard import parse_pitch
from guitarvis_core.tabdoc import STANDARD_TUNING
from guitarvis_jobs.settings import Settings

from guitarvis_worker import runner
from guitarvis_worker.ingest import UploadSource
from guitarvis_worker.pipeline import StageProgress, run_pipeline
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper
from guitarvis_worker.stages.separation import DemucsSeparator
from guitarvis_worker.stages.structure import LibrosaStructureAnalyzer
from guitarvis_worker.stages.transcription import BasicPitchTranscriber

TUNING_STRING_COUNT = 6  # matches Instrument.string_count and the fretboard invariant


def _print_progress(update: StageProgress) -> None:
    print(f"  {update.stage:<14} {update.percent:>3}%", file=sys.stderr)


def _parse_tuning(raw: str) -> list[str]:
    """Validate --tuning before it reaches the document the web client reads.

    Each entry must be a real scientific pitch name, and there must be
    exactly six of them — the count `Instrument.string_count` and the
    fretboard invariant both assume. An earlier version of this CLI wrote
    whatever it was given straight through; this reverses that deferral.
    """
    strings = [entry.strip() for entry in raw.split(",")]
    if len(strings) != TUNING_STRING_COUNT:
        raise PipelineError(
            FailureReason.UNSUPPORTED_FORMAT,
            f"--tuning must name exactly {TUNING_STRING_COUNT} strings, got "
            f"{len(strings)}: {raw!r}",
        )
    for pitch in strings:
        try:
            parse_pitch(pitch)
        except ValueError as exc:
            raise PipelineError(
                FailureReason.UNSUPPORTED_FORMAT,
                f"--tuning has an invalid open string {pitch!r}: {exc}",
            ) from exc
    return strings


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
    run.add_argument(
        "--stems-dir",
        default=None,
        help=(
            "keep Demucs stems here instead of a temporary directory that is "
            "deleted when the run finishes. Separation dominates runtime, so "
            "this is useful when re-running later stages against the same song."
        ),
    )

    serve = subparsers.add_parser("serve", help="run jobs from the queue until stopped")
    serve.add_argument(
        "--device", default=None, help="torch device for every job, e.g. cuda"
    )
    serve.add_argument(
        "--burst", action="store_true", help="exit once the queue is empty"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    return _process(args)


def _serve(args: argparse.Namespace) -> int:
    if args.device:
        # Each job runs in a forked work horse that reads its settings from
        # the environment, so this is how the flag reaches every job.
        os.environ["GUITARVIS_DEVICE"] = args.device
    runner.serve(Settings.from_env(), burst=args.burst)
    return 0


def _process(args: argparse.Namespace) -> int:
    try:
        audio = UploadSource(args.audio, max_duration_sec=args.max_duration).fetch()
        tuning = _parse_tuning(args.tuning)

        with contextlib.ExitStack() as stack:
            if args.stems_dir:
                # Opt-in: leave the stems in place for reuse across runs.
                work_dir = Path(args.stems_dir)
                work_dir.mkdir(parents=True, exist_ok=True)
            else:
                # Default: clean up after ourselves. The context must stay
                # open for the whole run_pipeline call below — stages 2 and 3
                # read the stem after separation returns it.
                work_dir = Path(
                    stack.enter_context(
                        tempfile.TemporaryDirectory(prefix="guitarvis-stems-")
                    )
                )

            result = run_pipeline(
                audio,
                separator=DemucsSeparator(device=args.device, work_dir=work_dir),
                transcriber=BasicPitchTranscriber(),
                analyzer=LibrosaStructureAnalyzer(),
                mapper=ViterbiFretboardMapper(),
                tuning=tuning,
                progress=_print_progress,
            )
    except PipelineError as error:
        print(f"error [{error.reason.value}]: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # last resort: still a typed, actionable line
        print(
            f"error [{FailureReason.INTERNAL.value}]: unexpected failure: {error}",
            file=sys.stderr,
        )
        return 2

    document = result.document
    try:
        Path(args.output).write_text(document.model_dump_json(indent=2))
    except Exception as error:  # OSError, or anything serialising raised
        print(
            f"error [{FailureReason.INTERNAL.value}]: could not write "
            f"{args.output}: {error}",
            file=sys.stderr,
        )
        return 2

    print(
        f"wrote {args.output}: {result.transcribed_note_count} note events "
        f"transcribed, {len(document.notes)} "
        f"{'note' if len(document.notes) == 1 else 'notes'} placed, "
        f"{len(document.chords)} chords, {len(document.timing.beats)} beats",
        file=sys.stderr,
    )
    for warning in document.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
