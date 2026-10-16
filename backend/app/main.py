"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.v1.routes import router
from app.core.config import Settings, get_settings
from app.core.errors import NexFlowError
from app.core.logging import configure_logging, get_logger
from app.services.container import AppState

log = get_logger("api")


def _err(status: int, code: str, message: str, hint: str | None = None, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "hint": hint}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


def create_app(settings: Settings | None = None, state: AppState | None = None) -> FastAPI:
    s = settings or get_settings()
    configure_logging(s.log_level, s.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.nexflow = state or AppState(s)
        log.info("NexFlow API started", extra={"network_loaded": app.state.nexflow.net is not None})
        yield

    app = FastAPI(title="NexFlow API", version=__version__, lifespan=lifespan,
                  description="Traffic forecasting, digital twin and congestion-management API (synthetic SUMO data).")
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(NexFlowError)
    async def _nf(_: Request, exc: NexFlowError):
        return _err(exc.status_code, exc.code, exc.message, exc.hint)

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(x) for x in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return _err(422, "validation_error", "The request is invalid.", details=details)

    @app.exception_handler(Exception)
    async def _any(_: Request, exc: Exception):
        log.error("unhandled error", exc_info=exc)
        return _err(500, "internal_error", "Unexpected server error.")

    app.include_router(router)
    return app


app = create_app()
