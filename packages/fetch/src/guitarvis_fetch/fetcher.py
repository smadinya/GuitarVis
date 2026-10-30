"""Fetching: the UrlFetcher contract, and ChildFetcher, which runs yt-dlp in a
process of its own (spec 012, *Where yt-dlp runs*).

Nothing here imports yt-dlp. ChildFetcher starts `python -I -m
guitarvis_fetch.child`, reads JSON lines from it, and kills its whole process
group at a deadline or on any way out, which a thread could not do. The
child gets no GUITARVIS_* variables, so yt-dlp is never handed the database
URL or the storage secret. It is not a sandbox: it runs as the same user, and
could still read them from /proc/<ppid>/environ, or any file that user can.

The protocol, one JSON object per line on the child's stdout:

    {"progress": 0.42}
    {"result": {...}, "ytdlp": "2026.10.26", "js": "deno/2.5.4"}
    {"error": {"kind": "private", "detail": "...", "duration_sec": null},
     "ytdlp": "...", "js": "..."}

`ytdlp` and `js` may ride on any line; the last ones seen go on every failure
raised for the call, so a timeout or a crash still says which version broke.

The child is in a session of its own, which takes it out of any process group
its parent's supervisor kills (RQ kills its work horse's group). So the parent
holds the write end of the child's stdin, writes nothing to it, and the child
calls `watch_parent()`: when the parent dies, even by SIGKILL, the kernel
closes the pipe and the child kills its own group.
"""

import contextlib
import importlib.metadata
import json
import logging
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Protocol, runtime_checkable

from guitarvis_core.audio import MAX_DURATION_SEC, check_duration
from guitarvis_core.contracts import FailureReason, PipelineError

from guitarvis_fetch.catalog import CATALOG, Entry, FetchKind, message_for
from guitarvis_fetch.links import Link

LOOKUP_DEADLINE_SEC = 30.0
DOWNLOAD_DEADLINE_SEC = 300.0
DETAIL_CHARS = 500
TAIL_BYTES = 2048
REAP_SEC = 5.0  # how long to wait for the reader thread after the kill
# yt_dlp.utils._jsruntime.DenoJsRuntime.MIN_SUPPORTED_VERSION in 2026.10.26.
MIN_DENO_VERSION = (2, 3, 0)
# What the api and the worker say at start when links are on and Deno isn't.
NO_DENO_WARNING = (
    f"links are on, but Deno {'.'.join(str(part) for part in MIN_DENO_VERSION)} "
    "or later was not found: every link will fail as fetch_failed until it is "
    "installed"
)

Progress = Callable[[float], None]


@dataclass(frozen=True)
class Versions:
    """Which yt-dlp and which JavaScript runtime answered: on every log line,
    so "it broke on Tuesday" can be traced to a version."""

    ytdlp: str = "-"
    js: str = "-"


@dataclass(frozen=True)
class VideoInfo:
    """What a lookup learns. `live_status` and `availability` are yt-dlp's
    words for them; `duration_sec` is None when the metadata has none."""

    title: str
    duration_sec: float | None
    live_status: str | None = None
    availability: str | None = None
    versions: Versions = field(default_factory=Versions)


@dataclass(frozen=True)
class Download:
    """A downloaded file in the job's directory, and what it came from."""

    path: Path
    info: VideoInfo
    format_id: str
    ext: str
    size: int


class FetchError(Exception):
    """A classified failure. `kind` picks the catalog row; `detail` is
    yt-dlp's text and `tail` the end of the child's stderr, for the log
    only. `str()` of this error is a log line, never a message."""

    def __init__(
        self,
        kind: FetchKind,
        detail: str = "",
        *,
        duration_sec: float | None = None,
        tail: str = "",
        exit_code: int | None = None,
        versions: Versions | None = None,
    ) -> None:
        super().__init__(f"{kind.value}: {detail}")
        self.kind = kind
        self.detail = detail
        self.duration_sec = duration_sec
        self.tail = tail
        self.exit_code = exit_code
        self.versions = versions or Versions()

    @property
    def entry(self) -> Entry:
        return CATALOG[self.kind]

    @property
    def message(self) -> str:
        """What the user is told: the catalog's words, never yt-dlp's."""
        return message_for(self.kind, duration_sec=self.duration_sec)

    def as_pipeline_error(self) -> PipelineError:
        """The worker's form of this failure: reason, message, retry rule."""
        return PipelineError(
            self.entry.reason, self.message, retryable=self.entry.retryable
        )


