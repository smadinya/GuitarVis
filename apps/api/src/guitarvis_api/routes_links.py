"""Links: POST /jobs/from-url and GET /features (spec 012).

Everything links add to the api is here, so removing them for good is
deleting this module and its one line in app.py. The checks run cheapest
first, and nothing touches the network until the lookup: the switch, the
link's form, dedupe by video, the address's limit, then one child process.
"""

import logging
import time
import unicodedata
from collections.abc import Callable, Coroutine
from typing import Any, NoReturn

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from guitarvis_core.contracts import FailureReason
from guitarvis_fetch.catalog import (
    BAD_REQUEST_MESSAGE,
    LINKS_OFF_MESSAGE,
    REFUSALS,
    REQUEST_TOO_LARGE_MESSAGE,
    FetchKind,
)
from guitarvis_fetch.fetcher import (
    FetchError,
    VideoInfo,
    check_info,
    log_failed,
    log_fetched,
)
from guitarvis_fetch.links import Link, LinkRefused, parse
from guitarvis_jobs.models import NewJob
from guitarvis_jobs.settings import Settings
from starlette.exceptions import HTTPException as StarletteHTTPException

from guitarvis_api.errors import ApiError, HttpReason
from guitarvis_api.routes import (
    check_limit,
    client_ip_of,
    create_and_enqueue,
    live_job,
    services_of,
)
from guitarvis_api.schemas import Features, JobView, LinkRequest
from guitarvis_api.services import Services
from guitarvis_api.uploads import MAX_TITLE_CHARS, UploadSizeLimit

log = logging.getLogger(__name__)

LINK_PATH = "/jobs/from-url"
LINK_BODY_MAX_BYTES = 16 * 1024
# A refused link's host and first segment are the sender's text, up to ~2 KB
# of it; the log keeps this much of each.
LOG_FIELD_CHARS = 100


class _LinkRoute(APIRoute):
    """POST /jobs/from-url's own front door.

    The switch is checked before the body is read, and a body FastAPI cannot
    validate is answered as a link we cannot use (R2). The app's validation
    handler speaks for uploads, and this keeps links out of it.
    """

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def route(request: Request) -> Response:
            if not services_of(request).settings.url_ingestion:  # R1
                raise _links_off()
            try:
                return await handler(request)
            except RequestValidationError as exc:  # R2
                raise _bad_request() from exc
            except StarletteHTTPException as exc:
                if _is_unreadable_body(exc):  # R2: bytes that are not JSON text
                    raise _bad_request() from exc
                raise  # an ApiError, such as R3's 413, passes untouched

        return route


def _links_off() -> ApiError:  # R1
    log.info("link refused kind=links_disabled")
    return ApiError(403, FailureReason.LINKS_DISABLED, LINKS_OFF_MESSAGE)


def _bad_request() -> ApiError:  # R2
    log.info("link refused kind=bad_request")
    return ApiError(422, HttpReason.UNSUPPORTED_LINK, BAD_REQUEST_MESSAGE)


def _is_unreadable_body(exc: StarletteHTTPException) -> bool:
    """FastAPI answers a JSON body it cannot decode (UnicodeDecodeError, or
    any other ValueError) with a bare 400 whose cause is that error, which
    the app's handler reads as our failure. From the sender it is R2."""
    return (
        not isinstance(exc, ApiError)
        and exc.status_code == 400
        and isinstance(exc.__cause__, ValueError)
    )


links = APIRouter(route_class=_LinkRoute)
router = APIRouter()


@router.get("/features", response_model=Features)
def features(request: Request) -> Features:
    """What this api has switched on. The client shows the link field only
    when this says so."""
    return Features(url_ingestion=services_of(request).settings.url_ingestion)


@links.post(LINK_PATH, status_code=202, response_model=JobView)
def create_job_from_url(
    body: LinkRequest, request: Request, response: Response
) -> JobView:
    services = services_of(request)
    client_ip = client_ip_of(request)
    link = _parse(body.url)

    live = live_job(services, link.dedupe_key)  # Q1: in any form, no lookup
    if live is not None:
        response.status_code = 200
        return JobView.of(live)

    check_limit(services, client_ip)  # Q2: before any outbound request
    info, duration = _lookup(services, link)
    return create_and_enqueue(  # E1 to E3
        services,
        NewJob(
            content_hash=link.dedupe_key,
            title=_title(info.title),
            duration_sec=duration,
            upload_key=None,
            client_ip=client_ip,
            source_url=link.canonical_url,
        ),
        response,
    )


def _parse(raw: str) -> Link:
    try:
        return parse(raw)
    except LinkRefused as refused:  # R4 to R7
        # Its kind, host and first path segment, each cut short: never the
        # whole string, which can carry the sharer's si= id.
        log.info(
            "link refused kind=%s host=%s path=%s",
            refused.kind,
            refused.host[:LOG_FIELD_CHARS] or "-",
            refused.segment[:LOG_FIELD_CHARS] or "-",
        )
        raise ApiError(
            422, HttpReason.UNSUPPORTED_LINK, REFUSALS[refused.kind]
        ) from None


def _lookup(services: Services, link: Link) -> tuple[VideoInfo, float]:
    """Ask the site, in a child process with its deadline; then step 6.
    The video's metadata, and its length."""
    started = time.monotonic()
    if not services.lookups.acquire(blocking=False):  # Q3
        _refuse(FetchError(FetchKind.BUSY, "lookups at their limit"), link, started)
    try:
        if services.fetcher is None:  # the switch is on, but nothing can fetch
            raise FetchError(FetchKind.MISCONFIGURED, "links are on with no fetcher")
        info = services.fetcher.lookup(link)
        duration = check_info(info)
    except FetchError as error:
        _refuse(error, link, started)
    finally:
        services.lookups.release()
    log_fetched(
        log,
        phase="lookup",
        link=link,
        versions=info.versions,
        elapsed_sec=time.monotonic() - started,
    )
    return info, duration


def _refuse(error: FetchError, link: Link, started: float) -> NoReturn:
    log_failed(
        log, error, phase="lookup", link=link, elapsed_sec=time.monotonic() - started
    )
    entry = error.entry
    raise ApiError(entry.status, entry.reason, error.message) from None


def _title(raw: str) -> str:
    """The video's title as a job's: no control characters, at most 200
    characters, and "Untitled" when nothing is left."""
    kept = "".join(c for c in raw if not unicodedata.category(c).startswith("C"))
    return kept.strip()[:MAX_TITLE_CHARS].strip() or "Untitled"


def _link_body_limit(settings: Settings) -> int:
    return LINK_BODY_MAX_BYTES


def _link_body_too_large(settings: Settings) -> ApiError:
    """R3, unless links are off: the switch answers before the body's size."""
    if not settings.url_ingestion:
        return _links_off()
    return ApiError(413, HttpReason.TOO_LARGE, REQUEST_TOO_LARGE_MESSAGE)


def install(app: FastAPI) -> None:
    """Everything links add to the api: the routes, and a body limit for
    the link's own route."""
    app.add_middleware(
        UploadSizeLimit,
        path=LINK_PATH,
        limit=_link_body_limit,
        refuse=_link_body_too_large,
    )
    app.include_router(router)


router.include_router(links)
