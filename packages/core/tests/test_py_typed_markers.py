"""Every workspace package must ship a `py.typed` marker (PEP 561).

mypy.ini no longer sets the blanket `ignore_missing_imports`, which is what
let a missing `py.typed` marker hide silently before a reviewer found it by
hand (Ruling 7). Without the blanket flag, a missing marker resurfaces as a
real mypy error the next time it happens — but only for a package mypy is
actually pointed at. This test is the second half of that guarantee: it
checks the file exists directly, so the mechanism does not depend on some
other module happening to import the affected package during a type-check
run.

Lives in packages/core because core is the bottom of the dependency graph and
every other workspace member already depends on it, matching the reasoning in
test_package.py.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# import name -> path from repo root to its src/ package directory
WORKSPACE_PACKAGES = {
    "guitarvis_core": REPO_ROOT / "packages" / "core" / "src" / "guitarvis_core",
    "guitarvis_api": REPO_ROOT / "apps" / "api" / "src" / "guitarvis_api",
    "guitarvis_worker": REPO_ROOT / "apps" / "worker" / "src" / "guitarvis_worker",
    "guitarvis_eval": REPO_ROOT / "apps" / "eval" / "src" / "guitarvis_eval",
}


def test_every_workspace_package_ships_a_py_typed_marker() -> None:
    missing = [
        name
        for name, package_dir in WORKSPACE_PACKAGES.items()
        if not (package_dir / "py.typed").is_file()
    ]

    assert not missing, (
        f"missing py.typed marker(s) for: {missing}. Without it, a type "
        "checker treats the package as untyped and silently skips it — add "
        "an empty `py.typed` file next to the package's __init__.py (PEP 561)."
    )
