"""The core package must import cleanly and stay free of heavy dependencies.

core is imported by api, which must never pull torch into its process. The
cheapest guard is at the bottom of the dependency graph.
"""

import sys


def test_core_exposes_a_version() -> None:
    import guitarvis_core

    assert guitarvis_core.__version__ == "0.1.0"


def test_importing_core_loads_no_ml_modules() -> None:
    import guitarvis_core  # noqa: F401

    for forbidden in ("torch", "demucs", "basic_pitch"):
        assert forbidden not in sys.modules, f"core pulled in {forbidden}"
