"""What a run leaves behind, and the command that produces it."""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from guitarset_fixture import write_jams
from guitarvis_eval.__main__ import main
from guitarvis_eval.results import REPO_ROOT, RESULTS_DIR, git_state, write_results
from guitarvis_worker.stages.fretboard import MapperCosts


def test_results_file_is_named_and_shaped(tmp_path: Path) -> None:
    written = write_results(
        mode="oracle",
        split="test",
        costs=MapperCosts(),
        summary={"all": {"excerpts": 0}},
        excerpts=[],
        out_dir=tmp_path,
        today=date(2026, 9, 29),
    )
    sha, dirty = git_state()
    suffix = "-dirty" if dirty else ""

    assert written == tmp_path / f"2026-09-29-{sha}-oracle-test{suffix}.json"
    payload = json.loads(written.read_text())
    assert set(payload) == {
        "date",
        "commit",
        "dirty",
        "mode",
        "split",
        "mapper_costs",
        "summary",
        "excerpts",
    }
    assert payload["mapper_costs"]["max_fret"] == MapperCosts().max_fret


def test_git_state_inside_the_repository() -> None:
    sha, dirty = git_state(REPO_ROOT)
    assert len(sha) >= 7
    assert isinstance(dirty, bool)


def test_git_state_outside_a_repository(tmp_path: Path) -> None:
    assert git_state(tmp_path) == ("unknown", True)


def test_main_scores_the_test_split(tmp_path: Path) -> None:
    data = tmp_path / "guitarset"
    write_jams(data / "annotation", "05_a_comp", notes=[(0.0, 1.0, 40.0, 0)])
    write_jams(data / "annotation", "00_a_comp", notes=[(0.0, 1.0, 45.0, 1)])
    out = tmp_path / "out"

    assert main(["--data-dir", str(data), "--out", str(out)]) == 0

    [written] = list(out.glob("*.json"))
    payload = json.loads(written.read_text())
    assert payload["mode"] == "oracle"
    assert payload["split"] == "test"
    assert [e["name"] for e in payload["excerpts"]] == ["05_a_comp"]
    assert payload["summary"]["all"]["string"]["total"] == 1


def test_main_without_data_says_how_to_get_it(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "guitarvis_eval", "--data-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 1
    assert "make eval-data" in result.stderr


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def results_in(repo: Path) -> Path:
    """The results directory's place inside a stand-in repository."""
    return repo / RESULTS_DIR.relative_to(REPO_ROOT)


def committed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    results_in(repo).mkdir(parents=True)
    (repo / "mapper.py").write_text("x = 1\n")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def test_an_untracked_source_file_makes_the_run_dirty(tmp_path: Path) -> None:
    repo = committed_repo(tmp_path)
    (repo / "helper.py").write_text("y = 2\n")
    assert git_state(repo)[1] is True


def test_an_uncommitted_result_file_does_not_make_the_run_dirty(
    tmp_path: Path,
) -> None:
    repo = committed_repo(tmp_path)
    (results_in(repo) / "earlier.json").write_text("{}\n")
    assert git_state(repo)[1] is False


def test_a_dirty_run_never_takes_a_clean_run_s_name(tmp_path: Path) -> None:
    repo = committed_repo(tmp_path)

    def run() -> Path:
        return write_results(
            mode="oracle",
            split="test",
            costs=MapperCosts(),
            summary={},
            excerpts=[],
            out_dir=results_in(repo),
            today=date(2026, 10, 7),
            repo=repo,
        )

    clean = run()
    (repo / "mapper.py").write_text("x = 5\n")
    dirty = run()

    assert dirty != clean
    assert dirty.name.endswith("-oracle-test-dirty.json")
    assert json.loads(clean.read_text())["dirty"] is False
