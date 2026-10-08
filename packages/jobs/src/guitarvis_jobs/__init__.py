"""Job state shared by the api and the worker.

The api and the worker never import each other — the worker is reachable only
through the queue — so what both must agree on lives here: the job record and
its store, the blob store, the queue, and the settings that point at all
three. Nothing here imports the ML stack. apps/api/tests/test_boundaries.py
proves it, because importing the api imports this.
"""

__version__ = "0.1.0"
