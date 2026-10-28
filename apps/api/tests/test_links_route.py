"""POST /jobs/from-url and GET /features (spec 012): every R, Q, L, E and G
row of the failure catalog, on in-memory stores and a fake fetcher that
records its calls. Nothing here makes a network request."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import httpx2
import pytest
from api_fixture import CLIENT_IP, Api, make_api
from fastapi.testclient import TestClient
from guitarvis_fetch.catalog import CATALOG, FetchKind, message_for
from guitarvis_fetch.fetcher import FetchError, VideoInfo
from guitarvis_fetch.links import parse
from guitarvis_fetch.testing import FakeFetcher, video_info
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, JobStatus, NewJob
from guitarvis_jobs.store import InMemoryJobStore

ID = "kPdv44HtEoA"
LINK = f"https://www.youtube.com/watch?v={ID}"
DEDUPE_KEY = parse(LINK).dedupe_key
SENTINEL = "SENTINEL-4f2a"
ROUTE_LOG = "guitarvis_api.routes_links"


def links_api(fetcher: FakeFetcher | None = None, **settings: Any) -> Api:
    return make_api(
        fetcher=fetcher if fetcher is not None else FakeFetcher(),
        url_ingestion=settings.pop("url_ingestion", True),
        **settings,
    )


def fake(api: Api) -> FakeFetcher:
    fetcher = api.services.fetcher
    assert isinstance(fetcher, FakeFetcher)
    return fetcher


def post_link(client: TestClient, url: str = LINK) -> httpx2.Response:
    return client.post("/jobs/from-url", json={"url": url})


def error_of(response: httpx2.Response) -> tuple[int, str, str]:
    body = response.json()["error"]
    return response.status_code, body["reason"], body["message"]


# Success


def test_a_new_link_is_looked_up_queued_and_accepted() -> None:
    api = links_api()

    response = post_link(api.client, f"https://youtu.be/{ID}?si=SHARER&t=42")

    assert response.status_code == 202
    body = response.json()
    assert response.headers["location"] == f"/jobs/{body['id']}"
    assert (body["status"], body["title"], body["duration_sec"]) == (
        "queued",
        "Elephants Dream - 10 years of open movies",
        37.0,
    )
    assert body["source_url"] == LINK  # canonical: no si=, no t=
    job = api.job(body["id"])
    assert (job.content_hash, job.upload_key, job.client_ip) == (
        DEDUPE_KEY,
        None,
        CLIENT_IP,
    )
    assert fake(api).lookups == [parse(LINK)]
    assert api.queue.enqueued == [body["id"]]


@pytest.mark.parametrize(
    ("title", "stored"),
    [
        ("Song\x00 with\x1b[31m controls​", "Song with[31m controls"),
        ("x" * 250, "x" * 200),
        ("   ", "Untitled"),
        ("", "Untitled"),
    ],
)
def test_the_title_is_the_videos_cleaned(title: str, stored: str) -> None:
    api = links_api(FakeFetcher(info=video_info(title=title)))

    assert post_link(api.client).json()["title"] == stored


# GET /features


@pytest.mark.parametrize("on", [True, False])
def test_features_says_whether_links_are_on(on: bool) -> None:
    api = links_api(url_ingestion=on)

    response = api.client.get("/features")

    assert (response.status_code, response.json()) == (200, {"url_ingestion": on})


# R. The request, before any network


def test_links_switched_off_are_refused_before_anything_is_read(
    caplog: pytest.LogCaptureFixture,
) -> None:  # R1
    api = links_api(url_ingestion=False)

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        responses = [
            post_link(api.client),
            api.client.post("/jobs/from-url", content=b"not json"),
        ]

    for response in responses:
        assert error_of(response) == (
            403,
            "links_disabled",
            "Links are turned off on this server. Upload the audio file instead.",
        )
    assert fake(api).lookups == []
    assert caplog.messages == ["link refused kind=links_disabled"] * 2


def test_links_switched_off_answer_for_a_big_body_too_before_its_size(
    caplog: pytest.LogCaptureFixture,
) -> None:  # R1, before R3
    api = links_api(url_ingestion=False)

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        response = api.client.post(
            "/jobs/from-url",
            content=b'{"url": "' + b"a" * (20 * 1024) + b'"}',
            headers={"content-type": "application/json"},
        )

    assert error_of(response) == (
        403,
        "links_disabled",
        "Links are turned off on this server. Upload the audio file instead.",
    )
    assert caplog.messages == ["link refused kind=links_disabled"]


@pytest.mark.parametrize(
    "send",
    [
        pytest.param(
            {"content": b"not json", "headers": {"content-type": "application/json"}},
            id="not-json",
        ),
        pytest.param(
            {
                "content": b"url=x",
                "headers": {"content-type": "application/x-www-form-urlencoded"},
            },
            id="a-form",
        ),
        pytest.param({"content": b""}, id="empty"),
        pytest.param(
            {
                "content": b"\xff\xfe\xfd",
                "headers": {"content-type": "application/json"},
            },
            id="not-text",
        ),
        pytest.param(
            {
                "content": '{"url": "café"}'.encode("latin-1"),
                "headers": {"content-type": "application/json"},
            },
            id="latin-1",
        ),
        pytest.param({"json": {}}, id="no-url"),
        pytest.param({"json": {"link": LINK}}, id="misnamed"),
        pytest.param({"json": {"url": 42}}, id="not-a-string"),
        pytest.param({"json": [LINK]}, id="a-list"),
        pytest.param({"json": {"url": LINK + "&x=" + "a" * 2048}}, id="over-2048"),
    ],
)
def test_a_body_that_is_not_a_link_in_json_is_refused(
    send: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:  # R2
    api = links_api()

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        response = api.client.post("/jobs/from-url", **send)

    assert error_of(response) == (
        422,
        "unsupported_link",
        "Send the link as JSON, in a field named `url`.",
    )
    assert fake(api).lookups == []
    # The request's fault, not ours: one INFO line, and no traceback.
    assert caplog.messages == ["link refused kind=bad_request"]
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_a_body_over_16_kb_is_refused_before_it_is_read() -> None:  # R3
    api = links_api()

    response = api.client.post(
        "/jobs/from-url",
        content=b'{"url": "' + b"a" * (16 * 1024) + b'"}',
        headers={"content-type": "application/json"},
    )

    assert error_of(response) == (
        413,
        "too_large",
        "That request is too large. Send only the link.",
    )
    assert fake(api).lookups == []


def test_a_body_that_streams_past_16_kb_is_refused_as_it_arrives() -> None:  # R3
    api = links_api()

    response = api.client.post(
        "/jobs/from-url",
        content=iter([b'{"url": "' + b"a" * 9000, b"a" * 9000 + b'"}']),
        headers={"content-type": "application/json"},
    )

    assert error_of(response)[:2] == (413, "too_large")
    assert fake(api).lookups == []


def test_the_upload_limit_still_guards_uploads_only() -> None:
    api = links_api(max_upload_mb=1)

    upload = api.client.post(
        "/jobs", files={"file": ("a.mp3", b"x" * (1024 * 1024 + 1), "audio/mpeg")}
    )

    assert error_of(upload)[:2] == (413, "too_large")
    assert "1 MB" in error_of(upload)[2]


@pytest.mark.parametrize(
    ("url", "row", "message"),
    [
        (
            "   ",
            "R4",
            "That doesn't look like a link. Copy the video's address from your "
            "browser and paste it here.",
        ),
        (
            "javascript:alert(1)",
            "R5",
            "Only web links (https://…) can be used. Copy the video's address "
            "from your browser.",
        ),
        (
            "http://169.254.169.254/latest/meta-data/",
            "R6",
            "We can only fetch songs from YouTube for now. For anything else, "
            "upload the audio file.",
        ),
        (
            "https://www.youtube.com/playlist?list=PL123",
            "R7",
            "That link isn't to a single video. Open the video itself and copy "
            "its address.",
        ),
    ],
)
def test_a_link_we_cannot_use_is_refused_without_a_lookup(
    url: str, row: str, message: str
) -> None:  # R4 to R7
    api = links_api()

    assert error_of(post_link(api.client, url)) == (422, "unsupported_link", message), (
        row
    )
    assert fake(api).lookups == []
    assert api.queue.enqueued == []


def test_a_refused_link_is_logged_by_its_kind_host_and_first_segment_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = links_api()

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        post_link(api.client, "https://www.youtube.com/playlist?list=PL123&si=SHARER")

    assert caplog.messages == [
        "link refused kind=not_a_video host=www.youtube.com path=playlist"
    ]


def test_a_refused_links_host_and_segment_are_cut_to_100_characters_each(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = links_api()
    long_host = "h" * 300 + ".example"
    long_segment = "s" * 500

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        post_link(api.client, f"https://{long_host}/{long_segment}?si=SHARER")
        post_link(api.client, f"https://www.youtube.com/{long_segment}?si=SHARER")

    assert caplog.messages == [
        f"link refused kind=unsupported_site host={'h' * 100} path={'s' * 100}",
        f"link refused kind=not_a_video host=www.youtube.com path={'s' * 100}",
    ]


def test_a_body_that_is_not_a_link_in_json_is_logged_by_its_kind(
    caplog: pytest.LogCaptureFixture,
) -> None:  # R2
    api = links_api()

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        api.client.post("/jobs/from-url", json={"url": 42})

    assert caplog.messages == ["link refused kind=bad_request"]


# Q. Dedupe and limits, before any network


@pytest.mark.parametrize(
    "again",
    [
        f"https://youtu.be/{ID}",
        f"https://www.youtube.com/shorts/{ID}",
        f"https://m.youtube.com/watch?v={ID}&t=30",
        f"youtube.com/watch?v={ID}&list=PL123",
    ],
)
def test_the_same_video_in_any_form_is_the_same_job_without_a_lookup(
    again: str,
) -> None:  # Q1
    api = links_api()
    first = post_link(api.client).json()["id"]

    response = post_link(api.client, again)

    assert (response.status_code, response.json()["id"]) == (200, first)
    assert len(fake(api).lookups) == 1
    assert api.queue.enqueued == [first]


def test_a_link_whose_job_the_queue_lost_starts_a_fresh_one() -> None:  # Q1
    api = links_api()
    first = post_link(api.client).json()["id"]
    api.queue.lose(first)
    api.clock.advance(seconds=61)

    again = post_link(api.client)

    assert again.status_code == 202
    assert again.json()["id"] != first
    assert api.job(first).status is JobStatus.FAILED


def test_an_address_at_its_limit_is_refused_without_a_lookup() -> None:  # Q2
    api = links_api(max_active_jobs_per_ip=1)
    post_link(api.client)

    response = post_link(api.client, "https://youtu.be/YE7VzlLtp-4")

    assert error_of(response) == (
        429,
        "too_many_jobs",
        "You already have 1 song processing. Wait for one to finish, then try again.",
    )
    assert len(fake(api).lookups) == 1


def test_a_fifth_lookup_at_once_is_turned_away_without_waiting() -> None:  # Q3
    api = links_api()
    for _ in range(4):
        assert api.services.lookups.acquire(blocking=False)

    response = post_link(api.client)

    assert error_of(response) == (
        503,
        "fetch_failed",
        "We're checking a lot of links right now. Try again in a minute.",
    )
    assert fake(api).lookups == []


class BlockingFetcher(FakeFetcher):
    """Holds every lookup until released, counting those in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()
        self.four_waiting = threading.Barrier(5)

    def lookup(self, link: Any) -> VideoInfo:
        self.four_waiting.wait(timeout=10)
        self.release.wait(timeout=10)
        return super().lookup(link)


