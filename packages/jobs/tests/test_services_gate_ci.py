"""`make check` in CI must run the integration suite, never skip it.

Locally, a test that needs Postgres, Redis or object storage skips when they
are down, as ingest tests skip without ffprobe. In CI the same skip would let
the build pass with the integration suite unrun, so CI sets
GUITARVIS_REQUIRE_SERVICES=1, which turns the skip into a failure. These
tests keep that true.
"""

import re
from pathlib import Path

import pytest
from guitarvis_jobs import testing

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"


def test_ci_starts_the_services_migrates_and_forbids_skipping() -> None:
    workflow = WORKFLOW.read_text()

    start = workflow.index("docker compose up -d --wait")
    migrate = workflow.index("make migrate")
    check = workflow.index("run: make check")
    assert start < migrate < check
    assert re.search(r'GUITARVIS_REQUIRE_SERVICES:\s*"1"', workflow[migrate:]), (
        "the check step must set GUITARVIS_REQUIRE_SERVICES=1, or the "
        "integration suite skips in CI and make check passes without it"
    )


def test_a_missing_service_fails_when_services_are_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(testing.REQUIRE_SERVICES_ENV, "1")
    monkeypatch.setattr(testing, "_probe", lambda service: "ConnectionRefusedError")

    with pytest.raises(pytest.fail.Exception, match="make services"):
        testing.require("postgres")


def test_a_missing_service_skips_otherwise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(testing.REQUIRE_SERVICES_ENV, raising=False)
    monkeypatch.setattr(testing, "_probe", lambda service: "ConnectionRefusedError")

    with pytest.raises(pytest.skip.Exception):
        testing.require("postgres")
