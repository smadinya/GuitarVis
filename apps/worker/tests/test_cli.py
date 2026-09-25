"""The CLI's contract: a written document, honest errors, useful exit codes."""

import json
import shutil
import wave
from pathlib import Path

import pytest
from guitarvis_core.contracts import IngestedAudio, SeparationResult, StructureResult
from guitarvis_core.tabdoc import Timing
from guitarvis_worker import cli

requires_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None,
    reason="ffprobe not installed; install ffmpeg",
)


def write_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


class StubSeparator:
    def isolate(self, audio_path: Path) -> SeparationResult:
        return SeparationResult(stem_path=audio_path)


class StubTranscriber:
    def transcribe(self, stem_path: Path) -> list:
        return []


class StubAnalyzer:
    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        return StructureResult(timing=Timing(), chords=[], sections=[])


class StubAudioSource:
    """Stands in for UploadSource so a test needs no ffprobe on PATH."""

    def __init__(self, path: Path | str, **kwargs: object) -> None:
        self._path = Path(path)

    def fetch(self) -> IngestedAudio:
        return IngestedAudio(path=self._path, title=self._path.stem, duration_sec=1.0)


@pytest.fixture
def stub_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "DemucsSeparator", lambda **kwargs: StubSeparator())
    monkeypatch.setattr(
        cli, "BasicPitchTranscriber", lambda **kwargs: StubTranscriber()
    )
    monkeypatch.setattr(
        cli, "LibrosaStructureAnalyzer", lambda **kwargs: StubAnalyzer()
    )


@requires_ffprobe
def test_writes_a_valid_document_and_exits_zero(
    tmp_path: Path, stub_stages: None, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "song.json"
    code = cli.main(["process", str(write_wav(tmp_path / "song.wav")), "-o", str(out)])

    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert payload["notes"] == []
    assert "100%" in capsys.readouterr().err


@requires_ffprobe
def test_reports_the_fretboard_stage_is_not_implemented(
    tmp_path: Path, stub_stages: None, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "song.json"
    cli.main(["process", str(write_wav(tmp_path / "song.wav")), "-o", str(out)])
    assert "Fretboard assignment is not implemented yet" in capsys.readouterr().err


def test_missing_file_reports_its_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        ["process", str(tmp_path / "nope.wav"), "-o", str(tmp_path / "o.json")]
    )
    assert code == 2
    assert "unsupported_format" in capsys.readouterr().err


@requires_ffprobe
def test_too_long_reports_its_own_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        [
            "process",
            str(write_wav(tmp_path / "song.wav", seconds=2.0)),
            "-o",
            str(tmp_path / "o.json"),
            "--max-duration",
            "1",
        ]
    )
    assert code == 2
    assert "too_long" in capsys.readouterr().err


def test_unwritable_output_reports_its_reason(
    tmp_path: Path,
    stub_stages: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "UploadSource", StubAudioSource)
    bad_out = tmp_path / "does-not-exist" / "song.json"

    code = cli.main(
        ["process", str(write_wav(tmp_path / "song.wav")), "-o", str(bad_out)]
    )

    assert code == 2
    assert "internal" in capsys.readouterr().err
