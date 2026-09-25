"""Stage 1 and the first rung of the degradation ladder.

The Demucs call is stubbed out: what is under test is the fallback decision,
which must hold whether or not the ml extra is installed.
"""

import wave
from pathlib import Path

import pytest
from guitarvis_core.contracts import FailureReason, PipelineError
from guitarvis_worker.stages.separation import (
    SILENCE_RMS,
    DemucsSeparator,
    measure_rms,
)


def write_wav(path: Path, amplitude: int = 8000, rate: int = 8000) -> Path:
    """One second of a square-ish tone at the given amplitude, or silence at 0."""
    frames = bytearray()
    for index in range(rate):
        value = amplitude if (index // 20) % 2 == 0 else -amplitude
        frames += int(value).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))
    return path


class FakeSeparator(DemucsSeparator):
    """Replaces the Demucs subprocess with prepared files."""

    def __init__(self, stems: dict[str, Path]) -> None:
        super().__init__()
        self.stems = stems
        self.calls: list[tuple[str, str]] = []

    def _demucs(self, model: str, audio_path: Path, stem_name: str) -> Path:
        self.calls.append((model, stem_name))
        return self.stems[model]


def test_measure_rms_separates_signal_from_silence(tmp_path: Path) -> None:
    assert measure_rms(write_wav(tmp_path / "loud.wav", amplitude=8000)) > SILENCE_RMS
    assert measure_rms(write_wav(tmp_path / "quiet.wav", amplitude=0)) < SILENCE_RMS


def test_audible_guitar_stem_is_used_directly(tmp_path: Path) -> None:
    guitar = write_wav(tmp_path / "guitar.wav", amplitude=8000)
    separator = FakeSeparator({"htdemucs_6s": guitar})

    result = separator.isolate(tmp_path / "song.wav")

    assert result.stem_path == guitar
    assert result.warnings == []
    assert separator.calls == [("htdemucs_6s", "guitar")]


def test_silent_guitar_stem_falls_back_to_the_other_track(tmp_path: Path) -> None:
    separator = FakeSeparator(
        {
            "htdemucs_6s": write_wav(tmp_path / "guitar.wav", amplitude=0),
            "htdemucs": write_wav(tmp_path / "other.wav", amplitude=8000),
        }
    )

    result = separator.isolate(tmp_path / "song.wav")

    assert result.stem_path.name == "other.wav"
    assert result.warnings and "other" in result.warnings[0]
    assert separator.calls == [("htdemucs_6s", "guitar"), ("htdemucs", "other")]


def test_two_silent_stems_fail_honestly(tmp_path: Path) -> None:
    separator = FakeSeparator(
        {
            "htdemucs_6s": write_wav(tmp_path / "a.wav", amplitude=0),
            "htdemucs": write_wav(tmp_path / "b.wav", amplitude=0),
        }
    )

    with pytest.raises(PipelineError) as excinfo:
        separator.isolate(tmp_path / "song.wav")

    assert excinfo.value.reason is FailureReason.NO_GUITAR_DETECTED
    assert "guitar" in str(excinfo.value).lower()
