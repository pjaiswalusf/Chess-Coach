"""Local HTTP transport. Workers own all historical engine/import execution."""

import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.responses import Response
from structlog.contextvars import bound_contextvars

from chess_coach.api.dependencies import get_readiness_failure
from chess_coach.api.errors import ERROR_RESPONSES, error, install_handlers
from chess_coach.api.frontend import (
    FRONTEND_BUILD,
    frontend_available,
    install_frontend,
)
from chess_coach.api.routes.analysis import router as analysis_router
from chess_coach.api.routes.analytics import router as analytics_router
from chess_coach.api.routes.coaching import router as coaching_router
from chess_coach.api.routes.queries import router as queries_router
from chess_coach.api.routes.sync import router as sync_router
from chess_coach.api.routes.system import router as system_router
from chess_coach.api.routes.training import router as training_router
from chess_coach.api.schemas.contracts import HealthResponse
from chess_coach.api.schemas.system import Liveness, NotReady, Readiness
from chess_coach.config import get_settings
from chess_coach.infrastructure.system.diagnostics import core_checks
from chess_coach.observability.logging import configure_logging

logger = logging.getLogger(__name__)
LOCAL_HOST = re.compile(
    r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]+)?", re.IGNORECASE
)


def create_app(
    *, frontend_build: Path = FRONTEND_BUILD, force_packaged: bool = False
) -> FastAPI:
    try:
        settings = get_settings()
    except ValidationError, OSError:
        settings = None
    configure_logging(settings.log_level if settings else None)
    packaged = force_packaged or (settings is not None and settings.serve_frontend)

    @asynccontextmanager
    async def packaged_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _, checks = core_checks(get_settings)
        for check in checks:
            if check.required and check.status == "fail":
                raise RuntimeError(
                    f"{check.code}: {check.message} {check.action or ''}"
                )
        yield

    app = FastAPI(
        title="Chess Coach API",
        version="0.1.0",
        responses=ERROR_RESPONSES,
        lifespan=packaged_lifespan if packaged else None,
    )
    install_handlers(app)

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["health"],
        summary="Check HTTP liveness without probing dependencies",
    )
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/health/live", tags=["health"])
    async def liveness() -> Liveness:
        return Liveness()

    @app.get(
        "/health/ready",
        tags=["health"],
        response_model=Readiness,
        responses={
            503: {"model": NotReady, "description": "Core dependency unavailable"}
        },
    )
    def readiness(
        failure: Annotated[str | None, Depends(get_readiness_failure)],
        response: Response,
    ) -> Readiness | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        if not failure and packaged and not frontend_available(frontend_build):
            failure = "FRONTEND_BUILD_MISSING"
        if failure:
            return JSONResponse(
                status_code=503,
                content=NotReady(code=failure).model_dump(),
                headers={"Cache-Control": "no-store"},
            )
        return Readiness()

    for router in (
        system_router,
        analysis_router,
        queries_router,
        sync_router,
        analytics_router,
        coaching_router,
        training_router,
    ):
        app.include_router(router)

    if packaged:
        install_frontend(app, frontend_build)

    @app.middleware("http")
    async def local_requests_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        hosts = request.headers.getlist("host")
        if len(hosts) != 1 or LOCAL_HOST.fullmatch(hosts[0]) is None:
            return error(400, "HOST_NOT_ALLOWED", "Use the local Chess Coach address.")
        origin = request.headers.get("origin")
        allowed = {
            f"http://{host}:{port}"
            for host in ("localhost", "127.0.0.1")
            for port in ((8000,) if packaged else (5173, 4173, 8000))
        }
        probes = request.url.path.rstrip("/") in {
            "/health/ready",
            "/api/v1/system",
            "/api/v1/system/status",
            "/api/v1/system/health",
            "/api/v1/system/metrics",
        }
        if (probes or request.method not in {"GET", "HEAD", "OPTIONS"}) and (
            (origin is not None and origin not in allowed)
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return error(
                403, "ORIGIN_NOT_ALLOWED", "Use the local Chess Coach interface."
            )
        return await call_next(request)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid4())
        with bound_contextvars(request_id=request_id):
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "internal_error", extra={"error_code": "INTERNAL_ERROR"}
                )
                response = error(
                    500,
                    "INTERNAL_ERROR",
                    "An unexpected error occurred. Check backend logs and retry.",
                )
            if response.status_code >= 400:
                logger.warning(
                    "request_failed", extra={"http_status": response.status_code}
                )
            response.headers["X-Request-ID"] = request_id
            return response

    return app


def create_packaged_app() -> FastAPI:
    # The launcher must still fail closed if another setting is invalid.
    return create_app(force_packaged=True)


app = create_app()
