"""guitarvis_jobs sits between the api and the worker, so it must pull in
neither of them, and nothing from the ML stack."""

import subprocess
import sys

FORBIDDEN_ROOTS = {
    "torch",
    "demucs",
    "basic_pitch",
    "librosa",
    "numpy",
    "guitarvis_worker",
    "guitarvis_api",
}


def test_jobs_exposes_a_version() -> None:
    import guitarvis_jobs

    assert guitarvis_jobs.__version__ == "0.1.0"


def test_importing_every_jobs_module_loads_nothing_forbidden() -> None:
    probe = (
        "import importlib, pkgutil, sys, guitarvis_jobs as package;"
        "[importlib.import_module(m.name) for m in "
        "pkgutil.walk_packages(package.__path__, 'guitarvis_jobs.') "
        "if m.name != 'guitarvis_jobs.testing'];"
        "leaked = {name.split('.')[0] for name in sys.modules}"
        f" & {FORBIDDEN_ROOTS!r};"
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "", (
        f"importing guitarvis_jobs pulled in: {result.stdout.strip()}"
    )
