"""Per-stage caching, so a retried job resumes after the last stage that finished.

Each decorator wraps a real stage and implements that stage's own Protocol, so
run_pipeline and the stages know nothing about it. Entries are keyed by the
upload's content hash, under `cache/v{CACHE_VERSION}/{hash}/`.

A stage that raises stores nothing: the pipeline degrades exactly as it would
without a cache, and the next attempt runs the stage again rather than
replaying its failure. Nor does a structure result with warnings, which mean
a half of the stage failed and degraded inside it rather than raising. Stage
4 is fast and deterministic and is not cached.

For transcription and structure the cache is only an optimisation, so a
storage error reading or writing it is logged and treated as a miss. It must
never surface as the stage failing, which the pipeline would turn into a
degraded document. Separation's stem is different: the api serves it as the
guitar track, so failing to store it fails the attempt, and RQ retries.
"""

import dataclasses
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from guitarvis_core.contracts import (
    NoteEvent,
    SeparationProgress,
    SeparationResult,
    Separator,
    StructureAnalyzer,
    StructureResult,
    Transcriber,
)
from guitarvis_core.tabdoc import Chord, Section, Timing
from guitarvis_jobs.blobs import BlobNotFound, BlobStore

log = logging.getLogger(__name__)

# Bump by hand whenever a stage's output for the same input would change: a
# new model, a changed threshold, a fixed bug. Nothing enforces it. Forget,
# and audio processed before the change keeps being served the old result.
CACHE_VERSION = 1


@dataclass(frozen=True)
class CacheKeys:
    content_hash: str
    version: int = CACHE_VERSION

    @property
    def prefix(self) -> str:
        return f"cache/v{self.version}/{self.content_hash}"

    @property
    def stem(self) -> str:
        return f"{self.prefix}/separation/stem.wav"

    @property
    def separation(self) -> str:
        return f"{self.prefix}/separation/result.json"

    @property
    def transcription(self) -> str:
        return f"{self.prefix}/transcription.json"

    @property
    def structure(self) -> str:
        return f"{self.prefix}/structure.json"


def _load[T](blobs: BlobStore, key: str, decode: Callable[[Any], T]) -> T | None:
    """The cached value at `key`, or None on a miss.

    A store that cannot be read, or an entry that cannot be decoded, is a
    miss too: logged, never raised.
    """
    try:
        if not blobs.exists(key):
            return None
        return decode(json.loads(blobs.get_bytes(key)))
    except Exception:
        log.warning("cache read failed for %s; running the stage", key, exc_info=True)
        return None


def _store(blobs: BlobStore, key: str, value: Any) -> None:
    """Cache `value`. A failure is logged, never raised: the result stands."""
    try:
        blobs.put_bytes(key, json.dumps(value).encode())
    except Exception:
        log.warning(
            "cache write failed for %s; using the result anyway", key, exc_info=True
        )


class CachedSeparator:
    """Implements Separator around another Separator."""

    def __init__(
        self, inner: Separator, blobs: BlobStore, keys: CacheKeys, work_dir: Path
    ) -> None:
        self._inner = inner
        self._blobs = blobs
        self._keys = keys
        self._work_dir = work_dir

    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        cached = self._restore()
        if cached is not None:
            return cached

        result = self._inner.isolate(audio_path, progress=progress)
        # The stem first, then result.json, whose presence is what marks the
        # entry complete. Not _store: a failure here must fail the attempt.
        self._blobs.put_file(self._keys.stem, result.stem_path)
        self._blobs.put_bytes(
            self._keys.separation,
            json.dumps(
                {"stem": result.stem_path.stem, "warnings": list(result.warnings)}
            ).encode(),
        )
        return result

    def _restore(self) -> SeparationResult | None:
        warnings = _load(
            self._blobs, self._keys.separation, lambda meta: list(meta["warnings"])
        )
        if warnings is None:
            return None
        stem_path = self._work_dir / "cached-separation" / "stem.wav"
        try:
            self._blobs.get_file(self._keys.stem, stem_path)
        except BlobNotFound:
            log.warning(
                "%s has no stem beside it; separating again", self._keys.separation
            )
            return None
        return SeparationResult(stem_path=stem_path, warnings=warnings)


class CachedTranscriber:
    """Implements Transcriber around another Transcriber."""

    def __init__(self, inner: Transcriber, blobs: BlobStore, keys: CacheKeys) -> None:
        self._inner = inner
        self._blobs = blobs
        self._keys = keys

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        cached = _load(
            self._blobs,
            self._keys.transcription,
            lambda items: [NoteEvent(**item) for item in items],
        )
        if cached is not None:
            return cached
        events = self._inner.transcribe(stem_path)
        _store(
            self._blobs,
            self._keys.transcription,
            [dataclasses.asdict(event) for event in events],
        )
        return events


class CachedAnalyzer:
    """Implements StructureAnalyzer around another StructureAnalyzer."""

    def __init__(
        self, inner: StructureAnalyzer, blobs: BlobStore, keys: CacheKeys
    ) -> None:
        self._inner = inner
        self._blobs = blobs
        self._keys = keys

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        cached = _load(self._blobs, self._keys.structure, _structure_from_json)
        if cached is not None:
            return cached
        result = self._inner.analyze(stem_path, mix_path)
        if not result.warnings:  # a half failed, perhaps by chance
            _store(self._blobs, self._keys.structure, _structure_to_json(result))
        return result


def _structure_to_json(result: StructureResult) -> dict[str, Any]:
    return {
        "timing": result.timing.model_dump(mode="json"),
        "chords": [chord.model_dump(mode="json") for chord in result.chords],
        "sections": [section.model_dump(mode="json") for section in result.sections],
        "warnings": list(result.warnings),
    }


def _structure_from_json(data: dict[str, Any]) -> StructureResult:
    return StructureResult(
        timing=Timing.model_validate(data["timing"]),
        chords=[Chord.model_validate(chord) for chord in data["chords"]],
        sections=[Section.model_validate(section) for section in data["sections"]],
        warnings=list(data["warnings"]),
    )


if TYPE_CHECKING:  # Static conformance: the typed assignments are what mypy checks.
    from typing import cast

    from guitarvis_jobs.blobs import InMemoryBlobStore

    _blobs = InMemoryBlobStore()
    _s: Separator = CachedSeparator(
        cast(Separator, None), _blobs, CacheKeys(""), Path()
    )
    _t: Transcriber = CachedTranscriber(cast(Transcriber, None), _blobs, CacheKeys(""))
    _a: StructureAnalyzer = CachedAnalyzer(
        cast(StructureAnalyzer, None), _blobs, CacheKeys("")
    )
