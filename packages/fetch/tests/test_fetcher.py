"""The UrlFetcher contract, the metadata checks, and ChildFetcher against a
fake child: results, progress, each error, garbage, a crash, and a hang
killed at its deadline along with its process group."""

import logging
import os
import stat
import sys
import time
from pathlib import Path

import pytest
from guitarvis_core.contracts import FailureReason
from guitarvis_fetch.catalog import FetchKind
from guitarvis_fetch.fetcher import (
    ChildFetcher,
    FetchError,
    UrlFetcher,
    Versions,
    VideoInfo,
    check_info,
    child_environment,
    find_deno,
    log_failed,
    log_fetched,
)
from guitarvis_fetch.links import parse
from guitarvis_fetch.testing import FakeFetcher, video_info

FAKE_CHILD = Path(__file__).with_name("fake_child.py")
LINK = parse("https://youtu.be/kPdv44HtEoA")
SENTINEL = "SENTINEL-4f2a"


def child(*scenario: str, **deadlines: float) -> ChildFetcher:
    return ChildFetcher(
        command=[sys.executable, "-I", str(FAKE_CHILD), *scenario], **deadlines
    )


def gone(pid: int) -> bool:
    """Whether `pid` is dead: no such process, or a zombie awaiting its reaper."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    status = Path(f"/proc/{pid}/stat")
    return status.exists() and status.read_text().split(")")[-1].split()[0] == "Z"


def wait_until_gone(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if gone(pid):
            return True
        time.sleep(0.05)
    return False


# The fetchers


def test_child_fetcher_and_the_fake_satisfy_the_protocol() -> None:
    assert isinstance(ChildFetcher(), UrlFetcher)
    assert isinstance(FakeFetcher(), UrlFetcher)


# check_info: step 6, and the child's check before downloading


@pytest.mark.parametrize(
    ("info", "kind"),
    [
        (video_info(live_status="is_live", duration_sec=None), FetchKind.LIVE),  # L6
        (video_info(live_status="is_upcoming"), FetchKind.UPCOMING),  # L7
        (
            video_info(live_status="post_live", duration_sec=7200),
            FetchKind.POST_LIVE,
        ),  # L8
        (video_info(availability="private"), FetchKind.PRIVATE),  # L1
        (video_info(availability="needs_auth"), FetchKind.AGE_RESTRICTED),  # L4
        (video_info(availability="subscriber_only"), FetchKind.MEMBERS_ONLY),  # L5
        (video_info(availability="premium_only"), FetchKind.MEMBERS_ONLY),  # L5
        (video_info(duration_sec=None), FetchKind.NO_DURATION),  # L9
        (video_info(duration_sec=0), FetchKind.NO_DURATION),  # L9
        (video_info(duration_sec=float("nan")), FetchKind.NO_DURATION),  # L9
        (video_info(duration_sec=721), FetchKind.TOO_LONG),  # L10
    ],
)
def test_check_info_refuses_what_we_cannot_use(
    info: VideoInfo, kind: FetchKind
) -> None:
    with pytest.raises(FetchError) as excinfo:
        check_info(info)

    assert excinfo.value.kind is kind


@pytest.mark.parametrize("live_status", ["not_live", "was_live", None])
def test_check_info_passes_a_finished_video_and_gives_its_length(
    live_status: str | None,
) -> None:
    assert check_info(video_info(live_status=live_status, duration_sec=600)) == 600


def test_too_long_carries_the_length_for_its_message() -> None:
    with pytest.raises(FetchError) as excinfo:
        check_info(video_info(duration_sec=721))

    assert "12:01" in excinfo.value.message


# FetchError: the catalog's words out, yt-dlp's words in the log only


def test_a_fetch_errors_message_is_the_catalogs_never_its_detail() -> None:
    error = FetchError(
        FetchKind.PRIVATE, f"ERROR: [youtube] x: Private video. {SENTINEL}"
    )

    assert SENTINEL not in error.message
    assert error.message.startswith("That video is private.")


@pytest.mark.parametrize(
    ("kind", "reason", "retryable"),
    [
        (FetchKind.NETWORK, FailureReason.FETCH_FAILED, True),
        (FetchKind.RATE_LIMITED, FailureReason.FETCH_FAILED, False),
        (FetchKind.PRIVATE, FailureReason.LINK_UNUSABLE, False),
        (FetchKind.CRASHED, FailureReason.INTERNAL, True),
    ],
)
def test_as_a_pipeline_error_a_fetch_error_keeps_its_row(
    kind: FetchKind, reason: FailureReason, retryable: bool
) -> None:
    error = FetchError(kind, SENTINEL).as_pipeline_error()

    assert (error.reason, error.retryable) == (reason, retryable)
    assert SENTINEL not in str(error)


# The JavaScript runtime


def fake_deno(directory: Path, answer: str) -> str:
    path = directory / "deno"
    path.write_text(f"#!/bin/sh\necho '{answer}'\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_find_deno_takes_a_new_enough_deno(tmp_path: Path) -> None:
    path = fake_deno(tmp_path, "deno 2.5.4 (stable, release, x86_64-unknown-linux-gnu)")

    found = find_deno(which=lambda name: path)

    assert found is not None
    assert (found.path, found.label) == (path, "deno/2.5.4")


@pytest.mark.parametrize("answer", ["deno 2.2.9 (stable)", "node v22.20.0", ""])
def test_find_deno_refuses_an_old_one_or_something_else(
    tmp_path: Path, answer: str
) -> None:
    path = fake_deno(tmp_path, answer)

    assert find_deno(which=lambda name: path) is None


def test_find_deno_finds_nothing_when_there_is_nothing() -> None:
    assert find_deno(which=lambda name: None) is None


# ChildFetcher


def test_the_childs_environment_has_no_guitarvis_variables() -> None:
    env = child_environment(
        {
            "PATH": "/usr/bin",
            "GUITARVIS_DATABASE_URL": "postgresql://secret",
            "HOME": "/h",
        }
    )

    assert env == {"PATH": "/usr/bin", "HOME": "/h", "YTDLP_NO_PLUGINS": "1"}


def test_the_child_runs_without_the_parents_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GUITARVIS_S3_SECRET_KEY", "hunter2")

    info = child("env").lookup(LINK)

    assert info.title == '[[], "1"]'  # no GUITARVIS_* names; plugins off


def test_a_lookup_returns_the_childs_result() -> None:
    info = child("lookup-ok").lookup(LINK)

    assert info == VideoInfo(
        title="Elephants Dream - 10 years of open movies",
        duration_sec=37.0,
        live_status="not_live",
        availability="public",
        versions=Versions(ytdlp="2026.10.26", js="deno/2.5.4"),
    )


def test_a_download_reports_clamped_progress_and_returns_the_file(
    tmp_path: Path,
) -> None:
    seen: list[float] = []

    download = child("download-ok").download(
        LINK, tmp_path, max_bytes=10_000, progress=seen.append
    )

    assert seen == [0.0, 0.25, 1.0, 1.0]  # NaN dropped, 2.0 clamped
    assert download.path == tmp_path / "source.m4a"
    assert (download.format_id, download.ext, download.size) == ("140", "m4a", 1000)
    assert download.info.title == "Elephants Dream - 10 years of open movies"


@pytest.mark.parametrize("kind", list(FetchKind))
def test_a_classified_error_comes_back_as_its_kind(kind: FetchKind) -> None:
    with pytest.raises(FetchError) as excinfo:
        child("error", kind.value).lookup(LINK)

    error = excinfo.value
    assert error.kind is kind
    assert SENTINEL in error.detail  # for the log
    assert SENTINEL not in error.message  # never for the user
    assert "the tail of what yt-dlp said" in error.tail
    assert error.versions == Versions(ytdlp="2026.10.26", js="deno/2.5.4")


def test_too_long_from_the_child_keeps_its_length() -> None:
    with pytest.raises(FetchError) as excinfo:
        child("error", "too_long").lookup(LINK)

    assert "12:01" in excinfo.value.message


def test_a_kind_this_build_does_not_know_is_unknown() -> None:
    with pytest.raises(FetchError) as excinfo:
        child("unknown-kind").lookup(LINK)

    assert excinfo.value.kind is FetchKind.UNKNOWN


def test_garbage_on_stdout_is_a_crash_at_once() -> None:  # L18
    started = time.monotonic()
    with pytest.raises(FetchError) as excinfo:
        child("garbage").lookup(LINK)

    assert excinfo.value.kind is FetchKind.CRASHED
    assert time.monotonic() - started < 10  # not the 30 s deadline


def test_a_child_that_crashes_is_a_crash_with_its_exit_code_and_tail() -> (
    None
):  # L18, D9
    with pytest.raises(FetchError) as excinfo:
        child("crash").lookup(LINK)

    error = excinfo.value
    assert (error.kind, error.exit_code) == (FetchKind.CRASHED, 3)
    assert "MemoryError: boom" in error.tail


def test_a_child_that_exits_without_an_answer_is_a_crash() -> None:  # L18
    with pytest.raises(FetchError) as excinfo:
        child("silent").lookup(LINK)

    assert (excinfo.value.kind, excinfo.value.exit_code) == (FetchKind.CRASHED, 0)


def test_a_result_missing_a_field_is_a_crash(tmp_path: Path) -> None:
    with pytest.raises(FetchError) as excinfo:
        child("bad-result").download(LINK, tmp_path, max_bytes=10)

    assert excinfo.value.kind is FetchKind.CRASHED


def test_a_lookup_past_its_deadline_is_killed_with_its_process_group(
    tmp_path: Path,
) -> None:  # L14
    pid_file = tmp_path / "grandchild.pid"
    started = time.monotonic()

    with pytest.raises(FetchError) as excinfo:
        child("hang", str(pid_file), lookup_deadline_sec=2).lookup(LINK)

    assert excinfo.value.kind is FetchKind.LOOKUP_TIMEOUT
    assert time.monotonic() - started < 10
    assert wait_until_gone(int(pid_file.read_text())), (
        "the grandchild outlived its group"
    )


def test_a_download_past_its_deadline_is_a_download_timeout(
    tmp_path: Path,
) -> None:  # D2
    with pytest.raises(FetchError) as excinfo:
        child("hang", str(tmp_path / "pid"), download_deadline_sec=2).download(
            LINK, tmp_path, max_bytes=10
        )

    assert excinfo.value.kind is FetchKind.DOWNLOAD_TIMEOUT


class JobTimeout(BaseException):
    """Stands in for the worker's JobTimedOut, which is not an Exception."""


