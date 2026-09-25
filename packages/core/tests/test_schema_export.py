"""The JSON Schema is generated, committed, and diff-checked.

Determinism matters more than prettiness here: an unstable key order would make
every regeneration look like a change and train everyone to ignore the diff.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED_SCHEMA = REPO_ROOT / "schema" / "tab-document.schema.json"


def test_export_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"

    for target in (first, second):
        subprocess.run(
            [sys.executable, "-m", "guitarvis_core.schema_export", str(target)],
            check=True,
        )

    assert first.read_text() == second.read_text()


def test_committed_schema_is_current(tmp_path: Path) -> None:
    """The same assertion CI makes, available before you push."""
    fresh = tmp_path / "fresh.json"
    subprocess.run(
        [sys.executable, "-m", "guitarvis_core.schema_export", str(fresh)],
        check=True,
    )

    assert COMMITTED_SCHEMA.exists(), "run `make schema` and commit the output"
    assert json.loads(fresh.read_text()) == json.loads(COMMITTED_SCHEMA.read_text()), (
        "schema/tab-document.schema.json is stale; run `make schema`"
    )


def test_schema_describes_the_documented_top_level_fields() -> None:
    schema = json.loads(COMMITTED_SCHEMA.read_text())

    assert set(schema["properties"]) == {
        "schema_version",
        "source",
        "instrument",
        "timing",
        "notes",
        "chords",
        "sections",
    }
