"""The FastAPI application object.

Routes arrive in phase 3 (003 onwards). The object exists now so that the
dependency boundary is under test from the first commit rather than from the
first endpoint.
"""

from fastapi import FastAPI

app = FastAPI(
    title="GuitarVis API",
    version="0.1.0",
    description="Audio in, tab documents out.",
)
