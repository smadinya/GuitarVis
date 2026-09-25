"""api must carry no ML code and no model weights.

The parent spec makes this a scaling property: api stays thin so it can scale
independently of GPU work. A comment saying so is something a tired developer
talks past at 2am, so it is a test instead.

Two checks, because they fail at different times. The AST scan catches a
forbidden import even when the package is not installed, which is the normal
state of this repo. The sys.modules check catches an import smuggled in
through a transitive dependency.
"""

import ast
import subprocess
import sys
from pathlib import Path

FORBIDDEN_ROOTS = {"torch", "demucs", "basic_pitch", "librosa", "numpy"}
API_SOURCE = Path(__file__).resolve().parents[1] / "src"


def imported_roots(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(), filename=str(source_file))
    roots: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])

    return roots


def test_api_source_imports_nothing_from_the_ml_stack() -> None:
    offenders: dict[str, set[str]] = {}

    for source_file in sorted(API_SOURCE.rglob("*.py")):
        forbidden = imported_roots(source_file) & FORBIDDEN_ROOTS
        if forbidden:
            offenders[str(source_file)] = forbidden

    assert not offenders, (
        f"api must stay free of the ML stack, but found: {offenders}. "
        "That code belongs in apps/worker."
    )


def test_importing_api_loads_no_ml_modules() -> None:
    """Catches an ML module arriving through a transitive dependency."""
    probe = (
        "import sys, guitarvis_api.app;"
        f"leaked = sorted(set(sys.modules) & {FORBIDDEN_ROOTS!r});"
        "print(','.join(leaked))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "", (
        f"importing guitarvis_api pulled in: {result.stdout.strip()}"
    )
