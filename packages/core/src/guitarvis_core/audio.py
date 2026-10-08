"""Audio facts the api and the worker both need, from the standard library.

The api probes an upload before queueing it, so a user with a bad file learns
in a second rather than after a queue wait. The worker probes again, because
it must not trust its caller. Both go through these functions so the two
checks cannot drift apart.

ffprobe rather than a Python audio library: it decodes every container a user
might supply, and core must stay free of heavy dependencies.
"""

import json
import subprocess
from pathlib import Path

from guitarvis_core.contracts import FailureReason, PipelineError

MAX_DURATION_SEC = 600.0  # ten minutes

_UNREADABLE = "That file could not be read as audio. Try an mp3, wav, or m4a file."


def probe_duration(path: Path) -> float:
    """Read a file's duration in seconds with ffprobe."""
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
        raise PipelineError(FailureReason.UNSUPPORTED_FORMAT, _UNREADABLE) from exc

    try:
        return float(json.loads(completed.stdout)["format"]["duration"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PipelineError(FailureReason.UNSUPPORTED_FORMAT, _UNREADABLE) from exc


def check_duration(
    duration_sec: float, max_duration_sec: float = MAX_DURATION_SEC
) -> None:
    """Refuse a recording longer than the limit, before any expensive work."""
    if duration_sec > max_duration_sec:
        raise PipelineError(
            FailureReason.TOO_LONG,
            f"That recording is longer than {max_duration_sec / 60:.0f} "
            "minutes. Try a single song rather than a full set.",
        )
