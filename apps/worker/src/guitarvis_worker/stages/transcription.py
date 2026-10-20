"""Stage 2 — transcription. basic-pitch, run through ONNX Runtime.

Polyphonic, CPU-runnable, and it emits per-note activation strength that maps
to the confidence field the degradation ladder depends on. It runs through
onnxruntime rather than TensorFlow, which cannot install on Python 3.12: see
ADR 0006 and the override-dependencies block in the root pyproject.toml.

Returns NoteEvent and deliberately not string/fret, so a guitar-specific model
can implement the same interface later. This is the single upgrade point the
staged architecture exists to protect.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_core.contracts import NoteEvent

MIN_CONFIDENCE = 0.1  # near-noise only; faint notes must survive to render faintly

_MIDI_MIN = 0
_MIDI_MAX = 127


@dataclass(frozen=True)
class TranscriptionSettings:
    """basic-pitch's decoding settings, defaulted to its own predict() defaults.

    Evaluation results record the values they ran with, so a change here shows
    up in the eval/results/ history next to the number it moved. The two
    thresholds are on the model's 0..1 activation scale.
    """

    onset_threshold: float = 0.5
    frame_threshold: float = 0.3
    minimum_note_length_ms: float = 127.7
    melodia_trick: bool = True

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
