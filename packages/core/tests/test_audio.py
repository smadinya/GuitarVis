"""Duration probing and the length limit, shared by the api and the worker."""

import shutil
import subprocess
import wave
from pathlib import Path

import pytest
from guitarvis_core.audio import MAX_DURATION_SEC, check_duration, probe_duration
from guitarvis_core.contracts import FailureReason, PipelineError

requires_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None,
    reason="ffprobe not installed; install ffmpeg",
)


def write_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> Path:
    """A silent wav, written with the stdlib so the test needs no ml extra."""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


@requires_ffprobe
def test_probe_duration_reads_length(tmp_path: Path) -> None:
    assert probe_duration(write_wav(tmp_path / "a.wav", seconds=2.0)) == pytest.approx(
        2.0, abs=0.05
    )


@requires_ffprobe
def test_probe_rejects_a_file_that_is_not_audio(tmp_path: Path) -> None:
    path = tmp_path / "not-audio.wav"
    path.write_bytes(b"this is not audio")

    with pytest.raises(PipelineError) as excinfo:
        probe_duration(path)

    assert excinfo.value.reason is FailureReason.UNSUPPORTED_FORMAT


def test_missing_ffprobe_is_internal_not_the_users_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_ffprobe(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(subprocess, "run", no_ffprobe)

    with pytest.raises(PipelineError) as excinfo:
        probe_duration(tmp_path / "a.wav")

    assert excinfo.value.reason is FailureReason.INTERNAL
    assert "ffmpeg" in str(excinfo.value)


def test_a_probe_that_hangs_is_cut_off_and_the_file_called_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A pathological file must not hold an api thread forever.
    seen: dict[str, object] = {}

    def hangs(*args: object, **kwargs: object) -> None:
        seen["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=30)

    monkeypatch.setattr(subprocess, "run", hangs)

    with pytest.raises(PipelineError) as excinfo:
        probe_duration(tmp_path / "a.wav")

    assert excinfo.value.reason is FailureReason.UNSUPPORTED_FORMAT
    assert "could not be read as audio" in str(excinfo.value)
    assert seen["timeout"] == 30  # seconds: generous for reading a header


def test_the_limit_is_ten_minutes() -> None:
    assert MAX_DURATION_SEC == 600.0


def test_check_duration_accepts_exactly_the_limit() -> None:
    check_duration(MAX_DURATION_SEC)


def test_check_duration_rejects_past_the_limit() -> None:
    with pytest.raises(PipelineError, match="single song") as excinfo:
        check_duration(MAX_DURATION_SEC + 0.1)
    assert excinfo.value.reason is FailureReason.TOO_LONG


@pytest.mark.parametrize("duration", [0.0, -1.0, float("nan")])
def test_check_duration_rejects_a_recording_with_no_length(duration: float) -> None:
    # A wav header with no frames probes as 0.0, and NaN > limit is False.
    with pytest.raises(PipelineError) as excinfo:
        check_duration(duration)
    assert excinfo.value.reason is FailureReason.UNSUPPORTED_FORMAT


def test_check_duration_honours_a_custom_limit() -> None:
    with pytest.raises(PipelineError) as excinfo:
        check_duration(2.0, max_duration_sec=1.0)
    assert excinfo.value.reason is FailureReason.TOO_LONG
