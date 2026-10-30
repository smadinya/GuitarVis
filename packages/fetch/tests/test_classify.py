"""The child's classifier: yt-dlp's exception types, built offline, and the
messages yt-dlp gives for real failures (fixtures/youtube-messages.json, each
with where it came from). `make smoke-url` prints fresh ones to compare."""

import errno
import io
import json
import socket
import ssl
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from guitarvis_fetch.catalog import FetchKind
from guitarvis_fetch.child import (
    ChildLog,
    _new_ydl,
    classify,
    exception_chain,
    lookup,
    offers_only_video,
    ydl_options,
)
from yt_dlp.networking import Response
from yt_dlp.networking.exceptions import (
    CertificateVerifyError,
    HTTPError,
    ProxyError,
    SSLError,
    TransportError,
)
from yt_dlp.utils import (
    ContentTooShortError,
    DownloadError,
    ExtractorError,
    GeoRestrictedError,
    UnavailableVideoError,
)

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "youtube-messages.json").read_text()
)
ID = "kPdv44HtEoA"
CHALLENGE = "[youtube] x: n challenge solving failed: Some formats may be missing."


def reported(raise_it: Callable[[], None]) -> DownloadError:
    """What yt-dlp hands back for an error: YoutubeDL.trouble's DownloadError,
    whose exc_info is the ExtractorError's own cause when it has one."""
    try:
        raise_it()
    except Exception as error:
        exc_info: Any = getattr(error, "exc_info", None)
        return DownloadError(
            f"ERROR: {error}", exc_info if exc_info and exc_info[0] else sys.exc_info()
        )
    raise AssertionError("raise_it did not raise")


def while_extracting(cause: Exception) -> Callable[[], None]:
    """A network failure inside the extractor, wrapped as it wraps one."""

    def extract() -> None:
        try:
            raise cause
        except Exception as error:
            raise ExtractorError(
                f"Unable to download API page: {error}",
                cause=error,
                video_id=ID,
                ie="youtube",
            ) from None

    return extract


def http_error(status: int, reason: str) -> HTTPError:
    response = Response(
        fp=io.BytesIO(b""),
        url="https://www.youtube.com/youtubei/v1/player",
        headers={},
        status=status,
        reason=reason,
    )
    return HTTPError(response)


def raises(error: BaseException) -> Callable[[], None]:
    def go() -> None:
        raise error

    return go


def caught(raise_it: Callable[[], None]) -> BaseException:
    """The exception itself, as the child sees one process_info raised."""
    try:
        raise_it()
    except Exception as error:
        return error
    raise AssertionError("raise_it did not raise")


def disk_full() -> None:
    # YoutubeDL.process_info, when writing the file fails.
    try:
        raise OSError(errno.ENOSPC, "No space left on device")
    except OSError as error:
        raise UnavailableVideoError(error)  # noqa: B904 -- as yt-dlp does


@pytest.mark.parametrize(
    "fixture",
    FIXTURES,
    ids=[f"{item['kind']}-{n}" for n, item in enumerate(FIXTURES)],
)
def test_each_recorded_message_classifies_as_its_kind(fixture: dict[str, Any]) -> None:
    error = DownloadError(fixture["message"])
    warnings = fixture.get("warnings", [])
    video_only = fixture.get("video_only", False)  # what the lookup was offered

    assert classify(error, warnings, video_only=video_only) is FetchKind(
        fixture["kind"]
    )


