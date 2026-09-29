"""`make eval-data`: fetch GuitarSet from Zenodo, verify it, unpack it.

Into a cache outside the repo, never into git. Each archive is checked
against the MD5 Zenodo publishes before anything is unpacked, and an archive
already unpacked is skipped, so rerunning is cheap.
"""

import argparse
import hashlib
import shutil
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from guitarvis_eval.dataset import ANNOTATION_DIR, MIC_AUDIO_DIR, data_dir

ZENODO_RECORD = "https://zenodo.org/api/records/3371780/files"
CHUNK = 1 << 20


@dataclass(frozen=True)
class Archive:
    filename: str
    md5: str
    unpack_to: str  # directory under the data root

    @property
    def url(self) -> str:
        return f"{ZENODO_RECORD}/{self.filename}/content"


# Checksums as published on the Zenodo record, verified against a download
# on 2026-09-29.
ANNOTATIONS = Archive(
    "annotation.zip", "b39b78e63d3446f2e54ddb7a54df9b10", ANNOTATION_DIR
)
MIC_AUDIO = Archive(
    "audio_mono-mic.zip", "275966d6610ac34999b58426beb119c3", MIC_AUDIO_DIR
)


class ChecksumMismatch(Exception):
    """A downloaded archive is not the one Zenodo published."""


def md5_of(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(archive: Archive, root: Path, url: str | None = None) -> Path:
    """Download, verify, unpack. Returns the unpacked directory.

    `url` overrides the Zenodo URL; tests pass a file:// URL.
    """
    target = root / archive.unpack_to
    if target.is_dir() and any(target.iterdir()):
        return target

    root.mkdir(parents=True, exist_ok=True)
    partial = root / f"{archive.filename}.part"
    with (
        urllib.request.urlopen(url or archive.url) as response,
        partial.open("wb") as out,
    ):
        shutil.copyfileobj(response, out, CHUNK)

    actual = md5_of(partial)
    if actual != archive.md5:
        partial.unlink()
        raise ChecksumMismatch(
            f"{archive.filename}: expected MD5 {archive.md5}, got {actual}"
        )

    # Unpack beside the target and rename, so an interrupted unpack never
    # leaves a half-filled directory that the skip check above would trust.
    staging = root / f"{archive.unpack_to}.part"
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(partial) as bundle:
        bundle.extractall(staging)
    staging.replace(target)
    partial.unlink()
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m guitarvis_eval.download")
    parser.add_argument(
        "--audio",
        action="store_true",
        help="also fetch the mic audio (about 650 MB), needed only for --full",
    )
    args = parser.parse_args(argv)

    root = data_dir()
    archives = [ANNOTATIONS, MIC_AUDIO] if args.audio else [ANNOTATIONS]
    for archive in archives:
        print(f"{archive.filename} → {root / archive.unpack_to}", file=sys.stderr)
        try:
            fetch(archive, root)
        except (OSError, ChecksumMismatch) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
