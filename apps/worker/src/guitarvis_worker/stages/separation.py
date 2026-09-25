"""Stage 1 — separation. Demucs htdemucs_6s, which has a dedicated guitar stem.

Output is normalised to 44.1kHz mono. When the guitar stem comes back empty or
near-silent — common when a heavily distorted guitar is attributed elsewhere —
the implementation falls back to the 4-stem `other` track and marks the
document with a quality warning. This stage dominates job time.
"""

import array
import subprocess
import sys
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_core.contracts import FailureReason, PipelineError, SeparationResult

SILENCE_RMS = 1e-3  # below this, a stem is empty rather than quiet

_RMS_STRIDE = 97  # sample every Nth frame; silence detection needs no more


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
        model: str = "htdemucs_6s",
        fallback_model: str = "htdemucs",
        device: str | None = None,
    ) -> None:
        self.model = model
        self.fallback_model = fallback_model
        self.device = device

    def isolate(self, audio_path: Path) -> SeparationResult:
        guitar = self._demucs(self.model, audio_path, "guitar")
        if measure_rms(guitar) >= SILENCE_RMS:
            return SeparationResult(stem_path=guitar)

        # A heavily distorted guitar is often attributed elsewhere by the
        # 6-stem model. The 4-stem `other` track is the next best thing, and
        # saying so is better than returning silence.
        other = self._demucs(self.fallback_model, audio_path, "other")
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

    def _demucs(self, model: str, audio_path: Path, stem_name: str) -> Path:
        """Run Demucs as a subprocess and return the requested stem.

        A subprocess rather than the Python API: the CLI is stable across
        releases, and a model that dies cannot take the worker down with it.
        """
        out_dir = audio_path.parent / "stems"
        command = [
            sys.executable,
            "-m",
            "demucs",
            "-n",
            model,
            "-o",
            str(out_dir),
            str(audio_path),
        ]
        if self.device:
            command += ["-d", self.device]

        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise PipelineError(
                FailureReason.INTERNAL,
                "demucs is not installed. Run `uv sync --extra ml`.",
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise PipelineError(
                FailureReason.INTERNAL, f"Separation failed: {exc.stderr[-500:]}"
            ) from exc

        stem = out_dir / model / audio_path.stem / f"{stem_name}.wav"
        if not stem.exists():
            raise PipelineError(
                FailureReason.INTERNAL, f"Separation produced no stem at {stem}"
            )
        return stem


if TYPE_CHECKING:  # Static conformance: isinstance compares method names
    from guitarvis_core.contracts import Separator  # only, so this

    _conforms: Separator = DemucsSeparator()  # assignment is what
    # actually checks the signature.
