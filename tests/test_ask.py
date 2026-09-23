from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from chapter_and_verse.errors import UpstreamUnavailable
from chapter_and_verse.llm import get_answerer
from chapter_and_verse.main import app

client = TestClient(app)


def test_ask_returns_the_answerer_text() -> None:
    response = client.post("/ask", json={"question": "What is the Equality Act 2010?"})

    assert response.status_code == 200
    assert response.json()["answer"] == "Fake answer to: What is the Equality Act 2010?"


def test_ask_returns_503_when_upstream_fails() -> None:
    async def broken(question: str) -> str:
        raise UpstreamUnavailable("Claude is down")

    app.dependency_overrides[get_answerer] = lambda: broken

    response = client.post("/ask", json={"question": "What is the Equality Act 2010?"})

    assert response.status_code == 503
    assert response.json() == {"detail": "The service is unavailable. Try again later."}
    assert "Claude" not in response.text


def test_ask_logs_one_line_without_the_question() -> None:
    question = "What is the Equality Act 2010?"

    with capture_logs() as logs:
        response = client.post("/ask", json={"question": question})

    assert response.status_code == 200
    assert len(logs) == 1
    assert logs[0]["event"] == "ask"
    assert logs[0]["outcome"] == "ok"
    assert logs[0]["question_length"] == len(question)
    assert logs[0]["latency_ms"] >= 0
    assert question not in str(logs)


def test_ask_logs_the_outcome_and_the_upstream_failure() -> None:
    async def broken(question: str) -> str:
        raise UpstreamUnavailable("Claude is down")

    app.dependency_overrides[get_answerer] = lambda: broken

    with capture_logs() as logs:
        response = client.post(
            "/ask", json={"question": "What is the Equality Act 2010?"}
        )

    assert response.status_code == 503
    events = {entry["event"]: entry for entry in logs}
    assert events["ask"]["outcome"] == "error"
    assert events["upstream_unavailable"]["path"] == "/ask"
    assert "Claude is down" in events["upstream_unavailable"]["error"]


def test_ask_does_not_call_answerer_for_invalid_input() -> None:
    calls: list[str] = []

    async def spy(question: str) -> str:
        calls.append(question)
        return "unused"

    app.dependency_overrides[get_answerer] = lambda: spy

    response = client.post("/ask", json={"question": "ab"})

    assert response.status_code == 422
    assert calls == []
