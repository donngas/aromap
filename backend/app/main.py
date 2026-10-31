"""Application factory; use one API process for the local job queue."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.config import Settings
from app.floor_plans.router import router
from app.floor_plans.service import FloorPlanService
from app.infrastructure.database import Database
from app.infrastructure.jobs import Jobs
from app.infrastructure.storage import LocalStorage
from app.infrastructure.upload_limit import UploadLimitMiddleware

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        storage = LocalStorage(settings.data_dir)
        database = Database(storage.root / "registry.sqlite3")
        database.initialize()
        jobs = Jobs(settings, database, storage)
        app.state.settings = settings
        app.state.floor_plans = FloorPlanService(settings, database, storage)
        app.state.jobs = jobs
        await jobs.start()
        try:
            yield
        finally:
            await jobs.close()

    app = FastAPI(title="Aromap API", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {
            "code": "http_error", "message": str(exc.detail),
        }
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse({"detail": {"code": "invalid_request", "message":
                            "Request fields are missing or invalid."}}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.error("Unhandled backend failure", exc_info=exc)
        return JSONResponse({"detail": {"code": "internal_error", "message":
                            "The operation could not complete."}}, status_code=500)

    app.include_router(router)
    app.add_middleware(UploadLimitMiddleware, max_bytes=settings.max_upload_bytes + 1024 * 1024)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    return app


app = create_app()
