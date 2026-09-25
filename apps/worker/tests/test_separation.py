"""Stage 1 and the first rung of the degradation ladder.

The Demucs call is stubbed out: what is under test is the fallback decision,
which must hold whether or not the ml extra is installed.
"""

import subprocess
import sys
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


# The tests above replace _demucs entirely, so nothing above exercises the
# subprocess it wraps. These call _demucs directly on a real DemucsSeparator,
# with subprocess.run monkeypatched, to cover its three failure paths and its
# command construction without installing Demucs or the ml extra.


def test_demucs_missing_binary_raises_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)
    separator = DemucsSeparator()

    with pytest.raises(PipelineError) as excinfo:
        separator._demucs("htdemucs_6s", tmp_path / "song.wav", "guitar")

    assert excinfo.value.reason is FailureReason.INTERNAL
    assert "--extra ml" in str(excinfo.value)


def test_demucs_nonzero_exit_raises_internal_error_with_stderr_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "demucs", stderr="boom: model crashed")

    monkeypatch.setattr(subprocess, "run", fake_run)
    separator = DemucsSeparator()

    with pytest.raises(PipelineError) as excinfo:
        separator._demucs("htdemucs_6s", tmp_path / "song.wav", "guitar")

    assert excinfo.value.reason is FailureReason.INTERNAL
    assert "boom: model crashed" in str(excinfo.value)


def test_demucs_missing_output_stem_raises_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # subprocess.run succeeds, but writes nothing to out_dir.
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)
    separator = DemucsSeparator()

    with pytest.raises(PipelineError) as excinfo:
        separator._demucs("htdemucs_6s", tmp_path / "song.wav", "guitar")

    assert excinfo.value.reason is FailureReason.INTERNAL
    expected_stem = tmp_path / "stems" / "htdemucs_6s" / "song" / "guitar.wav"
    assert str(expected_stem) in str(excinfo.value)


def test_demucs_builds_command_with_device_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(command: list[str], **kwargs: object) -> None:
        captured["command"] = command
        stem = tmp_path / "stems" / "htdemucs_6s" / "song" / "guitar.wav"
        stem.parent.mkdir(parents=True, exist_ok=True)
        stem.write_bytes(b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    separator = DemucsSeparator(device="cuda")

    stem = separator._demucs("htdemucs_6s", tmp_path / "song.wav", "guitar")

    assert stem.exists()
    assert captured["command"] == [
        sys.executable,
        "-m",
        "demucs",
        "-n",
        "htdemucs_6s",
        "-o",
        str(tmp_path / "stems"),
        str(tmp_path / "song.wav"),
        "-d",
        "cuda",
    ]


def test_demucs_uses_work_dir_when_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, list[str]] = {}
    work_dir = tmp_path / "elsewhere"

    def fake_run(command: list[str], **kwargs: object) -> None:
        captured["command"] = command
        stem = work_dir / "stems" / "htdemucs_6s" / "song" / "guitar.wav"
        stem.parent.mkdir(parents=True, exist_ok=True)
        stem.write_bytes(b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    separator = DemucsSeparator(work_dir=work_dir)

    stem = separator._demucs("htdemucs_6s", audio_dir / "song.wav", "guitar")

    # Stems land under work_dir, not next to the audio.
    assert stem == work_dir / "stems" / "htdemucs_6s" / "song" / "guitar.wav"
    assert str(work_dir / "stems") in captured["command"]
    assert not (audio_dir / "stems").exists()


def test_demucs_omits_device_flag_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(command: list[str], **kwargs: object) -> None:
        captured["command"] = command
        stem = tmp_path / "stems" / "htdemucs_6s" / "song" / "guitar.wav"
        stem.parent.mkdir(parents=True, exist_ok=True)
        stem.write_bytes(b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    separator = DemucsSeparator(device=None)

    separator._demucs("htdemucs_6s", tmp_path / "song.wav", "guitar")

    assert "-d" not in captured["command"]
