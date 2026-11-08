# Domain failures expose stable codes; database internals stay in server logs.
import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response

from chess_coach.api.routes.analysis import router as analysis_router
from chess_coach.api.routes.system import router as system_router
from chess_coach.infrastructure.persistence.analysis_repository import AnalysisError

app = FastAPI(
    title="Chess Coach API",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(system_router)


@app.exception_handler(AnalysisError)
async def analysis_error(request: Request, exc: AnalysisError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"detail": {"code": exc.code, "message": str(exc)}},
    )


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logging.getLogger(__name__).exception("database_unavailable", exc_info=exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "code": "DATABASE_UNAVAILABLE",
                "message": "Check database access and run uv run alembic upgrade head.",
            }
        },
    )


app.include_router(analysis_router)


@app.middleware("http")
async def local_mutations_only(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    origin = request.headers.get("origin")
    allowed = {
        f"http://{host}:{port}"
        for host in ("localhost", "127.0.0.1")
        for port in (5173, 4173, 8000)
    }
    if (
        request.method not in {"GET", "HEAD", "OPTIONS"}
        and origin
        and origin not in allowed
    ):
        return JSONResponse(
            status_code=403,
            content={
                "detail": {
                    "code": "ORIGIN_NOT_ALLOWED",
                    "message": "Use the local Chess Coach interface.",
                }
            },
        )
    return await call_next(request)
