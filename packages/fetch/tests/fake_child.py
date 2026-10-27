"""A stand-in for guitarvis_fetch.child, run by ChildFetcher in the tests.

argv: SCENARIO [EXTRA] then what ChildFetcher appends (`lookup URL` or
`download URL WORK_DIR MAX_BYTES`). Never imported; run as a script.
"""

import json
import os
import subprocess
import sys
import time

VERSIONS = {"ytdlp": "2026.10.26", "js": "deno/2.5.4"}
INFO = {
    "title": "Elephants Dream - 10 years of open movies",
    "duration_sec": 37,
    "live_status": "not_live",
    "availability": "public",
}


def say(message: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> None:
    scenario, rest = sys.argv[1], sys.argv[2:]
    if scenario == "lookup-ok":
        say({"result": INFO, **VERSIONS})
    elif scenario == "download-ok":
        work_dir = rest[-2]
        path = os.path.join(work_dir, "source.m4a")
        with open(path, "wb") as out:
            out.write(b"\x00" * 1000)
        for fraction in (0.0, 0.25, float("nan"), 2.0, 1.0):
            say({"progress": fraction})
        say(
            {
                "result": {
                    **INFO,
                    "path": path,
                    "format_id": "140",
                    "ext": "m4a",
                    "size": 1000,
                },
                **VERSIONS,
            }
        )
    elif scenario == "error":
        sys.stderr.write("ERROR: [youtube] the tail of what yt-dlp said\n")
        sys.stderr.flush()
        say(
            {
                "error": {
                    "kind": rest[0],
                    "detail": "ERROR: [youtube] SENTINEL-4f2a",
                    "duration_sec": 721,
                },
                **VERSIONS,
            }
        )
    elif scenario == "unknown-kind":
        say({"error": {"kind": "brand_new", "detail": "?"}, **VERSIONS})
    elif scenario == "garbage":
        sys.stdout.write("Traceback (most recent call last): not json\n")
        sys.stdout.flush()
        time.sleep(60)
    elif scenario == "crash":
        sys.stderr.write("Traceback (most recent call last):\nMemoryError: boom\n")
        sys.exit(3)
    elif scenario == "silent":
        sys.exit(0)
    elif scenario == "bad-result":
        say(
            {
                "result": {
                    **INFO,
                    "path": "/nowhere",
                    "format_id": "140",
                    "ext": "m4a",
                },
                **VERSIONS,
            }
        )
    elif scenario == "env":
        seen = sorted(name for name in os.environ if name.startswith("GUITARVIS_"))
        info = {**INFO, "title": json.dumps([seen, os.environ.get("YTDLP_NO_PLUGINS")])}
        say({"result": info, **VERSIONS})
    elif scenario == "hang":
        # A grandchild, as yt-dlp starts Deno, and its pid for the test.
        grandchild = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        with open(rest[0], "w") as out:
            out.write(str(grandchild.pid))
        say({"progress": 0.1})
        time.sleep(60)
    else:
        raise SystemExit(f"unknown scenario {scenario}")


main()
