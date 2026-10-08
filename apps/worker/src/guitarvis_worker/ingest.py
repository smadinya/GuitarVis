"""Getting audio into the pipeline.

UploadSource is one implementation of AudioSource; URL fetching will be
another, and nothing downstream will change when it lands. Guards run here, at
the front door, because rejecting a three-hour DJ set after separation has
already run is the expensive way to find out. The probe itself lives in
guitarvis_core.audio, because the api runs the same check before queueing.
"""

from pathlib import Path

from guitarvis_core.audio import MAX_DURATION_SEC, check_duration, probe_duration
from guitarvis_core.contracts import FailureReason, IngestedAudio, PipelineError


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
        check_duration(duration, self.max_duration_sec)
        return IngestedAudio(
            path=self.path, title=self.path.stem, duration_sec=duration
        )
