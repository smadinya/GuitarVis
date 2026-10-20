"""Stage 2 — transcription. basic-pitch, run through ONNX Runtime.

Polyphonic, CPU-runnable, and it emits per-note activation strength that maps
to the confidence field the degradation ladder depends on. It runs through
onnxruntime rather than TensorFlow, which cannot install on Python 3.12: see
ADR 0006 and the override-dependencies block in the root pyproject.toml.

Returns NoteEvent and deliberately not string/fret, so a guitar-specific model
can implement the same interface later. This is the single upgrade point the
staged architecture exists to protect.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_core.contracts import VOICING_WINDOW_SEC, NoteEvent

MIN_CONFIDENCE = 0.1  # near-noise only; faint notes must survive to render faintly

# A harmonic ghost sits an octave, an octave and a fifth, or two octaves above
# its base, and often starts a frame or two before it.
GHOST_INTERVALS = (12, 19, 24)
GHOST_LEAD_SEC = 0.05

_MIDI_MIN = 0
_MIDI_MAX = 127


@dataclass(frozen=True)
class TranscriptionSettings:
    """basic-pitch's decoding settings and the ghost rule.

    The defaults were tuned for spec 010 on GuitarSet's dev split; see
    docs/specs/010-tab-accuracy/tuning.md. basic-pitch's own predict()
    defaults are onset 0.5, frame 0.3, 127.7 ms, melodia on, and no ghost
    rule.

    Evaluation results record the values they ran with, so a change here shows
    up in the eval/results/ history next to the number it moved. The two
    thresholds are on the model's 0..1 activation scale.

    `ghost_ratio` switches on drop_ghosts, a rule against an artifact of this
    model: None leaves it off, which is basic-pitch's own output.
    """

    onset_threshold: float = 0.5
    frame_threshold: float = 0.4
    minimum_note_length_ms: float = 93.0
    melodia_trick: bool = False
    ghost_ratio: float | None = 0.8
    ghost_alone_only: bool = True

    def __post_init__(self) -> None:
        for name in ("onset_threshold", "frame_threshold"):
            value = getattr(self, name)
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1], not {value}")
        if self.minimum_note_length_ms < 0:
            raise ValueError(
                "minimum_note_length_ms cannot be negative, "
                f"not {self.minimum_note_length_ms}"
            )
        if self.ghost_ratio is not None and not 0 < self.ghost_ratio <= 1:
            raise ValueError(f"ghost_ratio must be in (0, 1], not {self.ghost_ratio}")


def drop_ghosts(
    events: Sequence[NoteEvent], ratio: float, *, alone_only: bool
) -> list[NoteEvent]:
    """Drop basic-pitch's harmonic ghosts, keeping the order of the rest.

    A note is a ghost when some other note, its base, is a GHOST_INTERVALS
    distance below it, is sounding at its onset (the ghost may start
    GHOST_LEAD_SEC before the base), and has a confidence the ghost's is
    under `ratio` times. With `alone_only`, every other note starting within
    VOICING_WINDOW_SEC of the ghost must be one of its bases too, so a
    chord's real octave stays.

    Bases are judged against every note passed in, never against the
    survivors: a weak E4 over a weak E3 over a strong E2 loses both.

    This is an artifact of basic-pitch, so it lives here and not in a stage
    that sees any transcriber's output. A future Transcriber should not
    inherit it.
    """
    by_pitch: dict[int, list[int]] = {}
    for index, event in enumerate(events):
        by_pitch.setdefault(event.midi, []).append(index)
    by_onset = sorted(range(len(events)), key=lambda index: events[index].onset)
    onsets = [events[index].onset for index in by_onset]

    def is_base(base: NoteEvent, ghost: NoteEvent) -> bool:
        return (
            base.onset - GHOST_LEAD_SEC <= ghost.onset <= base.onset + base.duration
            and ghost.confidence < ratio * base.confidence
        )

    def is_ghost(index: int) -> bool:
        ghost = events[index]
        bases = {
            other
            for interval in GHOST_INTERVALS
            for other in by_pitch.get(ghost.midi - interval, ())
            if is_base(events[other], ghost)
        }
        if not bases:
            return False
        if not alone_only:
            return True
        first = bisect_left(onsets, ghost.onset - VOICING_WINDOW_SEC)
        last = bisect_right(onsets, ghost.onset + VOICING_WINDOW_SEC)
        return all(other == index or other in bases for other in by_onset[first:last])

    return [event for index, event in enumerate(events) if not is_ghost(index)]


class BasicPitchTranscriber:
    """Implements guitarvis_core.contracts.Transcriber."""

    def __init__(
        self,
        min_confidence: float = MIN_CONFIDENCE,
        settings: TranscriptionSettings | None = None,
    ) -> None:
        self.min_confidence = min_confidence
        self.settings = settings or TranscriptionSettings()

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        events = []
        for start, end, midi, amplitude, *_ in self._predict(stem_path):
            confidence = min(1.0, max(0.0, float(amplitude)))
            pitch = int(midi)
            if confidence < self.min_confidence:
                continue
            if not _MIDI_MIN <= pitch <= _MIDI_MAX:
                continue
            events.append(
                NoteEvent(
                    onset=float(start),
                    duration=float(end) - float(start),
                    midi=pitch,
                    confidence=confidence,
                )
            )

        if self.settings.ghost_ratio is not None:
            events = drop_ghosts(
                events,
                self.settings.ghost_ratio,
                alone_only=self.settings.ghost_alone_only,
            )

        events.sort(key=lambda event: (event.onset, event.midi))
        return events

    def _predict(self, stem_path: Path) -> Sequence[tuple]:
        """Raw model output. Imported lazily so the module needs no ml extra.

        ICASSP_2022_MODEL_PATH resolves to the bundled nmp.onnx when
        onnxruntime is the only installed backend, which is how this repo
        installs it.
        """
        import basic_pitch
        from basic_pitch.inference import predict

        _, _, note_events = predict(
            str(stem_path),
            basic_pitch.ICASSP_2022_MODEL_PATH,
            onset_threshold=self.settings.onset_threshold,
            frame_threshold=self.settings.frame_threshold,
            minimum_note_length=self.settings.minimum_note_length_ms,
            melodia_trick=self.settings.melodia_trick,
        )
        return note_events


if TYPE_CHECKING:  # Static conformance: isinstance compares method names
    from guitarvis_core.contracts import Transcriber  # only, so this

    _conforms: Transcriber = BasicPitchTranscriber()  # assignment is what
    # actually checks the signature.
