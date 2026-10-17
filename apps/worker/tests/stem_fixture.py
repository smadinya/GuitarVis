"""A guitar stem written from numbers, for tests that measure one.

Imported by bare name, as apps/eval/tests imports guitarset_fixture; there is
no conftest.py anywhere in this repo (see the Makefile's mypy note).
"""

import array
import wave
from collections.abc import Sequence
from pathlib import Path


def write_stem(
    path: Path,
    plucks: Sequence[tuple[float, float, int]],
    *,
    seconds: float = 4.0,
    rate: int = 8000,
    channels: int = 2,
) -> Path:
    """Write a 16-bit wav of silence and square-wave plucks.

    Each pluck is `(onset, length, amplitude)`, in seconds and sample units.
    A square wave's RMS is its amplitude, so a test can say how loud a pluck is.
    """
    frames = int(seconds * rate)
    samples = array.array("h", bytes(2 * frames * channels))
    for onset, length, amplitude in plucks:
        for frame in range(
            int(onset * rate), min(int((onset + length) * rate), frames)
        ):
            value = amplitude if frame % 2 == 0 else -amplitude
            for channel in range(channels):
                samples[frame * channels + channel] = value
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return path
