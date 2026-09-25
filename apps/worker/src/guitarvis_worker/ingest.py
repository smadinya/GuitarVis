"""Getting audio into the pipeline.

UploadSource is one implementation of AudioSource; URL fetching will be
another, and nothing downstream will change when it lands. Guards run here, at
the front door, because rejecting a three-hour DJ set after separation has
already run is the expensive way to find out.
"""

import json
import subprocess
from pathlib import Path

from guitarvis_core.contracts import (
    FailureReason,
    IngestedAudio,
    PipelineError,
)

MAX_DURATION_SEC = 600.0  # ten minutes


def probe_duration(path: Path) -> float:
    """Read a file's duration with ffprobe.

    ffprobe rather than a Python audio library: it decodes every container a
    user might supply, and it is the same check for "is this audio at all".
    """
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise PipelineError(
            FailureReason.INTERNAL,
            "ffprobe is not installed. Install ffmpeg to process audio.",
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise PipelineError(
            FailureReason.UNSUPPORTED_FORMAT,
            "That file could not be read as audio. Try an mp3, wav, or m4a file.",
        ) from exc

    try:
        return float(json.loads(completed.stdout)["format"]["duration"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PipelineError(
            FailureReason.UNSUPPORTED_FORMAT,
            "That file could not be read as audio. Try an mp3, wav, or m4a file.",
        ) from exc


class UploadSource:
    """Implements guitarvis_core.contracts.AudioSource for a local file."""

    def __init__(
        self, path: Path | str, *, max_duration_sec: float = MAX_DURATION_SEC
    ) -> None:
        self.path = Path(path)
        self.max_duration_sec = max_duration_sec

    def fetch(self) -> IngestedAudio:
        if not self.path.is_file():
            raise PipelineError(
                FailureReason.UNSUPPORTED_FORMAT, f"No such audio file: {self.path}"
            )

        duration = probe_duration(self.path)
        if duration > self.max_duration_sec:
            raise PipelineError(
                FailureReason.TOO_LONG,
                f"That recording is longer than {self.max_duration_sec / 60:.0f} "
                "minutes. Try a single song rather than a full set.",
            )

        return IngestedAudio(
            path=self.path, title=self.path.stem, duration_sec=duration
        )
