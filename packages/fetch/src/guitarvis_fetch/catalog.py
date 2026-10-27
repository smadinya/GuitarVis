"""The failure catalog: what each way of failing to fetch a link means.

Spec 012's *Failure catalog*, as data. Every reason, HTTP status, message,
log level and retry rule a link failure produces comes from here, keyed by
kind, so the api, the worker and the tests cannot drift apart. The reason
says what to do, the message says why, and the kind, logged, says what broke
(D9). yt-dlp's own words never reach a message: they go to the log only.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum

from guitarvis_core.audio import MAX_DURATION_SEC
from guitarvis_core.contracts import FailureReason

from guitarvis_fetch.links import RefusalKind

# guitarvis_jobs.models.INTERNAL_FAILURE_MESSAGE, which this package does not
# depend on; test_catalog.py keeps the two the same.
INTERNAL_MESSAGE = "Something went wrong on our side. Try again later."

# The request (R1 to R3), and the worker's switch (W1).
LINKS_OFF_MESSAGE = (
    "Links are turned off on this server. Upload the audio file instead."
)
BAD_REQUEST_MESSAGE = "Send the link as JSON, in a field named `url`."
REQUEST_TOO_LARGE_MESSAGE = "That request is too large. Send only the link."
LINKS_OFF_IN_QUEUE_MESSAGE = (
    "Links were turned off before this song could be fetched. "
    "Upload the audio file instead."
)

REFUSALS: dict[RefusalKind, str] = {
    RefusalKind.NOT_A_LINK: (
        "That doesn't look like a link. Copy the video's address from your "
        "browser and paste it here."
    ),
    RefusalKind.BAD_SCHEME: (
        "Only web links (https://…) can be used. Copy the video's address "
        "from your browser."
    ),
    RefusalKind.UNSUPPORTED_SITE: (
        "We can only fetch songs from YouTube for now. For anything else, "
        "upload the audio file."
    ),
    RefusalKind.NOT_A_VIDEO: (
        "That link isn't to a single video. Open the video itself and copy its address."
    ),
}


class FetchKind(StrEnum):
    """What went wrong, finer than the reason. Logged, never shown."""

    PRIVATE = "private"
    UNAVAILABLE = "unavailable"
    GEO_RESTRICTED = "geo_restricted"
    AGE_RESTRICTED = "age_restricted"
    MEMBERS_ONLY = "members_only"
    LIVE = "live"
    UPCOMING = "upcoming"
    POST_LIVE = "post_live"
    NO_DURATION = "no_duration"
    TOO_LONG = "too_long"
    NO_AUDIO = "no_audio"
    RATE_LIMITED = "rate_limited"
    NETWORK = "network"
    LOOKUP_TIMEOUT = "lookup_timeout"
    EXTRACTOR_BROKEN = "extractor_broken"
    MISCONFIGURED = "misconfigured"
    UNKNOWN = "unknown"
    CRASHED = "crashed"
    DOWNLOAD_TIMEOUT = "download_timeout"
    MEDIA_REFUSED = "media_refused"
    TOO_LARGE = "too_large"
    EMPTY_DOWNLOAD = "empty_download"
    LOCAL_IO = "local_io"
    UNREADABLE = "unreadable"
    BUSY = "busy"


class Retry(StrEnum):
    """The catalog's Retry column."""

    NO = "no"  # the same link fails the same way
    LATER = "later"  # it may work later, but nothing retries it for the user
    RQ = "rq"  # the worker's attempt is retried automatically


@dataclass(frozen=True)
class Entry:
    """One catalog row. `status` is the api's answer for a lookup; a worker
    failure is recorded on the row instead. `tail` adds the end of the
    child's stderr to the log line."""

    reason: FailureReason
    status: int
    message: str
    level: int
    retry: Retry
    tail: bool = False

    @property
    def retryable(self) -> bool:
        return self.retry is Retry.RQ


_UNREACHABLE = (
    "We couldn't reach YouTube. Try again in a few minutes, or upload the audio file."
)
_BROKEN = (
    "We can't fetch from YouTube at the moment. Upload the audio file instead, "
    "or try the link again tomorrow."
)
_UNRECOGNISED = (
    "We couldn't fetch that video. Try again in a few minutes, or upload the "
    "audio file."
)
_NO_AUDIO = (
    "That video has no audio we can use. Try a different link, or upload the "
    "audio file."
)
_LIMITED = (
    "YouTube is limiting how often we can fetch right now. Try again later, or "
    "upload the audio file."
)

_UNUSABLE = FailureReason.LINK_UNUSABLE
_FAILED = FailureReason.FETCH_FAILED
_INFO, _WARNING, _ERROR = logging.INFO, logging.WARNING, logging.ERROR