@runtime_checkable
class UrlFetcher(Protocol):
    """Looks a link up, and downloads its audio. Raises FetchError."""

    def lookup(self, link: Link) -> VideoInfo: ...

    def download(
        self,
        link: Link,
        work_dir: Path,
        *,
        max_bytes: int,
        progress: Progress | None = None,
    ) -> Download: ...


_REFUSED_LIVE = {
    "is_live": FetchKind.LIVE,
    "is_upcoming": FetchKind.UPCOMING,
    "post_live": FetchKind.POST_LIVE,
}
_REFUSED_AVAILABILITY = {
    "private": FetchKind.PRIVATE,
    "premium_only": FetchKind.MEMBERS_ONLY,
    "subscriber_only": FetchKind.MEMBERS_ONLY,
    "needs_auth": FetchKind.AGE_RESTRICTED,
}


def check_info(info: VideoInfo, *, max_duration_sec: float = MAX_DURATION_SEC) -> float:
    """Refuse a video we cannot use, from its metadata alone; else its length.

    The api runs this after a lookup (step 6), and the child again on fresh
    metadata before downloading, since a video can change while queued.
    Missing duration is refused here, not left to ffprobe: the size cap
    would stop a three-hour download only after 150 MB of it had arrived.
    """
    live = _REFUSED_LIVE.get(info.live_status or "")
    if live is not None:
        raise FetchError(
            live, f"live_status={info.live_status}", versions=info.versions
        )
    refused = _REFUSED_AVAILABILITY.get(info.availability or "")
    if refused is not None:
        raise FetchError(
            refused, f"availability={info.availability}", versions=info.versions
        )
    if info.duration_sec is None:
        raise FetchError(
            FetchKind.NO_DURATION,
            "no duration in the metadata",
            versions=info.versions,
        )
    try:
        check_duration(info.duration_sec, max_duration_sec)
    except PipelineError as error:
        if error.reason is FailureReason.TOO_LONG:
            raise FetchError(
                FetchKind.TOO_LONG,
                f"duration={info.duration_sec}",
                duration_sec=info.duration_sec,
                versions=info.versions,
            ) from None
        raise FetchError(  # zero, negative or NaN
            FetchKind.NO_DURATION,
            f"duration={info.duration_sec}",
            versions=info.versions,
        ) from None
    return info.duration_sec


@dataclass(frozen=True)
class JsRuntime:
    name: str
    path: str
    version: str

    @property
    def label(self) -> str:
        return f"{self.name}/{self.version}"


_DENO_VERSION = re.compile(r"deno (\d+)\.(\d+)\.(\d+)")


def find_deno(*, which: Callable[[str], str | None] = shutil.which) -> JsRuntime | None:
    """Deno, where yt-dlp itself looks first — beside this Python, then on
    PATH — if it is new enough for the pinned yt-dlp. None otherwise."""
    beside = Path(sysconfig.get_path("scripts")) / "deno"
    for candidate in (str(beside) if beside.is_file() else None, which("deno")):
        if candidate is None:
            continue
        try:
            answer = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        match = _DENO_VERSION.search(answer.stdout)
        if match is None:
            continue
        version = tuple(int(part) for part in match.groups())
        if version >= MIN_DENO_VERSION:
            return JsRuntime("deno", candidate, ".".join(match.groups()))
    return None


def log_links_at_start(log: logging.Logger, links_on: bool) -> None:
    """What the api and the worker each say at start, in the same words:
    whether links are on, so one on and the other off (W1) shows in the
    logs, and a warning when they are on but Deno is missing."""
    log.info("links are %s (GUITARVIS_URL_INGESTION)", "on" if links_on else "off")
    if links_on and find_deno() is None:
        log.warning("%s", NO_DENO_WARNING)


