"""The pipeline. The only component that needs torch, a GPU, or weights.

Reachable only through the queue: the worker exposes no HTTP surface, which is
what lets it move to a GPU host, another cloud, or a user's own machine without
an API change.
"""

__version__ = "0.1.0"
