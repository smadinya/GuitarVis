"""Getting audio into the pipeline.

UploadSource and UrlSource implement AudioSource, and nothing downstream
knows which ran. Guards run here, at the front door, because rejecting a
three-hour DJ set after separation has already run is the expensive way to
find out. The probe itself lives in guitarvis_core.audio, because the api runs
the same check before queueing.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_core.audio import MAX_DURATION_SEC, check_duration, probe_duration
from guitarvis_core.contracts import (
    AudioSource,
    FailureReason,
    IngestedAudio,
    PipelineError,
)
from guitarvis_fetch.catalog import FetchKind, message_for
from guitarvis_fetch.fetcher import (
    Download,
    FetchError,
    Progress,
    UrlFetcher,
    log_failed,
    log_fetched,
)
from guitarvis_fetch.links import Link

log = logging.getLogger(__name__)


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


class UrlSource:
    """Implements AudioSource for a link (spec 012).

    Downloads into the job's directory through a UrlFetcher, then probes the
    file as UploadSource does: ffprobe's length is the one that counts,
    since metadata is rounded and can be wrong.

    Every way this fails is a row of the spec's failure catalog, and every
    failure is logged once, here, at the catalog's level: a FetchError
    (D1 to D10, and W2, which the child raises from fresh metadata) through
    `log_failed`, an unreadable file (P1) and one too long by ffprobe (P2)
    below. yt-dlp's own words go to the log and no further: the
    PipelineError carries the catalog's message.
    """

    def __init__(
        self,
        link: Link,
        work_dir: Path,
        fetcher: UrlFetcher,
        *,
        max_bytes: int,
        progress: Progress | None = None,
        probe: Callable[[Path], float] = probe_duration,
        max_duration_sec: float = MAX_DURATION_SEC,
        job_id: str | None = None,
        attempt: int | None = None,
    ) -> None:
        self.link = link
        self.work_dir = work_dir
        self.fetcher = fetcher
        self.max_bytes = max_bytes
        self.progress = progress
        self.probe = probe
        self.max_duration_sec = max_duration_sec
        self.job_id = job_id
        self.attempt = attempt

    def fetch(self) -> IngestedAudio:
        download = self._download()
        try:
            duration = self.probe(download.path)
            check_duration(duration, self.max_duration_sec)
        except PipelineError as error:
            versions = download.info.versions
            if error.reason is FailureReason.UNSUPPORTED_FORMAT:  # P1
                log.warning(
                    "link audio unreadable job=%s video=%s format=%s ext=%s "
                    "ytdlp=%s js=%s ffprobe=%r",
                    self.job_id,
                    self.link.video_id,
                    download.format_id,
                    download.ext,
                    versions.ytdlp,
                    versions.js,
                    _ffprobe_tail(error),
                )
                raise PipelineError(
                    FailureReason.LINK_UNUSABLE, message_for(FetchKind.UNREADABLE)
                ) from error
            if error.reason is FailureReason.TOO_LONG:  # P2
                log.info(
                    "link audio too long job=%s video=%s metadata=%s probed=%s "
                    "ytdlp=%s js=%s",
                    self.job_id,
                    self.link.video_id,
                    download.info.duration_sec,
                    duration,
                    versions.ytdlp,
                    versions.js,
                )
            raise  # P2 too_long, or P3: ffprobe missing is ours
        return IngestedAudio(
            path=download.path, title=download.info.title, duration_sec=duration
        )

    def _download(self) -> Download:
        started = time.monotonic()
        try:
            download = self._checked(
                self.fetcher.download(
                    self.link,
                    self.work_dir,
                    max_bytes=self.max_bytes,
                    progress=self.progress,
                )
            )
        except FetchError as error:
            log_failed(
                log,
                error,
                phase="download",
                link=self.link,
                elapsed_sec=time.monotonic() - started,
                job_id=self.job_id,
                attempt=self.attempt,
            )
            # Not `from error`: RQ logs a retried job's traceback and keeps
            # it in Redis, and the FetchError's text is yt-dlp's. It is in
            # the log line above, cut to size; nowhere else.
            raise error.as_pipeline_error() from None
        log_fetched(
            log,
            phase="download",
            link=self.link,
            versions=download.info.versions,
            elapsed_sec=time.monotonic() - started,
            job_id=self.job_id,
            attempt=self.attempt,
            download=download,
        )
        return download

    def _checked(self, download: Download) -> Download:
        """The download, once what the fetcher said is checked against the disk.

        ChildFetcher passes on whatever path and size the child reports, and
        nothing else looks at them before the file is hashed and stored. So,
        before any of that: the path must lead, symlinks followed, to a
        regular file inside the job's directory (a path that does not is an
        answer we cannot accept, which is a crash as D9 reads it: "wrote
        garbage"); it must hold bytes (D7); and by its size on disk, not the
        child's word for it, within the cap (D6).
        """
        versions = download.info.versions
        path = download.path.resolve()
        if not path.is_relative_to(self.work_dir.resolve()):
            raise FetchError(
                FetchKind.CRASHED,
                f"{download.path} resolves to {path}, outside the work directory",
                versions=versions,
            )
        if not path.is_file():
            raise FetchError(  # D7: no file
                FetchKind.EMPTY_DOWNLOAD, f"no file at {path.name}", versions=versions
            )
        size = path.stat().st_size
        if size == 0:
            raise FetchError(  # D7: an empty one
                FetchKind.EMPTY_DOWNLOAD, f"{path.name} is empty", versions=versions
            )
        if size > self.max_bytes:
            raise FetchError(  # D6
                FetchKind.TOO_LARGE,
                f"{path.name} is {size} bytes, over the {self.max_bytes} cap",
                versions=versions,
            )
        return replace(download, path=path, size=size)


def _ffprobe_tail(error: PipelineError) -> str:
    stderr = getattr(error.__cause__, "stderr", None)
    return stderr[-500:] if isinstance(stderr, str) else ""


if TYPE_CHECKING:  # Static conformance: the typed assignments are what mypy checks.
    from typing import cast

    _upload: AudioSource = UploadSource(Path())
    _url: AudioSource = UrlSource(
        Link("youtube", "", ""), Path(), cast(UrlFetcher, None), max_bytes=0
    )
