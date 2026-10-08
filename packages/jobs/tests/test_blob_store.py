"""The BlobStore contract. Task 7 adds an "s3" param against RustFS."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from guitarvis_jobs.blobs import (
    PRESIGN_EXPIRES_SEC,
    BlobNotFound,
    BlobStore,
    InMemoryBlobStore,
)


@pytest.fixture(params=["memory"])
def blobs(request: pytest.FixtureRequest) -> Iterator[BlobStore]:
    yield InMemoryBlobStore()


def test_bytes_round_trip(blobs: BlobStore) -> None:
    blobs.put_bytes("cache/v1/h/transcription.json", b'[{"midi": 52}]')

    assert blobs.get_bytes("cache/v1/h/transcription.json") == b'[{"midi": 52}]'


def test_a_file_round_trips_into_a_directory_that_does_not_exist_yet(
    blobs: BlobStore, tmp_path: Path
) -> None:
    source = tmp_path / "stem.wav"
    source.write_bytes(b"RIFF....WAVE")
    blobs.put_file("cache/v1/h/separation/stem.wav", source)

    target = tmp_path / "restored" / "deeper" / "stem.wav"
    blobs.get_file("cache/v1/h/separation/stem.wav", target)

    assert target.read_bytes() == b"RIFF....WAVE"


def test_exists(blobs: BlobStore) -> None:
    assert not blobs.exists("uploads/nothing.mp3")
    blobs.put_bytes("uploads/something.mp3", b"x")
    assert blobs.exists("uploads/something.mp3")


def test_a_put_replaces_what_was_there(blobs: BlobStore) -> None:
    blobs.put_bytes("k", b"old")
    blobs.put_bytes("k", b"new")

    assert blobs.get_bytes("k") == b"new"


def test_a_missing_key_raises_blob_not_found(blobs: BlobStore, tmp_path: Path) -> None:
    with pytest.raises(BlobNotFound):
        blobs.get_bytes("cache/v1/none.json")

    target = tmp_path / "out.wav"
    with pytest.raises(BlobNotFound):
        blobs.get_file("cache/v1/none.wav", target)
    assert not target.exists()


def test_presign_names_the_key(blobs: BlobStore) -> None:
    blobs.put_bytes("uploads/abc.mp3", b"x")

    url = blobs.presign_get("uploads/abc.mp3", expires_sec=PRESIGN_EXPIRES_SEC)

    assert "uploads/abc.mp3" in url


def test_presign_lifetime_is_fifteen_minutes() -> None:
    assert PRESIGN_EXPIRES_SEC == 15 * 60


def test_ping_answers(blobs: BlobStore) -> None:
    blobs.ping()
