"""guitarvis_fetch is walled off: importing it, child aside, loads no yt-dlp,
and it never imports the api, the worker or the ML stack."""

import subprocess
import sys

FORBIDDEN_ROOTS = {
    "yt_dlp",
    "torch",
    "demucs",
    "basic_pitch",
    "librosa",
    "numpy",
    "guitarvis_api",
    "guitarvis_worker",
}


def test_fetch_exposes_a_version() -> None:
    import guitarvis_fetch

    assert guitarvis_fetch.__version__ == "0.1.0"


def test_importing_every_module_but_the_child_loads_nothing_forbidden() -> None:
    probe = (
        "import importlib, pkgutil, sys, guitarvis_fetch as package;"
        "[importlib.import_module(m.name) for m in "
        "pkgutil.walk_packages(package.__path__, 'guitarvis_fetch.') "
        "if m.name != 'guitarvis_fetch.child'];"
        "leaked = {name.split('.')[0] for name in sys.modules}"
        f" & {FORBIDDEN_ROOTS!r};"
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "", (
        f"importing guitarvis_fetch pulled in: {result.stdout.strip()}"
    )
