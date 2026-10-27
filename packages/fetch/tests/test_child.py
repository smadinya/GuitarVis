"""The child, in-process against a fake YoutubeDL, and as a process: the
options it gives yt-dlp, the checks before any byte is downloaded, and its
answers. No network: nothing here asks YouTube anything."""

import contextlib
import io
import json
import logging
import os
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yt_dlp
from guitarvis_fetch.catalog import FetchKind
from guitarvis_fetch.child import (
    FORMAT,
    ChildLog,
    ProgressHook,
    check_media,
    download,
    lookup,
    ydl_options,
)
from guitarvis_fetch.fetcher import (
    ChildFetcher,
    FetchError,
    Versions,
    child_environment,
    log_failed,
)
from guitarvis_fetch.links import parse
from guitarvis_fetch.testing import read_pid, wait_until_gone

URL = "https://www.youtube.com/watch?v=kPdv44HtEoA"
RAW = {
    "id": "kPdv44HtEoA",
    "title": "Elephants Dream - 10 years of open movies",
    "duration": 37,
    "live_status": "not_live",
    "availability": "public",
    "formats": [{"format_id": "140"}],
}
SELECTED = {
    **RAW,
    "format_id": "140",
    "ext": "m4a",
    "protocol": "https",
    "url": "https://rr1---sn-qja5mc-54.googlevideo.com/videoplayback?itag=140",
    "filesize": 600547,
}
PUBLIC = [(2, 1, 6, "", ("74.125.170.113", 443))]


def resolving(*addresses: str) -> Any:
    return lambda host, port, **kwargs: [(2, 1, 6, "", (a, port)) for a in addresses]


class FakeYdl:
    """The three YoutubeDL calls the child makes, recorded."""

    def __init__(
        self,
        raw: Any = None,
        selected: dict[str, Any] | None = None,
        select_error: Exception | None = None,
        writes: bytes | None = b"\x00" * 1000,
    ) -> None:
        self.raw = dict(RAW) if raw is None else raw
        self.selected = dict(SELECTED) if selected is None else selected
        self.select_error = select_error
        self.writes = writes
        self.calls: list[str] = []
        self.work_dir: Path | None = None

    def extract_info(self, url: str, *, download: bool, process: bool) -> Any:
        assert (url, download, process) == (URL, False, False)
        self.calls.append("extract")
        return self.raw

    def process_ie_result(self, raw: Any, *, download: bool) -> dict[str, Any]:
        assert download is False
        self.calls.append("select")
        if self.select_error is not None:
            raise self.select_error
        return self.selected

    def process_info(self, info: dict[str, Any]) -> None:
        self.calls.append("download")
        if self.writes is not None and self.work_dir is not None:
            (self.work_dir / f"source.{info['ext']}").write_bytes(self.writes)


def log() -> ChildLog:
    return ChildLog(io.StringIO())


def fetch(
    ydl: FakeYdl, work_dir: Path, max_bytes: int = 10**7, **kwargs: Any
) -> dict[str, Any]:
    ydl.work_dir = work_dir
    return download(
        ydl,
        URL,
        work_dir,
        max_bytes,
        kwargs.pop("child_log", log()),
        resolve=kwargs.pop("resolve", resolving("74.125.170.113")),
        **kwargs,
    )


# What yt-dlp is told


def test_the_options_are_exactly_these() -> None:
    logger = log()

    assert ydl_options(deno="/usr/bin/deno", logger=logger) == {
        "logger": logger,
        "quiet": True,
        "noprogress": True,
        "color": "never",
        "ignoreerrors": False,
        "allowed_extractors": ["youtube"],
        "noplaylist": True,
        "format": "bestaudio[ext=m4a][protocol=https]/bestaudio[protocol=https]",
        "js_runtimes": {"deno": {"path": "/usr/bin/deno"}},
        "remote_components": [],
        "geo_bypass": False,
        "socket_timeout": 15,
        "retries": 1,
        "fragment_retries": 1,
        "extractor_retries": 1,
        "file_access_retries": 1,
        "postprocessors": [],
    }


