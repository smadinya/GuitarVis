"""Stage 3 — musical structure.

Beat and downbeat tracking run on the original mix, not the guitar stem: drums
are the strongest beat cue and the stem has them removed. Chord detection runs
on the stem via chroma template matching. Section labels are optional; when
unreliable the field stays empty and the UI omits them.
"""

import math
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_core.contracts import StructureResult
from guitarvis_core.tabdoc import Beat, Chord, Timing

MIN_CHORD_CONFIDENCE = 0.5

_PITCH_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_TRIADS = (("", (0, 4, 7)), ("m", (0, 3, 7)))


def chord_templates() -> list[tuple[str, tuple[float, ...]]]:
    """Unit-normalised chroma templates for all 24 major and minor triads.

    Plain tuples rather than numpy arrays: numpy must not be imported at module
    level in a stage, and keeping this pure means CI can test it.
    """
    magnitude = 1.0 / math.sqrt(3.0)
    templates = []
    for root, root_name in enumerate(_PITCH_NAMES):
        for suffix, intervals in _TRIADS:
            vector = [0.0] * 12
            for interval in intervals:
                vector[(root + interval) % 12] = magnitude
            templates.append((f"{root_name}{suffix}", tuple(vector)))
    return templates


def beats_to_events(beat_times: Sequence[float], beats_per_bar: int = 4) -> list[Beat]:
    """Number a flat list of beat times into bars and beats.

    Bar 1 starts at the first detected beat; downbeat detection is not
    attempted. A wrong phase shifts bar lines and never affects note sync,
    because notes carry their own wall-clock onsets.
    """
    return [
        Beat(t=float(t), bar=index // beats_per_bar + 1, beat=index % beats_per_bar + 1)
        for index, t in enumerate(beat_times)
    ]


def merge_chords(
    symbols: Sequence[str | None],
    times: Sequence[float],
    confidences: Sequence[float],
    end_time: float,
) -> list[Chord]:
    """Collapse per-segment labels into held chords, dropping unlabelled runs."""
    chords: list[Chord] = []
    index = 0
    while index < len(symbols):
        symbol = symbols[index]
        run_end = index + 1
        while run_end < len(symbols) and symbols[run_end] == symbol:
            run_end += 1

        if symbol is not None:
            stop = times[run_end] if run_end < len(times) else end_time
            span = confidences[index:run_end]
            chords.append(
                Chord(
                    t=float(times[index]),
                    dur=float(stop - times[index]),
                    symbol=symbol,
                    confidence=sum(span) / len(span),
                )
            )
        index = run_end
    return chords


class LibrosaStructureAnalyzer:
    """Implements guitarvis_core.contracts.StructureAnalyzer."""

    def __init__(
        self,
        beats_per_bar: int = 4,
        min_chord_confidence: float = MIN_CHORD_CONFIDENCE,
    ) -> None:
        self.beats_per_bar = beats_per_bar
        self.min_chord_confidence = min_chord_confidence

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        import librosa
        import numpy as np

        mix, mix_rate = librosa.load(str(mix_path), mono=True)
        tempo, beat_frames = librosa.beat.beat_track(y=mix, sr=mix_rate)
        beat_times = [
            float(t) for t in librosa.frames_to_time(beat_frames, sr=mix_rate)
        ]
        tempo_value = float(np.atleast_1d(tempo)[0]) if np.size(tempo) else None

        timing = Timing(
            beats=beats_to_events(beat_times, self.beats_per_bar),
            tempo_bpm_avg=tempo_value if tempo_value and tempo_value > 0 else None,
            time_signature=f"{self.beats_per_bar}/4",
        )

        stem, stem_rate = librosa.load(str(stem_path), mono=True)
        chroma = librosa.feature.chroma_cqt(y=stem, sr=stem_rate)
        duration = float(librosa.get_duration(y=stem, sr=stem_rate))
        frame_times = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=stem_rate)

        # Without a beat grid, fall back to fixed one-second segments: the
        # chord track should survive beat tracking failing.
        segments = (
            beat_times
            if len(beat_times) >= 2
            else [float(t) for t in np.arange(0.0, duration, 1.0)]
        )

        templates = [(name, np.array(vector)) for name, vector in chord_templates()]
        symbols: list[str | None] = []
        confidences: list[float] = []

        for index, start in enumerate(segments):
            stop = segments[index + 1] if index + 1 < len(segments) else duration
            mask = (frame_times >= start) & (frame_times < stop)
            profile = chroma[:, mask].mean(axis=1) if mask.any() else None
            norm = float(np.linalg.norm(profile)) if profile is not None else 0.0

            if profile is None or norm == 0.0:
                symbols.append(None)
                confidences.append(0.0)
                continue

            unit = profile / norm
            score, name = max(
                (float(unit @ vector), name) for name, vector in templates
            )
            if score < self.min_chord_confidence:
                symbols.append(None)
                confidences.append(0.0)
            else:
                symbols.append(name)
                confidences.append(min(1.0, score))

        return StructureResult(
            timing=timing,
            chords=merge_chords(symbols, segments, confidences, duration),
            sections=[],  # Section labelling is optional and not attempted in v1.
        )


if TYPE_CHECKING:  # Static conformance: isinstance compares method names
    from guitarvis_core.contracts import StructureAnalyzer  # only, so this

    _conforms: StructureAnalyzer = LibrosaStructureAnalyzer()  # assignment is
    # what actually checks the signature.
