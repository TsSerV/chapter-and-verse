import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from structlog.typing import FilteringBoundLogger

from chapter_and_verse.middleware import REQUEST_ID_HEADER

logger: FilteringBoundLogger = structlog.get_logger()


class UpstreamUnavailable(Exception):
    """A service we depend on did not give us a usable answer."""


async def upstream_unavailable_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.warning("upstream_unavailable", path=request.url.path, error=repr(exc))
    return JSONResponse(
        status_code=503,
        content={"detail": "The service is unavailable. Try again later."},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Full traceback goes to the log, never to the client.
    logger.exception("unhandled_error", path=request.url.path, exc_info=exc)
    # Starlette runs this outside all middleware, so it adds the ID header itself.
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error."},
        headers={REQUEST_ID_HEADER: request_id} if request_id else None,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(UpstreamUnavailable, upstream_unavailable_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
