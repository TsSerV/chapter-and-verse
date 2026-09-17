import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class UpstreamUnavailable(Exception):
    """A service we depend on did not give us a usable answer."""


async def upstream_unavailable_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.warning("Upstream unavailable on %s: %r", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "The service is unavailable. Try again later."},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Full traceback goes to the log, never to the client.
    logger.exception("Unhandled error on %s", request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(UpstreamUnavailable, upstream_unavailable_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
