"""Object storage for uploads, stems and cached stage output.

Keys are plain strings laid out as spec 005 describes: `uploads/{hash}{ext}`
for originals, `cache/v{N}/{hash}/...` for stage output.
"""

import threading
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from guitarvis_jobs.settings import Settings

PRESIGN_EXPIRES_SEC = 15 * 60

# The Content-Type every stored object is served with, by its key's
# extension. An upload keeps the extension its client sent, and a server left
# to guess would serve `uploads/<hash>.html` as text/html; anything off this
# list is opaque bytes a browser downloads rather than renders.
_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "m4a": "audio/mp4",
    "aac": "audio/mp4",
    "mp4": "audio/mp4",
    "aif": "audio/aiff",
    "aiff": "audio/aiff",
    "webm": "audio/webm",
    "json": "application/json",
}
_OPAQUE = "application/octet-stream"


def content_type_for(key: str) -> str:
    """The Content-Type to store `key` with: from the allow-list, else opaque."""
    extension = PurePosixPath(key).suffix.removeprefix(".").lower()
    return _CONTENT_TYPES.get(extension, _OPAQUE)


class BlobNotFound(KeyError):
    """Nothing is stored at that key."""


class BlobStore(Protocol):
    def put_file(self, key: str, path: Path) -> None: ...

    def put_bytes(self, key: str, data: bytes) -> None: ...

    def get_file(self, key: str, path: Path) -> None:
        """Download to `path`, creating its directory. Raises BlobNotFound,
        writing nothing, when the key is missing."""
        ...

    def get_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def presign_get(self, key: str, *, expires_sec: int) -> str:
        """A URL a browser can GET without credentials. Does not check that
        the key exists; S3 presigning cannot either."""
        ...

    def ping(self) -> None:
        """Raise if the store cannot be reached."""
        ...


class InMemoryBlobStore:
    """Implements BlobStore in a dict."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def put_file(self, key: str, path: Path) -> None:
        self.put_bytes(key, path.read_bytes())

    def put_bytes(self, key: str, data: bytes) -> None:
        with self._lock:
            self._objects[key] = bytes(data)

    def get_file(self, key: str, path: Path) -> None:
        data = self.get_bytes(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        with self._lock:
            try:
                return self._objects[key]
            except KeyError:
                raise BlobNotFound(key) from None

    def exists(self, key: str) -> bool:
        with self._lock:
            return key in self._objects

    def presign_get(self, key: str, *, expires_sec: int) -> str:
        return f"memory://{key}?expires={expires_sec}"

    def ping(self) -> None:
        return None


_MISSING_CODES = {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}


def s3_client(
    settings: Settings,
    endpoint: str,
    *,
    connect_timeout: float = 5,
    max_attempts: int = 3,
) -> Any:
    """A boto3 client for any S3-compatible server.

    Path-style addressing, because a local server has no per-bucket DNS
    names. Signature v4, which presigned URLs need.
    """
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=connect_timeout,
            read_timeout=60,
            retries={"max_attempts": max_attempts, "mode": "standard"},
        ),
    )


class S3BlobStore:
    """Implements BlobStore on any S3-compatible server, such as compose.yaml's."""

    def __init__(
        self, client: Any, public_client: Any, bucket: str, region: str = "us-east-1"
    ) -> None:
        self._client = client
        # Signs URLs for the host a browser reaches; never sends a request.
        self._public = public_client
        self.bucket = bucket
        self._region = region

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3BlobStore":
        return cls(
            s3_client(settings, settings.s3_endpoint),
            s3_client(settings, settings.s3_public_endpoint or settings.s3_endpoint),
            settings.s3_bucket,
            settings.s3_region,
        )

    def put_file(self, key: str, path: Path) -> None:
        self._client.upload_file(
            str(path),
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type_for(key)},
        )

    def put_bytes(self, key: str, data: bytes) -> None:
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type_for(key)
        )

    def get_file(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client.download_file(self.bucket, key, str(path))
        except ClientError as exc:
            if _is_missing(exc):
                raise BlobNotFound(key) from exc
            raise

    def get_bytes(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if _is_missing(exc):
                raise BlobNotFound(key) from exc
            raise
        return bytes(response["Body"].read())

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if _is_missing(exc):
                return False
            raise
        return True

    def presign_get(self, key: str, *, expires_sec: int) -> str:
        return str(
            self._public.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_sec,
            )
        )

    def ping(self) -> None:
        self._client.head_bucket(Bucket=self.bucket)

    def ensure_bucket(self) -> None:
        """Create the bucket unless it exists. `make migrate` calls this."""
        try:
            self._client.head_bucket(Bucket=self.bucket)
            return
        except ClientError as exc:
            if not _is_missing(exc):
                raise
        if self._region == "us-east-1":
            self._client.create_bucket(Bucket=self.bucket)
        else:
            self._client.create_bucket(
                Bucket=self.bucket,
                CreateBucketConfiguration={"LocationConstraint": self._region},
            )


def _is_missing(exc: Any) -> bool:
    return str(exc.response.get("Error", {}).get("Code")) in _MISSING_CODES


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    _conforms: BlobStore = InMemoryBlobStore()
    _s3: BlobStore = S3BlobStore(None, None, "bucket")