def test_a_download_adds_a_fixed_template_in_the_job_directory_and_the_cap(
    tmp_path: Path,
) -> None:
    hook = ProgressHook(io.StringIO(), 100)

    options = ydl_options(
        deno="deno", logger=log(), work_dir=tmp_path, max_bytes=100, hooks=[hook]
    )

    assert options["paths"] == {"home": str(tmp_path), "temp": str(tmp_path)}
    assert options["outtmpl"] == {"default": "source.%(ext)s"}
    assert (options["max_filesize"], options["progress_hooks"]) == (100, [hook])
    assert options["overwrites"] is True
    for key in ("cookiefile", "cookiesfrombrowser", "proxy", "username", "usenetrc"):
        assert key not in options


def test_yt_dlp_accepts_the_options_and_loads_only_the_youtube_extractor() -> None:
    with yt_dlp.YoutubeDL(ydl_options(deno="deno", logger=log())) as ydl:
        # _ies is private, but it is the one place this is visible, and it
        # is what keeps the generic extractor, which fetches anything, away.
        assert set(ydl._ies) == {"Youtube"}
        assert ydl.params["format"] == FORMAT


def run_python(code: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """`code` in an isolated Python, its stdin a pipe held open and never
    written, as ChildFetcher holds the child's: the child run as __main__
    watches that pipe, and kills itself when it reaches end-of-file."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", code],
            stdin=subprocess.PIPE,
            stdout=out,
            stderr=err,
            env=env,
        )
        try:
            returncode = process.wait(timeout=60)
        finally:
            process.kill()  # only if it has not exited
            process.wait()
            assert process.stdin is not None
            process.stdin.close()
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(
            process.args, returncode, out.read().decode(), err.read().decode()
        )


def test_the_child_loads_no_ytdlp_plugins(tmp_path: Path) -> None:
    """yt-dlp loads plugins from the user's config directory when a
    YoutubeDL is made; the child's must not run anyone's code."""
    plugin = (
        tmp_path
        / "config"
        / "yt-dlp"
        / "plugins"
        / "evil"
        / "yt_dlp_plugins"
        / "extractor"
    )
    plugin.mkdir(parents=True)
    marker = tmp_path / "ran"
    (plugin / "marker.py").write_text(f"open({str(marker)!r}, 'w').write('ran')\n")
    env = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "config")}
    env.pop("YTDLP_NO_PLUGINS", None)

    control = run_python("import yt_dlp; yt_dlp.YoutubeDL({'quiet': True})", env)
    assert control.returncode == 0, control.stderr
    assert marker.exists(), (
        "the control did not load the plugin: this test proves nothing"
    )
    marker.unlink()

    ours = run_python(
        "from guitarvis_fetch.child import _new_ydl; _new_ydl({'quiet': True})", env
    )
    assert ours.returncode == 0, ours.stderr
    assert not marker.exists()


# A lookup


def test_a_lookup_checks_the_metadata_then_chooses_a_format() -> None:
    ydl = FakeYdl()

    info = lookup(ydl, URL)

    assert info == {
        "title": "Elephants Dream - 10 years of open movies",
        "duration_sec": 37.0,
        "live_status": "not_live",
        "availability": "public",
    }
    assert ydl.calls == ["extract", "select"]


def test_a_live_stream_is_refused_before_formats_are_chosen() -> None:  # L6
    ydl = FakeYdl(raw={**RAW, "live_status": "is_live", "duration": None})

    with pytest.raises(FetchError) as excinfo:
        lookup(ydl, URL)

    assert excinfo.value.kind is FetchKind.LIVE
    assert ydl.calls == ["extract"]  # choosing first would have said "no audio"


def test_a_trailer_in_place_of_a_paid_video_is_members_only() -> None:  # L5
    ydl = FakeYdl(
        raw={"_type": "url", "url": "https://www.youtube.com/watch?v=trailer0000"}
    )

    with pytest.raises(FetchError) as excinfo:
        lookup(ydl, URL)

    assert excinfo.value.kind is FetchKind.MEMBERS_ONLY


def test_a_format_error_is_left_for_the_classifier() -> None:  # L11
    error = yt_dlp.utils.ExtractorError(
        "Requested format is not available", expected=True
    )

    with pytest.raises(yt_dlp.utils.ExtractorError):
        lookup(FakeYdl(select_error=error), URL)


# A download


def test_a_download_returns_the_file_and_its_format(tmp_path: Path) -> None:
    ydl = FakeYdl()

    result = fetch(ydl, tmp_path)

    assert result["path"] == str(tmp_path / "source.m4a")
    assert (result["format_id"], result["ext"], result["size"]) == ("140", "m4a", 1000)
    assert result["title"] == "Elephants Dream - 10 years of open movies"
    assert ydl.calls == ["extract", "select", "download"]


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ({**RAW, "availability": "private"}, FetchKind.PRIVATE),
        ({**RAW, "live_status": "is_upcoming"}, FetchKind.UPCOMING),
        ({**RAW, "duration": 721}, FetchKind.TOO_LONG),
        ({**RAW, "duration": None}, FetchKind.NO_DURATION),
    ],
)
def test_a_video_that_changed_in_the_queue_is_refused_before_downloading(
    tmp_path: Path, raw: dict[str, Any], kind: FetchKind
) -> None:  # W2
    ydl = FakeYdl(raw=raw)

    with pytest.raises(FetchError) as excinfo:
        fetch(ydl, tmp_path)

    assert excinfo.value.kind is kind
    assert "download" not in ydl.calls


@pytest.mark.parametrize(
    ("selected", "addresses"),
    [
        (
            {**SELECTED, "protocol": "http", "url": "http://rr1.googlevideo.com/x"},
            ["74.125.170.113"],
        ),
        ({**SELECTED, "protocol": "m3u8_native"}, ["74.125.170.113"]),
        ({**SELECTED, "url": "https://evil.example/videoplayback"}, ["74.125.170.113"]),
        (
            {**SELECTED, "url": "https://googlevideo.com.evil.example/x"},
            ["74.125.170.113"],
        ),
        (SELECTED, ["10.0.0.7"]),
        (SELECTED, ["74.125.170.113", "127.0.0.1"]),
        (SELECTED, ["169.254.169.254"]),
        (SELECTED, ["fd00::1"]),
        ({**SELECTED, "requested_formats": [{}, {}]}, ["74.125.170.113"]),
    ],
)
def test_a_media_url_we_did_not_expect_is_refused_before_connecting(
    tmp_path: Path, selected: dict[str, Any], addresses: list[str]
) -> None:  # D5
    ydl = FakeYdl(selected=selected)

    with pytest.raises(FetchError) as excinfo:
        fetch(ydl, tmp_path, resolve=resolving(*addresses))

    assert excinfo.value.kind is FetchKind.MEDIA_REFUSED
    assert "download" not in ydl.calls


def test_a_format_larger_than_the_cap_is_refused_before_downloading(
    tmp_path: Path,
) -> None:  # D6
    ydl = FakeYdl(selected={**SELECTED, "filesize": 10_001})

    with pytest.raises(FetchError) as excinfo:
        fetch(ydl, tmp_path, max_bytes=10_000)

    assert excinfo.value.kind is FetchKind.TOO_LARGE
    assert "download" not in ydl.calls


def test_a_file_larger_than_the_cap_on_disk_is_refused(tmp_path: Path) -> None:  # D6
    ydl = FakeYdl(selected={**SELECTED, "filesize": None}, writes=b"\x00" * 2000)

    with pytest.raises(FetchError) as excinfo:
        fetch(ydl, tmp_path, max_bytes=1000)

    assert excinfo.value.kind is FetchKind.TOO_LARGE


def test_yt_dlps_quiet_size_cap_is_too_large_not_empty(tmp_path: Path) -> None:  # D6
    child_log = log()
    child_log.debug(
        "[download] File is larger than max-filesize (2000 bytes > 1000 bytes). "
        "Aborting."
    )

    with pytest.raises(FetchError) as excinfo:
        fetch(
            FakeYdl(selected={**SELECTED, "filesize": None}, writes=None),
            tmp_path,
            max_bytes=1000,
            child_log=child_log,
        )

    assert excinfo.value.kind is FetchKind.TOO_LARGE


@pytest.mark.parametrize("writes", [None, b""])
def test_a_download_that_leaves_no_file_or_an_empty_one_is_unusable(
    tmp_path: Path, writes: bytes | None
) -> None:  # D7
    with pytest.raises(FetchError) as excinfo:
        fetch(FakeYdl(writes=writes), tmp_path)

    assert excinfo.value.kind is FetchKind.EMPTY_DOWNLOAD


def test_check_media_passes_youtubes_own_host_at_a_public_address() -> None:
    check_media(SELECTED, 10**9, resolve=lambda *args, **kwargs: PUBLIC)


# Progress, and the cap for a response with no length


def test_the_hook_reports_each_whole_percent_once() -> None:
    out = io.StringIO()
    hook = ProgressHook(out, 10_000)

    for done in (0, 10, 4999, 5000, 5001, 10_000):
        hook({"status": "downloading", "downloaded_bytes": done, "total_bytes": 10_000})

    sent = [json.loads(line)["progress"] for line in out.getvalue().splitlines()]
    assert sent == [0.0, 0.49, 0.5, 1.0]


def test_the_hook_stops_a_download_past_the_cap_with_no_length() -> None:  # D6
    hook = ProgressHook(io.StringIO(), 1000)

    with pytest.raises(FetchError) as excinfo:
        hook({"status": "downloading", "downloaded_bytes": 1001, "total_bytes": None})

    assert excinfo.value.kind is FetchKind.TOO_LARGE


# The child as a process


def empty_path(tmp_path: Path) -> str:
    beside = Path(sys.executable).with_name("deno")
    if beside.exists():
        pytest.skip("a deno is installed beside this Python; it cannot be hidden")
    path = tmp_path / "bin"
    path.mkdir()
    return str(path)


def test_without_a_javascript_runtime_the_child_says_misconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # L16
    monkeypatch.setenv("PATH", empty_path(tmp_path))

    with pytest.raises(FetchError) as excinfo:
        ChildFetcher().lookup(parse(URL))

    assert excinfo.value.kind is FetchKind.MISCONFIGURED
    assert "Deno 2.3.0 or later" in excinfo.value.detail
    # A version the child never learned is left out, not sent as "-", so the
    # parent names the installed yt-dlp instead.
    assert excinfo.value.versions == Versions(ytdlp=yt_dlp.version.__version__)


def fake_deno(tmp_path: Path) -> str:
    """A PATH holding only a "deno" new enough to pass the child's check."""
    bin_dir = Path(empty_path(tmp_path))
    deno = bin_dir / "deno"
    deno.write_text("#!/bin/sh\necho 'deno 2.5.4 (stable)'\n")
    deno.chmod(deno.stat().st_mode | stat.S_IEXEC)
    return str(bin_dir)


def test_when_yt_dlp_will_not_import_the_child_says_misconfigured(
    tmp_path: Path,
) -> None:  # L16
    code = (
        "import sys; sys.modules['yt_dlp'] = None; sys.argv[1:] = ['lookup', "
        f"{URL!r}]; import runpy; "
        "runpy.run_module('guitarvis_fetch.child', run_name='__main__')"
    )

    answer = run_python(code, {**os.environ, "PATH": fake_deno(tmp_path)})

    [line] = answer.stdout.splitlines()
    error = json.loads(line)["error"]
    assert error["kind"] == "misconfigured"
    assert "yt-dlp will not import" in error["detail"]


# A yt-dlp half upgraded: its files are there, but its code will not load.
BROKEN_YT_DLP = """
import sys

class Broken:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "yt_dlp":
            raise {error}
        return None

sys.meta_path.insert(0, Broken())
"""
BROKEN = [
    "SyntaxError('invalid syntax')",
    "AttributeError(\"module 'yt_dlp.utils' has no attribute 'traverse_obj'\")",
]


@pytest.mark.parametrize("error", BROKEN, ids=["SyntaxError", "AttributeError"])
def test_a_yt_dlp_that_fails_to_import_another_way_is_misconfigured_too(
    tmp_path: Path, error: str
) -> None:  # L16
    code = BROKEN_YT_DLP.format(error=error) + (
        f"sys.argv[1:] = ['lookup', {URL!r}]\n"
        "import runpy\n"
        "runpy.run_module('guitarvis_fetch.child', run_name='__main__')\n"
    )

    answer = run_python(code, {**os.environ, "PATH": fake_deno(tmp_path)})

    [line] = answer.stdout.splitlines()
    sent = json.loads(line)["error"]
    assert sent["kind"] == "misconfigured", answer.stderr
    assert "yt-dlp will not import" in sent["detail"]
    assert error.split("(")[0] in sent["detail"]


@pytest.mark.parametrize("error", BROKEN, ids=["SyntaxError", "AttributeError"])
def test_an_unforeseen_failure_with_yt_dlp_broken_still_gets_an_answer(
    error: str,
) -> None:  # L16
    """The child's last resort classifies with yt-dlp's types; when those will
    not import either, it must still answer, not die with a traceback."""
    code = BROKEN_YT_DLP.format(error=error) + (
        "import guitarvis_fetch.child as child\n"
        "def find_deno():\n"
        "    raise RuntimeError('unforeseen, before yt-dlp is imported')\n"
        "child.find_deno = find_deno\n"
        f"child.main(['lookup', {URL!r}])\n"
    )

    answer = run_python(code, dict(os.environ))

    assert answer.returncode == 0, answer.stderr
    [line] = answer.stdout.splitlines()
    assert json.loads(line)["error"]["kind"] == "misconfigured"


def test_nothing_but_answers_reaches_the_childs_stdout() -> None:
    """yt-dlp and Deno print; fd 1 points at stderr, so only JSON is on stdout."""
    code = (
        "import guitarvis_fetch.child as child\n"
        "from guitarvis_fetch.fetcher import JsRuntime\n"
        "child.find_deno = lambda: JsRuntime('deno', 'deno', '2.5.4')\n"
        "def answer(args, runtime, log, out):\n"
        "    print('[youtube] chatter on stdout')\n"
        "    import os; os.write(1, b'and from a subprocess\\n')\n"
        "    return {'title': 't'}\n"
        "child._answer = answer\n"
        "child.main(['lookup', 'x'])\n"
    )

    answer = run_python(code, dict(os.environ))

    assert answer.returncode == 0, answer.stderr
    *before, last = [json.loads(line) for line in answer.stdout.splitlines()]
    assert all(set(line) <= {"progress", "ytdlp", "js"} for line in before)
    assert last["result"] == {"title": "t"}
    assert "chatter on stdout" in answer.stderr
    assert "and from a subprocess" in answer.stderr


# The real child, stopped once it knows its versions, by a lookup that hangs.
HANGS = (
    "import time\n"
    "import guitarvis_fetch.child as child\n"
    "from guitarvis_fetch.fetcher import JsRuntime\n"
    "child.find_deno = lambda: JsRuntime('deno', 'deno', '2.5.4')\n"
    "child._answer = lambda args, runtime, log, out: time.sleep(60)\n"
    "child.main()\n"
)


def test_a_child_past_its_deadline_is_logged_with_its_versions(
    caplog: pytest.LogCaptureFixture,
) -> None:  # L14, D2
    """A hung Deno is a likely cause of a timeout. The child names both
    versions before it starts work, so a timeout's log line names them too."""
    fetcher = ChildFetcher(
        command=[sys.executable, "-I", "-c", HANGS], lookup_deadline_sec=2
    )
    link = parse(URL)

    with pytest.raises(FetchError) as excinfo:
        fetcher.lookup(link)
    with caplog.at_level(logging.WARNING, logger="test.child"):
        log_failed(
            logging.getLogger("test.child"),
            excinfo.value,
            phase="lookup",
            link=link,
            elapsed_sec=2.0,
        )

    assert excinfo.value.kind is FetchKind.LOOKUP_TIMEOUT
    [line] = caplog.messages
    assert f"ytdlp={yt_dlp.version.__version__} js=deno/2.5.4 " in line


def test_the_child_dies_when_its_stdin_reaches_end_of_file(tmp_path: Path) -> None:
    """The real child, as ChildFetcher starts it. Its parent holds its stdin
    open; when the parent dies the kernel closes it, and the child must kill
    itself and what it started. Here it is held up by a "deno" that never
    answers `--version`, which it would otherwise wait 10 s for."""
    bin_dir = Path(empty_path(tmp_path))
    pid_file = tmp_path / "deno.pid"
    hang = shlex.quote(sys.executable) + " -c 'import time; time.sleep(60)'"
    deno = bin_dir / "deno"
    deno.write_text(f"#!/bin/sh\necho $$ > {shlex.quote(str(pid_file))}\nexec {hang}\n")
    deno.chmod(deno.stat().st_mode | stat.S_IEXEC)

    with subprocess.Popen(
        [sys.executable, "-I", "-m", "guitarvis_fetch.child", "lookup", URL],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=child_environment({**os.environ, "PATH": str(bin_dir)}),
        start_new_session=True,
    ) as process:
        assert process.stdin is not None and process.stdout is not None
        try:
            deno_pid = read_pid(pid_file)
            assert process.poll() is None  # alive while its stdin is open

            process.stdin.close()

            assert process.wait(timeout=5) == -signal.SIGKILL
            assert wait_until_gone(deno_pid), "the child's deno outlived it"
            assert process.stdout.read() == b""  # killed, not answering
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
