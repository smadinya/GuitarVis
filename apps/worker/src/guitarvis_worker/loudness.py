"""How loud each strum is, measured from the guitar stem.

Not a stage, and not `confidence`. Transcription already reports a per-note
strength as `confidence`, and reusing it would make one number mean two things:
a later recalibration of confidence would change how far strings swing. So the
pipeline measures loudness itself, after the fretboard mapper, from the stem
separation left and the onsets of the notes the mapper placed. Any transcriber
and any mapper gets it with nothing to copy, and no stage's cached output
changes. See spec 008, *Loudness*.

Stdlib only, like `measure_rms` in `stages/separation.py`, so it runs in CI
without the ml extra. It imports no stage: a stage must not, and neither may
a helper that sits beside them.
"""

import array
import math
import wave
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from guitarvis_core.contracts import VOICING_WINDOW_SEC, TabNote

FLOOR_DB = -30.0  # this far below the reference reads as 0
REFERENCE_PERCENTILE = 0.95  # of the song's strum levels, so one spike is not it


def measure_loudness(stem_path: Path, notes: Sequence[TabNote]) -> list[TabNote]:
    """Each note, in the order given, with `loudness` set to 0..1.

    A strum is the notes within `VOICING_WINDOW_SEC` of its first onset, as
    the mapper groups a voicing. Its notes share one level, measured over the
    window from that onset to `VOICING_WINDOW_SEC` after its last. Measured
    note by note, a strum's later strings would catch the earlier ones still
    ringing and read louder. Levels are RMS in dB against the 95th percentile
    of the song's strums, with `FLOOR_DB`..0 dB mapped onto 0..1 and clipped.

    Raises when the stem cannot be measured: `EOFError`, `wave.Error` or
    `OSError` as the file demands, `ValueError` for a sample width other than
    16-bit or a stem that is silent under every note. The caller degrades.
    """
    if not notes:
        return []

    groups = _strums(notes)
    levels = _levels(stem_path, [_window(notes, group) for group in groups])

    reference = sorted(levels)[math.ceil(REFERENCE_PERCENTILE * len(levels)) - 1]
    if reference == 0:
        raise ValueError("the stem is silent under every note")

    measured = list(notes)
    for group, level in zip(groups, levels, strict=True):
        loudness = round(_scale(level, reference), 3)
        for index in group:
            measured[index] = replace(notes[index], loudness=loudness)
    return measured


def _strums(notes: Sequence[TabNote]) -> list[list[int]]:
    """Indices of `notes` grouped into strums, each in onset order.

    A note joins the current group when it is within the window of the
    group's *first* note, by the mapper's rule for voicings. Anchored there, a
    fast run cannot chain into one group, and a strum spans at most the window.

    The groups are of the notes the mapper kept, so they can differ from its
    voicings. If it dropped a voicing's first note, the rest anchor on the
    next one, and may take in the start of the next voicing. That costs only
    a shared swing size, in a rare case.
    """
    groups: list[list[int]] = []
    first = 0.0
    for index in sorted(range(len(notes)), key=lambda i: notes[i].onset):
        onset = notes[index].onset
        if groups and onset - first <= VOICING_WINDOW_SEC:
            groups[-1].append(index)
        else:
            groups.append([index])
            first = onset
    return groups


def _window(notes: Sequence[TabNote], group: Sequence[int]) -> tuple[float, float]:
    return notes[group[0]].onset, notes[group[-1]].onset + VOICING_WINDOW_SEC


def _levels(stem_path: Path, windows: Sequence[tuple[float, float]]) -> list[float]:
    """The RMS of each window, all channels together. Silence reads 0."""
    levels: list[float] = []
    with wave.open(str(stem_path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit PCM, got {handle.getsampwidth()} bytes")
        rate = handle.getframerate()
        total = handle.getnframes()
        for start_sec, end_sec in windows:
            start = min(max(int(start_sec * rate), 0), total)
            end = min(max(int(end_sec * rate), 0), total)
            if end <= start:
                levels.append(0.0)
                continue
            handle.setpos(start)
            samples = array.array("h")
            samples.frombytes(handle.readframes(end - start))
            if not samples:
                levels.append(0.0)
                continue
            squares = sum(value * value for value in samples)
            levels.append(math.sqrt(squares / len(samples)))
    return levels


def _scale(level: float, reference: float) -> float:
    if level == 0:
        return 0.0
    decibels = 20 * math.log10(level / reference)
    return min(1.0, max(0.0, (decibels - FLOOR_DB) / -FLOOR_DB))
