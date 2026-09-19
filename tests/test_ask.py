from fastapi.testclient import TestClient

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


def test_ask_does_not_call_answerer_for_invalid_input() -> None:
    calls: list[str] = []

    async def spy(question: str) -> str:
        calls.append(question)
        return "unused"

    app.dependency_overrides[get_answerer] = lambda: spy

    response = client.post("/ask", json={"question": "ab"})

    assert response.status_code == 422
    assert calls == []
