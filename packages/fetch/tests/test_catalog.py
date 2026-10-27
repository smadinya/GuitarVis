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
    ("row", "kind", "reason", "status", "level", "retry", "tail"),
    [
        ("L1", FetchKind.PRIVATE, UNUSABLE, 422, INFO, Retry.NO, False),
        ("L2", FetchKind.UNAVAILABLE, UNUSABLE, 422, INFO, Retry.NO, False),
        ("L3", FetchKind.GEO_RESTRICTED, UNUSABLE, 422, INFO, Retry.NO, False),
        ("L4", FetchKind.AGE_RESTRICTED, UNUSABLE, 422, INFO, Retry.NO, False),
        ("L5", FetchKind.MEMBERS_ONLY, UNUSABLE, 422, INFO, Retry.NO, False),
        ("L6", FetchKind.LIVE, UNUSABLE, 422, INFO, Retry.LATER, False),
        ("L7", FetchKind.UPCOMING, UNUSABLE, 422, INFO, Retry.LATER, False),
        ("L8", FetchKind.POST_LIVE, UNUSABLE, 422, INFO, Retry.LATER, False),
        ("L9", FetchKind.NO_DURATION, UNUSABLE, 422, WARNING, Retry.NO, False),
        ("L10", FetchKind.TOO_LONG, FailureReason.TOO_LONG, 422, INFO, Retry.NO, False),
        ("L11", FetchKind.NO_AUDIO, UNUSABLE, 422, WARNING, Retry.NO, False),
        ("L12", FetchKind.RATE_LIMITED, FAILED, 503, WARNING, Retry.LATER, False),
        ("L13", FetchKind.NETWORK, FAILED, 502, WARNING, Retry.RQ, False),
        ("L14", FetchKind.LOOKUP_TIMEOUT, FAILED, 504, WARNING, Retry.LATER, False),
        ("L15", FetchKind.EXTRACTOR_BROKEN, FAILED, 502, ERROR, Retry.LATER, True),
        ("L16", FetchKind.MISCONFIGURED, FAILED, 503, ERROR, Retry.LATER, False),
        ("L17", FetchKind.UNKNOWN, FAILED, 502, ERROR, Retry.RQ, True),
        ("L18", FetchKind.CRASHED, FailureReason.INTERNAL, 500, ERROR, Retry.RQ, True),
        ("D2", FetchKind.DOWNLOAD_TIMEOUT, FAILED, 504, WARNING, Retry.RQ, False),
        ("D5", FetchKind.MEDIA_REFUSED, FAILED, 502, ERROR, Retry.NO, False),
        ("D6", FetchKind.TOO_LARGE, UNUSABLE, 422, WARNING, Retry.NO, False),
        ("D7", FetchKind.EMPTY_DOWNLOAD, UNUSABLE, 422, WARNING, Retry.NO, False),
        ("D8", FetchKind.LOCAL_IO, FailureReason.INTERNAL, 500, ERROR, Retry.RQ, True),
        ("P1", FetchKind.UNREADABLE, UNUSABLE, 422, WARNING, Retry.NO, False),
        ("Q3", FetchKind.BUSY, FAILED, 503, WARNING, Retry.LATER, False),
    ],
)
def test_each_kind_is_its_catalog_row(
    row: str,
    kind: FetchKind,
    reason: FailureReason,
    status: int,
    level: int,
    retry: Retry,
    tail: bool,
) -> None:
    entry = CATALOG[kind]

    assert (entry.reason, entry.status, entry.level, entry.retry, entry.tail) == (
        reason,
        status,
        level,
        retry,
        tail,
    ), row


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
