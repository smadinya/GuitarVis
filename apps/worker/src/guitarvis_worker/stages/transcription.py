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
from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_core.contracts import NoteEvent

MIN_CONFIDENCE = 0.1  # near-noise only; faint notes must survive to render faintly

_MIDI_MIN = 0
_MIDI_MAX = 127


class BasicPitchTranscriber:
    """Implements guitarvis_core.contracts.Transcriber."""

    def __init__(self, min_confidence: float = MIN_CONFIDENCE) -> None:
        self.min_confidence = min_confidence

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

        _, _, note_events = predict(str(stem_path), basic_pitch.ICASSP_2022_MODEL_PATH)
        return note_events


if TYPE_CHECKING:  # Static conformance: isinstance compares method names
    from guitarvis_core.contracts import Transcriber  # only, so this

    _conforms: Transcriber = BasicPitchTranscriber()  # assignment is what
    # actually checks the signature.
