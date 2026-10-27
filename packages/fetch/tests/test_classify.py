"""The child's classifier: yt-dlp's exception types, built offline, and the
messages yt-dlp gives for real failures (fixtures/youtube-messages.json, each
with where it came from). `make smoke-url` prints fresh ones to compare."""

import errno
import io
import json
import socket
import ssl
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from guitarvis_fetch.catalog import FetchKind
from guitarvis_fetch.child import classify, exception_chain
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

    assert classify(error, fixture.get("warnings", [])) is FetchKind(fixture["kind"])


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


def test_a_format_error_is_no_audio_unless_challenges_failed() -> None:  # L11, L15
    error = reported(
        raises(
            ExtractorError(
                "Requested format is not available. Use --list-formats for a "
                "list of available formats",
                expected=True,
                video_id=ID,
                ie="youtube",
            )
        )
    )

    assert classify(error) is FetchKind.NO_AUDIO
    assert classify(error, [CHALLENGE]) is FetchKind.EXTRACTOR_BROKEN


def test_a_private_videos_sign_in_request_is_not_age_restriction() -> None:
    error = DownloadError(
        "ERROR: [youtube] x: Private video. If the owner of this video has granted "
        "you access, please sign in."
    )

    assert classify(error) is FetchKind.PRIVATE


def test_the_chain_follows_exc_info_cause_and_context() -> None:
    network = TransportError(cause=ConnectionResetError())
    error = reported(while_extracting(network))

    chain = list(exception_chain(error))

    assert chain[0] is error
    assert network in chain
