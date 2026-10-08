"""Fetching GuitarSet: verified before unpacked, skipped when present."""

import hashlib
import zipfile
from pathlib import Path

import pytest
from guitarvis_eval.download import (
    ANNOTATIONS,
    MIC_AUDIO,
    Archive,
    ChecksumMismatch,
    fetch,
)


def make_zip(path: Path) -> str:
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("00_a_comp.jams", "{}")
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_fetch_verifies_and_unpacks(tmp_path: Path) -> None:
    source = tmp_path / "annotation.zip"
    archive = Archive("annotation.zip", make_zip(source), "annotation")
    root = tmp_path / "data"

    target = fetch(archive, root, url=source.as_uri())

    assert target == root / "annotation"
    assert (target / "00_a_comp.jams").read_text() == "{}"
    assert not list(root.glob("*.part"))  # no leftovers


def test_a_bad_checksum_unpacks_nothing(tmp_path: Path) -> None:
    source = tmp_path / "annotation.zip"
    make_zip(source)
    archive = Archive("annotation.zip", "0" * 32, "annotation")
    root = tmp_path / "data"

    with pytest.raises(ChecksumMismatch):
        fetch(archive, root, url=source.as_uri())
    assert not (root / "annotation").exists()
    assert not list(root.glob("*.part"))


def test_an_unpacked_archive_is_not_fetched_again(tmp_path: Path) -> None:
    root = tmp_path / "data"
    (root / "annotation").mkdir(parents=True)
    (root / "annotation" / "existing.jams").write_text("{}")
    archive = Archive("annotation.zip", "0" * 32, "annotation")

    # The URL does not exist; reaching for it would raise.
    assert (
        fetch(archive, root, url=(tmp_path / "nope.zip").as_uri())
        == root / "annotation"
    )


def test_archives_point_at_the_zenodo_record() -> None:
    assert ANNOTATIONS.url == (
        "https://zenodo.org/api/records/3371780/files/annotation.zip/content"
    )
    assert ANNOTATIONS.md5 == "b39b78e63d3446f2e54ddb7a54df9b10"
    assert MIC_AUDIO.md5 == "275966d6610ac34999b58426beb119c3"
