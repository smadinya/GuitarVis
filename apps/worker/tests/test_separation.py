"""Stage 1 and the first rung of the degradation ladder.

The Demucs call is stubbed out: what is under test is the fallback decision,
which must hold whether or not the ml extra is installed.
"""

import subprocess
import sys
import wave
from pathlib import Path

import pytest
from guitarvis_core.contracts import FailureReason, PipelineError, SeparationProgress
from guitarvis_worker.stages.separation import (
    FIRST_PASS_SHARE,
    SILENCE_RMS,
    DemucsSeparator,
    TqdmPercent,
    measure_rms,
)
from guitarvis_worker.timeouts import JobTimedOut


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
    """Replaces the Demucs subprocess with prepared files.

    Each fake pass reports half-way, then done, so the scaling of the two
    passes onto one stage is visible to a test.
    """

    def __init__(self, stems: dict[str, Path]) -> None:
        super().__init__(work_dir=Path("unused"))
        self.stems = stems
        self.calls: list[tuple[str, str]] = []

    def _demucs(
        self,
        model: str,
        audio_path: Path,
        stem_name: str,
        progress: SeparationProgress | None = None,
    ) -> Path:
        self.calls.append((model, stem_name))
        if progress is not None:
            progress(0.5)
            progress(1.0)
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


def test_the_first_pass_fills_three_quarters_of_the_stage(tmp_path: Path) -> None:
    separator = FakeSeparator({"htdemucs_6s": write_wav(tmp_path / "g.wav")})
    seen: list[float] = []

    separator.isolate(tmp_path / "song.wav", progress=seen.append)

    assert seen == [0.375, FIRST_PASS_SHARE]


def test_the_fallback_pass_fills_the_rest_without_running_backwards(
    tmp_path: Path,
) -> None:
    separator = FakeSeparator(
        {
            "htdemucs_6s": write_wav(tmp_path / "guitar.wav", amplitude=0),
            "htdemucs": write_wav(tmp_path / "other.wav", amplitude=8000),
        }
    )
    seen: list[float] = []

    separator.isolate(tmp_path / "song.wav", progress=seen.append)

    assert seen == [0.375, 0.75, 0.875, 1.0]
    assert seen == sorted(seen)


# The tests above replace _demucs entirely, so nothing above exercises the
# subprocess it wraps. These call _demucs directly on a real DemucsSeparator,
# with subprocess.Popen monkeypatched, to cover its output parsing, its
# failure paths and its command construction without installing Demucs.

# Captured from tqdm 4.70.1 driven with the arguments Demucs 4.1.0 passes it
# (demucs/apply.py: unit_scale=..., ncols=120, unit="seconds"); the bars are
# shortened. tqdm redraws one line with \r, so there are no newlines to split
# on, and its block characters are multi-byte UTF-8.
DEMUCS_OUTPUT = (
    "Separated tracks will be stored in /tmp/w/htdemucs_6s\n"
    "Separating track /tmp/w/upload.wav\n"
    "\r  0%|          | 0.0/29.25 [00:00<?, ?seconds/s]"
    "\r 20%|██▌       | 5.85/29.25 [00:03<00:14,  1.62seconds/s]"
    "\r 40%|████▏     | 11.7/29.25 [00:07<00:10,  1.62seconds/s]"
    "\r 60%|██████▍   | 17.549999999999997/29.25 [00:10<00:07,  1.62seconds/s]"
    "\r 80%|████████▍ | 23.4/29.25 [00:14<00:03,  1.62seconds/s]"
    "\r100%|██████████| 29.25/29.25 [00:18<00:00,  1.62seconds/s]"
    "\r100%|██████████| 29.25/29.25 [00:18<00:00,  1.61seconds/s]\n"
)
DEMUCS_PERCENTS = [0, 20, 40, 60, 80, 100, 100]


class TrickleReader:
    """A pipe that hands back a few bytes per read, so bars and multi-byte
    characters split across reads the way a real pipe splits them."""

    def __init__(
        self, data: bytes, size: int = 7, error: BaseException | None = None
    ) -> None:
        self._data = data
        self._size = size
        self._error = error
        self._position = 0

    def read1(self, size: int = -1) -> bytes:
        if self._position >= len(self._data):
            if self._error is not None:
                raise self._error
            return b""
        chunk = self._data[self._position : self._position + self._size]
        self._position += len(chunk)
        return chunk


class FakeProcess:
    def __init__(self, stdout: TrickleReader, exit_code: int) -> None:
        self.stdout = stdout
        self._exit_code = exit_code
        self.returncode: int | None = None
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self) -> int:
        self.returncode = -9 if self.killed else self._exit_code
        return self.returncode

    def kill(self) -> None:
        self.killed = True


class FakeDemucs:
    """Stands in for subprocess.Popen: records the command, writes the stem
    Demucs would have written, and replays canned output."""

    def __init__(
        self,
        output: str = DEMUCS_OUTPUT,
        exit_code: int = 0,
        write_stem: bool = True,
        read_error: BaseException | None = None,
    ) -> None:
        self.output = output.encode()
        self.exit_code = exit_code
        self.write_stem = write_stem
        self.read_error = read_error
        self.commands: list[list[str]] = []
        self.processes: list[FakeProcess] = []

    def __call__(self, command: list[str], **kwargs: object) -> FakeProcess:
        assert kwargs["stderr"] is subprocess.STDOUT  # tqdm draws on stderr
        self.commands.append(command)
        if self.write_stem:
            out_dir = Path(command[command.index("-o") + 1])
            audio = Path(command[command.index("-o") + 2])
            stem = out_dir / command[command.index("-n") + 1] / audio.stem
            stem.mkdir(parents=True, exist_ok=True)
            (stem / "guitar.wav").write_bytes(b"")
        process = FakeProcess(
            TrickleReader(self.output, error=self.read_error), self.exit_code
        )
        self.processes.append(process)
        return process


