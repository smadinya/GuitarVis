"""The CLI's contract: a written document, honest errors, useful exit codes."""

import json
import os
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import pytest
from guitarvis_core.contracts import (
    IngestedAudio,
    NoteEvent,
    SeparationProgress,
    SeparationResult,
    StructureResult,
)
from guitarvis_core.tabdoc import Timing
from guitarvis_jobs.settings import Settings
from guitarvis_worker import cli, runner

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
    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
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
def test_places_transcribed_notes_on_the_neck(
    tmp_path: Path,
    stub_stages: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class OneNote:
        def transcribe(self, stem_path: Path) -> list[NoteEvent]:
            return [NoteEvent(onset=0.1, duration=0.5, midi=40, confidence=0.9)]

    monkeypatch.setattr(cli, "BasicPitchTranscriber", lambda **kwargs: OneNote())
    out = tmp_path / "song.json"
    code = cli.main(["process", str(write_wav(tmp_path / "song.wav")), "-o", str(out)])

    assert code == 0
    notes = json.loads(out.read_text())["notes"]
    assert [(n["string"], n["fret"], n["midi"]) for n in notes] == [(0, 0, 40)]
    assert "1 note placed" in capsys.readouterr().err


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


@requires_ffprobe
def test_summary_line_reports_the_transcribed_note_count(
    tmp_path: Path, stub_stages: None, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "song.json"
    code = cli.main(["process", str(write_wav(tmp_path / "song.wav")), "-o", str(out)])

    assert code == 0
    assert "0 note events transcribed" in capsys.readouterr().err


def test_invalid_tuning_pitch_reports_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "UploadSource", StubAudioSource)

    code = cli.main(
        [
            "process",
            str(tmp_path / "song.wav"),
            "-o",
            str(tmp_path / "o.json"),
            "--tuning",
            "E2,A2,D3,G3,B3,Zz9",
        ]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "unsupported_format" in err
    assert "Zz9" in err


def test_wrong_tuning_string_count_reports_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "UploadSource", StubAudioSource)

    code = cli.main(
        [
            "process",
            str(tmp_path / "song.wav"),
            "-o",
            str(tmp_path / "o.json"),
            "--tuning",
            "E2,A2,D3",
        ]
    )

    assert code == 2
    assert "unsupported_format" in capsys.readouterr().err


class ExplodingSeparator:
    """Simulates an untyped failure escaping a stage, e.g. measure_rms's bare
    ValueError on a non-16-bit stem."""

    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        raise ValueError("expected 16-bit PCM, got 3 bytes")


def test_unexpected_exception_is_still_reported_as_typed_and_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "UploadSource", StubAudioSource)
    monkeypatch.setattr(cli, "DemucsSeparator", lambda **kwargs: ExplodingSeparator())

    code = cli.main(
        ["process", str(tmp_path / "song.wav"), "-o", str(tmp_path / "o.json")]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "internal" in err
    assert "expected 16-bit PCM" in err


def test_stems_use_a_temporary_directory_cleaned_up_after_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Path] = {}

    def fake_demucs_separator(**kwargs: object) -> StubSeparator:
        work_dir = kwargs["work_dir"]
        assert isinstance(work_dir, Path)
        captured["work_dir"] = work_dir
        return StubSeparator()

    monkeypatch.setattr(cli, "DemucsSeparator", fake_demucs_separator)
    monkeypatch.setattr(
        cli, "BasicPitchTranscriber", lambda **kwargs: StubTranscriber()
    )
    monkeypatch.setattr(
        cli, "LibrosaStructureAnalyzer", lambda **kwargs: StubAnalyzer()
    )
    monkeypatch.setattr(cli, "UploadSource", StubAudioSource)

    code = cli.main(
        ["process", str(tmp_path / "song.wav"), "-o", str(tmp_path / "o.json")]
    )

    assert code == 0
    work_dir = captured["work_dir"]
    assert isinstance(work_dir, Path)
    # Default: no --stems-dir, so the temporary directory is gone once the
    # run finishes, and it was never a subdirectory of the audio's own folder.
    assert not work_dir.exists()
    assert work_dir != tmp_path / "stems"


