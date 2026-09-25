"""HTTP surface. Thin by design: no ML code, no model weights.

Everything expensive happens in the worker, reachable only through the queue.
See apps/api/tests/test_boundaries.py for the enforcement.
"""

__version__ = "0.1.0"