def test_tqdm_percentages_are_read_from_a_recorded_bar() -> None:
    assert TqdmPercent().feed(DEMUCS_OUTPUT) == DEMUCS_PERCENTS


def test_tqdm_percentages_survive_a_bar_split_across_reads() -> None:
    parser = TqdmPercent()
    found: list[int] = []
    for start in range(0, len(DEMUCS_OUTPUT), 3):
        found += parser.feed(DEMUCS_OUTPUT[start : start + 3])

    assert found == DEMUCS_PERCENTS


def test_output_without_a_bar_yields_nothing() -> None:
    # Demucs's output is not an API. If the format changes, progress jumps
    # 0 -> 40% as it did before this parser existed; it never fails a job.
    assert TqdmPercent().feed("Separating track song.wav\nDone.\n") == []


def test_a_number_past_100_is_not_a_percentage() -> None:
    assert TqdmPercent().feed("\r142%|") == []


def test_demucs_reports_progress_as_its_bar_advances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "Popen", FakeDemucs())
    seen: list[float] = []

    DemucsSeparator(work_dir=tmp_path)._demucs(
        "htdemucs_6s", tmp_path / "song.wav", "guitar", seen.append
    )

    assert seen == [p / 100 for p in DEMUCS_PERCENTS]


def test_demucs_missing_binary_raises_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_python(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "Popen", no_python)

    with pytest.raises(PipelineError) as excinfo:
        DemucsSeparator(work_dir=tmp_path)._demucs(
            "htdemucs_6s", tmp_path / "song.wav", "guitar"
        )

    assert excinfo.value.reason is FailureReason.INTERNAL
    assert "--extra ml" in str(excinfo.value)


def test_demucs_nonzero_exit_raises_internal_error_with_output_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    noise = "x" * 2000
    monkeypatch.setattr(
        subprocess,
        "Popen",
        FakeDemucs(output=noise + "boom: model crashed", exit_code=1),
    )

    with pytest.raises(PipelineError) as excinfo:
        DemucsSeparator(work_dir=tmp_path)._demucs(
            "htdemucs_6s", tmp_path / "song.wav", "guitar"
        )

    message = str(excinfo.value)
    assert excinfo.value.reason is FailureReason.INTERNAL
    assert message.endswith("boom: model crashed")
    assert len(message) <= len("Separation failed: ") + 500


def test_demucs_missing_output_stem_raises_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "Popen", FakeDemucs(write_stem=False))

    with pytest.raises(PipelineError) as excinfo:
        DemucsSeparator(work_dir=tmp_path)._demucs(
            "htdemucs_6s", tmp_path / "song.wav", "guitar"
        )

    assert excinfo.value.reason is FailureReason.INTERNAL
    expected_stem = tmp_path / "htdemucs_6s" / "song" / "guitar.wav"
    assert str(expected_stem) in str(excinfo.value)


def test_demucs_builds_command_with_device_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeDemucs()
    monkeypatch.setattr(subprocess, "Popen", fake)

    DemucsSeparator(work_dir=tmp_path, device="cuda")._demucs(
        "htdemucs_6s", tmp_path / "song.wav", "guitar"
    )

    assert fake.commands == [
        [
            sys.executable,
            "-m",
            "demucs",
            "-n",
            "htdemucs_6s",
            "-o",
            str(tmp_path),
            str(tmp_path / "song.wav"),
            "-d",
            "cuda",
        ]
    ]


def test_demucs_omits_device_flag_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeDemucs()
    monkeypatch.setattr(subprocess, "Popen", fake)

    DemucsSeparator(work_dir=tmp_path)._demucs(
        "htdemucs_6s", tmp_path / "song.wav", "guitar"
    )

    assert "-d" not in fake.commands[0]


def test_stems_land_directly_in_work_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 003's finding: `--stems-dir X` used to write to X/stems/.
    monkeypatch.setattr(subprocess, "Popen", FakeDemucs())
    work_dir = tmp_path / "kept"
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()

    stem = DemucsSeparator(work_dir=work_dir)._demucs(
        "htdemucs_6s", audio_dir / "song.wav", "guitar"
    )

    assert stem == work_dir / "htdemucs_6s" / "song" / "guitar.wav"
    assert not (work_dir / "stems").exists()
    assert not (audio_dir / "stems").exists()


def test_an_exception_while_streaming_kills_the_demucs_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A job timeout raises inside the read loop; Demucs must not outlive it.
    The worker's timeout is a BaseException, which `finally` still sees."""
    fake = FakeDemucs(output="\r 10%|", read_error=JobTimedOut("job timeout"))
    monkeypatch.setattr(subprocess, "Popen", fake)

    with pytest.raises(JobTimedOut):
        DemucsSeparator(work_dir=tmp_path)._demucs(
            "htdemucs_6s", tmp_path / "song.wav", "guitar"
        )

    assert fake.processes[0].killed


def test_a_failing_progress_hook_also_kills_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeDemucs()
    monkeypatch.setattr(subprocess, "Popen", fake)

    def unreachable_database(fraction: float) -> None:
        raise ConnectionError("postgres went away")

    with pytest.raises(ConnectionError):
        DemucsSeparator(work_dir=tmp_path)._demucs(
            "htdemucs_6s", tmp_path / "song.wav", "guitar", unreachable_database
        )

    assert fake.processes[0].killed
