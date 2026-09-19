import time
from typing import Annotated

from fastapi import Depends, FastAPI

from chapter_and_verse.errors import register_error_handlers
from chapter_and_verse.llm import Answerer, get_answerer
from chapter_and_verse.models import (
    AskRequest,
    AskResponse,
    ErrorResponse,
    HealthResponse,
)

app = FastAPI(
    title="Chapter and Verse",
    description="Question answering for UK legislation, with a citation for every claim.",
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
