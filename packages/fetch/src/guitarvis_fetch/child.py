"""The child process, and the only module that imports yt-dlp (spec 012).

ChildFetcher runs `python -I -m guitarvis_fetch.child lookup URL`, or
`... download URL WORK_DIR MAX_BYTES`, and reads JSON lines from stdout
(guitarvis_fetch.fetcher describes them). Every failure is classified here,
while yt-dlp's exception types are still visible: only a kind crosses the
process boundary, with yt-dlp's text beside it for the log.

yt-dlp is imported inside functions. If it will not import, the child still
answers, as misconfigured, instead of dying with a traceback the parent can
only call a crash.
"""

import ipaddress
import json
import os
import re
import socket
import ssl
import sys
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import IO, Any
from urllib.parse import urlsplit

from guitarvis_fetch.catalog import FetchKind
from guitarvis_fetch.fetcher import (
    MIN_DENO_VERSION,
    FetchError,
    JsRuntime,
    Versions,
    VideoInfo,
    check_info,
    find_deno,
    watch_parent,
)

# Audio only, over plain HTTPS, so the download is one GET whose host can be
# checked first. m4a first: Opus in WebM does not play in older Safari.
FORMAT = "bestaudio[ext=m4a][protocol=https]/bestaudio[protocol=https]"
OUTPUT_TEMPLATE = "source.%(ext)s"  # fixed: a title never becomes a path
SOCKET_TIMEOUT_SEC = 15
MEDIA_HOST_SUFFIX = ".googlevideo.com"

Resolve = Callable[..., list[tuple[Any, ...]]]
Hook = Callable[[dict[str, Any]], None]


def ydl_options(
    *,
    deno: str,
    logger: Any,
    work_dir: Path | None = None,
    max_bytes: int | None = None,
    hooks: Sequence[Hook] = (),
) -> dict[str, Any]:
    """Everything yt-dlp is told, and nothing more: the YouTube extractor
    only, one video, no cookies, no geo-bypass, no post-processors of ours,
    no code fetched at run time, and low retry counts, since RQ retries the
    job. yt-dlp's own fixup still remuxes a DASH m4a with ffmpeg, which
    makes it a file every browser plays.

    Verbose, because the extractor says it skipped the default clients'
    formats, for want of a PO token or a URL, only in debug lines, and
    yt-dlp drops those otherwise (YoutubeDL.py:1164-1167). ChildLog keeps
    only those of what verbose adds."""
    options: dict[str, Any] = {
        "logger": logger,
        "quiet": True,
        "verbose": True,
        "noprogress": True,
        "color": "never",
        "ignoreerrors": False,
        "allowed_extractors": ["youtube"],
        "noplaylist": True,
        "format": FORMAT,
        "js_runtimes": {"deno": {"path": deno}},
        "remote_components": [],
        "geo_bypass": False,
        "socket_timeout": SOCKET_TIMEOUT_SEC,
        "retries": 1,
        "fragment_retries": 1,
        "extractor_retries": 1,
        "file_access_retries": 1,
        "postprocessors": [],
    }
    if work_dir is not None:
        options |= {
            "paths": {"home": str(work_dir), "temp": str(work_dir)},
            "outtmpl": {"default": OUTPUT_TEMPLATE},
            "overwrites": True,
            "max_filesize": max_bytes,
            "progress_hooks": list(hooks),
        }
    return options


