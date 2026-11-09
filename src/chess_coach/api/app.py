"""Local HTTP transport. Workers own all historical engine/import execution."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from starlette.responses import Response

from chess_coach.api.errors import ERROR_RESPONSES, error, install_handlers
from chess_coach.api.routes.analysis import router as analysis_router
from chess_coach.api.routes.analytics import router as analytics_router
from chess_coach.api.routes.coaching import router as coaching_router
from chess_coach.api.routes.queries import router as queries_router
from chess_coach.api.routes.sync import router as sync_router
from chess_coach.api.routes.system import router as system_router
from chess_coach.api.routes.training import router as training_router
from chess_coach.api.schemas.contracts import HealthResponse


def create_app() -> FastAPI:
    app = FastAPI(title="Chess Coach API", version="0.1.0", responses=ERROR_RESPONSES)
    install_handlers(app)

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["health"],
        summary="Check HTTP liveness without probing dependencies",
    )
    def health() -> HealthResponse:
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
        if request.method not in {"GET", "HEAD", "OPTIONS"} and (
            (origin is not None and origin not in allowed)
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return error(
                403, "ORIGIN_NOT_ALLOWED", "Use the local Chess Coach interface."
            )
        return await call_next(request)

    return app


app = create_app()