def test_every_fixture_says_where_it_came_from() -> None:
    assert all(item["source"] for item in FIXTURES)


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (  # L3
            reported(
                raises(
                    GeoRestrictedError(
                        "The uploader has not made this video available in your "
                        "country",
                        countries=["US"],
                    )
                )
            ),
            FetchKind.GEO_RESTRICTED,
        ),
        (
            reported(while_extracting(http_error(429, "Too Many Requests"))),
            FetchKind.RATE_LIMITED,
        ),  # L12
        (
            reported(while_extracting(http_error(503, "Service Unavailable"))),
            FetchKind.NETWORK,
        ),  # L13
        (
            reported(while_extracting(http_error(500, "Internal Server Error"))),
            FetchKind.NETWORK,
        ),
        (
            reported(
                while_extracting(
                    TransportError(
                        cause=socket.gaierror(-2, "Name or service not known")
                    )
                )
            ),
            FetchKind.NETWORK,
        ),
        (
            reported(while_extracting(TransportError(cause=ConnectionRefusedError()))),
            FetchKind.NETWORK,
        ),
        (
            reported(while_extracting(SSLError(cause=ssl.SSLError(1, "bad record")))),
            FetchKind.NETWORK,
        ),
        (
            reported(while_extracting(CertificateVerifyError(cause="expired"))),
            FetchKind.NETWORK,
        ),
        (reported(while_extracting(ProxyError(cause="refused"))), FetchKind.NETWORK),
        (reported(raises(ContentTooShortError(1000, 2000))), FetchKind.NETWORK),  # D1
        (reported(raises(TimeoutError("timed out"))), FetchKind.NETWORK),
        (caught(disk_full), FetchKind.LOCAL_IO),  # D8: process_info raises it
        (reported(disk_full), FetchKind.LOCAL_IO),  # D8, through YoutubeDL.download
        (
            UnavailableVideoError(OSError(errno.ENOSPC, "No space left on device")),
            FetchKind.LOCAL_IO,
        ),
        (OSError(errno.EACCES, "Permission denied"), FetchKind.LOCAL_IO),
        (
            reported(while_extracting(http_error(404, "Not Found"))),
            FetchKind.UNKNOWN,
        ),  # L17
        (RuntimeError("something new"), FetchKind.UNKNOWN),  # L17, D10
    ],
)
def test_ytdlp_exception_types_classify(error: BaseException, kind: FetchKind) -> None:
    assert classify(error) is kind


def test_a_forbidden_media_url_after_challenge_warnings_is_a_broken_extractor() -> None:
    error = reported(
        raises(
            DownloadError(
                "ERROR: unable to download video data: HTTP Error 403: Forbidden",
                (HTTPError, http_error(403, "Forbidden"), None),
            )
        )
    )

    assert classify(error) is FetchKind.UNKNOWN
    assert classify(error, [CHALLENGE]) is FetchKind.EXTRACTOR_BROKEN


REQUESTED_FORMAT = (
    "Requested format is not available. Use --list-formats for a list of "
    "available formats"
)


def format_error(message: str = REQUESTED_FORMAT) -> ExtractorError:
    """What process_ie_result raises when no format passes our filter
    (YoutubeDL.py:3090-3093), or none is left (:2959-2960, :1188-1196). It
    is not wrapped: only extract_info catches and reports (:1858)."""
    return ExtractorError(message, expected=True, video_id=ID, ie="youtube")


@pytest.mark.parametrize("message", [REQUESTED_FORMAT, "No video formats found!"])
def test_a_format_error_is_ours_unless_the_formats_show_no_audio(
    message: str,
) -> None:  # L11, L15
    """YouTube withholding formats, for want of a PO token or during a SABR
    rollout, looks the same from here as a video with no audio. Only the
    formats the extractor offered can tell them apart."""
    error = format_error(message)

    assert classify(error) is FetchKind.EXTRACTOR_BROKEN
    assert classify(error, video_only=True) is FetchKind.NO_AUDIO


