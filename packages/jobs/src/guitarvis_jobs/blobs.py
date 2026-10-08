"""Object storage for uploads, stems and cached stage output.

Keys are plain strings laid out as spec 005 describes: `uploads/{hash}{ext}`
for originals, `cache/v{N}/{hash}/...` for stage output.
"""

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

PRESIGN_EXPIRES_SEC = 15 * 60


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


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    _conforms: BlobStore = InMemoryBlobStore()