class ChildLog:
    """yt-dlp's logger, and the evidence a failure is classified by.

    Everything goes to stderr, where the parent keeps the last 2 KB for the
    log; of what verbose adds, only the notices that formats were withheld,
    each once, since the rest would push them out. Warnings are kept too,
    and whether the formats offered were only video (`_choose`): a format
    error is "no audio" only when they were, and no warning said formats
    were withheld."""

    def __init__(self, stream: IO[str]) -> None:
        self._stream = stream
        self.warnings: list[str] = []
        self.hit_size_cap = False
        self.video_only = False
        self._notices: set[str] = set()

    def debug(self, message: str) -> None:
        # yt-dlp's max_filesize gives up quietly: no error, and no file.
        if "max-filesize" in message:
            self.hit_size_cap = True
        if message.startswith("[debug] "):  # verbose's own (YoutubeDL.py:1168)
            # Each notice once: through a logger, yt-dlp drops write_debug's
            # only_once (:1169-1170), and the extractor notes each format.
            if not _WITHHELD.search(message) or message in self._notices:
                return
            self._notices.add(message)
        self._write(message)

    def info(self, message: str) -> None:
        self._write(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)
        self._write(f"WARNING: {message}")

    def error(self, message: str) -> None:
        # Verbose follows an ERROR line with its traceback, more than 1 KB
        # of it (YoutubeDL.py:1085-1095); the ERROR line is what matters.
        if _TRACEBACK.search(message):
            return
        self._write(message)

    def _write(self, message: str) -> None:
        self._stream.write(message + "\n")
        self._stream.flush()


def lookup(ydl: Any, url: str, log: ChildLog) -> dict[str, Any]:
    """The video's metadata, checked, then its formats chosen, so a video
    with no audio we can use is refused now rather than in the queue.

    Metadata first, without choosing formats: a live stream has no format
    our filter accepts, and choosing first would fail it as a format error.
    """
    raw = ydl.extract_info(url, download=False, process=False)
    info = _checked(raw)
    _choose(ydl, raw, log)
    return info


def _choose(ydl: Any, raw: dict[str, Any], log: ChildLog) -> dict[str, Any]:
    """The format our filter picks from those the extractor offered.

    What was offered is noted first. If nothing passes, it is the only
    evidence of whether the video has no audio or YouTube withheld it, and
    choosing replaces it with what survived yt-dlp's own filters
    (YoutubeDL.py:3028-3033).
    """
    log.video_only = offers_only_video(raw.get("formats"))
    return ydl.process_ie_result(raw, download=False)


def offers_only_video(formats: object) -> bool:
    """Positive evidence that a video has no audio: the extractor offered
    formats a player could use, with a URL, video and no DRM, and not one
    format of any kind that carries audio, or may.

    An empty list, only storyboards, or audio our filter refuses (in a
    muxed or HLS format, or behind DRM) prove nothing: YouTube withholding
    formats looks like that too.
    """
    if not isinstance(formats, list) or not all(isinstance(f, dict) for f in formats):
        return False
    playable = [
        f
        for f in formats
        if f.get("url") and not _locked(f) and f.get("vcodec") not in (None, "none")
    ]
    return bool(playable) and all(f.get("acodec") == "none" for f in formats)


def _locked(fmt: dict[str, Any]) -> bool:
    """DRM, as yt-dlp drops it: "maybe", said of HLS, still plays
    (YoutubeDL.py:2925-2928)."""
    return bool(fmt.get("has_drm")) and fmt.get("has_drm") != "maybe"


def download(
    ydl: Any,
    url: str,
    work_dir: Path,
    max_bytes: int,
    log: ChildLog,
    *,
    resolve: Resolve = socket.getaddrinfo,
) -> dict[str, Any]:
    """Fresh metadata and the same checks as a lookup, then the one GET.

    Not the api's format URLs: those are bound to the api's address, they
    expire, and the worker may be on another host.
    """
    raw = ydl.extract_info(url, download=False, process=False)
    info = _checked(raw)
    selected = _choose(ydl, raw, log)
    check_media(selected, max_bytes, resolve=resolve)
    ydl.process_info(selected)

    path = work_dir / f"source.{selected.get('ext')}"
    if not path.is_file():
        kind = FetchKind.TOO_LARGE if log.hit_size_cap else FetchKind.EMPTY_DOWNLOAD
        raise FetchError(kind, f"no file at {path.name}")
    size = path.stat().st_size
    if size == 0:
        raise FetchError(FetchKind.EMPTY_DOWNLOAD, f"{path.name} is empty")
    if size > max_bytes:
        raise FetchError(FetchKind.TOO_LARGE, f"{path.name} is {size} bytes")
    return {
        **info,
        "path": str(path),
        "format_id": str(selected.get("format_id") or "-"),
        "ext": path.suffix.removeprefix("."),
        "size": size,
    }