def test_four_lookups_run_at_once_and_a_fifth_is_refused() -> None:  # Q3
    fetcher = BlockingFetcher()
    api = links_api(fetcher, max_active_jobs_per_ip=10)
    ids = ["YE7VzlLtp-4", "M4gD1WSo5mA", "rKb_Uyn56Dw", "ejNMjg5b1lg"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        held = [
            pool.submit(post_link, api.client, f"https://youtu.be/{i}") for i in ids
        ]
        fetcher.four_waiting.wait(timeout=10)  # all four are inside lookup
        fifth = post_link(api.client)
        fetcher.release.set()
        statuses = [future.result().status_code for future in held]

    assert error_of(fifth)[:2] == (503, "fetch_failed")
    assert statuses == [202, 202, 202, 202]


# L. The lookup


LOOKUP_ROWS = [
    ("L1", FetchKind.PRIVATE, 422, "link_unusable"),
    ("L2", FetchKind.UNAVAILABLE, 422, "link_unusable"),
    ("L3", FetchKind.GEO_RESTRICTED, 422, "link_unusable"),
    ("L4", FetchKind.AGE_RESTRICTED, 422, "link_unusable"),
    ("L5", FetchKind.MEMBERS_ONLY, 422, "link_unusable"),
    ("L11", FetchKind.NO_AUDIO, 422, "link_unusable"),
    ("L12", FetchKind.RATE_LIMITED, 503, "fetch_failed"),
    ("L13", FetchKind.NETWORK, 502, "fetch_failed"),
    ("L14", FetchKind.LOOKUP_TIMEOUT, 504, "fetch_failed"),
    ("L15", FetchKind.EXTRACTOR_BROKEN, 502, "fetch_failed"),
    ("L16", FetchKind.MISCONFIGURED, 503, "fetch_failed"),
    ("L17", FetchKind.UNKNOWN, 502, "fetch_failed"),
    ("L18", FetchKind.CRASHED, 500, "internal"),
]


@pytest.mark.parametrize(("row", "kind", "status", "reason"), LOOKUP_ROWS)
def test_a_failed_lookup_answers_with_its_catalog_row(
    row: str, kind: FetchKind, status: int, reason: str
) -> None:
    api = links_api(
        FakeFetcher(lookup_error=FetchError(kind, f"ERROR: [youtube] {SENTINEL}"))
    )

    response = post_link(api.client)

    assert error_of(response) == (status, reason, message_for(kind)), row
    assert api.queue.enqueued == []
    assert api.store.find_live(DEDUPE_KEY) is None


def test_an_internal_lookup_failure_says_what_every_internal_failure_says() -> (
    None
):  # L18
    api = links_api(FakeFetcher(lookup_error=FetchError(FetchKind.CRASHED, "Killed")))

    assert error_of(post_link(api.client))[2] == INTERNAL_FAILURE_MESSAGE


@pytest.mark.parametrize(
    ("row", "info", "reason", "message"),
    [
        (
            "L6",
            video_info(live_status="is_live", duration_sec=None),
            "link_unusable",
            message_for(FetchKind.LIVE),
        ),
        (
            "L7",
            video_info(live_status="is_upcoming"),
            "link_unusable",
            message_for(FetchKind.UPCOMING),
        ),
        (
            "L8",
            video_info(live_status="post_live"),
            "link_unusable",
            message_for(FetchKind.POST_LIVE),
        ),
        (
            "L9",
            video_info(duration_sec=None),
            "link_unusable",
            message_for(FetchKind.NO_DURATION),
        ),
        (
            "L10",
            video_info(duration_sec=10800),
            "too_long",
            "That video is 3:00:00 long. The limit is 10 minutes: try a link to "
            "a single song.",
        ),
    ],
)
def test_metadata_we_cannot_use_is_refused_before_queueing(
    row: str, info: VideoInfo, reason: str, message: str
) -> None:
    api = links_api(FakeFetcher(info=info))

    response = post_link(api.client)

    assert error_of(response) == (422, reason, message), row
    assert api.queue.enqueued == []


def test_ytdlp_text_reaches_the_log_and_never_the_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    detail = f"ERROR: [youtube] {ID}: Private video. {SENTINEL} Traceback"
    api = links_api(FakeFetcher(lookup_error=FetchError(FetchKind.PRIVATE, detail)))

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        response = post_link(api.client)

    assert SENTINEL not in response.text
    assert "yt-dlp" not in response.text and "Traceback" not in response.text
    [line] = [m for m in caplog.messages if m.startswith("link fetch failed")]
    assert line.startswith(
        f"link fetch failed kind=private phase=lookup site=youtube video={ID} job=- "
    )
    assert SENTINEL in line
    assert [r.levelno for r in caplog.records if "fetch failed" in r.message] == [
        CATALOG[FetchKind.PRIVATE].level
    ]


@pytest.mark.parametrize(
    "kind",
    [kind for kind in FetchKind if CATALOG[kind].tail],
    ids=lambda kind: kind.value,
)
def test_an_error_that_keeps_the_childs_stderr_logs_it_and_never_answers_with_it(
    kind: FetchKind, caplog: pytest.LogCaptureFixture
) -> None:
    error = FetchError(kind, "no answer", tail=f"Traceback ... {SENTINEL}")
    api = links_api(FakeFetcher(lookup_error=error))

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        response = post_link(api.client)

    assert SENTINEL not in response.text
    [line] = [m for m in caplog.messages if m.startswith("link fetch failed")]
    assert f'tail="Traceback ... {SENTINEL}"' in line
    assert [r.levelno for r in caplog.records if "fetch failed" in r.message] == [
        CATALOG[kind].level
    ]


@pytest.mark.parametrize(
    "kind", [FetchKind.LIVE, FetchKind.TOO_LONG, FetchKind.NO_DURATION]
)
def test_a_refusal_from_the_metadata_is_logged_like_a_failed_lookup(
    kind: FetchKind, caplog: pytest.LogCaptureFixture
) -> None:
    info = {
        FetchKind.LIVE: video_info(live_status="is_live", duration_sec=None),
        FetchKind.TOO_LONG: video_info(duration_sec=10800),
        FetchKind.NO_DURATION: video_info(duration_sec=None),
    }[kind]
    api = links_api(FakeFetcher(info=info))

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        post_link(api.client)

    [line] = [m for m in caplog.messages if m.startswith("link fetch failed")]
    assert line.startswith(f"link fetch failed kind={kind.value} phase=lookup ")
    assert "ytdlp=2026.10.26 js=deno/2.5.4" in line
    assert [r.levelno for r in caplog.records if "fetch failed" in r.message] == [
        CATALOG[kind].level
    ]


def test_a_busy_lookup_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:  # Q3
    api = links_api()
    for _ in range(4):
        assert api.services.lookups.acquire(blocking=False)

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        post_link(api.client)

    [record] = [r for r in caplog.records if r.message.startswith("link fetch failed")]
    assert record.message.startswith(
        f"link fetch failed kind=busy phase=lookup site=youtube video={ID} job=- "
    )
    assert record.levelno == CATALOG[FetchKind.BUSY].level


def test_a_successful_lookup_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    api = links_api()

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        post_link(api.client)

    assert any(
        m.startswith(f"link fetched phase=lookup site=youtube video={ID}")
        and "ytdlp=2026.10.26 js=deno/2.5.4" in m
        for m in caplog.messages
    )


def test_a_lookup_slot_is_given_back_whatever_the_outcome() -> None:
    api = links_api(FakeFetcher(lookup_error=FetchError(FetchKind.NETWORK)))
    for _ in range(6):
        post_link(api.client)

    for _ in range(4):
        assert api.services.lookups.acquire(blocking=False)


def test_links_on_with_no_fetcher_is_our_misconfiguration(
    caplog: pytest.LogCaptureFixture,
) -> None:  # L16
    api = make_api(fetcher=None, url_ingestion=True)

    with caplog.at_level(logging.INFO, logger=ROUTE_LOG):
        response = post_link(api.client)

    assert error_of(response) == (
        503,
        "fetch_failed",
        message_for(FetchKind.MISCONFIGURED),
    )
    assert any(
        m.startswith("link fetch failed kind=misconfigured") for m in caplog.messages
    )
    for _ in range(4):  # and it gave its slot back
        assert api.services.lookups.acquire(blocking=False)


# E. Queueing


def test_the_same_video_created_at_the_same_moment_returns_the_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # E1
    api = links_api()
    winner, _ = api.store.create(
        NewJob(DEDUPE_KEY, "t", 37.0, None, "198.51.100.1", source_url=LINK)
    )
    # As if the winner committed between this request's dedupe and its insert.
    monkeypatch.setattr(api.store, "find_live", lambda content_hash: None)

    response = post_link(api.client)

    assert (response.status_code, response.json()["id"]) == (200, winner.id)
    assert api.queue.enqueued == []


def test_an_address_that_races_past_the_count_is_refused_when_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # E2
    api = links_api(max_active_jobs_per_ip=1)
    post_link(api.client, "https://youtu.be/YE7VzlLtp-4")
    monkeypatch.setattr(api.store, "count_active", lambda client_ip: 0)

    response = post_link(api.client)

    assert error_of(response)[:2] == (429, "too_many_jobs")
    assert len(api.queue.enqueued) == 1


def test_a_queue_that_refuses_the_job_fails_the_row() -> None:  # E3
    api = links_api()
    api.queue.fail_next = True

    response = post_link(api.client)

    assert error_of(response) == (
        503,
        "internal",
        "We could not queue that song. Try again in a minute.",
    )
    assert api.store.find_live(DEDUPE_KEY) is None
    assert post_link(api.client).status_code == 202


def test_a_store_that_cannot_be_reached_is_our_failure() -> None:  # E4
    class Down(InMemoryJobStore):
        def find_live(self, content_hash: str) -> None:
            raise ConnectionError("postgres went away")

    api = make_api(
        store=Down(),
        fetcher=FakeFetcher(),
        url_ingestion=True,
        raise_server_exceptions=False,
    )

    assert error_of(post_link(api.client)) == (
        500,
        "internal",
        INTERNAL_FAILURE_MESSAGE,
    )


# G. Reading


def test_a_link_jobs_mix_is_not_ready_until_the_worker_stores_it() -> None:  # G1
    api = links_api()
    job_id = post_link(api.client).json()["id"]

    response = api.client.get(f"/jobs/{job_id}/audio/mix", follow_redirects=False)

    assert error_of(response) == (
        409,
        "not_ready",
        "The audio is not ready yet. Poll the job until it succeeds.",
    )


# The switch, for jobs made before it was turned off


def test_links_off_still_serves_the_jobs_links_made() -> None:
    api = links_api()
    job_id = post_link(api.client).json()["id"]
    off = make_api(store=api.store, blobs=api.blobs, fetcher=None, url_ingestion=False)

    assert off.client.get(f"/jobs/{job_id}").json()["source_url"] == LINK


def test_switching_links_off_in_settings_alone_turns_the_route_off() -> None:
    api = links_api()
    services = replace(
        api.services, settings=replace(api.settings, url_ingestion=False)
    )
    api.client.app.state.services = services  # type: ignore[attr-defined]

    assert post_link(api.client).status_code == 403
