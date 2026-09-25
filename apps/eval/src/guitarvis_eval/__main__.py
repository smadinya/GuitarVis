"""Entry point for `make eval`.

Deliberately outside `make check`. If you find yourself wiring this into CI,
read the module docstring in __init__.py first.
"""

import sys


def main() -> int:
    print(
        "The evaluation harness lands in 004-fretboard-mapper, alongside the "
        "deterministic stage it measures. See "
        "docs/specs/001-guitarvis-design/spec.md.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