def child_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The child's environment: ours, minus every GUITARVIS_* variable, with
    yt-dlp's plugins switched off (it loads them from config directories)."""
    source = os.environ if environ is None else environ
    env = {
        name: value
        for name, value in source.items()
        if not name.startswith("GUITARVIS_")
    }
    env["YTDLP_NO_PLUGINS"] = "1"
    return env


def watch_parent() -> None:
    """For the child to call first thing: die when the parent does.

    ChildFetcher holds the write end of the child's stdin and never writes to
    it. When the parent dies, SIGKILL included, the kernel closes that end;
    the read here returns end-of-file and the child kills its own process
    group, the JavaScript runtime it started with it. A child whose stdin is
    already at end-of-file (`/dev/null`) therefore ends at once. Stdlib only.

    The pipe is watched through a copy no other process inherits, and file
    descriptor 0 becomes /dev/null before this returns: what the child starts
    (Deno, through yt-dlp; ffmpeg) reads end-of-file from its stdin, rather
    than waiting forever on a pipe nobody writes to.
    """
    try:
        watched: int | None = os.dup(0)  # non-inheritable, as os.dup makes it
    except OSError:  # no stdin at all: nothing to tell us the parent is alive
        watched = None
    _stdin_from_devnull()
    threading.Thread(target=_die_with_parent, args=(watched,), daemon=True).start()


def _stdin_from_devnull() -> None:
    devnull = os.open(os.devnull, os.O_RDONLY)
    if devnull != 0:  # 0 when fd 0 was closed: then it is /dev/null already
        os.dup2(devnull, 0)
        os.close(devnull)


def _die_with_parent(watched: int | None) -> None:
    if watched is not None:
        with contextlib.suppress(OSError):  # a pipe that cannot be read is gone too
            while os.read(watched, 4096):
                pass
    pid = os.getpid()
    if os.getpgrp() == pid:  # ChildFetcher's start_new_session made us its leader
        os.killpg(pid, signal.SIGKILL)
    os.kill(pid, signal.SIGKILL)  # not the leader: never signal a group not ours


