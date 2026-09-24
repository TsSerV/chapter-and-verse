import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
import structlog
from fastapi import Depends, FastAPI
from structlog.typing import FilteringBoundLogger

from chapter_and_verse.config import get_settings
from chapter_and_verse.errors import register_error_handlers
from chapter_and_verse.llm import Answerer, get_answerer
from chapter_and_verse.middleware import add_request_id
from chapter_and_verse.models import (
    AskRequest,
    AskResponse,
    ErrorResponse,
    HealthResponse,
)

logger: FilteringBoundLogger = structlog.get_logger()


def configure_logging() -> None:
    # One JSON object per line, with a level and a UTC timestamp.
    structlog.configure(
        processors=[
            # Adds the request_id that middleware.py binds.
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    # One pooled client for the whole process, closed on shutdown.
    settings = get_settings()
    async with httpx.AsyncClient(
        timeout=settings.claude_timeout_seconds,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
    ) as client:
        app.state.http_client = client
        yield


app = FastAPI(
    title="Chapter and Verse",
    description="Question answering for UK legislation, with a citation for every claim.",
    lifespan=lifespan,
)
register_error_handlers(app)
app.middleware("http")(add_request_id)


@app.get("/health")
def health() -> HealthResponse:
    # Cheap on purpose: this becomes a Kubernetes probe. It logs nothing.
    return HealthResponse(status="ok")


@app.post(
    "/ask",
    responses={
        503: {"model": ErrorResponse, "description": "An upstream service failed."}
    },
)
async def ask(
    request: AskRequest, answer: Annotated[Answerer, Depends(get_answerer)]
) -> AskResponse:
    start = time.perf_counter()
    # The question is user input, so only its length is logged.
    try:
        text = await answer(request.question)
    except Exception:
        logger.warning(
            "ask",
            outcome="error",
            question_length=len(request.question),
            latency_ms=elapsed_ms(start),
        )
        raise
    latency_ms = elapsed_ms(start)
    logger.info(
        "ask",
        outcome="ok",
        question_length=len(request.question),
        latency_ms=latency_ms,
    )
    return AskResponse(answer=text, latency_ms=latency_ms)


def elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
