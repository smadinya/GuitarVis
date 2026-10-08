"""Where the services are, and the limits the api enforces.

A frozen stdlib dataclass read from GUITARVIS_* environment variables — one
per field, named after it. The defaults match compose.yaml, so local
development needs no env file.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

_PREFIX = "GUITARVIS_"


@dataclass(frozen=True)
class Settings:
    database_url: str = (
        "postgresql+psycopg://guitarvis:guitarvis@localhost:5432/guitarvis"
    )
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    # Presigned URLs are signed for this host, because a browser has to reach
    # it. It differs from s3_endpoint once the api runs somewhere a browser
    # cannot address by the same name.
    s3_public_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "guitarvis"
    s3_secret_key: str = "guitarvis-secret"
    s3_bucket: str = "guitarvis"
    s3_region: str = "us-east-1"
    max_upload_mb: int = 150  # a ten-minute 16-bit stereo WAV is about 106 MB
    max_active_jobs_per_ip: int = 2
    job_timeout_sec: int = 1800
    device: str | None = None  # worker only: the torch device, e.g. "cuda"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        values: dict[str, Any] = {}
        for field in fields(cls):
            name = _PREFIX + field.name.upper()
            raw = env.get(name, "")
            if raw == "":
                continue
            values[field.name] = _parse_int(name, raw) if field.type is int else raw
        return cls(**values)


def _parse_int(name: str, raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got {value}")
    return value
