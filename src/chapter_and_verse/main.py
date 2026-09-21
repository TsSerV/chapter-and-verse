import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI

from chapter_and_verse.config import get_settings
from chapter_and_verse.errors import register_error_handlers
from chapter_and_verse.llm import Answerer, get_answerer
from chapter_and_verse.models import (
    AskRequest,
    AskResponse,
    ErrorResponse,
    HealthResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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


@app.get("/health")
def health() -> HealthResponse:
    # Cheap on purpose: this becomes a Kubernetes probe.
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
    text = await answer(request.question)
    latency_ms = int((time.perf_counter() - start) * 1000)
    return AskResponse(answer=text, latency_ms=latency_ms)
