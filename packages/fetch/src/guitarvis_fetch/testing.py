"""A UrlFetcher for tests: records its calls, answers as told. No process,
no network. Imported by tests only, as guitarvis_jobs.testing is."""

import os
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_fetch.fetcher import (
    Download,
    FetchError,
    Progress,
    UrlFetcher,
    Versions,
    VideoInfo,
)
from guitarvis_fetch.links import Link

VERSIONS = Versions(ytdlp="2026.10.26", js="deno/2.5.4")


def video_info(
    *,
    title: str = "Elephants Dream - 10 years of open movies",
    duration_sec: float | None = 37.0,
    live_status: str | None = "not_live",
    availability: str | None = "public",
) -> VideoInfo:
    return VideoInfo(
        title=title,
        duration_sec=duration_sec,
        live_status=live_status,
        availability=availability,
        versions=VERSIONS,
    )


def write_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> Path:
    """A short wav, from the standard library, as a download's file."""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x01\x00" * int(rate * seconds))
    return path


def gone(pid: int) -> bool:
    """Whether `pid` is dead: no such process, or a zombie awaiting its reaper."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    status = Path(f"/proc/{pid}/stat")
    return status.exists() and status.read_text().split(")")[-1].split()[0] == "Z"


def wait_until_gone(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if gone(pid):
            return True
        time.sleep(0.05)
    return False


def read_pid(path: Path, seconds: float = 10.0) -> int:
    """The pid in `path`, once the process that writes it has."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and (text := path.read_text()).strip():
            return int(text)
        time.sleep(0.05)
    raise AssertionError(f"{path.name} never appeared")


@dataclass
class FakeFetcher:
    """Implements UrlFetcher. `info` answers lookups unless `lookup_error`
    is set; a download writes `content` (a wav by default) to
    `work_dir/source.<ext>` unless `download_error` is set."""

    info: VideoInfo = field(default_factory=video_info)
    lookup_error: FetchError | None = None
    download_error: FetchError | None = None
    content: bytes | None = None
    ext: str = "wav"
    progress_steps: tuple[float, ...] = (0.0, 0.5, 1.0)
    lookups: list[Link] = field(default_factory=list)
    downloads: list[Link] = field(default_factory=list)

    def lookup(self, link: Link) -> VideoInfo:
        self.lookups.append(link)
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.info

    def download(
        self,
        link: Link,
        work_dir: Path,
        *,
        max_bytes: int,
        progress: Progress | None = None,
    ) -> Download:
        self.downloads.append(link)
        if self.download_error is not None:
            raise self.download_error
        path = work_dir / f"source.{self.ext}"
        if self.content is None:
            write_wav(path)
        else:
            path.write_bytes(self.content)
        for step in self.progress_steps:
            if progress is not None:
                progress(step)
        return Download(
            path=path,
            info=self.info,
            format_id="140",
            ext=self.ext,
            size=path.stat().st_size,
        )


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    _conforms: UrlFetcher = FakeFetcher()
