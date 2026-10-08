"""Stage caching: a retried job resumes after the last stage that finished."""

import json
import logging
from collections.abc import Sequence
from pathlib import Path

import pytest
from guitarvis_core.contracts import (
    FailureReason,
    IngestedAudio,
    NoteEvent,
    PipelineError,
    SeparationProgress,
    SeparationResult,
    Separator,
    StructureAnalyzer,
    StructureResult,
    Transcriber,
)
from guitarvis_core.tabdoc import Beat, Chord, Section, Timing
from guitarvis_jobs.blobs import InMemoryBlobStore
from guitarvis_worker.caching import (
    CACHE_VERSION,
    CachedAnalyzer,
    CachedSeparator,
    CachedTranscriber,
    CacheKeys,
)
from guitarvis_worker.pipeline import run_pipeline
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper

KEYS = CacheKeys("f" * 64)
EVENTS = [NoteEvent(onset=1.0, duration=0.5, midi=52, confidence=0.8)]
STRUCTURE = StructureResult(
    timing=Timing(beats=[Beat(t=0.5, bar=1, beat=1)], tempo_bpm_avg=96.0),
    chords=[Chord(t=0.0, dur=2.0, symbol="Am", confidence=0.7)],
    sections=[Section(t=0.0, dur=8.0, label="verse")],
    warnings=["Chord detection was unsure in places."],
)


class CountingSeparator:
    def __init__(
        self,
        stem: Path,
        warnings: Sequence[str] = (),
        error: Exception | None = None,
    ) -> None:
        self.stem = stem
        self.warnings = list(warnings)
        self.error = error
        self.calls = 0

    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if progress is not None:
            progress(0.5)
        return SeparationResult(stem_path=self.stem, warnings=list(self.warnings))


class CountingTranscriber:
    def __init__(
        self, events: Sequence[NoteEvent] = EVENTS, error: Exception | None = None
    ) -> None:
        self.events = list(events)
        self.error = error
        self.calls = 0

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.events)


class CountingAnalyzer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return STRUCTURE


class FlakyBlobStore(InMemoryBlobStore):
    """Storage that cannot be read, or cannot be written."""

    def __init__(self, *, reads_fail: bool = False, writes_fail: bool = False) -> None:
        super().__init__()
        self.reads_fail = reads_fail
        self.writes_fail = writes_fail

    def exists(self, key: str) -> bool:
        if self.reads_fail:
            raise ConnectionError("storage went away")
        return super().exists(key)

    def put_bytes(self, key: str, data: bytes) -> None:
        if self.writes_fail:
            raise ConnectionError("storage went away")
        super().put_bytes(key, data)


def stem_file(tmp_path: Path) -> Path:
    path = tmp_path / "guitar.wav"
    path.write_bytes(b"stem-bytes")
    return path


def test_keys_are_versioned_and_per_upload() -> None:
    assert CACHE_VERSION == 1
    assert KEYS.prefix == f"cache/v1/{'f' * 64}"
    assert KEYS.stem == f"{KEYS.prefix}/separation/stem.wav"
    assert KEYS.separation == f"{KEYS.prefix}/separation/result.json"
    assert KEYS.transcription == f"{KEYS.prefix}/transcription.json"
    assert KEYS.structure == f"{KEYS.prefix}/structure.json"
    assert CacheKeys("e" * 64).prefix != KEYS.prefix
    assert CacheKeys("f" * 64, version=2).prefix != KEYS.prefix