def test_stems_dir_option_keeps_the_directory_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Path] = {}

    def fake_demucs_separator(**kwargs: object) -> StubSeparator:
        work_dir = kwargs["work_dir"]
        assert isinstance(work_dir, Path)
        captured["work_dir"] = work_dir
        return StubSeparator()

    monkeypatch.setattr(cli, "DemucsSeparator", fake_demucs_separator)
    monkeypatch.setattr(
        cli, "BasicPitchTranscriber", lambda **kwargs: StubTranscriber()
    )
    monkeypatch.setattr(
        cli, "LibrosaStructureAnalyzer", lambda **kwargs: StubAnalyzer()
    )
    monkeypatch.setattr(cli, "UploadSource", StubAudioSource)
    stems_dir = tmp_path / "kept-stems"

    code = cli.main(
        [
            "process",
            str(tmp_path / "song.wav"),
            "-o",
            str(tmp_path / "o.json"),
            "--stems-dir",
            str(stems_dir),
        ]
    )

    assert code == 0
    assert captured["work_dir"] == stems_dir
    assert stems_dir.exists()  # opted in, so it is left in place


def test_any_failure_writing_the_output_reports_its_reason(
    tmp_path: Path,
    stub_stages: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 003's finding: only OSError was caught here, so anything else raised
    # while serialising or writing surfaced as a traceback.
    monkeypatch.setattr(cli, "UploadSource", StubAudioSource)

    def explode(self: Path, *args: object, **kwargs: object) -> int:
        raise ValueError("cannot serialise that")

    monkeypatch.setattr(Path, "write_text", explode)

    code = cli.main(
        ["process", str(tmp_path / "song.wav"), "-o", str(tmp_path / "o.json")]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "internal" in err
    assert "cannot serialise that" in err


def test_serve_runs_the_queue_worker_with_the_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Recorded so monkeypatch restores it, although serve sets it directly.
    monkeypatch.setenv("GUITARVIS_DEVICE", "")
    seen: dict[str, object] = {}
    calls: list[str] = []

    def fake_serve(settings: Settings, *, burst: bool) -> None:
        calls.append("serve")
        seen.update(device=settings.device, burst=burst)

    monkeypatch.setattr(runner, "serve", fake_serve)
    monkeypatch.setattr(cli, "configure_logging", lambda: calls.append("logging"))

    assert cli.main(["serve", "--device", "cuda", "--burst"]) == 0
    assert seen == {"device": "cuda", "burst": True}
    assert calls == ["logging", "serve"]  # before RQ looks for a handler
    # Each job runs in a forked work horse that reads the environment.
    assert os.environ["GUITARVIS_DEVICE"] == "cuda"


# What `serve` logs, run in a child interpreter so the logging setup cannot
# leak into this one.
LOGGING_SCRIPT = """
import logging
from rq.logutils import setup_loghandlers
from guitarvis_worker import cli

cli.configure_logging()
setup_loghandlers(None, name="rq.worker")  # what Worker.work does on start
logging.warning("Coremltools is not installed.")  # what importing basic_pitch does
logging.getLogger("rq.worker").info("rq info line")
logging.getLogger("rq.worker").warning("rq warning line")
logging.getLogger("guitarvis_worker.runner").info("worker line")
logging.getLogger("guitarvis_jobs.queue").info("jobs line")
logging.getLogger("botocore.hooks").info("library chatter")
"""


def test_serve_logs_each_line_once_with_its_time_and_logger() -> None:
    result = subprocess.run(
        [sys.executable, "-c", LOGGING_SCRIPT],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    output = result.stdout + result.stderr

    assert re.search(
        r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} INFO "
        r"guitarvis_worker\.runner: worker line$",
        output,
        re.MULTILINE,
    ), output
    assert "INFO guitarvis_jobs.queue: jobs line" in output
    assert output.count("rq info line") == 1
    assert output.count("rq warning line") == 1  # not again via basic-pitch's root
    assert "library chatter" not in output
