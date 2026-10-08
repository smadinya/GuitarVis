"""One error vocabulary for every client.

Every error body is {"error": {"reason": ..., "message": ...}}. `reason` is a
FailureReason value or one of the four HttpReason values only the HTTP layer
produces, so a client maps one vocabulary to text.
"""

import logging
from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from guitarvis_core.contracts import FailureReason
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class HttpReason(StrEnum):
    TOO_LARGE = "too_large"
    TOO_MANY_JOBS = "too_many_jobs"
    NOT_FOUND = "not_found"
    NOT_READY = "not_ready"


Reason = FailureReason | HttpReason


class ApiError(StarletteHTTPException):
    """An HTTP error carrying a reason a client can map to text.

    A Starlette HTTPException on purpose: FastAPI re-raises those untouched
    from inside request-body parsing, which is what lets the upload limit
    abandon a request mid-stream with its own status and body.
    """

    def __init__(self, status_code: int, reason: Reason, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.reason = reason
        self.message = message


def error_body(reason: Reason, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"reason": reason.value, "message": message}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if isinstance(exc, ApiError):
            reason: Reason = exc.reason
            message = exc.message
        else:  # Starlette's own: an unknown route, a wrong method
            reason = (
                HttpReason.NOT_FOUND
                if exc.status_code in (404, 405)
                else FailureReason.INTERNAL
            )
            message = str(exc.detail)
        return JSONResponse(
            error_body(reason, message),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # The only validated input is POST /jobs's multipart body.
        return JSONResponse(
            error_body(
                FailureReason.UNSUPPORTED_FORMAT,
                "Send the audio as a multipart form field named `file`.",
            ),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error(
            "unhandled error on %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return JSONResponse(
            error_body(FailureReason.INTERNAL, INTERNAL_FAILURE_MESSAGE),
            status_code=500,
        )
