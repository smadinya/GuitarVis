"""The FastAPI application.

`create_app(services)` is what tests use, with in-memory twins. The
module-level `app` — what `make api` serves — builds the real stores from
Settings when it starts, not when it is imported, so importing this module
opens no connection and the boundary test can import it freely.

Behind a proxy, run uvicorn with --forwarded-allow-ips so request.client is
the user's address; the api parses no proxy headers itself.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from guitarvis_jobs.settings import Settings

from guitarvis_api import __version__
from guitarvis_api.errors import install_error_handlers
from guitarvis_api.routes import router
from guitarvis_api.services import Services, build_services
from guitarvis_api.uploads import UploadSizeLimit


def create_app(services: Services | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if services is None:
            app.state.services = build_services(Settings.from_env())
        yield

    app = FastAPI(
        title="GuitarVis API",
        version=__version__,
        description="Audio in, tab documents out.",
        lifespan=lifespan,
    )
    if services is not None:
        app.state.services = services
    install_error_handlers(app)
    app.add_middleware(UploadSizeLimit)
    app.include_router(router)
    return app


app = create_app()
