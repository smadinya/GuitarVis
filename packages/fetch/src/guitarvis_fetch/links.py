"""Links: parse, refuse, canonicalize. Pure, and standard library only.

The user's string never reaches the network. A link is accepted only when a
site's parser reads one video id out of it, and what goes on is a URL built
fresh from that id: no YouTube id can spell a private address. Supported
sites are code, not config, because each needs a parser (spec 012, D6).
Adding one is a new Site here, with its own spec.
"""

import hashlib
import ipaddress
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import SplitResult, parse_qs, urlsplit

MAX_LINK_CHARS = 2048

_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_YOUTUBE_ID = re.compile(r"[A-Za-z0-9_-]{11}")
# Paths yt-dlp reads as something other than a video, though each is an id's
# eleven characters: /embed/videoseries?list=… is a playlist, and
# /embed/live_stream?channel=… a channel's live stream.
_NOT_IDS = frozenset({"videoseries", "live_stream"})


class RefusalKind(StrEnum):
    """Why a string is not a link we can use: rows R4 to R7."""

    NOT_A_LINK = "not_a_link"
    BAD_SCHEME = "bad_scheme"
    UNSUPPORTED_SITE = "unsupported_site"
    NOT_A_VIDEO = "not_a_video"


class LinkRefused(ValueError):
    """`parse` refused the string. `host` and `segment` are what may be
    logged of it: never the whole string, which can carry a share id."""

    def __init__(self, kind: RefusalKind, *, host: str = "", segment: str = "") -> None:
        super().__init__(kind.value)
        self.kind = kind
        self.host = host
        self.segment = segment


@dataclass(frozen=True)
class Link:
    """One video on one supported site."""

    site: str
    video_id: str
    canonical_url: str

    @property
    def dedupe_key(self) -> str:
        """What a link job's `content_hash` holds: the video's identity, so a
        repeat in any form finds the same job without asking the site."""
        return hashlib.sha256(f"{self.site}:{self.video_id}".encode()).hexdigest()


@dataclass(frozen=True)
class Site:
    name: str
    hosts: frozenset[str]
    video_id: Callable[[str, SplitResult], str | None]
    canonical_url: Callable[[str], str]


def _youtube_id(host: str, parts: SplitResult) -> str | None:
    """The one video a YouTube URL names, or None when it names anything else."""
    segments = [segment for segment in parts.path.split("/") if segment]
    if host == "youtu.be":
        candidate = segments[0] if len(segments) == 1 else None
    elif segments == ["watch"]:
        values = parse_qs(parts.query).get("v", [])
        candidate = values[0] if len(values) == 1 else None
    elif len(segments) == 2 and segments[0] in ("shorts", "live", "embed", "v"):
        candidate = None if segments[1] in _NOT_IDS else segments[1]
    else:
        candidate = None
    if candidate is None or not _YOUTUBE_ID.fullmatch(candidate):
        return None
    return candidate


YOUTUBE = Site(
    name="youtube",
    hosts=frozenset(
        {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtube-nocookie.com",
            "www.youtube-nocookie.com",
            "youtu.be",
        }
    ),
    video_id=_youtube_id,
    canonical_url=lambda video_id: f"https://www.youtube.com/watch?v={video_id}",
)

SITES = (YOUTUBE,)


def parse(raw: str) -> Link:
    """The link in `raw`, or LinkRefused. No I/O.

    The canonical URL is built from the id alone, so every other parameter —
    `t=`, `list=` and the `si=` share id — is dropped, never edited out.
    """
    text = raw.strip()
    if not text or len(text) > MAX_LINK_CHARS or "\\" in text:
        raise LinkRefused(RefusalKind.NOT_A_LINK)
    if any(_is_space_or_control(character) for character in text):
        raise LinkRefused(RefusalKind.NOT_A_LINK)

    try:
        parts = urlsplit(_with_scheme(text))
    except ValueError:  # an unbalanced [ in the host, say
        raise LinkRefused(RefusalKind.NOT_A_LINK) from None
    if parts.scheme not in ("http", "https"):
        if parts.netloc:  # ftp://host/…, ws://host/…: a host and a path
            raise _refused(RefusalKind.BAD_SCHEME, parts)
        # No host: what follows the scheme (javascript:, mailto:, data:,
        # file:///) is code, an address, data or a local path. Its kind alone.
        raise LinkRefused(RefusalKind.BAD_SCHEME)
    host = _host_of(parts)
    site = next((site for site in SITES if host in site.hosts), None)
    if site is None:
        raise _refused(RefusalKind.UNSUPPORTED_SITE, parts, host)
    video_id = site.video_id(host, parts)
    if video_id is None:
        raise _refused(RefusalKind.NOT_A_VIDEO, parts, host)
    return Link(
        site=site.name, video_id=video_id, canonical_url=site.canonical_url(video_id)
    )


def _is_space_or_control(character: str) -> bool:
    # Category C is control, format (zero-width and direction marks among
    # them), private use, surrogate and unassigned.
    return character.isspace() or unicodedata.category(character).startswith("C")


def _with_scheme(text: str) -> str:
    """`text` with https:// added when it has no scheme.

    `javascript:` and `mailto:` have no slashes, but they are schemes; a
    host and port (`youtube.com:443`) look like one but have a dot.
    """
    if text.startswith("//"):
        return "https:" + text
    scheme = _SCHEME.match(text)
    if scheme is None:
        return "https://" + text
    if text[scheme.end() :].startswith("//") or "." not in scheme.group():
        return text
    return "https://" + text


def _host_of(parts: SplitResult) -> str:
    """The host, lowercased and without a trailing dot; LinkRefused when the
    authority is anything but a plain host name."""
    try:
        port = parts.port
    except ValueError:  # not a number, or out of range
        raise _refused(RefusalKind.UNSUPPORTED_SITE, parts) from None
    host = parts.hostname or ""
    if not host:
        raise _refused(RefusalKind.NOT_A_LINK, parts)
    if "@" in parts.netloc or port is not None or not host.isascii():
        raise _refused(RefusalKind.UNSUPPORTED_SITE, parts)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host.removesuffix(".")
    raise _refused(RefusalKind.UNSUPPORTED_SITE, parts)


def _refused(
    kind: RefusalKind, parts: SplitResult, host: str | None = None
) -> LinkRefused:
    """A link with a host, refused once parsed, with what the log may keep
    of it: the host (never the user info or port) and the first path segment
    (never the query or fragment, where a share id rides)."""
    return LinkRefused(
        kind,
        host=(parts.hostname or "") if host is None else host,
        segment=_first_segment(parts),
    )


def _first_segment(parts: SplitResult) -> str:
    return next((segment for segment in parts.path.split("/") if segment), "")
