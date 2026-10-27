"""The catalog is spec 012's table, kept as data: every kind has an entry, and
no message carries yt-dlp's words."""

import logging

import pytest
from guitarvis_core.contracts import FailureReason
from guitarvis_fetch.catalog import (
    BAD_REQUEST_MESSAGE,
    CATALOG,
    INTERNAL_MESSAGE,
    LINKS_OFF_IN_QUEUE_MESSAGE,
    LINKS_OFF_MESSAGE,
    REFUSALS,
    REQUEST_TOO_LARGE_MESSAGE,
    FetchKind,
    Retry,
    clock,
    message_for,
)
from guitarvis_fetch.links import RefusalKind
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE

UNUSABLE = FailureReason.LINK_UNUSABLE
FAILED = FailureReason.FETCH_FAILED
INFO, WARNING, ERROR = logging.INFO, logging.WARNING, logging.ERROR

# Messages the spec gives as "as L15", "as L17", "as L11" or MSG_INTERNAL, so
# several rows can say they are the same words.
BROKEN = (
    "We can't fetch from YouTube at the moment. Upload the audio file instead, "
    "or try the link again tomorrow."
)
UNRECOGNISED = (
    "We couldn't fetch that video. Try again in a few minutes, or upload the "
    "audio file."
)
NO_AUDIO = (
    "That video has no audio we can use. Try a different link, or upload the "
    "audio file."
)
INTERNAL = "Something went wrong on our side. Try again later."


def every_message() -> list[str]:
    return [
        *(message_for(kind, duration_sec=721) for kind in FetchKind),
        *REFUSALS.values(),
        LINKS_OFF_MESSAGE,
        LINKS_OFF_IN_QUEUE_MESSAGE,
        BAD_REQUEST_MESSAGE,
        REQUEST_TOO_LARGE_MESSAGE,
    ]


def test_every_fetch_kind_has_an_entry() -> None:
    assert set(CATALOG) == set(FetchKind)


def test_every_refusal_kind_has_a_message() -> None:
    assert set(REFUSALS) == set(RefusalKind)


@pytest.mark.parametrize("message", every_message())
def test_no_message_carries_ytdlp_text(message: str) -> None:
    lowered = message.lower()
    for forbidden in ("yt-dlp", "youtube-dl", "error:", "traceback", "[youtube]"):
        assert forbidden not in lowered, f"{forbidden!r} in {message!r}"


