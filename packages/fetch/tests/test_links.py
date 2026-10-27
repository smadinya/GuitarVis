"""Every form of a YouTube link maps to one id and one canonical URL, and
every refusal to its kind (spec 012, *Links*; catalog rows R4 to R7)."""

import hashlib

import pytest
from guitarvis_fetch.links import MAX_LINK_CHARS, LinkRefused, RefusalKind, parse

ID = "dQw4w9WgXcQ"
CANONICAL = f"https://www.youtube.com/watch?v={ID}"


@pytest.mark.parametrize(
    "raw",
    [
        f"https://www.youtube.com/watch?v={ID}",
        f"http://www.youtube.com/watch?v={ID}",
        f"https://youtube.com/watch?v={ID}",
        f"https://m.youtube.com/watch?v={ID}",
        f"https://music.youtube.com/watch?v={ID}&feature=share",
        f"www.youtube.com/watch?v={ID}",
        f"youtube.com/watch?v={ID}",
        f"//www.youtube.com/watch?v={ID}",
        f"HTTPS://WWW.YOUTUBE.COM/watch?v={ID}",
        f"https://www.youtube.com./watch?v={ID}",
        f"  https://www.youtube.com/watch?v={ID}  \n",
        f"https://www.youtube.com/watch?v={ID}&t=42s",
        f"https://www.youtube.com/watch?v={ID}&list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI&index=3",
        f"https://www.youtube.com/watch?feature=youtu.be&v={ID}#t=30",
        f"https://www.youtube.com/watch/?v={ID}",
        f"https://youtu.be/{ID}",
        f"https://youtu.be/{ID}?si=B_RZg_I-lLaa7UU-",
        f"https://youtu.be/{ID}?t=1:30",
        f"youtu.be/{ID}/",
        f"https://www.youtube.com/shorts/{ID}",
        f"https://www.youtube.com/live/{ID}?si=abc",
        f"https://www.youtube.com/embed/{ID}",
        f"https://www.youtube-nocookie.com/embed/{ID}",
        f"https://youtube-nocookie.com/embed/{ID}",
        f"https://www.youtube.com/v/{ID}",
    ],
)
def test_every_accepted_form_is_one_video_with_one_canonical_url(raw: str) -> None:
    link = parse(raw)

    assert (link.site, link.video_id, link.canonical_url) == ("youtube", ID, CANONICAL)


def test_the_dedupe_key_is_the_videos_identity() -> None:
    expected = hashlib.sha256(f"youtube:{ID}".encode()).hexdigest()

    assert parse(f"https://youtu.be/{ID}").dedupe_key == expected
    assert parse(f"https://www.youtube.com/shorts/{ID}").dedupe_key == expected


