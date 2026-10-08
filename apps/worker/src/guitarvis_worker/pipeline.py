"""Runs the stages in order and assembles a tab document.

The degradation ladder lives here. Every stage after separation is optional to
the core promise, so a failure downstream costs the user a feature rather than
the whole job. Only "no usable guitar audio" fails outright.

Stages arrive by injection: the worker decides what to run, and the stages stay
ignorant of each other.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from guitarvis_core.contracts import (
    FailureReason,
    FretboardMapper,
    IngestedAudio,
    NoteEvent,
    PipelineError,
    Separator,
    StructureAnalyzer,
    StructureResult,
    TabNote,
    Transcriber,
)
from guitarvis_core.fretboard import InvariantViolation, check_invariant
from guitarvis_core.tabdoc import (
    STANDARD_TUNING,
    Instrument,
    Note,
    Source,
    TabDocument,
    Timing,
)

# The whole job's percent when each stage starts. Separation fills the band
# up to transcription's start as it reports; `fretboard 100` marks the end.
STAGE_START_PERCENT = {
    "separation": 0,
    "transcription": 40,
    "structure": 65,
    "fretboard": 80,
}
_SEPARATION_BAND = STAGE_START_PERCENT["transcription"]


@dataclass(frozen=True)
class StageProgress:
    """The stage now running, and the whole job's percent. 100 means done."""

    stage: str
    percent: int


ProgressCallback = Callable[[StageProgress], None]


@dataclass(frozen=True)
class PipelineResult:
    """What `run_pipeline` hands back: the document plus what stage 2 saw.

    `transcribed_note_count` is how many note events transcription produced,
    before stage 4 dropped any it could not place. Comparing it with
    `len(document.notes)` shows how much the fretboard stage lost. Returned
    as data rather than folded into a warning string so a caller gets it
    without parsing prose.
    """

    document: TabDocument
    transcribed_note_count: int


class _Reporter:
    """Turns stage starts and separation fractions into monotonic progress.

    A separator's fractions are not trusted: anything that would not raise
    the whole-number percent is dropped, values past 1 are clamped and NaN or
    negative values are ignored. That is what lets the worker write the row
    only when something changed — at most about a hundred writes a job.
    """

    def __init__(self, callback: ProgressCallback | None) -> None:
        self._callback = callback
        self._percent = -1

    def start(self, stage: str) -> None:
        self._emit(stage, max(STAGE_START_PERCENT[stage], self._percent))

    def separation(self, fraction: float) -> None:
        if not fraction >= 0.0:  # also False for NaN
            return
        percent = int(min(fraction, 1.0) * _SEPARATION_BAND)
        if percent > self._percent:
            self._emit("separation", percent)

    def finish(self) -> None:
        self._emit("fretboard", 100)

    def _emit(self, stage: str, percent: int) -> None:
        self._percent = percent
        if self._callback is not None:
            self._callback(StageProgress(stage=stage, percent=percent))


def run_pipeline(
    audio: IngestedAudio,
    *,
    separator: Separator,
    transcriber: Transcriber,
    analyzer: StructureAnalyzer,
    mapper: FretboardMapper,
    tuning: Sequence[str] = STANDARD_TUNING,
    progress: ProgressCallback | None = None,
    audio_url: str | None = None,
) -> PipelineResult:
    """Turn ingested audio into a tab document.

    `audio_url` becomes the document's `source.audio_url`. The CLI leaves it
    unset and gets a file:// URI of the input; the job runner passes the api
    path a client fetches the mix from.
    """
    report = _Reporter(progress)
    warnings: list[str] = []

    # Stage 1. The only stage whose failure is fatal: with no guitar audio
    # there is nothing to transcribe and nothing honest to show.
    report.start("separation")
    separation = separator.isolate(audio.path, progress=report.separation)
    warnings.extend(separation.warnings)

    # Stage 2. Optional like stages 3 and 4: a raised exception costs notes,
    # not the whole job. A genuinely empty result (no exception, no notes)
    # gets its own, more specific warning, so a caller can tell "found
    # nothing" apart from "blew up".
    report.start("transcription")
    events: list[NoteEvent] = []
    try:
        events = transcriber.transcribe(separation.stem_path)
    except Exception as exc:  # every transcriber failure degrades alike
        warnings.append(
            f"Transcription failed ({exc.__class__.__name__}), so no notes "
            "could be detected."
        )
    else:
        if not events:
            warnings.append("No notes were detected in the isolated guitar part.")

    # Stage 3. Optional: notes carry their own onsets, so losing the beat grid
    # costs bar lines and chord symbols, never synchronisation. Beats and
    # chords each fail independently inside `analyze` now, and each failure
    # produces its own warning on `structure.warnings`. This except is a
    # backstop for an analyzer implementation that does not catch its own
    # halves (or that dies before returning a StructureResult at all) — the
    # shipped LibrosaStructureAnalyzer never takes this path, since both of
    # its halves already degrade internally.
    report.start("structure")
    structure = StructureResult(timing=Timing(), chords=[], sections=[])
    try:
        structure = analyzer.analyze(separation.stem_path, audio.path)
    except Exception as exc:  # the analyzer itself raised, not just a half
        warnings.append(
            f"Structure analysis failed entirely ({exc.__class__.__name__}), "
            "so bar lines and chord symbols are unavailable."
        )
    warnings.extend(structure.warnings)

    # Stage 4. Optional like stages 2 and 3: a mapper that raises costs the
    # notes track, not the job — including NotImplementedError, which a real
    # mapper may raise for a genuinely unsupported case. Notes the mapper
    # could not place arrive as warnings on its result. A wrong fret is a
    # different matter: the invariant check below fails the job instead.
    report.start("fretboard")
    tab_notes: list[TabNote] = []
    try:
        fretboard = mapper.assign(events, tuning)
    except Exception as exc:  # every mapper failure degrades alike
        warnings.append(
            f"Fretboard assignment failed ({exc.__class__.__name__}), so this "
            "document carries no notes."
        )
    else:
        tab_notes = fretboard.notes
        warnings.extend(fretboard.warnings)

    # A tab that renders the wrong fret is worse than no tab: a beginner cannot
    # tell it from a hard passage. Refuse to emit one. A string or fret that
    # does not exist on the neck is the same failure, not a crash: pitch_of
    # raises IndexError and Note's validation raises ValueError.
    notes: list[Note] = []
    for index, tab in enumerate(tab_notes):
        try:
            note = Note(
                id=f"n_{index:04d}",
                t=tab.onset,
                dur=tab.duration,
                midi=tab.midi,
                string=tab.string,
                fret=tab.fret,
                confidence=tab.confidence,
            )
            check_invariant(note, tuning)
        except (InvariantViolation, IndexError, ValueError) as exc:
            raise PipelineError(
                FailureReason.INTERNAL, f"Fretboard assignment is inconsistent: {exc}"
            ) from exc
        notes.append(note)

    # 100 only once every note has passed the invariant: a job must never
    # read 100% and then fail.
    report.finish()

    document = TabDocument(
        source=Source(
            title=audio.title,
            duration_sec=audio.duration_sec,
            audio_url=(
                audio_url if audio_url is not None else audio.path.resolve().as_uri()
            ),
        ),
        instrument=Instrument(tuning=list(tuning), string_count=len(tuning)),
        timing=structure.timing,
        notes=notes,
        chords=structure.chords,
        sections=structure.sections,
        warnings=warnings,
    )
    return PipelineResult(document=document, transcribed_note_count=len(events))