def check_media(
    selected: dict[str, Any], max_bytes: int, *, resolve: Resolve = socket.getaddrinfo
) -> None:
    """The download is one HTTPS GET to YouTube's media hosts, at public
    addresses, and no larger than we accept. Refused before connecting.

    Redirects yt-dlp follows mid-download, and DNS answers that change after
    this check, are not re-checked: only egress rules at hosting close that.
    """
    if selected.get("requested_formats"):
        raise FetchError(FetchKind.MEDIA_REFUSED, "more than one format selected")
    parts = urlsplit(str(selected.get("url") or ""))
    host = parts.hostname or ""
    if selected.get("protocol") != "https" or parts.scheme != "https":
        raise FetchError(
            FetchKind.MEDIA_REFUSED,
            f"protocol={selected.get('protocol')} scheme={parts.scheme}",
        )
    if not host.endswith(MEDIA_HOST_SUFFIX):
        raise FetchError(FetchKind.MEDIA_REFUSED, f"host={host}")
    addresses = {
        answer[4][0] for answer in resolve(host, 443, proto=socket.IPPROTO_TCP)
    }
    if not addresses or not all(_is_public(address) for address in addresses):
        raise FetchError(
            FetchKind.MEDIA_REFUSED, f"host={host} resolves to {sorted(addresses)}"
        )
    size = selected.get("filesize") or selected.get("filesize_approx")
    if isinstance(size, int | float) and size > max_bytes:
        raise FetchError(FetchKind.TOO_LARGE, f"filesize={size}")


def _is_public(address: str) -> bool:
    try:
        return ipaddress.ip_address(address.split("%")[0]).is_global
    except ValueError:
        return False


def _checked(raw: Any) -> dict[str, Any]:
    """The fields a lookup returns, once check_info has passed them."""
    if not isinstance(raw, dict) or raw.get("_type", "video") != "video":
        # YouTube answers a paid video with its trailer instead.
        raise FetchError(FetchKind.MEMBERS_ONLY, "not one video: a trailer, perhaps")
    duration = raw.get("duration")
    info = VideoInfo(
        title=str(raw.get("title") or ""),
        duration_sec=float(duration)
        if isinstance(duration, int | float) and not isinstance(duration, bool)
        else None,
        live_status=raw.get("live_status"),
        availability=raw.get("availability"),
    )
    check_info(info)
    return {
        "title": info.title,
        "duration_sec": info.duration_sec,
        "live_status": info.live_status,
        "availability": info.availability,
    }


class ProgressHook:
    """yt-dlp's progress hook: the byte fraction to the parent, each whole
    percent once, and the size cap again for a response with no length."""

    def __init__(self, out: IO[str], max_bytes: int) -> None:
        self._out = out
        self._max_bytes = max_bytes
        self._shown = -1

    def __call__(self, status: dict[str, Any]) -> None:
        done = status.get("downloaded_bytes") or 0
        if done > self._max_bytes:
            raise FetchError(FetchKind.TOO_LARGE, f"{done} bytes and counting")
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        if not total:
            return
        percent = int(min(done / total, 1.0) * 100)
        if percent > self._shown:
            self._shown = percent
            send(self._out, {"progress": percent / 100})