def test_a_job_timeout_mid_download_still_kills_the_child(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"

    def time_runs_out(fraction: float) -> None:
        raise JobTimeout

    with pytest.raises(JobTimeout):
        child("hang", str(pid_file)).download(
            LINK, tmp_path, max_bytes=10, progress=time_runs_out
        )

    assert wait_until_gone(int(pid_file.read_text()))


# The log lines


def test_a_failure_is_one_line_at_its_catalog_level(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = logging.getLogger("test.fetch")
    error = FetchError(
        FetchKind.PRIVATE,
        "x" * 600,
        tail="STDERR-TAIL",
        versions=Versions(ytdlp="2026.10.26", js="deno/2.5.4"),
    )

    with caplog.at_level(logging.INFO, logger="test.fetch"):
        log_failed(log, error, phase="lookup", link=LINK, elapsed_sec=1.84)

    [record] = caplog.records
    assert record.levelno == logging.INFO
    line = record.getMessage()
    assert line.startswith(
        "link fetch failed kind=private phase=lookup site=youtube "
        "video=kPdv44HtEoA job=- attempt=- elapsed=1.8s ytdlp=2026.10.26 "
        'js=deno/2.5.4 detail="'
    )
    assert "x" * 500 + '"' in line and "x" * 501 not in line
    assert "STDERR-TAIL" not in line  # INFO rows carry no tail


def test_an_error_level_failure_adds_the_childs_stderr(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = logging.getLogger("test.fetch")
    error = FetchError(
        FetchKind.EXTRACTOR_BROKEN, "Unable to extract", tail="STDERR-TAIL"
    )

    with caplog.at_level(logging.INFO, logger="test.fetch"):
        log_failed(
            log,
            error,
            phase="download",
            link=LINK,
            elapsed_sec=3,
            job_id="j",
            attempt=2,
        )

    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert "job=j attempt=2" in record.getMessage()
    assert record.getMessage().endswith("\nSTDERR-TAIL")


def test_a_success_is_logged_with_its_format(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    log = logging.getLogger("test.fetch")
    download = FakeFetcher(ext="m4a", content=b"abc").download(
        LINK, tmp_path, max_bytes=10
    )

    with caplog.at_level(logging.INFO, logger="test.fetch"):
        log_fetched(
            log,
            phase="download",
            link=LINK,
            versions=download.info.versions,
            elapsed_sec=2.0,
            download=download,
        )

    assert caplog.records[0].getMessage().endswith("format=140 ext=m4a bytes=3")
