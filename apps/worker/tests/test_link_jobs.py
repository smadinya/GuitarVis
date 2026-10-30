"""Link jobs in the worker (spec 012): every W, D, P and S row of the failure
catalog, retried or not as it says, with a fake fetcher and in-memory stores.
The download is a stage of its own and fills the first 5% of progress."""

import contextlib
import hashlib
import logging
import os
import shutil
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import guitarvis_fetch.fetcher
import pytest
from guitarvis_core.audio import probe_duration
from guitarvis_core.contracts import (
    FailureReason,
    IngestedAudio,
    NoteEvent,
    PipelineError,
    SeparationProgress,
    SeparationResult,
    StructureResult,
)
from guitarvis_core.tabdoc import TabDocument, Timing
from guitarvis_fetch.catalog import FetchKind, message_for
from guitarvis_fetch.fetcher import (
    NO_DENO_WARNING,
    ChildFetcher,
    Download,
    FetchError,
    Progress,
    VideoInfo,
)
from guitarvis_fetch.links import Link, parse
from guitarvis_fetch.testing import FakeFetcher, video_info, write_wav
from guitarvis_jobs.blobs import InMemoryBlobStore
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, Job, JobStatus
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.store import InMemoryJobStore
from guitarvis_jobs.testing import sample_link_job, sample_new_job
from guitarvis_worker import runner
from guitarvis_worker.caching import CacheKeys
from guitarvis_worker.runner import Stages, WorkerDeps, open_deps, process_job
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper

requires_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None,
    reason="ffprobe not installed; install ffmpeg",
)

LINK = parse("https://www.youtube.com/watch?v=kPdv44HtEoA")
SENTINEL = "SENTINEL-4f2a"
PROBED = 37.059


class StubSeparator:
    def __init__(self) -> None:
        self.calls = 0

    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        self.calls += 1
        if progress is not None:
            progress(0.5)
        return SeparationResult(stem_path=audio_path)


class StubTranscriber:
    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        return [NoteEvent(onset=1.0, duration=0.5, midi=52, confidence=0.8)]


class StubAnalyzer:
    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        return StructureResult(timing=Timing(), chords=[], sections=[])


@dataclass
class Harness:
    store: InMemoryJobStore = field(default_factory=InMemoryJobStore)
    blobs: InMemoryBlobStore = field(default_factory=InMemoryBlobStore)
    fetcher: FakeFetcher = field(default_factory=FakeFetcher)
    separator: StubSeparator = field(default_factory=StubSeparator)
    probe: Callable[[Path], float] = lambda path: PROBED
    links_on: bool = True
    job_id: str = ""

    def __post_init__(self) -> None:
        job, _ = self.store.create(sample_link_job())
        self.job_id = job.id

    def deps(self) -> WorkerDeps:
        return WorkerDeps(
            store=self.store,
            blobs=self.blobs,
            stages=lambda work_dir: Stages(
                separator=self.separator,
                transcriber=StubTranscriber(),
                analyzer=StubAnalyzer(),
                mapper=ViterbiFretboardMapper(),
            ),
            fetcher=self.fetcher if self.links_on else None,
            max_download_bytes=1024 * 1024,
            probe=self.probe,
        )

    def run(self, retries_left: int = 2) -> None:
        process_job(self.job_id, self.deps(), retries_left=retries_left)

    def row(self) -> Job:
        row = self.store.get(self.job_id)
        assert row is not None
        return row


@pytest.fixture
def harness() -> Harness:
    return Harness()


def wav_bytes(tmp_path: Path) -> bytes:
    return write_wav(tmp_path / "w.wav").read_bytes()


# Success


def test_a_link_job_downloads_stores_and_runs(harness: Harness, tmp_path: Path) -> None:
    harness.fetcher.content = wav_bytes(tmp_path)
    content_hash = hashlib.sha256(harness.fetcher.content).hexdigest()

    harness.run()

    row = harness.row()
    assert (row.status, row.percent, row.attempts) == (JobStatus.SUCCEEDED, 100, 1)
    assert row.upload_key == f"uploads/{content_hash}.wav"  # content-addressed
    assert harness.blobs.get_bytes(row.upload_key) == harness.fetcher.content
    assert row.duration_sec == PROBED  # ffprobe's, not the metadata's 37.0
    assert row.content_hash == LINK.dedupe_key  # still the video's identity
    assert row.stem_key == CacheKeys(content_hash).stem  # cached by the bytes
    document = TabDocument.model_validate(row.document)
    assert document.source.title == row.title
    assert document.source.duration_sec == PROBED
    assert document.source.audio_url == f"/jobs/{row.id}/audio/mix"
    assert harness.fetcher.downloads == [LINK]


