import time

from fastapi import FastAPI

from chapter_and_verse.errors import UpstreamUnavailable, register_error_handlers
from chapter_and_verse.models import (
    AskRequest,
    AskResponse,
    ErrorResponse,
    HealthResponse,
)

# Temporary. A question starting with this fakes an upstream failure until llm.py exists.
FAKE_FAILURE_PREFIX = "fail:"

app = FastAPI(
    title="Chapter and Verse",
    description="Question answering for UK legislation, with a citation for every claim.",
)
register_error_handlers(app)


@app.get("/health")
def health() -> HealthResponse:
    # Cheap on purpose: this becomes a Kubernetes probe.
    return HealthResponse(status="ok")


def fake_answer(question: str) -> str:
    if question.startswith(FAKE_FAILURE_PREFIX):
        raise UpstreamUnavailable("fake upstream failure")
    return f"Not answered yet. You asked: {question}"


@app.post(
    "/ask",
    responses={
        503: {"model": ErrorResponse, "description": "An upstream service failed."}
    },
)
def ask(request: AskRequest) -> AskResponse:
    start = time.perf_counter()
    answer = fake_answer(request.question)
    latency_ms = int((time.perf_counter() - start) * 1000)
    return AskResponse(answer=answer, latency_ms=latency_ms)