class ChildFetcher:
    """Implements UrlFetcher with yt-dlp, in `python -I -m guitarvis_fetch.child`.

    `command` is for tests, which run a fake child instead.
    """

    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        lookup_deadline_sec: float = LOOKUP_DEADLINE_SEC,
        download_deadline_sec: float = DOWNLOAD_DEADLINE_SEC,
    ) -> None:
        self._command = (
            list(command)
            if command is not None
            else [sys.executable, "-I", "-m", "guitarvis_fetch.child"]
        )
        self._lookup_deadline_sec = lookup_deadline_sec
        self._download_deadline_sec = download_deadline_sec

    def lookup(self, link: Link) -> VideoInfo:
        result, versions = self._run(
            ["lookup", link.canonical_url],
            deadline_sec=self._lookup_deadline_sec,
            timeout_kind=FetchKind.LOOKUP_TIMEOUT,
        )
        return _video_info(result, versions)

    def download(
        self,
        link: Link,
        work_dir: Path,
        *,
        max_bytes: int,
        progress: Progress | None = None,
    ) -> Download:
        result, versions = self._run(
            ["download", link.canonical_url, str(work_dir), str(max_bytes)],
            deadline_sec=self._download_deadline_sec,
            timeout_kind=FetchKind.DOWNLOAD_TIMEOUT,
            progress=progress,
        )
        try:
            return Download(
                path=Path(_text(result, "path")),
                info=_video_info(result, versions),
                format_id=_text(result, "format_id"),
                ext=_text(result, "ext"),
                size=int(result["size"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FetchError(
                FetchKind.CRASHED, f"unreadable result: {error!r}", versions=versions
            ) from None

    def _run(
        self,
        args: list[str],
        *,
        deadline_sec: float,
        timeout_kind: FetchKind,
        progress: Progress | None = None,
    ) -> tuple[dict[str, Any], Versions]:
        try:
            stderr = tempfile.TemporaryFile()  # noqa: SIM115  (closed by `with`)
        except OSError as error:
            raise _could_not_start("a file for the child's stderr", error) from None
        with stderr:
            try:
                process = subprocess.Popen(
                    [*self._command, *args],
                    # Never written to: its closing is the child's cue that we
                    # are gone (see watch_parent).
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=stderr,
                    env=child_environment(),
                    start_new_session=True,  # its own process group, to kill whole
                )
            except OSError as error:
                raise _could_not_start("the child", error) from None
            lines: queue.Queue[bytes | None] = queue.Queue()
            reader = threading.Thread(
                target=_read_lines, args=(process.stdout, lines), daemon=True
            )
            try:
                try:
                    reader.start()
                except RuntimeError as error:  # no thread to be had
                    raise _could_not_start("a reader thread", error) from None
                return _answer(
                    lines,
                    process,
                    stderr,
                    deadline=time.monotonic() + deadline_sec,
                    timeout_kind=timeout_kind,
                    progress=progress,
                )
            finally:
                # Every way out, a job timeout's BaseException included: no
                # child, and no JavaScript runtime it started, outlives this.
                _kill_group(process)
                process.wait()
                _close_pipes(process, reader)


def _could_not_start(what: str, error: Exception) -> FetchError:
    return FetchError(
        FetchKind.CRASHED,
        f"could not start {what}: {type(error).__name__}: {error}",
        versions=Versions(ytdlp=_installed_ytdlp()),
    )


def _close_pipes(process: "subprocess.Popen[bytes]", reader: threading.Thread) -> None:
    """After the kill: let the reader reach end of output, then close our ends."""
    if reader.is_alive():  # false if it never started
        reader.join(timeout=REAP_SEC)
    if process.stdout is not None and not reader.is_alive():
        process.stdout.close()  # closing under a blocked reader would block too
    if process.stdin is not None:
        with contextlib.suppress(OSError):
            process.stdin.close()


class _Seen:
    """The versions the child has reported, from whichever lines carried them.
    Every failure raised for a call carries them: a timeout or a crash is
    when "which version broke" matters most."""

    def __init__(self) -> None:
        self._ytdlp: str | None = None
        self._js: str | None = None

    def note(self, message: dict[str, Any]) -> None:
        if message.get("ytdlp"):
            self._ytdlp = str(message["ytdlp"])
        if message.get("js"):
            self._js = str(message["js"])

    @property
    def versions(self) -> Versions:
        return Versions(ytdlp=self._ytdlp or _installed_ytdlp(), js=self._js or "-")


def _installed_ytdlp() -> str:
    """The installed yt-dlp's version, for when the child never said: read
    from package metadata, without importing yt-dlp."""
    try:
        return importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        return "-"


def _answer(
    lines: "queue.Queue[bytes | None]",
    process: "subprocess.Popen[bytes]",
    stderr: IO[bytes],
    *,
    deadline: float,
    timeout_kind: FetchKind,
    progress: Progress | None,
) -> tuple[dict[str, Any], Versions]:
    seen = _Seen()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError(
                timeout_kind,
                "no answer before the deadline",
                tail=_tail(stderr),
                versions=seen.versions,
            )
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            continue
        if line is None:
            code = _exit_code(process)
            raise FetchError(
                FetchKind.CRASHED,
                f"exited with {code} and no answer",
                tail=_tail(stderr),
                exit_code=code,
                versions=seen.versions,
            )
        message = _decode(line)
        if message is None:
            raise FetchError(
                FetchKind.CRASHED,
                f"unreadable line: {line[:200]!r}",
                tail=_tail(stderr),
                versions=seen.versions,
            )
        seen.note(message)
        if "progress" in message:
            if progress is not None:
                _report(progress, message["progress"])
            continue
        if isinstance(message.get("result"), dict):
            return message["result"], seen.versions
        if isinstance(message.get("error"), dict):
            raise _error_from(message["error"], seen.versions, _tail(stderr))
        raise FetchError(
            FetchKind.CRASHED,
            f"unexpected line: {line[:200]!r}",
            tail=_tail(stderr),
            versions=seen.versions,
        )


def _read_lines(stream: IO[bytes] | None, lines: "queue.Queue[bytes | None]") -> None:
    if stream is not None:
        for line in stream:
            lines.put(line)
    lines.put(None)  # end of output: the child has exited, or closed stdout


def _decode(line: bytes) -> dict[str, Any] | None:
    try:
        message = json.loads(line)
    except ValueError:
        return None
    return message if isinstance(message, dict) else None


def _report(progress: Progress, value: object) -> None:
    """Pass on a fraction, clamped; anything else the child sent is dropped."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return
    if math.isfinite(value):
        progress(min(max(float(value), 0.0), 1.0))


def _error_from(error: dict[str, Any], versions: Versions, tail: str) -> FetchError:
    try:
        kind = FetchKind(str(error.get("kind")))
    except ValueError:
        kind = FetchKind.UNKNOWN
    duration = error.get("duration_sec")
    return FetchError(
        kind,
        str(error.get("detail") or ""),
        duration_sec=float(duration) if isinstance(duration, int | float) else None,
        tail=tail,
        versions=versions,
    )


def _exit_code(process: "subprocess.Popen[bytes]") -> int | None:
    try:
        return process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return None


def _kill_group(process: "subprocess.Popen[bytes]") -> None:
    with contextlib.suppress(ProcessLookupError):  # the group is already gone
        os.killpg(process.pid, signal.SIGKILL)


def _tail(stderr: IO[bytes]) -> str:
    stderr.flush()
    size = stderr.seek(0, os.SEEK_END)
    stderr.seek(max(0, size - TAIL_BYTES))
    return stderr.read().decode(errors="replace")


def _text(result: dict[str, Any], key: str) -> str:
    value = result[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} is not text")
    return value


def _video_info(result: dict[str, Any], versions: Versions) -> VideoInfo:
    title = result.get("title")
    duration = result.get("duration_sec")
    live_status = result.get("live_status")
    availability = result.get("availability")
    return VideoInfo(
        title=title if isinstance(title, str) else "",
        duration_sec=float(duration)
        if isinstance(duration, int | float) and not isinstance(duration, bool)
        else None,
        live_status=live_status if isinstance(live_status, str) else None,
        availability=availability if isinstance(availability, str) else None,
        versions=versions,
    )


def log_failed(
    log: logging.Logger,
    error: FetchError,
    *,
    phase: str,
    link: Link,
    elapsed_sec: float,
    job_id: str | None = None,
    attempt: int | None = None,
) -> None:
    """One line per failure, at the catalog's level (spec 012, *Logging*)."""
    entry = error.entry
    line = (
        f"link fetch failed kind={error.kind} phase={phase} site={link.site} "
        f"video={link.video_id} job={job_id or '-'} attempt={attempt or '-'} "
        f"elapsed={elapsed_sec:.1f}s ytdlp={error.versions.ytdlp} "
        f"js={error.versions.js} detail={_quoted(error.detail[:DETAIL_CHARS])}"
    )
    if error.exit_code is not None:
        line += f" exit={error.exit_code}"
    if entry.tail and error.tail:
        line += f" tail={_quoted(error.tail)}"
    log.log(entry.level, "%s", line)


def _quoted(text: str) -> str:
    """`text` as one double-quoted token. yt-dlp's words, and the stderr they
    end up in, are untrusted: no newline, quote or control character in them
    may end the field or start another line (spec 012, *Logging*)."""
    return json.dumps(text)


def log_fetched(
    log: logging.Logger,
    *,
    phase: str,
    link: Link,
    versions: Versions,
    elapsed_sec: float,
    job_id: str | None = None,
    attempt: int | None = None,
    download: Download | None = None,
) -> None:
    """Successes too: a broken extractor shows as a change in the ratio of
    ERROR lines to these, and the format ids show how often m4a is missing."""
    line = (
        f"link fetched phase={phase} site={link.site} video={link.video_id} "
        f"job={job_id or '-'} attempt={attempt or '-'} elapsed={elapsed_sec:.1f}s "
        f"ytdlp={versions.ytdlp} js={versions.js}"
    )
    if download is not None:
        line += f" format={download.format_id} ext={download.ext} bytes={download.size}"
    log.info("%s", line)


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    _conforms: UrlFetcher = ChildFetcher()
