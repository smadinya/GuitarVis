"""Ingestion guards. Cheap checks before the expensive stages run."""

import shutil
import wave
from pathlib import Path

import pytest
from guitarvis_core.contracts import AudioSource, FailureReason, PipelineError
from guitarvis_worker.ingest import UploadSource, probe_duration

requires_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None,
    reason="ffprobe not installed; install ffmpeg",
)


def write_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> Path:
    """A silent wav, written with the stdlib so tests need no ml extra."""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def test_upload_source_satisfies_the_protocol(tmp_path: Path) -> None:
    assert isinstance(UploadSource(write_wav(tmp_path / "a.wav")), AudioSource)


@requires_ffprobe
def test_probe_duration_reads_length(tmp_path: Path) -> None:
    assert probe_duration(write_wav(tmp_path / "a.wav", seconds=2.0)) == pytest.approx(
        2.0, abs=0.05
    )


@requires_ffprobe
def test_fetch_returns_path_title_and_duration(tmp_path: Path) -> None:
    ingested = UploadSource(write_wav(tmp_path / "my song.wav", seconds=1.5)).fetch()
    assert ingested.title == "my song"
    assert ingested.duration_sec == pytest.approx(1.5, abs=0.05)


def test_missing_file_is_unsupported_format(tmp_path: Path) -> None:
    with pytest.raises(PipelineError) as excinfo:
        UploadSource(tmp_path / "nope.wav").fetch()
    assert excinfo.value.reason is FailureReason.UNSUPPORTED_FORMAT


@requires_ffprobe
def test_undecodable_file_is_unsupported_format(tmp_path: Path) -> None:
    path = tmp_path / "not-audio.wav"
    path.write_bytes(b"this is not audio")
    with pytest.raises(PipelineError) as excinfo:
        UploadSource(path).fetch()
    assert excinfo.value.reason is FailureReason.UNSUPPORTED_FORMAT


@requires_ffprobe
def test_overlong_input_is_too_long(tmp_path: Path) -> None:
    with pytest.raises(PipelineError) as excinfo:
        UploadSource(
            write_wav(tmp_path / "a.wav", seconds=2.0), max_duration_sec=1.0
        ).fetch()
    assert excinfo.value.reason is FailureReason.TOO_LONG


@requires_ffprobe
def test_too_long_message_tells_the_user_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="single song"):
        UploadSource(
            write_wav(tmp_path / "a.wav", seconds=2.0), max_duration_sec=1.0
        ).fetch()