CATALOG: dict[FetchKind, Entry] = {
    FetchKind.PRIVATE: Entry(  # L1
        _UNUSABLE,
        422,
        "That video is private. Try a different link, or upload the audio file.",
        _INFO,
        Retry.NO,
    ),
    FetchKind.UNAVAILABLE: Entry(  # L2
        _UNUSABLE,
        422,
        "That video isn't available. It may have been removed. Check the link, "
        "or upload the audio file.",
        _INFO,
        Retry.NO,
    ),
    FetchKind.GEO_RESTRICTED: Entry(  # L3
        _UNUSABLE,
        422,
        "That video can't be watched from where our server is. Try a different "
        "link, or upload the audio file.",
        _INFO,
        Retry.NO,
    ),
    FetchKind.AGE_RESTRICTED: Entry(  # L4
        _UNUSABLE,
        422,
        "That video is age-restricted, and we don't sign in to YouTube. Upload "
        "the audio file instead.",
        _INFO,
        Retry.NO,
    ),
    FetchKind.MEMBERS_ONLY: Entry(  # L5
        _UNUSABLE,
        422,
        "That video is only for channel members or paying viewers. Upload the "
        "audio file instead.",
        _INFO,
        Retry.NO,
    ),
    FetchKind.LIVE: Entry(  # L6
        _UNUSABLE,
        422,
        "That's a live stream. Once it has ended and been saved as a video, try "
        "the link again.",
        _INFO,
        Retry.LATER,
    ),
    FetchKind.UPCOMING: Entry(  # L7
        _UNUSABLE,
        422,
        "That video hasn't premiered yet. Try the link again once it has.",
        _INFO,
        Retry.LATER,
    ),
    FetchKind.POST_LIVE: Entry(  # L8
        _UNUSABLE,
        422,
        "That stream has only just ended, and YouTube is still processing it. "
        "Try the link again in a few hours.",
        _INFO,
        Retry.LATER,
    ),
    FetchKind.NO_DURATION: Entry(  # L9
        _UNUSABLE,
        422,
        "We couldn't tell how long that video is, so we didn't fetch it. Upload "
        "the audio file instead.",
        _WARNING,
        Retry.NO,
    ),
    FetchKind.TOO_LONG: Entry(  # L10; the message is message_for's
        FailureReason.TOO_LONG,
        422,
        "That video is {length} long. The limit is {limit} minutes: try a link "
        "to a single song.",
        _INFO,
        Retry.NO,
    ),
    FetchKind.NO_AUDIO: Entry(_UNUSABLE, 422, _NO_AUDIO, _WARNING, Retry.NO),  # L11
    FetchKind.RATE_LIMITED: Entry(
        _FAILED, 503, _LIMITED, _WARNING, Retry.LATER
    ),  # L12, D3
    FetchKind.NETWORK: Entry(_FAILED, 502, _UNREACHABLE, _WARNING, Retry.RQ),  # L13, D1
    FetchKind.LOOKUP_TIMEOUT: Entry(  # L14
        _FAILED,
        504,
        "YouTube took too long to answer. Try again in a few minutes, or upload "
        "the audio file.",
        _WARNING,
        Retry.LATER,
    ),
    FetchKind.EXTRACTOR_BROKEN: Entry(  # L15, D4
        _FAILED, 502, _BROKEN, _ERROR, Retry.LATER, tail=True
    ),
    FetchKind.MISCONFIGURED: Entry(
        _FAILED, 503, _BROKEN, _ERROR, Retry.LATER
    ),  # L16, D4
    FetchKind.UNKNOWN: Entry(  # L17, D10
        _FAILED, 502, _UNRECOGNISED, _ERROR, Retry.RQ, tail=True
    ),
    FetchKind.CRASHED: Entry(  # L18, D9
        FailureReason.INTERNAL, 500, INTERNAL_MESSAGE, _ERROR, Retry.RQ, tail=True
    ),
    FetchKind.DOWNLOAD_TIMEOUT: Entry(  # D2
        _FAILED,
        504,
        "Fetching that video took too long. Try again in a few minutes, or "
        "upload the audio file.",
        _WARNING,
        Retry.RQ,
    ),
    FetchKind.MEDIA_REFUSED: Entry(_FAILED, 502, _UNRECOGNISED, _ERROR, Retry.NO),  # D5
    FetchKind.TOO_LARGE: Entry(  # D6
        _UNUSABLE,
        422,
        "That video's audio is larger than we accept. Try a shorter video, or "
        "upload the audio file.",
        _WARNING,
        Retry.NO,
    ),
    FetchKind.EMPTY_DOWNLOAD: Entry(
        _UNUSABLE, 422, _NO_AUDIO, _WARNING, Retry.NO
    ),  # D7
    FetchKind.LOCAL_IO: Entry(  # D8
        FailureReason.INTERNAL, 500, INTERNAL_MESSAGE, _ERROR, Retry.RQ, tail=True
    ),
    FetchKind.UNREADABLE: Entry(  # P1
        _UNUSABLE,
        422,
        "The audio we fetched from that video couldn't be read. Try a different "
        "link, or upload the audio file.",
        _WARNING,
        Retry.NO,
    ),
    FetchKind.BUSY: Entry(  # Q3
        _FAILED,
        503,
        "We're checking a lot of links right now. Try again in a minute.",
        _WARNING,
        Retry.LATER,
    ),
}


def message_for(kind: FetchKind, *, duration_sec: float | None = None) -> str:
    """The user's message for `kind`. Only too_long has blanks to fill."""
    template = CATALOG[kind].message
    if kind is not FetchKind.TOO_LONG:
        return template
    length = "over" if duration_sec is None else clock(duration_sec)
    return template.format(length=length, limit=f"{MAX_DURATION_SEC / 60:.0f}")


def clock(seconds: float) -> str:
    """`12:01`, or `1:02:03` past an hour."""
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
