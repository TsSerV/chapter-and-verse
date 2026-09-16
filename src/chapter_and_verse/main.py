import time

from fastapi import FastAPI

from chapter_and_verse.models import AskRequest, AskResponse

app = FastAPI(
    title="Chapter and Verse",
    description="Question answering for UK legislation, with a citation for every claim.",
)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"Hello": "World"}


@app.post("/ask")
def ask(request: AskRequest) -> AskResponse:
    start = time.perf_counter()
    answer = f"Not answered yet. You asked: {request.question}"
    latency_ms = int((time.perf_counter() - start) * 1000)
    return AskResponse(answer=answer, latency_ms=latency_ms)