def test_ids_keep_their_case_and_their_dashes() -> None:
    assert parse("https://youtu.be/a-B_c1D2e3F").video_id == "a-B_c1D2e3F"


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        # R4: not a link
        ("", RefusalKind.NOT_A_LINK),
        ("   \t ", RefusalKind.NOT_A_LINK),
        (f"https://www.youtube.com/watch?v={ID} and more", RefusalKind.NOT_A_LINK),
        (f"https://www.youtube.com/watch?v=​{ID}", RefusalKind.NOT_A_LINK),
        (f"https://www.youtube.com/watch?v={ID}\x00", RefusalKind.NOT_A_LINK),
        (
            f"https://www.youtube.com\\@evil.example/watch?v={ID}",
            RefusalKind.NOT_A_LINK,
        ),
        ("https://", RefusalKind.NOT_A_LINK),
        (f"https:///watch?v={ID}", RefusalKind.NOT_A_LINK),
        ("https://[::1/watch", RefusalKind.NOT_A_LINK),
        ("x" * (MAX_LINK_CHARS + 1), RefusalKind.NOT_A_LINK),
        # R5: not a web link
        ("javascript:alert(1)", RefusalKind.BAD_SCHEME),
        ("file:///etc/passwd", RefusalKind.BAD_SCHEME),
        (f"ftp://www.youtube.com/watch?v={ID}", RefusalKind.BAD_SCHEME),
        ("mailto:someone@example.com", RefusalKind.BAD_SCHEME),
        ("data:text/html,<script>alert(1)</script>", RefusalKind.BAD_SCHEME),
        # R6: not a supported site
        (
            f"https://www.youtube.com.example.net/watch?v={ID}",
            RefusalKind.UNSUPPORTED_SITE,
        ),
        (f"https://example.com/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        (f"https://notyoutube.com/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        (f"https://user@www.youtube.com/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        (
            f"https://www.youtube.com@evil.example/watch?v={ID}",
            RefusalKind.UNSUPPORTED_SITE,
        ),
        (f"https://www.youtube.com:443/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        (f"www.youtube.com:8080/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        (f"https://www.youtube.com:http/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        ("http://169.254.169.254/latest/meta-data/", RefusalKind.UNSUPPORTED_SITE),
        ("http://127.0.0.1:6379/", RefusalKind.UNSUPPORTED_SITE),
        (f"http://[::1]/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        (
            f"https://www.y\u043eutube.com/watch?v={ID}",
            RefusalKind.UNSUPPORTED_SITE,
        ),  # Cyrillic o
        (f"https://xn--yutube-wqf.com/watch?v={ID}", RefusalKind.UNSUPPORTED_SITE),
        ("https://localhost/", RefusalKind.UNSUPPORTED_SITE),
        # R7: a supported site, but not one video
        ("https://www.youtube.com/", RefusalKind.NOT_A_VIDEO),
        (
            "https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI",
            RefusalKind.NOT_A_VIDEO,
        ),
        ("https://www.youtube.com/@BlenderOfficial", RefusalKind.NOT_A_VIDEO),
        (
            "https://www.youtube.com/channel/UCSMOQeBJ2RAnuFungnQOxLg",
            RefusalKind.NOT_A_VIDEO,
        ),
        (
            "https://www.youtube.com/results?search_query=guitar",
            RefusalKind.NOT_A_VIDEO,
        ),
        (
            "https://www.youtube.com/clip/UgkxU2HSeGL_NvmDJ-nQJrlLwllwMDBdGZFs",
            RefusalKind.NOT_A_VIDEO,
        ),
        ("https://www.youtube.com/watch?v=", RefusalKind.NOT_A_VIDEO),
        ("https://www.youtube.com/watch?v=tooShort", RefusalKind.NOT_A_VIDEO),
        (f"https://www.youtube.com/watch?v={ID}x", RefusalKind.NOT_A_VIDEO),
        (
            f"https://www.youtube.com/watch?v={ID}&v=YE7VzlLtp-4",
            RefusalKind.NOT_A_VIDEO,
        ),
        (f"https://www.youtube.com/shorts/{ID}/extra", RefusalKind.NOT_A_VIDEO),
        (f"https://www.youtube.com/watch/{ID}", RefusalKind.NOT_A_VIDEO),
        ("https://youtu.be/", RefusalKind.NOT_A_VIDEO),
        (f"https://youtu.be/{ID}/{ID}", RefusalKind.NOT_A_VIDEO),
    ],
)
def test_each_refusal_has_its_kind(raw: str, kind: RefusalKind) -> None:
    with pytest.raises(LinkRefused) as excinfo:
        parse(raw)

    assert excinfo.value.kind is kind


def test_a_link_at_the_limit_is_read_and_one_over_is_not() -> None:
    padding = "&x=" + "a" * (MAX_LINK_CHARS - len(CANONICAL) - 3)
    at_limit = CANONICAL + padding
    assert len(at_limit) == MAX_LINK_CHARS

    assert parse(at_limit).video_id == ID
    with pytest.raises(LinkRefused):
        parse(at_limit + "a")


def test_a_refusal_carries_only_the_host_and_first_segment_for_the_log() -> None:
    with pytest.raises(LinkRefused) as excinfo:
        parse("https://www.youtube.com/playlist?list=PL123&si=SHARER-ID")

    refused = excinfo.value
    assert (refused.host, refused.segment) == ("www.youtube.com", "playlist")
    assert "SHARER-ID" not in str(refused)


def test_the_canonical_url_is_built_from_the_id_never_edited_from_the_input() -> None:
    link = parse(f"https://youtu.be/{ID}?si=SHARER-ID&t=42")

    assert link.canonical_url == CANONICAL
    assert "SHARER-ID" not in link.canonical_url
