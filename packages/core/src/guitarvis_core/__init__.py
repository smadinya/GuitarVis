"""Shared contract between the GuitarVis pipeline and every client.

This package is deliberately light: Pydantic and the standard library only.
api imports it, and api must never load torch.
"""

__version__ = "0.1.0"
