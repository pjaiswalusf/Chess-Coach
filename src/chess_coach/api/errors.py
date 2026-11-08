"""One documented error shape; logs retain diagnostic details."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from chess_coach.api.schemas.contracts import ErrorResponse
from chess_coach.application.errors import OperationError

ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in {
        400: "Invalid local Host header",
        403: "Untrusted browser origin",
        404: "Resource not found",
        409: "Conflicting operation or configuration",
        422: "Invalid request",
        503: "Local dependency unavailable",
        500: "Unexpected internal failure",
    }.items()
}


def error(
    status: int, code: str, message: str, details: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(
            code=code, message=message, details=details or {}
        ).model_dump(),
    )


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(OperationError)
    async def operation_error(request: Request, exc: OperationError) -> JSONResponse:
        return error(exc.status, exc.code, str(exc))

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Do not echo submitted values or validators' internal exception objects.
        return error(
            422,
            "VALIDATION_ERROR",
            "Invalid request parameters.",
            {
                ".".join(str(part) for part in item["loc"]): item["type"]
                for item in exc.errors()
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logging.getLogger(__name__).exception("database_unavailable", exc_info=exc)
        return error(
            503,
            "DATABASE_UNAVAILABLE",
            "Check database access and run uv run alembic upgrade head.",
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error(
            exc.status_code,
            "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR",
            "Resource not found."
            if exc.status_code == 404
            else "Request could not be handled.",
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger(__name__).exception("internal_error", exc_info=exc)
        return error(
            500,
            "INTERNAL_ERROR",
            "An unexpected error occurred. Check backend logs and retry.",
        )
