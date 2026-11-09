"""Local HTTP transport. Workers own all historical engine/import execution."""

import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from pydantic import ValidationError
from starlette.responses import Response
from structlog.contextvars import bound_contextvars

from chess_coach.api.errors import ERROR_RESPONSES, error, install_handlers
from chess_coach.api.routes.analysis import router as analysis_router
from chess_coach.api.routes.analytics import router as analytics_router
from chess_coach.api.routes.coaching import router as coaching_router
from chess_coach.api.routes.queries import router as queries_router
from chess_coach.api.routes.sync import router as sync_router
from chess_coach.api.routes.system import router as system_router
from chess_coach.api.routes.training import router as training_router
from chess_coach.api.schemas.contracts import HealthResponse
from chess_coach.config import get_settings
from chess_coach.observability.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    try:
        level = get_settings().log_level
    except ValidationError, OSError:
        level = None
    configure_logging(level)
    app = FastAPI(title="Chess Coach API", version="0.1.0", responses=ERROR_RESPONSES)
    install_handlers(app)

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["health"],
        summary="Check HTTP liveness without probing dependencies",
    )
    async def health() -> HealthResponse:
        return HealthResponse()

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

    @app.middleware("http")
    async def local_requests_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = request.url.hostname
        if host not in {"localhost", "127.0.0.1", "::1"}:
            return error(400, "HOST_NOT_ALLOWED", "Use the local Chess Coach address.")
        origin = request.headers.get("origin")
        allowed = {
            f"http://{host}:{port}"
            for host in ("localhost", "127.0.0.1")
            for port in (5173, 4173, 8000)
        }
        probes = request.url.path.rstrip("/") in {
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


app = create_app()