@pytest.mark.parametrize(
    ("row", "kind", "reason", "status", "message", "level", "retry", "tail"),
    [
        (
            "L1",
            FetchKind.PRIVATE,
            UNUSABLE,
            422,
            "That video is private. Try a different link, or upload the audio file.",
            INFO,
            Retry.NO,
            False,
        ),
        (
            "L2",
            FetchKind.UNAVAILABLE,
            UNUSABLE,
            422,
            "That video isn't available. It may have been removed. Check the link, "
            "or upload the audio file.",
            INFO,
            Retry.NO,
            False,
        ),
        (
            "L3",
            FetchKind.GEO_RESTRICTED,
            UNUSABLE,
            422,
            "That video can't be watched from where our server is. Try a different "
            "link, or upload the audio file.",
            INFO,
            Retry.NO,
            False,
        ),
        (
            "L4",
            FetchKind.AGE_RESTRICTED,
            UNUSABLE,
            422,
            "That video is age-restricted, and we don't sign in to YouTube. Upload "
            "the audio file instead.",
            INFO,
            Retry.NO,
            False,
        ),
        (
            "L5",
            FetchKind.MEMBERS_ONLY,
            UNUSABLE,
            422,
            "That video is only for channel members or paying viewers. Upload the "
            "audio file instead.",
            INFO,
            Retry.NO,
            False,
        ),
        (
            "L6",
            FetchKind.LIVE,
            UNUSABLE,
            422,
            "That's a live stream. Once it has ended and been saved as a video, try "
            "the link again.",
            INFO,
            Retry.LATER,
            False,
        ),
        (
            "L7",
            FetchKind.UPCOMING,
            UNUSABLE,
            422,
            "That video hasn't premiered yet. Try the link again once it has.",
            INFO,
            Retry.LATER,
            False,
        ),
        (
            "L8",
            FetchKind.POST_LIVE,
            UNUSABLE,
            422,
            "That stream has only just ended, and YouTube is still processing it. "
            "Try the link again in a few hours.",
            INFO,
            Retry.LATER,
            False,
        ),
        (
            "L9",
            FetchKind.NO_DURATION,
            UNUSABLE,
            422,
            "We couldn't tell how long that video is, so we didn't fetch it. Upload "
            "the audio file instead.",
            WARNING,
            Retry.NO,
            False,
        ),
        (
            "L10",
            FetchKind.TOO_LONG,
            FailureReason.TOO_LONG,
            422,
            "That video is 12:01 long. The limit is 10 minutes: try a link to a "
            "single song.",
            INFO,
            Retry.NO,
            False,
        ),
        ("L11", FetchKind.NO_AUDIO, UNUSABLE, 422, NO_AUDIO, WARNING, Retry.NO, False),
        (
            "L12",
            FetchKind.RATE_LIMITED,
            FAILED,
            503,
            "YouTube is limiting how often we can fetch right now. Try again later, "
            "or upload the audio file.",
            WARNING,
            Retry.LATER,
            False,
        ),
        (
            "L13/D1",
            FetchKind.NETWORK,
            FAILED,
            502,
            "We couldn't reach YouTube. Try again in a few minutes, or upload the "
            "audio file.",
            WARNING,
            Retry.RQ,
            False,
        ),
        (
            "L14",
            FetchKind.LOOKUP_TIMEOUT,
            FAILED,
            504,
            "YouTube took too long to answer. Try again in a few minutes, or upload "
            "the audio file.",
            WARNING,
            Retry.LATER,
            False,
        ),
        (
            "L15",
            FetchKind.EXTRACTOR_BROKEN,
            FAILED,
            502,
            BROKEN,
            ERROR,
            Retry.LATER,
            True,
        ),
        (
            "L16",
            FetchKind.MISCONFIGURED,
            FAILED,
            503,
            BROKEN,
            ERROR,
            Retry.LATER,
            False,
        ),
        (
            "L17/D10",
            FetchKind.UNKNOWN,
            FAILED,
            502,
            UNRECOGNISED,
            ERROR,
            Retry.RQ,
            True,
        ),
        (
            "L18/D9",
            FetchKind.CRASHED,
            FailureReason.INTERNAL,
            500,
            INTERNAL,
            ERROR,
            Retry.RQ,
            True,
        ),
        (
            "D2",
            FetchKind.DOWNLOAD_TIMEOUT,
            FAILED,
            504,
            "Fetching that video took too long. Try again in a few minutes, or "
            "upload the audio file.",
            WARNING,
            Retry.RQ,
            False,
        ),
        (
            "D5",
            FetchKind.MEDIA_REFUSED,
            FAILED,
            502,
            UNRECOGNISED,
            ERROR,
            Retry.NO,
            False,
        ),
        (
            "D6",
            FetchKind.TOO_LARGE,
            UNUSABLE,
            422,
            "That video's audio is larger than we accept. Try a shorter video, or "
            "upload the audio file.",
            WARNING,
            Retry.NO,
            False,
        ),
        (
            "D7",
            FetchKind.EMPTY_DOWNLOAD,
            UNUSABLE,
            422,
            NO_AUDIO,
            WARNING,
            Retry.NO,
            False,
        ),
        (
            "D8",
            FetchKind.LOCAL_IO,
            FailureReason.INTERNAL,
            500,
            INTERNAL,
            ERROR,
            Retry.RQ,
            True,
        ),
        (
            "P1",
            FetchKind.UNREADABLE,
            UNUSABLE,
            422,
            "The audio we fetched from that video couldn't be read. Try a different "
            "link, or upload the audio file.",
            WARNING,
            Retry.NO,
            False,
        ),
        (
            "Q3",
            FetchKind.BUSY,
            FAILED,
            503,
            "We're checking a lot of links right now. Try again in a minute.",
            WARNING,
            Retry.LATER,
            False,
        ),
    ],
)
def test_each_kind_is_its_catalog_row(
    row: str,
    kind: FetchKind,
    reason: FailureReason,
    status: int,
    message: str,
    level: int,
    retry: Retry,
    tail: bool,
) -> None:
    entry = CATALOG[kind]

    assert (
        entry.reason,
        entry.status,
        message_for(kind, duration_sec=721),
        entry.level,
        entry.retry,
        entry.tail,
    ) == (reason, status, message, level, retry, tail), row


