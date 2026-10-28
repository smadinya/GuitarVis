"""The api, served the way `make api` and a deployment serve it, prints its
own log lines (spec 012, *Logging*).

The api's link lines are INFO, and a process nobody has set logging up for
prints nothing below WARNING. The route tests read the lines through caplog,
which installs a handler of its own, so only a served api shows whether they
reach its output. This one is plain uvicorn in a child process: uvicorn's
logging setup and ours meet as they do when served, and neither leaks into
this process. It needs no Postgres, Redis or network: the parser refuses the
link, and the real services connect only on first use.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Plain uvicorn, as a deployment runs it; `make api` adds only --reload.
SERVE = [sys.executable, "-m", "uvicorn", "guitarvis_api.app:app"]
STARTED = re.compile(r"Uvicorn running on http://127\.0\.0\.1:(\d+)")
START_DEADLINE_SEC = 30.0


def wait_for_port(server: subprocess.Popen[bytes], stderr: Path) -> int:
    deadline = time.monotonic() + START_DEADLINE_SEC
    while time.monotonic() < deadline:
        started = STARTED.search(stderr.read_text())
        if started:
            return int(started.group(1))
        assert server.poll() is None, f"uvicorn exited:\n{stderr.read_text()}"
        time.sleep(0.05)
    raise AssertionError(f"uvicorn did not start:\n{stderr.read_text()}")


def post_link(port: int, url: str) -> tuple[int, dict[str, str]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/jobs/from-url",
        data=json.dumps({"url": url}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.load(error)["error"]


def test_the_served_api_prints_each_link_line_once_as_the_worker_does(
    tmp_path: Path,
) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("UVICORN_")}
    env.update(GUITARVIS_URL_INGESTION="1", PYTHONUNBUFFERED="1")
    stdout, stderr = tmp_path / "stdout.log", tmp_path / "stderr.log"
    with stdout.open("wb") as out, stderr.open("wb") as err:
        server = subprocess.Popen(
            [*SERVE, "--host", "127.0.0.1", "--port", "0"],
            stdout=out,
            stderr=err,
            env=env,
        )
        try:
            port = wait_for_port(server, stderr)
            status, error = post_link(port, "https://vimeo.com/1")
        finally:
            server.terminate()  # uvicorn shuts down and flushes on SIGTERM
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
    printed = stderr.read_text()
    access = stdout.read_text() + printed

    assert (status, error["reason"]) == (422, "unsupported_link")
    assert re.search(
        r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} INFO guitarvis_api\.routes_links: "
        r"link refused kind=unsupported_site host=vimeo\.com path=",
        printed,
        re.MULTILINE,
    ), printed
    assert printed.count("link refused") == 1
    # uvicorn's own lines, once each: its loggers keep their own handlers.
    assert printed.count("Application startup complete.") == 1
    assert access.count('"POST /jobs/from-url HTTP/1.1" 422') == 1