# yt-dlp's warnings that YouTube withheld formats, in its words
# (extractor/youtube/_video.py). The default clients' own notices are debug
# lines, and never reach the classifier: see test_child.py.
DRM_SKIPPED = (  # :3418-3427
    f"[youtube] {ID}: Some tv_samsung client https formats have been skipped as "
    "they are DRM protected. "
)
SABR_SKIPPED = (  # :3536-3549, for a client other than web
    f"[youtube] {ID}: Some tv_samsung client https formats have been skipped as "
    "they are missing a URL. YouTube may have enabled the SABR-only streaming "
    "experiment for the current session. See  "
    "https://github.com/yt-dlp/yt-dlp/issues/12482  for more details"
)
POT_SKIPPED = (  # :3195-3206, for a client not among the defaults
    f"[youtube] {ID}: mweb client https formats require a GVS PO Token which was "
    "not provided. They will be skipped as they may yield HTTP Error 403. You "
    'can manually pass a GVS PO Token for this client with --extractor-args "'
    'youtube:po_token=mweb.gvs+XXX". For more information, refer to  '
    "https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide"
)
NO_RUNTIME = (  # :2994-2999
    "[youtube] No supported JavaScript runtime could be found. Only deno is "
    "enabled by default; to use another runtime add  --js-runtimes "
    "RUNTIME[:PATH]  to your command/config. YouTube extraction without a JS "
    "runtime has been deprecated, and some formats may be missing. See  "
    "https://github.com/yt-dlp/yt-dlp/wiki/EJS  for details on installing one"
)


@pytest.mark.parametrize(
    "warning",
    [CHALLENGE, NO_RUNTIME, DRM_SKIPPED, SABR_SKIPPED, POT_SKIPPED],
    ids=["challenge", "no-runtime", "drm", "sabr", "po-token"],
)
def test_formats_withheld_make_a_format_error_ours_whatever_was_offered(
    warning: str,
) -> None:  # L15
    """Some formats skipped: what is left proves nothing about the rest."""
    assert classify(format_error(), [warning], video_only=True) is (
        FetchKind.EXTRACTOR_BROKEN
    )


# Formats as the YouTube extractor builds them (_video.py:3446-3486 for
# https, :3786-3803 for storyboards), cut to the fields that matter here.
def media(itag: str, **fields: Any) -> dict[str, Any]:
    return {
        "format_id": itag,
        "url": f"https://rr1---sn-qja5mc-54.googlevideo.com/videoplayback?itag={itag}",
        "protocol": "https",
        "has_drm": False,
        **fields,
    }


VIDEO = media("137", ext="mp4", vcodec="avc1.640028", acodec="none")
AUDIO = media("140", ext="m4a", vcodec="none", acodec="mp4a.40.2")
MUXED = media("18", ext="mp4", vcodec="avc1.42001E", acodec="mp4a.40.2")
HLS = media(
    "96", ext="mp4", vcodec="avc1.640028", acodec="mp4a.40.2", protocol="m3u8_native"
)
STORYBOARD = {
    "format_id": "sb0",
    "format_note": "storyboard",
    "ext": "mhtml",
    "protocol": "mhtml",
    "acodec": "none",
    "vcodec": "none",
    "url": f"https://i.ytimg.com/sb/{ID}/storyboard3_L0/default.jpg",
}


@pytest.mark.parametrize(
    ("formats", "only_video"),
    [
        ([VIDEO], True),
        ([VIDEO, STORYBOARD], True),
        ([{**VIDEO, "has_drm": "maybe"}], True),  # playable (YoutubeDL.py:2928)
        ([], False),
        (None, False),
        ([STORYBOARD], False),  # only images
        ([VIDEO, AUDIO], False),
        ([MUXED], False),  # audio our filter refuses: it wants audio alone
        ([VIDEO, HLS], False),  # audio our filter refuses: not one GET
        ([{**VIDEO, "url": None}], False),  # nothing playable
        ([{**VIDEO, "has_drm": True}], False),  # nothing playable
        ([VIDEO, {**AUDIO, "has_drm": True}], False),  # audio, locked
        ([{**VIDEO, "acodec": None}], False),  # audio unknown
        ([{**VIDEO, "vcodec": None, "acodec": None}], False),  # nothing known
        ([VIDEO, "not a format"], False),
    ],
    ids=[
        "video",
        "video-and-storyboard",
        "video-maybe-drm",
        "empty",
        "none",
        "storyboard",
        "video-and-audio",
        "muxed",
        "hls-with-audio",
        "no-url",
        "drm",
        "drm-audio",
        "audio-unknown",
        "codecs-unknown",
        "junk",
    ],
)
def test_only_real_video_and_nothing_with_audio_shows_a_video_has_no_audio(
    formats: Any, only_video: bool
) -> None:  # L11
    assert offers_only_video(formats) is only_video


