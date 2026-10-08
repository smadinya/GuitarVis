"""The BlobStore contract, run against the in-memory twin and against S3."""

import urllib.request
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from guitarvis_jobs.blobs import (
    PRESIGN_EXPIRES_SEC,
    BlobNotFound,
    BlobStore,
    InMemoryBlobStore,
    S3BlobStore,
    content_type_for,
    s3_client,
)
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.testing import integration_settings, require, s3_blob_store


@pytest.fixture(params=["memory", "s3"])
def blobs(request: pytest.FixtureRequest) -> Iterator[BlobStore]:
    if request.param == "memory":
        yield InMemoryBlobStore()
        return
    with s3_blob_store() as store:
        yield store


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


def test_a_presigned_url_is_signed_for_the_public_endpoint() -> None:
    # No network: presigning is local. The browser, not the api, fetches it.
    store = S3BlobStore.from_settings(
        Settings(s3_public_endpoint="http://public.example:9000")
    )

    url = store.presign_get("uploads/k.mp3", expires_sec=60)

    assert url.startswith("http://public.example:9000/guitarvis/uploads/k.mp3?")


def test_without_a_public_endpoint_urls_are_signed_for_the_endpoint() -> None:
    # Setting only GUITARVIS_S3_ENDPOINT must not sign URLs for localhost.
    store = S3BlobStore.from_settings(Settings(s3_endpoint="http://s3.example:9000"))

    url = store.presign_get("uploads/k.mp3", expires_sec=60)

    assert url.startswith("http://s3.example:9000/guitarvis/uploads/k.mp3?")


def test_a_presigned_s3_url_serves_byte_ranges() -> None:
    """Seeking needs Range, which is why the api redirects rather than proxies."""
    with s3_blob_store() as store:
        store.put_bytes("uploads/range.wav", b"0123456789")
        url = store.presign_get("uploads/range.wav", expires_sec=PRESIGN_EXPIRES_SEC)

        request = urllib.request.Request(url, headers={"Range": "bytes=2-5"})
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 206
            assert response.read() == b"2345"


def _delete_bucket_if_present(client: Any, bucket: str) -> None:
    try:
        client.delete_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchBucket"}:
            raise


def test_ensure_bucket_creates_a_missing_bucket_and_is_repeatable() -> None:
    require("storage")
    # A bucket of its own, deleted whatever happens: the shared test bucket
    # already exists by the time any test runs, so it cannot show creation.
    settings = replace(integration_settings(), s3_bucket="guitarvis-test-ensure")
    client = s3_client(settings, settings.s3_endpoint)
    store = S3BlobStore.from_settings(settings)
    _delete_bucket_if_present(client, settings.s3_bucket)  # a crashed earlier run
    try:
        with pytest.raises(ClientError):
            client.head_bucket(Bucket=settings.s3_bucket)

        store.ensure_bucket()
        client.head_bucket(Bucket=settings.s3_bucket)  # raises unless it exists

        store.ensure_bucket()  # repeatable: no error, still there
        client.head_bucket(Bucket=settings.s3_bucket)
    finally:
        _delete_bucket_if_present(client, settings.s3_bucket)


STEM_KEY = f"cache/v1/{'a' * 64}/separation/stem.wav"


@pytest.mark.parametrize(
    ("key", "content_type"),
    [
        ("uploads/h.mp3", "audio/mpeg"),
        ("uploads/h.wav", "audio/wav"),
        ("uploads/h.flac", "audio/flac"),
        ("uploads/h.ogg", "audio/ogg"),
        ("uploads/h.opus", "audio/ogg"),
        ("uploads/h.m4a", "audio/mp4"),
        ("uploads/h.aac", "audio/mp4"),
        ("uploads/h.mp4", "audio/mp4"),
        ("uploads/h.aif", "audio/aiff"),
        ("uploads/h.aiff", "audio/aiff"),
        ("uploads/h.webm", "audio/webm"),
        ("cache/v1/h/separation/result.json", "application/json"),
        (STEM_KEY, "audio/wav"),
        ("uploads/h.html", "application/octet-stream"),
        ("uploads/h.svg", "application/octet-stream"),
        ("uploads/h", "application/octet-stream"),
    ],
)
def test_content_type_comes_from_an_allow_list(key: str, content_type: str) -> None:
    assert content_type_for(key) == content_type


@pytest.mark.parametrize("put", ["bytes", "file"])
@pytest.mark.parametrize(
    ("key", "content_type"),
    [
        # An upload keeps its client's extension; a browser must never be
        # handed one to render.
        ("uploads/x.html", "application/octet-stream"),
        ("uploads/x.mp3", "audio/mpeg"),
        (STEM_KEY, "audio/wav"),
    ],
)
def test_stored_objects_carry_a_content_type_from_an_allow_list(
    key: str, content_type: str, put: str, tmp_path: Path
) -> None:
    with s3_blob_store() as store:
        body = b"<script>alert(1)</script>"
        if put == "bytes":
            store.put_bytes(key, body)
        else:
            path = tmp_path / "body"
            path.write_bytes(body)
            store.put_file(key, path)

        settings = integration_settings()
        head = s3_client(settings, settings.s3_endpoint).head_object(
            Bucket=store.bucket, Key=key
        )

    assert head["ContentType"] == content_type