def test_a_link_jobs_progress_runs_from_download_into_five_to_a_hundred(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, int]] = []
    write = harness.store.set_progress

    def recording(job_id: str, stage: str, percent: int) -> bool:
        seen.append((stage, percent))
        return write(job_id, stage, percent)

    monkeypatch.setattr(harness.store, "set_progress", recording)
    harness.run()

    assert seen == [
        ("download", 0),
        ("download", 2),
        ("download", 5),
        ("separation", 5),
        ("separation", 24),
        ("transcription", 43),
        ("structure", 66),
        ("fretboard", 81),
    ]


def test_a_link_and_an_upload_of_the_same_bytes_share_the_cache(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = wav_bytes(tmp_path)
    harness.fetcher.content = content
    harness.run()
    upload, _ = harness.store.create(
        sample_new_job(
            content_hash=hashlib.sha256(content).hexdigest(), upload_key="u.wav"
        )
    )
    harness.blobs.put_bytes("u.wav", content)
    monkeypatch.setattr(runner, "UploadSource", _NoProbeSource)

    process_job(upload.id, harness.deps(), retries_left=2)

    assert harness.separator.calls == 1  # the upload found the link's stem


class _NoProbeSource:
    def __init__(self, path: Path, **kwargs: object) -> None:
        self.path = path

    def fetch(self) -> IngestedAudio:
        return IngestedAudio(path=self.path, title="t", duration_sec=1.0)


# W. Before fetching


def test_links_off_fails_a_link_job_with_no_stored_audio(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:  # W1
    harness.links_on = False

    with caplog.at_level(logging.INFO, logger="guitarvis_worker"):
        harness.run()  # not retried: returns

    row = harness.row()
    assert row.failure_reason is FailureReason.LINKS_DISABLED
    assert row.failure_message == (
        "Links were turned off before this song could be fetched. "
        "Upload the audio file instead."
    )
    assert harness.fetcher.downloads == []
    [entry] = [r for r in caplog.records if r.name == "guitarvis_worker.runner"]
    assert entry.levelno == logging.INFO  # the catalog's level for W1
    assert row.id in entry.getMessage()
    assert "links are off" in entry.getMessage()
    assert "youtube.com" not in caplog.text  # the url is the row's, not the log's


def test_links_off_still_runs_a_link_job_whose_download_is_stored(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:  # W1
    harness.store.mark_running(harness.job_id)
    harness.store.attach_upload(
        harness.job_id, upload_key="uploads/abc.wav", duration_sec=1.0
    )
    harness.store.requeue(harness.job_id)
    harness.blobs.put_bytes("uploads/abc.wav", b"stored")
    monkeypatch.setattr(runner, "UploadSource", _NoProbeSource)
    harness.links_on = False

    harness.run()

    assert harness.row().status is JobStatus.SUCCEEDED
    assert harness.row().stem_key == CacheKeys("abc").stem


def test_a_retry_finds_the_download_stored_and_never_fetches(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    write = harness.store.set_progress
    crashed: list[bool] = []

    def crash_once_at_separation(job_id: str, stage: str, percent: int) -> bool:
        if stage == "separation" and not crashed:
            crashed.append(True)
            raise ConnectionError("postgres went away")
        return write(job_id, stage, percent)

    monkeypatch.setattr(harness.store, "set_progress", crash_once_at_separation)
    with pytest.raises(ConnectionError):
        harness.run(retries_left=1)
    monkeypatch.setattr(runner, "UploadSource", _NoProbeSource)

    harness.run(retries_left=0)

    assert harness.row().status is JobStatus.SUCCEEDED
    assert len(harness.fetcher.downloads) == 1


@pytest.mark.parametrize(
    "kind",
    [
        FetchKind.PRIVATE,  # L1
        FetchKind.UNAVAILABLE,  # L2
        FetchKind.GEO_RESTRICTED,  # L3
        FetchKind.AGE_RESTRICTED,  # L4
        FetchKind.MEMBERS_ONLY,  # L5
        FetchKind.LIVE,  # L6
        FetchKind.UPCOMING,  # L7
        FetchKind.POST_LIVE,  # L8
        FetchKind.NO_DURATION,  # L9
        FetchKind.TOO_LONG,  # L10
        FetchKind.NO_AUDIO,  # L11
    ],
)
def test_a_video_that_changed_in_the_queue_fails_with_its_own_reason(
    harness: Harness, kind: FetchKind
) -> None:  # W2
    harness.fetcher.download_error = FetchError(kind, duration_sec=721)

    harness.run(retries_left=2)  # no retry: returns

    row = harness.row()
    assert row.failure_reason is FetchError(kind).entry.reason
    assert row.failure_message == message_for(kind, duration_sec=721)
    assert row.failed_stage == "download"
    assert harness.separator.calls == 0


def test_a_stored_link_the_api_would_not_have_accepted_is_ours_and_never_fetched(
    harness: Harness,
) -> None:  # the api stores links canonical, so this row is a bug of ours
    bad, _ = harness.store.create(
        replace(sample_link_job(video_id="bbbbbbbbbbb"), source_url="https://a.test/x")
    )

    with pytest.raises(PipelineError):
        process_job(bad.id, harness.deps(), retries_left=0)

    row = harness.store.get(bad.id)
    assert row is not None
    assert (row.failure_reason, row.failure_message) == (
        FailureReason.INTERNAL,
        INTERNAL_FAILURE_MESSAGE,
    )
    assert harness.fetcher.downloads == []


# D. The download


RETRIED = [
    (
        "D1",
        FetchKind.NETWORK,
        FailureReason.FETCH_FAILED,
        message_for(FetchKind.NETWORK),
    ),
    (
        "D2",
        FetchKind.DOWNLOAD_TIMEOUT,
        FailureReason.FETCH_FAILED,
        message_for(FetchKind.DOWNLOAD_TIMEOUT),
    ),
    (  # our audio format, downloaded to nothing: not the video's fault
        "D7",
        FetchKind.EMPTY_DOWNLOAD,
        FailureReason.FETCH_FAILED,
        message_for(FetchKind.EMPTY_DOWNLOAD),
    ),
    ("D8", FetchKind.LOCAL_IO, FailureReason.INTERNAL, INTERNAL_FAILURE_MESSAGE),
    ("D9", FetchKind.CRASHED, FailureReason.INTERNAL, INTERNAL_FAILURE_MESSAGE),
    (
        "D10",
        FetchKind.UNKNOWN,
        FailureReason.FETCH_FAILED,
        message_for(FetchKind.UNKNOWN),
    ),
]


@pytest.mark.parametrize(("row", "kind", "reason", "message"), RETRIED)
def test_a_download_that_may_pass_is_retried(
    harness: Harness, row: str, kind: FetchKind, reason: FailureReason, message: str
) -> None:
    harness.fetcher.download_error = FetchError(kind, SENTINEL)

    with pytest.raises(PipelineError):
        harness.run(retries_left=1)

    assert harness.row().status is JobStatus.QUEUED, row


@pytest.mark.parametrize(("row", "kind", "reason", "message"), RETRIED)
def test_the_last_attempt_keeps_the_downloads_own_reason(
    harness: Harness, row: str, kind: FetchKind, reason: FailureReason, message: str
) -> None:
    harness.fetcher.download_error = FetchError(kind, SENTINEL)

    with pytest.raises(PipelineError):
        harness.run(retries_left=0)

    failed = harness.row()
    assert (failed.status, failed.failure_reason, failed.failure_message) == (
        JobStatus.FAILED,
        reason,
        message,
    ), row
    assert failed.failed_stage == "download"


@pytest.mark.parametrize(
    ("row", "kind", "reason"),
    [
        ("D3", FetchKind.RATE_LIMITED, FailureReason.FETCH_FAILED),
        ("D4", FetchKind.EXTRACTOR_BROKEN, FailureReason.FETCH_FAILED),
        ("D4", FetchKind.MISCONFIGURED, FailureReason.FETCH_FAILED),
        ("D5", FetchKind.MEDIA_REFUSED, FailureReason.FETCH_FAILED),
        ("D6", FetchKind.TOO_LARGE, FailureReason.LINK_UNUSABLE),
    ],
)
def test_a_download_that_will_not_pass_soon_is_not_retried(
    harness: Harness, row: str, kind: FetchKind, reason: FailureReason
) -> None:
    harness.fetcher.download_error = FetchError(kind, SENTINEL)

    harness.run(retries_left=2)  # returns: RQ does not retry

    failed = harness.row()
    assert (failed.failure_reason, failed.failure_message) == (
        reason,
        message_for(kind),
    ), row


def test_ytdlp_text_reaches_the_log_and_never_the_row(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    harness.fetcher.download_error = FetchError(
        FetchKind.UNKNOWN, f"ERROR: [youtube] {SENTINEL} Traceback", tail="STDERR"
    )

    with (
        caplog.at_level(logging.INFO, logger="guitarvis_worker"),
        pytest.raises(PipelineError),
    ):
        harness.run(retries_left=0)

    row = harness.row()
    assert SENTINEL not in repr(row)  # not the message, and no other field
    [line] = [m for m in caplog.messages if m.startswith("link fetch failed")]
    assert (
        f"phase=download site=youtube video={LINK.video_id} job={row.id} attempt=1"
        in line
    )
    assert SENTINEL in line and line.endswith(' tail="STDERR"')


@pytest.mark.parametrize("retries_left", [2, 0])
def test_ytdlp_text_stays_out_of_the_traceback_rq_keeps(
    harness: Harness, retries_left: int
) -> None:  # D1, D2, D7-D10
    """RQ logs a retried job's traceback at ERROR and keeps it in Redis. The
    PipelineError it is handed must carry nothing of yt-dlp's behind it."""
    harness.fetcher.download_error = FetchError(
        FetchKind.UNKNOWN, f"ERROR: [youtube] {SENTINEL} Traceback", tail="STDERR"
    )

    with pytest.raises(PipelineError) as excinfo:
        harness.run(retries_left=retries_left)

    shown = "".join(traceback.format_exception(excinfo.value))
    assert SENTINEL not in shown and "STDERR" not in shown


# (row, kind, the catalog's log level, whether it adds the end of stderr)
LOGGED = [
    ("W2", FetchKind.PRIVATE, logging.INFO, False),  # as L1
    ("W2", FetchKind.UNAVAILABLE, logging.INFO, False),  # as L2
    ("W2", FetchKind.GEO_RESTRICTED, logging.INFO, False),  # as L3
    ("W2", FetchKind.AGE_RESTRICTED, logging.INFO, False),  # as L4
    ("W2", FetchKind.MEMBERS_ONLY, logging.INFO, False),  # as L5
    ("W2", FetchKind.LIVE, logging.INFO, False),  # as L6
    ("W2", FetchKind.UPCOMING, logging.INFO, False),  # as L7
    ("W2", FetchKind.POST_LIVE, logging.INFO, False),  # as L8
    ("W2", FetchKind.NO_DURATION, logging.WARNING, False),  # as L9
    ("W2", FetchKind.TOO_LONG, logging.INFO, False),  # as L10
    ("W2", FetchKind.NO_AUDIO, logging.WARNING, False),  # as L11
    ("D1", FetchKind.NETWORK, logging.WARNING, False),
    ("D2", FetchKind.DOWNLOAD_TIMEOUT, logging.WARNING, False),
    ("D3", FetchKind.RATE_LIMITED, logging.WARNING, False),
    ("D4", FetchKind.EXTRACTOR_BROKEN, logging.ERROR, True),
    ("D4", FetchKind.MISCONFIGURED, logging.ERROR, False),  # the catalog's L16
    ("D5", FetchKind.MEDIA_REFUSED, logging.ERROR, False),  # a security event
    ("D6", FetchKind.TOO_LARGE, logging.WARNING, False),
    ("D7", FetchKind.EMPTY_DOWNLOAD, logging.ERROR, True),
    ("D8", FetchKind.LOCAL_IO, logging.ERROR, True),
    ("D9", FetchKind.CRASHED, logging.ERROR, True),
    ("D10", FetchKind.UNKNOWN, logging.ERROR, True),
]


@pytest.mark.parametrize(("row", "kind", "level", "tail"), LOGGED)
def test_a_failed_download_is_logged_once_at_the_catalogs_level(
    harness: Harness,
    caplog: pytest.LogCaptureFixture,
    row: str,
    kind: FetchKind,
    level: int,
    tail: bool,
) -> None:
    harness.fetcher.download_error = FetchError(kind, SENTINEL, tail="STDERR")

    with (
        caplog.at_level(logging.DEBUG, logger="guitarvis_worker"),
        contextlib.suppress(PipelineError),  # a retried failure is re-raised
    ):
        harness.run(retries_left=0)

    [record] = [r for r in caplog.records if r.getMessage().startswith("link fetch")]
    line = record.getMessage()
    assert record.levelno == level, row
    assert f"kind={kind.value} phase=download" in line, row
    assert (' tail="STDERR"' in line) is tail, row


def test_a_crashed_downloads_exit_code_is_logged(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:  # D9
    harness.fetcher.download_error = FetchError(FetchKind.CRASHED, "gone", exit_code=-9)

    with (
        caplog.at_level(logging.ERROR, logger="guitarvis_worker"),
        pytest.raises(PipelineError),
    ):
        harness.run(retries_left=0)

    assert "exit=-9" in caplog.text


def test_a_successful_download_is_logged_with_its_format(
    harness: Harness, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    harness.fetcher.content = wav_bytes(tmp_path)

    with caplog.at_level(logging.INFO, logger="guitarvis_worker"):
        harness.run()

    [line] = [m for m in caplog.messages if m.startswith("link fetched")]
    assert "phase=download" in line
    assert f"job={harness.job_id} attempt=1" in line
    assert "ytdlp=2026.10.26 js=deno/2.5.4" in line  # which versions answered
    assert f"format=140 ext=wav bytes={len(harness.fetcher.content)}" in line


# D. What the child says it wrote is checked, not trusted


class ClaimingFetcher:
    """A fetcher whose child names `path_of(work_dir)` and says it wrote
    `size` bytes: what ChildFetcher passes on without a look."""

    def __init__(self, path_of: Callable[[Path], Path], size: int = 1000) -> None:
        self.path_of = path_of
        self.size = size

    def lookup(self, link: Link) -> VideoInfo:
        raise NotImplementedError

    def download(
        self,
        link: Link,
        work_dir: Path,
        *,
        max_bytes: int,
        progress: Progress | None = None,
    ) -> Download:
        return Download(
            path=self.path_of(work_dir),
            info=video_info(),
            format_id="140",
            ext="wav",
            size=self.size,
        )


def run_with(harness: Harness, fetcher: ClaimingFetcher, retries_left: int) -> None:
    deps = replace(harness.deps(), fetcher=fetcher)
    process_job(harness.job_id, deps, retries_left=retries_left)


def recording_probe(harness: Harness) -> list[Path]:
    """Put a probe on the harness that records what it was asked to read."""
    asked: list[Path] = []

    def probe(path: Path) -> float:
        asked.append(path)
        return PROBED

    harness.probe = probe
    return asked


def symlink_to(outside: Path, work_dir: Path) -> Path:
    path = work_dir / "source.wav"
    path.symlink_to(outside)
    return path


@pytest.mark.parametrize(
    "named",
    [
        pytest.param(lambda work_dir, outside: outside, id="absolute"),
        pytest.param(
            lambda work_dir, outside: work_dir / os.path.relpath(outside, work_dir),
            id="traversal",
        ),
        pytest.param(
            lambda work_dir, outside: symlink_to(outside, work_dir), id="symlink"
        ),
        pytest.param(lambda work_dir, outside: Path("source.wav"), id="relative"),
    ],
)
def test_a_file_outside_the_work_dir_is_refused_before_it_is_read(
    harness: Harness,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    named: Callable[[Path, Path], Path],
) -> None:  # D9: a child that answers with a path we cannot accept is garbage
    outside = write_wav(tmp_path / "outside.wav")
    asked = recording_probe(harness)
    fetcher = ClaimingFetcher(lambda work_dir: named(work_dir, outside))

    with (
        caplog.at_level(logging.INFO, logger="guitarvis_worker"),
        pytest.raises(PipelineError),
    ):
        run_with(harness, fetcher, retries_left=0)

    row = harness.row()
    assert (row.failure_reason, row.failure_message) == (
        FailureReason.INTERNAL,
        INTERNAL_FAILURE_MESSAGE,
    )
    assert row.failed_stage == "download"
    assert row.upload_key is None  # nothing was hashed or stored
    assert asked == []  # nothing was read, not even by ffprobe
    assert str(outside) not in repr(row)
    [record] = [r for r in caplog.records if r.getMessage().startswith("link fetch")]
    assert record.levelno == logging.ERROR
    assert "kind=crashed" in record.getMessage()
    assert "outside the work directory" in record.getMessage()


def test_a_file_outside_the_work_dir_is_retried_while_attempts_remain(
    harness: Harness, tmp_path: Path
) -> None:
    outside = write_wav(tmp_path / "outside.wav")

    with pytest.raises(PipelineError):
        run_with(harness, ClaimingFetcher(lambda work_dir: outside), retries_left=1)

    assert harness.row().status is JobStatus.QUEUED


def test_a_file_bigger_than_the_cap_is_too_large_whatever_the_child_says(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:  # D6
    asked = recording_probe(harness)

    def oversized(work_dir: Path) -> Path:
        path = work_dir / "source.wav"
        path.write_bytes(b"\x00" * (1024 * 1024 + 1))  # the cap is 1 MiB here
        return path

    with caplog.at_level(logging.INFO, logger="guitarvis_worker"):
        run_with(harness, ClaimingFetcher(oversized, size=10), retries_left=2)

    row = harness.row()  # not retried: it returned
    assert (row.status, row.failure_reason, row.failure_message) == (
        JobStatus.FAILED,
        FailureReason.LINK_UNUSABLE,
        message_for(FetchKind.TOO_LARGE),
    )
    assert row.failed_stage == "download"
    assert asked == []
    [record] = [r for r in caplog.records if r.getMessage().startswith("link fetch")]
    assert record.levelno == logging.WARNING
    assert "kind=too_large" in record.getMessage()


def test_a_file_exactly_at_the_cap_is_accepted(harness: Harness) -> None:  # D6
    def at_the_cap(work_dir: Path) -> Path:
        path = write_wav(work_dir / "source.wav")
        with path.open("ab") as handle:
            handle.write(b"\x00" * (1024 * 1024 - path.stat().st_size))
        return path

    run_with(harness, ClaimingFetcher(at_the_cap), retries_left=2)

    assert harness.row().status is JobStatus.SUCCEEDED


def test_an_empty_file_is_an_empty_download_whatever_the_child_says(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:  # D7
    asked = recording_probe(harness)

    def empty(work_dir: Path) -> Path:
        path = work_dir / "source.wav"
        path.write_bytes(b"")
        return path

    with (
        caplog.at_level(logging.INFO, logger="guitarvis_worker"),
        pytest.raises(PipelineError),
    ):
        run_with(harness, ClaimingFetcher(empty, size=1000), retries_left=0)

    row = harness.row()  # ours, so retried until this, the last attempt
    assert (row.status, row.failure_reason, row.failure_message) == (
        JobStatus.FAILED,
        FailureReason.FETCH_FAILED,
        message_for(FetchKind.EMPTY_DOWNLOAD),
    )
    assert asked == []
    [record] = [r for r in caplog.records if r.getMessage().startswith("link fetch")]
    assert record.levelno == logging.ERROR
    assert "kind=empty_download" in record.getMessage()


@pytest.mark.parametrize(
    "named",
    [
        pytest.param(lambda work_dir: work_dir / "never-written.wav", id="missing"),
        pytest.param(lambda work_dir: work_dir, id="a directory"),
    ],
)
def test_a_path_that_is_no_file_is_an_empty_download(
    harness: Harness, named: Callable[[Path], Path]
) -> None:  # D7: the download produced no file
    asked = recording_probe(harness)

    with pytest.raises(PipelineError):
        run_with(harness, ClaimingFetcher(named), retries_left=0)

    row = harness.row()
    assert row.failure_reason is FailureReason.FETCH_FAILED
    assert row.failure_message == message_for(FetchKind.EMPTY_DOWNLOAD)
    assert asked == []


# P. After the download


def test_audio_ffprobe_cannot_read_is_unusable(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:  # P1
    def unreadable(path: Path) -> float:
        raise PipelineError(
            FailureReason.UNSUPPORTED_FORMAT, "That file could not be read"
        )

    harness.probe = unreadable

    with caplog.at_level(logging.INFO, logger="guitarvis_worker"):
        harness.run(retries_left=2)

    row = harness.row()
    assert row.failure_reason is FailureReason.LINK_UNUSABLE
    assert row.failure_message == (
        "The audio we fetched from that video couldn't be read. Try a different "
        "link, or upload the audio file."
    )
    [record] = [r for r in caplog.records if r.getMessage().startswith("link audio")]
    assert record.levelno == logging.WARNING
    assert f"job={row.id} video={LINK.video_id} format=140 ext=wav" in (
        record.getMessage()
    )
    assert " ytdlp=2026.10.26 js=deno/2.5.4 " in record.getMessage()


@requires_ffprobe
def test_audio_the_real_ffprobe_cannot_read_logs_ffprobes_own_words(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:  # P1
    harness.probe = probe_duration
    harness.fetcher.content = b"this is not audio, whatever the video claimed"

    with caplog.at_level(logging.WARNING, logger="guitarvis_worker"):
        harness.run(retries_left=2)

    row = harness.row()
    assert row.failure_reason is FailureReason.LINK_UNUSABLE
    assert "Invalid data" not in repr(row)  # ffprobe's words are the log's
    [line] = [m for m in caplog.messages if m.startswith("link audio unreadable")]
    assert "Invalid data found when processing input" in line


@pytest.mark.parametrize("probed", [0.0, float("nan")])
def test_audio_with_no_length_is_unusable(
    harness: Harness, probed: float
) -> None:  # P1
    harness.probe = lambda path: probed

    harness.run(retries_left=2)

    assert harness.row().failure_reason is FailureReason.LINK_UNUSABLE


def test_audio_over_ten_minutes_by_ffprobe_is_too_long(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:  # P2
    harness.probe = lambda path: 721.0

    with caplog.at_level(logging.INFO, logger="guitarvis_worker"):
        harness.run(retries_left=2)

    row = harness.row()
    assert row.failure_reason is FailureReason.TOO_LONG
    assert row.failure_message == (
        "That recording is longer than 10 minutes. Try a single song rather than a "
        "full set."
    )
    [record] = [r for r in caplog.records if r.getMessage().startswith("link audio")]
    assert record.levelno == logging.INFO
    assert "metadata=37.0 probed=721.0" in record.getMessage()
    assert " ytdlp=2026.10.26 js=deno/2.5.4" in record.getMessage()


def test_a_missing_ffprobe_after_a_download_is_retried_then_internal(
    harness: Harness,
) -> None:  # P3
    def missing(path: Path) -> float:
        raise PipelineError(FailureReason.INTERNAL, "ffprobe is not installed.")

    harness.probe = missing

    with pytest.raises(PipelineError):
        harness.run(retries_left=0)

    assert harness.row().failure_message == INTERNAL_FAILURE_MESSAGE


# S. Storing the download


def test_the_same_bytes_from_another_video_are_stored_once(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.fetcher.content = wav_bytes(tmp_path)
    other, _ = harness.store.create(sample_link_job(video_id="aaaaaaaaaaa"))
    puts: list[str] = []
    put = harness.blobs.put_file

    def counting(key: str, path: Path) -> None:
        if key.startswith("uploads/"):  # not the stem the cache keeps
            puts.append(key)
        put(key, path)

    monkeypatch.setattr(harness.blobs, "put_file", counting)

    harness.run()
    process_job(other.id, harness.deps(), retries_left=2)

    first, second = harness.row(), harness.store.get(other.id)
    assert second is not None and second.status is JobStatus.SUCCEEDED
    assert first.upload_key == second.upload_key
    assert puts == [first.upload_key]  # the second found it there


@pytest.mark.parametrize(
    ("ext", "suffix"),
    [("wav", ".wav"), ("M4A", ".m4a"), ("webm", ".webm"), ("x" * 9, "")],
)
def test_the_stored_key_keeps_a_sane_extension_and_drops_any_other(
    harness: Harness, ext: str, suffix: str
) -> None:
    harness.fetcher.ext = ext

    harness.run()

    key = harness.row().upload_key
    assert key is not None
    assert key.startswith("uploads/") and key.endswith(suffix)
    assert key.removeprefix("uploads/").removesuffix(suffix).isalnum()  # the hash


def test_a_failed_store_of_the_download_is_retried_and_downloads_again(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:  # S1
    put = harness.blobs.put_file
    broken: list[bool] = []

    def put_once_broken(key: str, path: Path) -> None:
        if not broken:
            broken.append(True)
            raise ConnectionError("storage went away")
        put(key, path)

    monkeypatch.setattr(harness.blobs, "put_file", put_once_broken)
    with pytest.raises(ConnectionError):
        harness.run(retries_left=1)
    assert harness.row().status is JobStatus.QUEUED

    harness.run(retries_left=0)

    assert harness.row().status is JobStatus.SUCCEEDED
    assert len(harness.fetcher.downloads) == 2


def test_a_failed_attach_is_retried_then_internal(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:  # S2
    def broken(job_id: str, *, upload_key: str, duration_sec: float) -> bool:
        raise ConnectionError("postgres went away")

    monkeypatch.setattr(harness.store, "attach_upload", broken)

    with pytest.raises(ConnectionError):
        harness.run(retries_left=1)
    assert harness.row().status is JobStatus.QUEUED
    with pytest.raises(ConnectionError):
        harness.run(retries_left=0)
    assert harness.row().failure_reason is FailureReason.INTERNAL


def test_a_download_for_a_row_failed_meanwhile_is_dropped(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:  # S3
    attach = harness.store.attach_upload

    def reconciled_first(job_id: str, *, upload_key: str, duration_sec: float) -> bool:
        harness.store.fail(
            job_id,
            reason=FailureReason.INTERNAL,
            message="lost",
            stage="download",
            expect=JobStatus.RUNNING,
        )
        return attach(job_id, upload_key=upload_key, duration_sec=duration_sec)

    monkeypatch.setattr(harness.store, "attach_upload", reconciled_first)

    with caplog.at_level(logging.WARNING, logger="guitarvis_worker"):
        harness.run()  # no exception

    row = harness.row()
    assert (row.status, row.failure_message, row.upload_key) == (
        JobStatus.FAILED,
        "lost",
        None,
    )
    assert harness.separator.calls == 0
    assert any("dropping" in m for m in caplog.messages)


# Wiring


def test_open_deps_gives_a_fetcher_only_when_links_are_on() -> None:
    with open_deps(Settings(url_ingestion=True, max_upload_mb=7)) as on:
        assert isinstance(on.fetcher, ChildFetcher)
        assert on.max_download_bytes == 7 * 1024 * 1024
    with open_deps(Settings()) as off:
        assert off.fetcher is None


class FakeWorker:
    def __init__(self, queues: object, connection: object) -> None:
        pass

    def work(self, **kwargs: object) -> bool:
        return False


@pytest.mark.parametrize(
    ("links_on", "said"),
    [
        (
            True,
            [
                (logging.INFO, "links are on (GUITARVIS_URL_INGESTION)"),
                (logging.WARNING, NO_DENO_WARNING),
            ],
        ),
        (False, [(logging.INFO, "links are off (GUITARVIS_URL_INGESTION)")]),
    ],
)
def test_serve_says_whether_links_are_on_and_warns_when_no_runtime_is_found(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    links_on: bool,
    said: list[tuple[int, str]],
) -> None:  # W1 is told from these lines; D4
    monkeypatch.setattr(guitarvis_fetch.fetcher, "find_deno", lambda: None)
    monkeypatch.setattr(runner, "JobWorker", FakeWorker)

    with caplog.at_level(logging.INFO, logger="guitarvis_worker"):
        runner.serve(Settings(url_ingestion=links_on), burst=True)

    ours = [r for r in caplog.records if r.name.startswith("guitarvis_")]
    assert [(r.levelno, r.getMessage()) for r in ours] == said