def test_the_decorators_implement_the_stage_protocols(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    assert isinstance(
        CachedSeparator(CountingSeparator(tmp_path), blobs, KEYS, tmp_path), Separator
    )
    assert isinstance(
        CachedTranscriber(CountingTranscriber(), blobs, KEYS), Transcriber
    )
    assert isinstance(
        CachedAnalyzer(CountingAnalyzer(), blobs, KEYS), StructureAnalyzer
    )


def test_a_separation_miss_runs_the_stage_and_stores_its_output(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    inner = CountingSeparator(stem_file(tmp_path), warnings=["used the 4-stem track"])
    seen: list[float] = []

    result = CachedSeparator(inner, blobs, KEYS, tmp_path).isolate(
        tmp_path / "upload.mp3", progress=seen.append
    )

    assert inner.calls == 1
    assert seen == [0.5]  # progress passes straight through on a miss
    assert result.warnings == ["used the 4-stem track"]
    assert blobs.get_bytes(KEYS.stem) == b"stem-bytes"
    assert json.loads(blobs.get_bytes(KEYS.separation)) == {
        "stem": "guitar",
        "warnings": ["used the 4-stem track"],
    }


def test_a_separation_hit_restores_the_stem_without_running_the_stage(
    tmp_path: Path,
) -> None:
    blobs = InMemoryBlobStore()
    first = CountingSeparator(stem_file(tmp_path), warnings=["w"])
    CachedSeparator(first, blobs, KEYS, tmp_path).isolate(tmp_path / "upload.mp3")

    retry_dir = tmp_path / "retry"
    second = CountingSeparator(tmp_path / "unused.wav")
    result = CachedSeparator(second, blobs, KEYS, retry_dir).isolate(
        retry_dir / "upload.mp3"
    )

    assert second.calls == 0
    assert result.stem_path == retry_dir / "cached-separation" / "stem.wav"
    assert result.stem_path.read_bytes() == b"stem-bytes"
    assert result.warnings == ["w"]


def test_a_failed_separation_stores_nothing(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    inner = CountingSeparator(
        tmp_path,
        error=PipelineError(FailureReason.NO_GUITAR_DETECTED, "No clear guitar part"),
    )

    with pytest.raises(PipelineError):
        CachedSeparator(inner, blobs, KEYS, tmp_path).isolate(tmp_path / "a.mp3")

    assert not blobs.exists(KEYS.separation)
    assert not blobs.exists(KEYS.stem)


def test_a_result_without_its_stem_is_a_miss(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    blobs.put_bytes(KEYS.separation, b'{"stem": "guitar", "warnings": []}')
    inner = CountingSeparator(stem_file(tmp_path))

    CachedSeparator(inner, blobs, KEYS, tmp_path).isolate(tmp_path / "a.mp3")

    assert inner.calls == 1


def test_failing_to_store_the_stem_fails_the_attempt(tmp_path: Path) -> None:
    # The api serves this stem as the guitar track, so it must be stored;
    # the exception reaches the runner, which hands the job back to RQ.
    inner = CountingSeparator(stem_file(tmp_path))

    with pytest.raises(ConnectionError):
        CachedSeparator(
            inner, FlakyBlobStore(writes_fail=True), KEYS, tmp_path
        ).isolate(tmp_path / "a.mp3")


def test_a_transcription_miss_then_hit(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    first = CountingTranscriber()
    assert CachedTranscriber(first, blobs, KEYS).transcribe(tmp_path) == EVENTS

    second = CountingTranscriber(events=[])
    assert CachedTranscriber(second, blobs, KEYS).transcribe(tmp_path) == EVENTS
    assert (first.calls, second.calls) == (1, 0)


def test_an_empty_transcription_is_cached_too(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    CachedTranscriber(CountingTranscriber(events=[]), blobs, KEYS).transcribe(tmp_path)

    again = CountingTranscriber()
    assert CachedTranscriber(again, blobs, KEYS).transcribe(tmp_path) == []
    assert again.calls == 0


def test_a_failed_transcription_stores_nothing(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    inner = CountingTranscriber(error=RuntimeError("model failed to load"))

    with pytest.raises(RuntimeError):
        CachedTranscriber(inner, blobs, KEYS).transcribe(tmp_path)

    assert not blobs.exists(KEYS.transcription)


def test_a_storage_failure_while_caching_notes_does_not_cost_the_notes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Review Focus 2: through the real pipeline, the notes still land."""
    blobs = FlakyBlobStore(writes_fail=True)
    audio_path = tmp_path / "upload.wav"
    audio_path.write_bytes(b"")

    with caplog.at_level(logging.WARNING, logger="guitarvis_worker.caching"):
        result = run_pipeline(
            IngestedAudio(path=audio_path, title="song", duration_sec=10.0),
            separator=CountingSeparator(audio_path),
            transcriber=CachedTranscriber(CountingTranscriber(), blobs, KEYS),
            analyzer=CountingAnalyzer(),
            mapper=ViterbiFretboardMapper(),
        )

    assert len(result.document.notes) == 1
    assert not any("Transcription failed" in w for w in result.document.warnings)
    assert "cache write failed" in caplog.text


def test_an_unreadable_cache_is_a_miss(tmp_path: Path) -> None:
    inner = CountingTranscriber()

    events = CachedTranscriber(inner, FlakyBlobStore(reads_fail=True), KEYS).transcribe(
        tmp_path
    )

    assert events == EVENTS
    assert inner.calls == 1


def test_a_corrupt_cache_entry_is_a_miss(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    blobs.put_bytes(KEYS.transcription, b"not json at all")
    inner = CountingTranscriber()

    assert CachedTranscriber(inner, blobs, KEYS).transcribe(tmp_path) == EVENTS
    assert inner.calls == 1


def test_structure_round_trips_through_the_cache(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()
    first = CountingAnalyzer()
    CachedAnalyzer(first, blobs, KEYS).analyze(tmp_path / "stem", tmp_path / "mix")

    second = CountingAnalyzer()
    restored = CachedAnalyzer(second, blobs, KEYS).analyze(
        tmp_path / "stem", tmp_path / "mix"
    )

    assert restored == STRUCTURE
    assert second.calls == 0


def test_a_failed_analysis_stores_nothing(tmp_path: Path) -> None:
    blobs = InMemoryBlobStore()

    with pytest.raises(RuntimeError):
        CachedAnalyzer(CountingAnalyzer(error=RuntimeError("x")), blobs, KEYS).analyze(
            tmp_path, tmp_path
        )

    assert not blobs.exists(KEYS.structure)
