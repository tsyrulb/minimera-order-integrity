"""Local Order Integrity app. The existing Context Lab remains independently available."""

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..config import Settings
from ..contracts import AppError
from ..dataset import ROOT
from ..security import BoundaryMiddleware
from .api import Service, router
from .auth import Sessions
from .deployment import is_local_origin, normalize_origin
from .model import Analyst
from .payments import Sandbox
from .service import IntegrityService
from .store import Store


def create_integrity_app(
    settings: Settings | None = None,
    *,
    integrity: IntegrityService | None = None,
    sandbox_enabled: bool = False,
    fresh_ai: bool = False,
    origin: str = "http://127.0.0.1:8766",
    recordings_dir: Path | None = None,
) -> FastAPI:
    origin = normalize_origin(origin)
    provider_enabled = (
        integrity.sandbox is not None or integrity.analyst.fresh
        if integrity is not None
        else sandbox_enabled or fresh_ai
    )
    if provider_enabled and not is_local_origin(origin):
        raise ValueError("Sandbox and fresh Bedrock calls require the local operator preview.")
    config = settings or Settings.from_env()
    hostname = urlsplit(origin).hostname
    if hostname and hostname not in config.allowed_hosts:
        config = replace(config, allowed_hosts=(*config.allowed_hosts, hostname))
    runtime = config.runtime_dir / "order-integrity-v1"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = integrity.store if integrity else Store(runtime)
        current = integrity or IntegrityService(
            store,
            Analyst(
                store,
                recordings_dir
                if recordings_dir is not None
                else ROOT / "reports" / "order-integrity-v1" / "recordings",
                fresh=fresh_ai,
                region=config.model.aws_region,
                profile=config.model.aws_profile,
            ),
            sandbox=Sandbox(config.paypal) if sandbox_enabled else None,
            origin=origin,
        )
        app.state.integrity = current
        app.state.sessions = Sessions(store.path.parent)
        yield

    app = FastAPI(
        title="Minimera Order Integrity", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(config.allowed_hosts))
    app.add_middleware(BoundaryMiddleware, post_limit=90, body_limit=4096, inline_styles=True)

    @app.exception_handler(AppError)
    async def safe_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "Use the supported demo fields and values.",
                }
            },
            status_code=422,
        )

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request: Request, exc: sqlite3.Error) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "STORAGE_UNAVAILABLE",
                    "message": "Local workflow storage is unavailable. No successful outcome is assumed; inspect the current payment before retrying.",
                }
            },
            status_code=503,
        )

    app.include_router(router)
    build = ROOT / "ui" / "dist"
    assets_mounted = (build / "integrity-assets").is_dir()

    @app.get("/api/integrity/health")
    async def health(current: Service) -> JSONResponse:
        with current.store.connection() as db:
            db.execute("SELECT revision FROM workspaces LIMIT 1").fetchone()
        assets = build / "integrity-assets"
        ready = (
            assets_mounted
            and (build / "index.html").is_file()
            and any(assets.glob("*.js"))
            and any(assets.glob("*.css"))
        )
        return JSONResponse(
            {
                "status": "ready" if ready else "ui_build_required",
                "product": "Minimera Order Integrity",
                "ui_ready": ready,
                "storage_ready": True,
            },
            status_code=200 if ready else 503,
        )

    if assets_mounted:
        app.mount(
            "/integrity-assets",
            StaticFiles(directory=build / "integrity-assets"),
            name="integrity-assets",
        )
    app.mount("/brand", StaticFiles(directory=ROOT / "web"), name="brand")

    @app.get("/")
    @app.get("/buyer/{token}")
    @app.get("/return")
    async def index(token: str = "") -> Any:
        if not (build / "index.html").exists():
            return JSONResponse(
                {
                    "error": {
                        "code": "UI_BUILD_REQUIRED",
                        "message": "Build the local interface with npm ci and npm run build inside ui/.",
                    }
                },
                status_code=503,
            )
        return FileResponse(build / "index.html", headers={"Cache-Control": "no-store"})

    return app
