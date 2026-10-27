"""Where the services are, and the limits the api enforces.

A frozen stdlib dataclass read from GUITARVIS_* environment variables — one
per field, named after it. The defaults match compose.yaml, so local
development needs no env file.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any

_PREFIX = "GUITARVIS_"


@dataclass(frozen=True)
class Settings:
    # Out of the repr, like s3_secret_key: the URL carries the password.
    database_url: str = field(
        default="postgresql+psycopg://guitarvis:guitarvis@localhost:5432/guitarvis",
        repr=False,
    )
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    # Presigned URLs are signed for this host, because a browser has to reach
    # it. It differs from s3_endpoint once the api runs somewhere a browser
    # cannot address by the same name. Unset, it is s3_endpoint.
    s3_public_endpoint: str | None = None
    s3_access_key: str = "guitarvis"
    s3_secret_key: str = field(default="guitarvis-secret", repr=False)
    s3_bucket: str = "guitarvis"
    s3_region: str = "us-east-1"
    max_upload_mb: int = 150  # a ten-minute 16-bit stereo WAV is about 106 MB
    max_active_jobs_per_ip: int = 2
    job_timeout_sec: int = 1800
    device: str | None = None  # worker only: the torch device, e.g. "cuda"
    # Spec 012's kill switch. Off unless a deployment turns it on, so one
    # that has not decided fetches nothing. The api and the worker each read
    # their own, at start.
    url_ingestion: bool = False

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        values: dict[str, Any] = {}
        for spec in fields(cls):
            name = _PREFIX + spec.name.upper()
            raw = env.get(name, "")
            if raw == "":
                continue
            if spec.type is int:
                values[spec.name] = _parse_int(name, raw)
            elif spec.type is bool:
                values[spec.name] = _parse_bool(name, raw)
            else:
                values[spec.name] = raw
        return cls(**values)


_TRUE = frozenset({"1", "true", "on"})
_FALSE = frozenset({"0", "false", "off"})


def _parse_bool(name: str, raw: str) -> bool:
    """A switch, read as strictly as a number: a typo fails at start, rather
    than leaving a feature in a state nobody chose."""
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"{name} must be 1, true, on, 0, false or off, got {raw!r}")


def _parse_int(name: str, raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got {value}")
    return value
