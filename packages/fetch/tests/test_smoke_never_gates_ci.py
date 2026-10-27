"""`make smoke-url` asks YouTube, so it must never gate the build: CI would
fail whenever YouTube changed, or refused a datacenter address. These keep
it out of `make check`, as test_eval_never_gates_ci keeps evaluation out."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SMOKE = REPO / "packages" / "fetch" / "smoke" / "live_fetch.py"


def test_pytest_never_collects_the_smoke_test_on_its_own() -> None:
    assert SMOKE.is_file()
    assert not SMOKE.name.startswith("test_"), "pytest would collect it in make check"


def test_check_does_not_reach_the_smoke_test() -> None:
    makefile = (REPO / "Makefile").read_text()
    check = re.search(r"^check:(.*)$", makefile, re.MULTILINE)

    assert check is not None
    assert "smoke" not in check.group(1)


def test_ci_never_fetches_live() -> None:
    for workflow in (REPO / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text()
        assert "smoke-url" not in text, workflow.name
        assert "GUITARVIS_LIVE_FETCH" not in text, workflow.name


def test_the_smoke_test_skips_unless_asked() -> None:
    assert 'os.environ.get("GUITARVIS_LIVE_FETCH") != "1"' in SMOKE.read_text()