# The classifier. Order matters: a private video's message also asks the
# viewer to sign in, and a hate-speech removal mentions "your country".
_MESSAGES: list[tuple[FetchKind, re.Pattern[str]]] = [
    (FetchKind.PRIVATE, re.compile(r"private video|this video is private")),
    (
        FetchKind.RATE_LIMITED,
        # "not a bot" matches YouTube's curly apostrophe and a straight one.
        re.compile(
            r"not a bot|try again later|rate-limited|captcha|likely being blocked"
            r"|too many requests"
        ),
    ),
    (
        FetchKind.AGE_RESTRICTED,
        re.compile(r"confirm your age|age-restricted|inappropriate for some users"),
    ),
    (
        FetchKind.MEMBERS_ONLY,
        re.compile(
            r"members-only|channel's members|join this channel|requires payment"
            r"|drm protected|premium members"
        ),
    ),
    (
        FetchKind.UPCOMING,
        re.compile(r"live event will begin|premieres in|premiere will begin"),
    ),
    (
        FetchKind.GEO_RESTRICTED,
        re.compile(r"not made this video available in your country|from your location"),
    ),
    (
        FetchKind.UNAVAILABLE,
        re.compile(
            r"video unavailable|video is unavailable|video is not available"
            r"|has been removed|no longer available|been terminated"
            r"|recording is not available|does not exist"
        ),
    ),
    # Last: any other reason that asks the viewer to sign in (L4). The
    # private and bot reasons above ask it too, and keep their own kinds.
    (FetchKind.AGE_RESTRICTED, re.compile(r"\bsign in\b")),
]
_FORMAT_ERROR = re.compile(
    r"requested format is not available|no video formats found"
    r"|only images are available"
)
_BROKEN = re.compile(
    r"unable to extract|unsupported url|no suitable extractor"
    r"|failed to extract any player response|signature extraction failed"
)
_CHALLENGE_WARNING = re.compile(
    r"challenge|javascript runtime|signature solving|remote components?", re.IGNORECASE
)
# yt-dlp's words for formats YouTube withheld, in yt-dlp 2026.10.26's
# extractor/youtube/_video.py: wanting a PO token (:3195-3206), missing a URL
# under SABR (:3536-3549), DRM (:3418-3427), and challenges unsolved or no
# runtime to solve them (:3349-3356, :2994-2999). For the default clients
# (:143) the first two are debug lines, the rest warnings.
_WITHHELD = re.compile(
    r"formats (?:have been skipped|require a GVS PO Token|may be missing)",
    re.IGNORECASE,
)
# A traceback as YoutubeDL.trouble writes it: whole, or as frames alone
# (ExtractorError.format_traceback, utils/_utils.py:1010-1014).
_TRACEBACK = re.compile(r'^(?:Traceback \(most recent call last\):|  File ")', re.M)
# YouTube's extractor turns a failed player request into a warning and tries
# its next client; when none is left it raises "Failed to extract any player
# response", with no cause. Only the warnings still say why.
_RATE_LIMITED_WARNING = re.compile(r"http error 429|too many requests", re.IGNORECASE)
_NO_PLAYER_RESPONSE = re.compile(r"failed to extract any player response")
_NETWORK_WARNING = re.compile(
    # A 5xx as message or repr, or a transport failure as its repr after
    # "caused by": yt-dlp's TransportError and each of its subclasses.
    r"http ?error 5\d\d"
    r"|(?:transporterror|sslerror|certificateverifyerror|proxyerror)\("
    r"|incompleteread",
    re.IGNORECASE,
)
# yt-dlp's HTTP downloader retries a 5xx, a dropped connection or a short
# read, then gives up in words alone: no exception is left to look at.
_DOWNLOAD_GAVE_UP = re.compile(r"\[download\] got error:")


