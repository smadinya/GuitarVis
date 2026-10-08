"""Receiving an upload: the size limit, the hash, the title and the key.

Starlette writes a whole multipart body to disk before a route sees it, so a
limit checked only in the route would accept 2 GB first and refuse it after.
UploadSizeLimit sits in front of the app and abandons an oversized body as it
arrives; `receive` then counts the file's own bytes exactly while hashing.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from fastapi.responses import JSONResponse
from guitarvis_core.contracts import FailureReason
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from guitarvis_api.errors import ApiError, HttpReason, error_body

CHUNK_BYTES = 1024 * 1024
# Boundary lines and part headers around the file. The route enforces the
# limit on the file itself; this only keeps the framing from tripping it.
MULTIPART_ALLOWANCE = 64 * 1024
MAX_TITLE_CHARS = 200
_EXTENSION = re.compile(r"\.[a-z0-9]{1,5}")


def too_large(max_bytes: int) -> ApiError:
    return ApiError(
        413,
        HttpReason.TOO_LARGE,
        f"That file is larger than the {max_bytes // (1024 * 1024)} MB limit.",
    )


class UploadSizeLimit:
    """ASGI middleware: refuse an oversized POST /jobs before it lands.

    A declared Content-Length over the limit is refused before a byte is
    read. A body that declares none (chunked) is counted as it streams and
    abandoned the moment it passes the limit: the ApiError raised here comes
    out of FastAPI's body parsing untouched, as the 413 itself.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] != "/jobs"
        ):
            await self.app(scope, receive, send)
            return

        max_bytes: int = scope["app"].state.services.settings.max_upload_bytes
        limit = max_bytes + MULTIPART_ALLOWANCE
        declared = _content_length(scope)
        if declared is not None and declared > limit:
            error = too_large(max_bytes)
            response = JSONResponse(
                error_body(error.reason, error.message), status_code=413
            )
            await response(scope, receive, send)
            return

        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise too_large(max_bytes)
            return message

        await self.app(scope, counted, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


@dataclass(frozen=True)
class ReceivedUpload:
    path: Path
    content_hash: str
    size: int


def receive(source: BinaryIO, destination: Path, *, max_bytes: int) -> ReceivedUpload:
    """Copy the upload to `destination`, hashing and counting as it goes."""
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as out:
        while chunk := source.read(CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                raise too_large(max_bytes)
            digest.update(chunk)
            out.write(chunk)
    if size == 0:
        raise ApiError(422, FailureReason.UNSUPPORTED_FORMAT, "That file is empty.")
    return ReceivedUpload(path=destination, content_hash=digest.hexdigest(), size=size)


def _basename(filename: str | None) -> str:
    """The last path component, whichever separator the client's OS used."""
    return (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()


def title_of(filename: str | None) -> str:
    """The upload's filename without its last extension: the job's title."""
    return (
        PurePosixPath(_basename(filename)).stem.strip()[:MAX_TITLE_CHARS] or "Untitled"
    )


def extension_of(filename: str | None) -> str:
    """The lowercased suffix, kept only when it is 1 to 5 alphanumerics.

    ffprobe and Demucs sniff content, so this is a courtesy to a human
    browsing the bucket, never something the pipeline relies on.
    """
    suffix = PurePosixPath(_basename(filename)).suffix.lower()
    return suffix if _EXTENSION.fullmatch(suffix) else ""


def upload_key(content_hash: str, filename: str | None) -> str:
    return f"uploads/{content_hash}{extension_of(filename)}"
