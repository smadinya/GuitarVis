"""Stage 1 — separation. Demucs htdemucs_6s, which has a dedicated guitar stem.

Output is whatever Demucs writes: 16-bit stereo at the model's own 44.1kHz,
which it resamples the input to (verified — a 22.05kHz input comes back at
44.1kHz). Nothing is resampled or downmixed *here*: stage 2 (basic-pitch)
resamples internally and stage 3 (librosa, `mono=True`) downmixes, so
normalising in this stage would just be redundant work on every job.

When the guitar stem comes back empty or near-silent — common when a heavily
distorted guitar is attributed elsewhere — the implementation falls back to the
4-stem `other` track and marks the document with a quality warning. This stage
dominates job time.
"""

import array
import codecs
import io
import re
import subprocess
import sys
import wave
from pathlib import Path
from typing import TYPE_CHECKING, cast

from guitarvis_core.contracts import (
    FailureReason,
    PipelineError,
    SeparationProgress,
    SeparationResult,
)

SILENCE_RMS = 1e-3  # below this, a stem is empty rather than quiet

_RMS_STRIDE = 97  # sample every Nth frame; silence detection needs no more

# The 6-stem pass fills this share of the stage's progress; the 4-stem
# fallback, when it runs, fills the rest, so progress never runs backwards.
FIRST_PASS_SHARE = 0.75


def _span(
    progress: SeparationProgress | None, start: float, end: float
) -> SeparationProgress | None:
    """Map one Demucs pass's 0..1 onto [start, end] of the whole stage."""
    if progress is None:
        return None
    report = progress

    def scaled(fraction: float) -> None:
        report(start + (end - start) * fraction)

    return scaled


_TAIL_CHARS = 500  # of Demucs's output, kept for the failure message
_READ_SIZE = 4096


class TqdmPercent:
    """Pull the percentages out of a tqdm bar as it streams.

    Demucs draws its progress with tqdm, which redraws one line with `\\r`, so
    the output has no newlines to split on and a read can end mid-number.
    This keeps the unmatched tail of each chunk and prepends it to the next.
    Demucs's output is not an API: if its format changes, this finds nothing
    and progress jumps from 0 to 40% exactly as it did before.
    """

    _PATTERN = re.compile(r"(\d{1,3})%\|")
    _CARRY = 8  # longer than any partial "100%|"

    def __init__(self) -> None:
        self._carry = ""

    def feed(self, chunk: str) -> list[int]:
        text = self._carry + chunk
        found: list[int] = []
        consumed = 0
        for match in self._PATTERN.finditer(text):
            value = int(match.group(1))
            if value <= 100:
                found.append(value)
            consumed = match.end()
        self._carry = text[consumed:][-self._CARRY :]
        return found


def measure_rms(path: Path) -> float:
    """Root-mean-square amplitude of a 16-bit PCM wav, normalised to 0..1.

    Stdlib only, on purpose: numpy is forbidden at module level in stage
    modules, and keeping this free of the ml extra is what lets the fallback
    tests run in CI.
    """
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit PCM, got {handle.getsampwidth()} bytes")
        frames = handle.readframes(handle.getnframes())

    samples = array.array("h")
    samples.frombytes(frames)
    if not samples:
        return 0.0

    sampled = samples[::_RMS_STRIDE] if len(samples) >= _RMS_STRIDE else samples
    total = sum(float(value) * float(value) for value in sampled)
    return (total / len(sampled)) ** 0.5 / 32768.0


class DemucsSeparator:
    """Implements guitarvis_core.contracts.Separator."""

    def __init__(
        self,
        *,
        work_dir: Path,
        model: str = "htdemucs_6s",
        fallback_model: str = "htdemucs",
        device: str | None = None,
    ) -> None:
        self.model = model
        self.fallback_model = fallback_model
        self.device = device
        # Required: a default of "next to the audio" left stems beside every
        # downloaded job file in a long-lived worker (003's review notes).
        # Stems land directly in it, so `--stems-dir X` writes to X.
        self.work_dir = work_dir

    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        guitar = self._demucs(
            self.model, audio_path, "guitar", _span(progress, 0.0, FIRST_PASS_SHARE)
        )
        if measure_rms(guitar) >= SILENCE_RMS:
            return SeparationResult(stem_path=guitar)

        # A heavily distorted guitar is often attributed elsewhere by the
        # 6-stem model. The 4-stem `other` track is the next best thing, and
        # saying so is better than returning silence.
        other = self._demucs(
            self.fallback_model,
            audio_path,
            "other",
            _span(progress, FIRST_PASS_SHARE, 1.0),
        )
        if measure_rms(other) < SILENCE_RMS:
            raise PipelineError(
                FailureReason.NO_GUITAR_DETECTED,
                "No clear guitar part was found in this recording.",
            )

        return SeparationResult(
            stem_path=other,
            warnings=[
                "The 6-stem model found no guitar, so this tab comes from the "
                "4-stem 'other' track and may include other instruments."
            ],
        )

    def _demucs(
        self,
        model: str,
        audio_path: Path,
        stem_name: str,
        progress: SeparationProgress | None = None,
    ) -> Path:
        """Run Demucs as a subprocess and return the requested stem.

        A subprocess rather than the Python API: the CLI is stable across
        releases, and a model that dies cannot take the worker down with it.
        stderr is merged into stdout and read as it arrives, because that is
        where tqdm draws the bar that progress is parsed from.
        """
        command = [
            sys.executable,
            "-m",
            "demucs",
            "-n",
            model,
            "-o",
            str(self.work_dir),
            str(audio_path),
        ]
        if self.device:
            command += ["-d", self.device]

        try:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
        except FileNotFoundError as exc:
            raise PipelineError(
                FailureReason.INTERNAL,
                "demucs is not installed. Run `uv sync --extra ml`.",
            ) from exc

        try:
            tail = _stream(process, progress)
            exit_code = process.wait()
        finally:
            # A job timeout, or a progress write that fails, raises in here.
            # The Demucs child must not outlive the job that started it.
            if process.poll() is None:
                process.kill()
                process.wait()

        if exit_code != 0:
            raise PipelineError(
                FailureReason.INTERNAL, f"Separation failed: {tail[-_TAIL_CHARS:]}"
            )

        stem = self.work_dir / model / audio_path.stem / f"{stem_name}.wav"
        if not stem.exists():
            raise PipelineError(
                FailureReason.INTERNAL, f"Separation produced no stem at {stem}"
            )
        return stem


def _stream(
    process: "subprocess.Popen[bytes]", progress: SeparationProgress | None
) -> str:
    """Read the child's output as it arrives, report progress, return the tail.

    `read1` returns whatever the pipe holds rather than waiting to fill a
    buffer, so progress is reported as Demucs draws it. The incremental
    decoder keeps a multi-byte bar character split across reads intact.
    """
    stdout = cast(io.BufferedIOBase, process.stdout)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    percents = TqdmPercent()
    tail = ""
    while chunk := stdout.read1(_READ_SIZE):
        text = decoder.decode(chunk)
        tail = (tail + text)[-_TAIL_CHARS:]
        for percent in percents.feed(text):
            if progress is not None:
                progress(percent / 100)
    return tail


if TYPE_CHECKING:  # Static conformance: isinstance compares method names
    from guitarvis_core.contracts import Separator  # only, so this

    _conforms: Separator = DemucsSeparator(work_dir=Path())  # assignment is what
    # actually checks the signature.