def classify(
    error: BaseException, warnings: Sequence[str] = (), *, video_only: bool = False
) -> FetchKind:
    """The kind of a failure, from yt-dlp's exception types first and its
    messages second. Anything unrecognised is unknown: fetch_failed, and
    retried, which is honest if less helpful.

    `video_only` is what the lookup saw offered (`offers_only_video`): the
    one thing that can show a format error is the video's own fault.

    A yt-dlp that will not import has no types to compare with, and is the
    failure itself: misconfigured, whatever was raised (L16).
    """
    try:
        from yt_dlp.networking.exceptions import HTTPError, TransportError
        from yt_dlp.utils import (
            ContentTooShortError,
            GeoRestrictedError,
            UnavailableVideoError,
        )
    except Exception:  # a SyntaxError, say, from a half-finished upgrade
        return FetchKind.MISCONFIGURED

    chain = list(exception_chain(error))
    text = " ".join(str(exc) for exc in chain).lower()
    statuses = {exc.status for exc in chain if isinstance(exc, HTTPError)}
    challenged = any(_CHALLENGE_WARNING.search(warning) for warning in warnings)
    warned = " ".join(warnings)

    if any(isinstance(exc, GeoRestrictedError) for exc in chain):
        return FetchKind.GEO_RESTRICTED
    if 429 in statuses:
        return FetchKind.RATE_LIMITED
    # The video's own words, before any warning: a private or removed video
    # is that, whatever another player client ran into on the way.
    for kind, pattern in _MESSAGES:
        if pattern.search(text):
            return kind
    network = (
        TransportError,
        ContentTooShortError,
        ConnectionError,
        TimeoutError,
        socket.gaierror,
        ssl.SSLError,
    )
    if any(isinstance(exc, network) for exc in chain):
        return FetchKind.NETWORK
    if any(status >= 500 for status in statuses):
        return FetchKind.NETWORK
    if _DOWNLOAD_GAVE_UP.search(text):
        return FetchKind.NETWORK
    if 403 in statuses and challenged:
        return FetchKind.EXTRACTOR_BROKEN
    # After the network types, which are OSErrors too (socket errors, and
    # URLError). yt-dlp raises UnavailableVideoError when writing fails.
    if any(isinstance(exc, OSError | UnavailableVideoError) for exc in chain):
        return FetchKind.LOCAL_IO  # a full disk, say
    # Before the format error: with some clients throttled or failing and
    # another's formats all skipped, yt-dlp says "Requested format is not
    # available", and "no audio" would refuse every link, for good, for as
    # long as YouTube throttles us or is down.
    if _RATE_LIMITED_WARNING.search(warned):
        return FetchKind.RATE_LIMITED
    if _FORMAT_ERROR.search(text) and _NETWORK_WARNING.search(warned):
        return FetchKind.NETWORK
    if _FORMAT_ERROR.search(text):
        # No audio only on positive evidence: real video offered, nothing
        # with audio, and no warning that formats were withheld. Anything
        # less is ours. YouTube withholding formats, for want of a PO token,
        # in a SABR rollout or without a working runtime, looks the same,
        # and "no audio" would refuse every link, for good, at WARNING.
        # The default clients' notices are debug lines, not warnings, and
        # are no evidence: web's come with nearly every lookup, since its formats
        # always want a PO token (extractor/youtube/_base.py:71-84). They go
        # to the log's tail instead (ChildLog).
        withheld = challenged or any(_WITHHELD.search(w) for w in warnings)
        if video_only and not withheld:
            return FetchKind.NO_AUDIO
        return FetchKind.EXTRACTOR_BROKEN
    if _NO_PLAYER_RESPONSE.search(text) and _NETWORK_WARNING.search(warned):
        return FetchKind.NETWORK
    if _BROKEN.search(text):
        return FetchKind.EXTRACTOR_BROKEN
    return FetchKind.UNKNOWN


def exception_chain(error: BaseException) -> Iterator[BaseException]:
    """`error` and everything behind it: yt-dlp's `exc_info` and `cause`,
    and Python's own __cause__ and __context__. Each once."""
    seen: set[int] = set()
    pending: list[BaseException | None] = [error]
    while pending:
        exc = pending.pop(0)
        if exc is None or id(exc) in seen:
            continue
        seen.add(id(exc))
        yield exc
        exc_info = getattr(exc, "exc_info", None)
        if isinstance(exc_info, tuple) and len(exc_info) == 3:
            pending.append(exc_info[1])
        cause = getattr(exc, "cause", None)
        if isinstance(cause, BaseException):
            pending.append(cause)
        pending += [exc.__cause__, exc.__context__]


def send(out: IO[str], message: dict[str, Any]) -> None:
    out.write(json.dumps(message) + "\n")
    out.flush()


