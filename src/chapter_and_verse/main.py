import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
import structlog
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from structlog.typing import FilteringBoundLogger

from chapter_and_verse.config import Settings, get_settings
from chapter_and_verse.db import Answer, get_session
from chapter_and_verse.errors import register_error_handlers
from chapter_and_verse.llm import Answerer, get_answerer
from chapter_and_verse.middleware import add_request_id
from chapter_and_verse.models import (
    AnswerRecord,
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
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    configure_logging()
    # One database pool and one HTTP client for the whole process, closed on shutdown.
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    # Values stay loaded after commit. A hidden reload query would fail under asyncio.
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with httpx.AsyncClient(
            timeout=settings.claude_timeout_seconds,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
        ) as client:
            app.state.http_client = client
            yield
    finally:
        await engine.dispose()


app = FastAPI(
    title="Chapter and Verse",
    description="Question answering for UK legislation, with a citation for every claim.",
    lifespan=lifespan,
)
register_error_handlers(app)
app.middleware("http")(add_request_id)


@app.get("/health")
def health() -> HealthResponse:
    # This becomes a Kubernetes probe, so it stays cheap and logs nothing.
    return HealthResponse(status="ok")


@app.post(
    "/ask",
    responses={
        503: {"model": ErrorResponse, "description": "An upstream service failed."}
    },
)
async def ask(
    request: AskRequest,
    answer: Annotated[Answerer, Depends(get_answerer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
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
    # Only successful answers are stored. A failed call is in the log with its request ID.
    row = Answer(
        request_id=structlog.contextvars.get_contextvars()["request_id"],
        question=request.question,
        answer=text,
        model=settings.claude_model,
        latency_ms=latency_ms,
    )
    session.add(row)
    await session.commit()
    return AskResponse(answer_id=row.id, answer=text, latency_ms=latency_ms)


@app.get(
    "/answers/{answer_id}",
    responses={404: {"model": ErrorResponse, "description": "No answer with this ID."}},
)
async def get_answer(
    answer_id: int, session: Annotated[AsyncSession, Depends(get_session)]
) -> AnswerRecord:
    row = await session.get(Answer, answer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Answer not found.")
    return AnswerRecord.model_validate(row)


def elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
