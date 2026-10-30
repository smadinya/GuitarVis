"""configure_logging, in child interpreters so it cannot leak into this one.
What a served api and the worker print is tested where they are served:
apps/api/tests/test_api_logging.py and apps/worker/tests/test_cli.py."""

import subprocess
import sys

PROBE = """
import logging, sys
from guitarvis_jobs.logs import configure_logging
{setup}
configure_logging("guitarvis_api")
root = logging.getLogger()
print(len(root.handlers), logging.getLevelName(root.level))
for name in ("guitarvis_api", "guitarvis_fetch", "guitarvis_jobs", "botocore"):
    print(name, logging.getLevelName(logging.getLogger(name).getEffectiveLevel()))
"""


def probe(setup: str = "") -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", PROBE.format(setup=setup)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return result.stdout.splitlines()


def test_ours_speak_at_info_and_every_other_library_from_warning() -> None:
    assert probe() == [
        "1 WARNING",
        "guitarvis_api INFO",
        "guitarvis_fetch INFO",
        "guitarvis_jobs INFO",
        "botocore WARNING",
    ]


def test_a_process_whose_logging_is_already_set_up_is_left_as_it_is() -> None:
    # A --log-config that gives the root a handler, or a test runner's capture.
    setup = "logging.getLogger().addHandler(logging.StreamHandler(sys.stderr))"

    assert probe(setup) == [
        "1 WARNING",
        "guitarvis_api WARNING",
        "guitarvis_fetch WARNING",
        "guitarvis_jobs WARNING",
        "botocore WARNING",
    ]
