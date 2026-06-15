"""Application-specific exceptions and error handlers."""

from fastapi import Request, status
from fastapi.responses import JSONResponse


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


async def kinova_exception_handler(request: Request, exc: KinovaError) -> JSONResponse:
    """Handle application exceptions uniformly."""
    body: dict = {"detail": exc.message}
    if isinstance(exc, KinoheldAPIError) and exc.upstream_errors:
        body["upstream_errors"] = exc.upstream_errors
    return JSONResponse(status_code=exc.status_code, content=body)


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unexpected errors."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred."},
    )
