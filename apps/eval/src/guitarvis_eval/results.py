"""One run, one file in eval/results/. Committing it is a human decision.

The file records enough to reproduce the number: the commit, whether the
tree had uncommitted changes (a dirty run measures code that is not in git),
the mode, the split, and every mapper cost it ran with.
"""

import dataclasses
import json
import subprocess
from datetime import date
from pathlib import Path

from guitarvis_worker.stages.fretboard import MapperCosts

REPO_ROOT = Path(__file__).resolve().parents[4]
RESULTS_DIR = REPO_ROOT / "eval" / "results"


def git_state(repo: Path = REPO_ROOT) -> tuple[str, bool]:
    """(short sha, dirty). ("unknown", True) when there is no repository: an
    evaluation must not fail because it ran from an exported tree.

    Untracked files count, because a new module the run imported is code
    that is not in git. Earlier results files do not: they are outputs.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
                "--",
                ".",
                f":(exclude){RESULTS_DIR.relative_to(REPO_ROOT).as_posix()}",
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True
    return sha, bool(status.strip())


def write_results(
    *,
    mode: str,
    split: str,
    costs: MapperCosts,
    summary: dict[str, object],
    excerpts: list[dict[str, object]],
    out_dir: Path = RESULTS_DIR,
    today: date | None = None,
    repo: Path = REPO_ROOT,
) -> Path:
    sha, dirty = git_state(repo)
    day = (today or date.today()).isoformat()
    # A dirty run gets its own name, so that rerunning mid-edit can never
    # overwrite the clean, committable result for the same commit.
    suffix = "-dirty" if dirty else ""
    path = out_dir / f"{day}-{sha}-{mode}-{split}{suffix}.json"
    payload = {
        "date": day,
        "commit": sha,
        "dirty": dirty,
        "mode": mode,
        "split": split,
        "mapper_costs": dataclasses.asdict(costs),
        "summary": summary,
        "excerpts": excerpts,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path
