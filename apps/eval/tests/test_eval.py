"""The harness is infrastructure, not a nice-to-have.

Without it, "swap in a better model later" is a wish. With it, it is a
measurement. These tests only hold the shape until phase 2 fills it in — plus
the one rule that must never be relaxed.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_results_directory_is_tracked() -> None:
    """eval/results/ holds the metric history. It must be in git, not ignored."""
    results = REPO_ROOT / "eval" / "results"

    assert results.is_dir()

    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(results / "README.md")],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    # check-ignore exits 1 for "not ignored" (what we want) and 0 for
    # "ignored" (what we're guarding against), but it also exits 128 on a
    # fatal error (e.g. git itself unavailable, or not run inside a repo) —
    # `!= 0` would let that pass for the wrong reason. Pin to exactly 1.
    assert ignored.returncode == 1, "eval/results/ must never be gitignored"


def test_harness_entry_point_exists_and_reports_its_status() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "guitarvis_eval"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "004-fretboard-mapper" in result.stderr