def test_requests_and_refusals_say_what_the_spec_says() -> None:
    assert LINKS_OFF_MESSAGE == (  # R1
        "Links are turned off on this server. Upload the audio file instead."
    )
    assert BAD_REQUEST_MESSAGE == (  # R2
        "Send the link as JSON, in a field named `url`."
    )
    assert REQUEST_TOO_LARGE_MESSAGE == (  # R3
        "That request is too large. Send only the link."
    )
    assert REFUSALS == {
        RefusalKind.NOT_A_LINK: (  # R4
            "That doesn't look like a link. Copy the video's address from your "
            "browser and paste it here."
        ),
        RefusalKind.BAD_SCHEME: (  # R5
            "Only web links (https://…) can be used. Copy the video's address "
            "from your browser."
        ),
        RefusalKind.UNSUPPORTED_SITE: (  # R6
            "We can only fetch songs from YouTube for now. For anything else, "
            "upload the audio file."
        ),
        RefusalKind.NOT_A_VIDEO: (  # R7
            "That link isn't to a single video. Open the video itself and copy "
            "its address."
        ),
    }
    assert LINKS_OFF_IN_QUEUE_MESSAGE == (  # W1
        "Links were turned off before this song could be fetched. "
        "Upload the audio file instead."
    )


def test_only_upstream_trouble_and_our_own_failures_are_retried_by_rq() -> None:
    retried = {kind for kind, entry in CATALOG.items() if entry.retryable}

    assert retried == {
        FetchKind.NETWORK,
        FetchKind.DOWNLOAD_TIMEOUT,
        FetchKind.UNKNOWN,
        FetchKind.CRASHED,
        FetchKind.LOCAL_IO,
    }


def test_messages_shared_between_rows_are_the_same_words() -> None:
    assert (
        CATALOG[FetchKind.MISCONFIGURED].message
        == CATALOG[FetchKind.EXTRACTOR_BROKEN].message
    )  # L16 as L15
    assert (
        CATALOG[FetchKind.MEDIA_REFUSED].message == CATALOG[FetchKind.UNKNOWN].message
    )  # D5 as L17
    assert (
        CATALOG[FetchKind.EMPTY_DOWNLOAD].message == CATALOG[FetchKind.NO_AUDIO].message
    )  # D7 as L11


def test_internal_kinds_say_what_every_internal_failure_says() -> None:
    assert INTERNAL_MESSAGE == INTERNAL_FAILURE_MESSAGE
    for kind in (FetchKind.CRASHED, FetchKind.LOCAL_IO):
        assert message_for(kind) == INTERNAL_FAILURE_MESSAGE


def test_too_long_names_the_videos_length_and_the_limit() -> None:
    assert message_for(FetchKind.TOO_LONG, duration_sec=721) == (
        "That video is 12:01 long. The limit is 10 minutes: try a link to a "
        "single song."
    )
    assert "3:00:00 long" in message_for(FetchKind.TOO_LONG, duration_sec=10800)


@pytest.mark.parametrize(
    ("seconds", "shown"),
    [(0, "0:00"), (59.9, "0:59"), (601, "10:01"), (3723, "1:02:03")],
)
def test_clock(seconds: float, shown: str) -> None:
    assert clock(seconds) == shown
