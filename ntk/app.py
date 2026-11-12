"""ASGI composition and lifecycle. Importing the module starts no integrations."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api import router
from .config import Settings
from .contracts import AppError
from .dataset import ROOT
from .security import BoundaryMiddleware
from .service import Service, create_service


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        raise exc
    return JSONResponse(
        {"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status
    )


async def _invalid_request(request: Request, exc: Exception) -> JSONResponse:
    # Validation errors can contain submitted input. Do not reflect arbitrary
    # customer data or accidentally pasted credentials in an API error body.
    return JSONResponse(
        {
            "error": {
                "code": "INVALID_REQUEST",
                "message": "Choose a predefined case and a supported context mode.",
            }
        },
        status_code=422,
    )


def create_app(settings: Settings | None = None, *, service: Service | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        current = service if service is not None else create_service(settings)
        app.state.service = current
        if current.sandbox.configured:
            try:
                await current.refresh_paypal()
            except AppError:
                # Health retains the error code; a failed refresh keeps the
                # timestamped, last known observation available for review.
                pass
        yield

    app = FastAPI(title="Minimera", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    app.add_middleware(BoundaryMiddleware)
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.include_router(router)
    app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")
    return app


app = create_app()
