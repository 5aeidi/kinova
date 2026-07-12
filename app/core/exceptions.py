"""Application-specific exceptions and error handlers."""

import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class KinovaError(Exception):
    """Base application exception."""

    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class KinoheldAPIError(KinovaError):
    """Raised when the upstream Kinoheld GraphQL API returns an error."""

    def __init__(self, message: str, upstream_errors: list[dict] | None = None):
        super().__init__(message, status.HTTP_502_BAD_GATEWAY)
        self.upstream_errors = upstream_errors or []


class KinoheldNotFoundError(KinovaError):
    """Raised when a requested resource is not found upstream."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, status.HTTP_404_NOT_FOUND)


class CinetixxAPIError(KinovaError):
    """Raised when the upstream Cinetixx API returns an error."""

    def __init__(self, message: str):
        super().__init__(message, status.HTTP_502_BAD_GATEWAY)


class CinetixxNotFoundError(KinovaError):
    """Raised when a requested Cinetixx resource is not found."""

    def __init__(self, message: str = "Cinetixx resource not found"):
        super().__init__(message, status.HTTP_404_NOT_FOUND)


def _apply_cors_headers(request: Request, response: JSONResponse) -> JSONResponse:
    """Mirror CORS headers on error responses.

    Starlette's CORSMiddleware does not wrap responses produced by exception
    handlers, so browsers may block error responses. This helper adds the same
    permissive headers configured in ``app.main``.
    """
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    else:
        response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


async def kinova_exception_handler(request: Request, exc: KinovaError) -> JSONResponse:
    """Handle application exceptions uniformly."""
    body: dict = {"detail": exc.message}
    if isinstance(exc, KinoheldAPIError) and exc.upstream_errors:
        body["upstream_errors"] = exc.upstream_errors
    response = JSONResponse(status_code=exc.status_code, content=body)
    return _apply_cors_headers(request, response)


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unexpected errors."""
    logger.exception("Unhandled exception for %s %s", request.method, request.url)
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred."},
    )
    return _apply_cors_headers(request, response)