# YouTube's extractor reports a player client whose request failed as a
# warning and tries the next. These are its words for three such failures.
THROTTLED = (
    f"[youtube] {ID}: Unable to download API page: HTTP Error 429: Too Many "
    "Requests (caused by <HTTPError 429: Too Many Requests>)"
)
FAILING = (
    f"[youtube] {ID}: Unable to download API page: HTTP Error 503: Service "
    "Unavailable (caused by <HTTPError 503: Service Unavailable>)"
)
DROPPED = (
    f"[youtube] {ID}: Unable to download API page: [Errno 104] Connection reset "
    "by peer (caused by TransportError('[Errno 104] Connection reset by peer'))"
)


@pytest.mark.parametrize(
    ("warning", "kind"),
    [
        (THROTTLED, FetchKind.RATE_LIMITED),  # L12
        (FAILING, FetchKind.NETWORK),  # L13
        (DROPPED, FetchKind.NETWORK),  # L13
    ],
    ids=["429", "503", "reset"],
)
def test_a_format_error_beside_a_failed_player_client_is_that_failure(
    warning: str, kind: FetchKind
) -> None:
    """Some clients throttled or failing, and another answering with every
    format skipped: yt-dlp says "Requested format is not available". Read as
    no audio, that would refuse every link, for good, for as long as YouTube
    throttles us or is down."""
    error = reported(raises(format_error()))

    assert classify(error, [warning]) is kind
    assert classify(error, [CHALLENGE, warning]) is kind  # challenges failed too
    assert classify(error, [warning], video_only=True) is kind  # first, still


def test_a_videos_own_words_beat_another_clients_failure() -> None:
    private = DownloadError(
        f"ERROR: [youtube] {ID}: Private video. If the owner of this video has "
        "granted you access, please sign in."
    )
    removed = DownloadError(f"ERROR: [youtube] {ID}: This video is unavailable")

    assert classify(private, [THROTTLED]) is FetchKind.PRIVATE
    assert classify(removed, [FAILING]) is FetchKind.UNAVAILABLE


def test_a_private_videos_sign_in_request_is_not_age_restriction() -> None:
    error = DownloadError(
        "ERROR: [youtube] x: Private video. If the owner of this video has granted "
        "you access, please sign in."
    )

    assert classify(error) is FetchKind.PRIVATE


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        ("Sign in to view this video.", FetchKind.AGE_RESTRICTED),  # L4
        ("Sign in to confirm you're not a bot.", FetchKind.RATE_LIMITED),  # L12
        ("Private video. Please sign in.", FetchKind.PRIVATE),  # L1
    ],
)
def test_a_sign_in_request_is_age_restriction_unless_it_says_more(
    message: str, kind: FetchKind
) -> None:  # L4: "age-restricted, or sign-in required"
    assert classify(DownloadError(f"ERROR: [youtube] {ID}: {message}")) is kind


def test_the_chain_follows_exc_info_cause_and_context() -> None:
    network = TransportError(cause=ConnectionResetError())
    error = reported(while_extracting(network))

    chain = list(exception_chain(error))

    assert chain[0] is error
    assert network in chain


# The chains yt-dlp really produces: a real YoutubeDL, with its urlopen
# replaced, so each request fails or answers as a test says, offline.

WATCH_URL = f"https://www.youtube.com/watch?v={ID}"
MEDIA = {  # a format as the child's checks pass it to process_info
    "id": ID,
    "title": "Elephants Dream",
    "extractor": "youtube",
    "extractor_key": "Youtube",
    "webpage_url": WATCH_URL,
    "format_id": "140",
    "ext": "m4a",
    "protocol": "https",
    "url": "https://rr1---sn-qja5mc-54.googlevideo.com/videoplayback?itag=140",
}