def _protocol_stream() -> IO[str]:
    """Our stdout, kept for the protocol. File descriptor 1 then points at
    stderr, so nothing yt-dlp or Deno prints can corrupt an answer."""
    sys.stdout.flush()
    protocol = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    return protocol


def _new_ydl(options: dict[str, Any]) -> Any:
    # yt-dlp loads plugins from the user's and the system's config
    # directories when a YoutubeDL is made; the parent sets this too.
    os.environ["YTDLP_NO_PLUGINS"] = "1"
    import yt_dlp

    # Verbose prints a header when a YoutubeDL is made, and runs ffmpeg,
    # ffprobe and others to fill it (YoutubeDL.py:635-638, 751-752, 4147).
    return yt_dlp.YoutubeDL(options, auto_init="no_verbose_header")


def _answer(
    args: list[str], runtime: JsRuntime, log: ChildLog, out: IO[str]
) -> dict[str, Any]:
    if len(args) == 2 and args[0] == "lookup":
        with _new_ydl(ydl_options(deno=runtime.path, logger=log)) as ydl:
            return lookup(ydl, args[1], log)
    if len(args) == 4 and args[0] == "download":
        work_dir, max_bytes = Path(args[2]), int(args[3])
        hook = ProgressHook(out, max_bytes)
        options = ydl_options(
            deno=runtime.path,
            logger=log,
            work_dir=work_dir,
            max_bytes=max_bytes,
            hooks=[hook],
        )
        with _new_ydl(options) as ydl:
            return download(ydl, args[1], work_dir, max_bytes, log)
    raise FetchError(
        FetchKind.CRASHED, f"usage: lookup URL | download URL DIR BYTES, got {args!r}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    out = _protocol_stream()
    log = ChildLog(sys.stderr)
    versions = Versions()
    try:
        runtime = find_deno()
        if runtime is None:
            minimum = ".".join(str(part) for part in MIN_DENO_VERSION)
            raise FetchError(
                FetchKind.MISCONFIGURED,
                f"no JavaScript runtime: Deno {minimum} or later is not installed",
            )
        try:
            from yt_dlp.version import __version__ as ytdlp_version
        except Exception as error:  # not only ImportError: a half-done upgrade
            raise FetchError(
                FetchKind.MISCONFIGURED, f"yt-dlp will not import: {error!r}"
            ) from None
        versions = Versions(ytdlp=ytdlp_version, js=runtime.label)
        # Before any work, so a timeout or a crash still names them: a hung
        # Deno is a likely cause of a timeout.
        send(out, {"progress": 0.0, **_known(versions)})
        result = _answer(args, runtime, log, out)
    except FetchError as error:
        _send_error(out, error.kind, error.detail, error.duration_sec, versions)
    except Exception as error:  # yt-dlp's, classified while its types are here
        kind = classify(error, log.warnings, video_only=log.video_only)
        _send_error(out, kind, str(error), None, versions)
    else:
        send(out, {"result": result, **_known(versions)})
    return 0


def _known(versions: Versions) -> dict[str, str]:
    """The versions to put on a line: those learned. One not yet learned is
    left out rather than sent as "-", so the parent names the installed
    yt-dlp in its place."""
    learned = {"ytdlp": versions.ytdlp, "js": versions.js}
    return {name: value for name, value in learned.items() if value != "-"}


def _send_error(
    out: IO[str],
    kind: FetchKind,
    detail: str,
    duration_sec: float | None,
    versions: Versions,
) -> None:
    sys.stderr.flush()  # so the parent's tail has all of it
    send(
        out,
        {
            "error": {
                "kind": kind.value,
                "detail": detail,
                "duration_sec": duration_sec,
            },
            **_known(versions),
        },
    )


if __name__ == "__main__":
    # First thing, and only as a process: die with the parent (see
    # fetcher.watch_parent). main() itself never does, so a test may call it.
    watch_parent()
    raise SystemExit(main())
