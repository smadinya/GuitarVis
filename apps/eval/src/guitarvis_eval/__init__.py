"""GuitarSet evaluation harness.

Reports note F1 (onset within 50ms plus correct pitch), string-assignment
accuracy, and chord accuracy against ground-truth annotations, written to
eval/results/ so changes are visible over time.

Measured, never gated. This must not be wired into CI pass/fail: a suite that
fails because a model got two percent worse on a Tuesday is a suite people
learn to ignore.
"""

__version__ = "0.1.0"