Failure = Callable[[str], Exception]


def status(code: int) -> Failure:
    return lambda url: http_error(code, "Reason")


def transport(cause: BaseException) -> Failure:
    return lambda url: TransportError(cause=cause)


class Offline:
    """Stands in for YoutubeDL.urlopen. A request whose path ends with `only`
    (any request, if None) fails with `failure`; any other is answered with
    an empty page, or empty JSON for YouTube's API."""

    def __init__(self, failure: Failure, only: str | None = None) -> None:
        self.failure = failure
        self.only = only

    def __call__(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        url = str(getattr(request, "url", request))
        path = urlsplit(url).path
        if self.only is None or path.endswith(self.only):
            raise self.failure(url)
        api = path.startswith("/youtubei/")
        return Response(
            fp=io.BytesIO(b"{}" if api else b"<html></html>"),
            url=url,
            headers={"Content-Type": "application/json" if api else "text/html"},
            status=200,
        )


class ShortRead:
    """Stands in for YoutubeDL.urlopen: the media answers with half of what
    its Content-Length promised."""

    def __call__(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        return Response(
            fp=io.BytesIO(b"\x00" * 1000),
            url=str(request.url),
            headers={"Content-Length": "2000"},
            status=200,
        )


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fails the test if anything gets past the replaced urlopen to a socket."""
    reached: list[object] = []

    def refuse(*args: Any, **kwargs: Any) -> None:
        reached.append(args)
        raise AssertionError("a test reached for the network")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    yield
    assert reached == []


@pytest.mark.usefixtures("offline")
@pytest.mark.parametrize(
    ("urlopen", "kind"),
    [
        (Offline(status(429)), FetchKind.RATE_LIMITED),  # L12
        (Offline(status(429), only="/player"), FetchKind.RATE_LIMITED),  # L12
        (Offline(status(503)), FetchKind.NETWORK),  # L13: raised with its cause
        (Offline(status(503), only="/player"), FetchKind.NETWORK),  # L13: a warning
        (Offline(status(500), only="/player"), FetchKind.NETWORK),  # L13
        (
            Offline(transport(ConnectionRefusedError(111, "Connection refused"))),
            FetchKind.NETWORK,
        ),  # L13
        (
            Offline(
                transport(ConnectionResetError(104, "Connection reset by peer")),
                only="/player",
            ),
            FetchKind.NETWORK,
        ),  # L13
        (
            Offline(
                transport(socket.gaierror(-2, "Name or service not known")),
                only="/player",
            ),
            FetchKind.NETWORK,
        ),  # L13
        (
            Offline(
                lambda url: SSLError(cause=ssl.SSLError(1, "bad record")),
                only="/player",
            ),
            FetchKind.NETWORK,
        ),  # L13
        (Offline(status(404), only="/player"), FetchKind.EXTRACTOR_BROKEN),  # L15
    ],
    ids=[
        "429",
        "429-player",
        "503",
        "503-player",
        "500-player",
        "refused",
        "reset-player",
        "dns-player",
        "tls-player",
        "404-player",
    ],
)
def test_a_lookup_that_fails_in_transit_classifies_as_its_cause(
    urlopen: Offline, kind: FetchKind
) -> None:
    """YouTube's extractor turns a failed player request into a warning and
    tries its next client; when none is left it raises "Failed to extract any
    player response", with no cause. Only the warnings still say why."""
    log = ChildLog(io.StringIO())

    with _new_ydl(ydl_options(deno="deno", logger=log)) as ydl:
        ydl.urlopen = urlopen
        with pytest.raises(DownloadError) as excinfo:
            lookup(ydl, WATCH_URL, log)

    assert classify(excinfo.value, log.warnings) is kind


@pytest.mark.usefixtures("offline")
@pytest.mark.parametrize(
    ("urlopen", "kind"),
    [
        (Offline(transport(ConnectionResetError())), FetchKind.NETWORK),  # D1
        (Offline(transport(TimeoutError("timed out"))), FetchKind.NETWORK),  # D1
        (Offline(status(503)), FetchKind.NETWORK),  # D1
        (ShortRead(), FetchKind.NETWORK),  # D1
        (Offline(status(403)), FetchKind.UNKNOWN),  # D10: not retried, not ours
    ],
    ids=["reset", "timeout", "503", "short-read", "403"],
)
def test_a_download_that_fails_in_transit_classifies_as_its_cause(
    tmp_path: Path, urlopen: Offline | ShortRead, kind: FetchKind
) -> None:
    """yt-dlp's HTTP downloader retries a 5xx, a dropped connection or a short
    read, then gives up with text alone: "[download] Got error: ...", with no
    exception behind it to look at."""
    log = ChildLog(io.StringIO())
    options = ydl_options(deno="deno", logger=log, work_dir=tmp_path, max_bytes=10**8)

    with _new_ydl(options) as ydl:
        ydl.urlopen = urlopen
        with pytest.raises(DownloadError) as excinfo:
            ydl.process_info(dict(MEDIA))  # as download() calls it

    assert classify(excinfo.value, log.warnings) is kind


# What verbose brings to stderr. The parent logs the last 2 KB of it with an
# ERROR line: the extractor's notices that YouTube withheld formats must be
# there, and nothing verbose adds may push them out.

POT_DEBUG = (  # _video.py:3195-3204: a default client's, so a debug line
    f"{ID}: tv_samsung client https formats require a GVS PO Token which was "
    "not provided."
)
SABR_DEBUG = (  # _video.py:3536-3543: web's, so a debug line
    f"{ID}: Some web client https formats have been skipped as they are missing "
    "a URL. YouTube is forcing SABR streaming for this client. See  "
    "https://github.com/yt-dlp/yt-dlp/issues/12482  for more details"
)


def test_youtubes_notices_of_skipped_formats_reach_stderr_once() -> None:
    """For the default clients (_video.py:143), the extractor says it skipped
    formats only in debug lines, which YoutubeDL writes only when verbose
    (YoutubeDL.py:1164-1172), and through a logger once per format: it drops
    `only_once` there."""
    stderr = io.StringIO()

    with _new_ydl(ydl_options(deno="deno", logger=ChildLog(stderr))) as ydl:
        youtube: Any = ydl.get_info_extractor("Youtube")
        for _ in range(20):  # one call per format, as _extract_formats makes
            youtube._report_pot_format_skipped(ID, "tv_samsung", "https")
            youtube.write_debug(SABR_DEBUG, only_once=True)

    written = stderr.getvalue().splitlines()
    assert len(written) == 2, written
    assert POT_DEBUG in written[0]
    assert written[1] == f"[debug] [youtube] {SABR_DEBUG}"


def lookup_stderr(*, verbose: bool) -> str:
    """A lookup whose player requests all fail, offline: yt-dlp's whole say,
    an ERROR at the end of it, after one of the extractor's notices."""
    stderr = io.StringIO()
    log = ChildLog(stderr)
    options = ydl_options(deno="deno", logger=log) | {"verbose": verbose}
    with _new_ydl(options) as ydl:
        ydl.urlopen = Offline(status(404), only="/player")
        ydl.get_info_extractor("Youtube").write_debug(SABR_DEBUG)
        with pytest.raises(DownloadError):
            lookup(ydl, WATCH_URL, log)
    return stderr.getvalue()


@pytest.mark.usefixtures("offline")
def test_verbose_adds_only_the_notices_to_stderr() -> None:
    """Not its other debug lines, and not the traceback it writes after an
    ERROR line (YoutubeDL.py:1085-1095): those would push the notices out of
    the tail. So the tail holds what it held before, and the notices."""
    verbose, plain = lookup_stderr(verbose=True), lookup_stderr(verbose=False)

    notice = f"[debug] [youtube] {SABR_DEBUG}\n"
    assert "ERROR: [youtube]" in plain
    assert notice not in plain
    assert verbose == notice + plain
