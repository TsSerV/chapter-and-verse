import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.contextvars import merge_contextvars
from structlog.testing import capture_logs

from chapter_and_verse.errors import register_error_handlers
from chapter_and_verse.llm import get_answerer
from chapter_and_verse.main import app

client = TestClient(app)


def test_ask_returns_answer_and_latency() -> None:
    response = client.post("/ask", json={"question": "What is the Equality Act 2010?"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"answer", "latency_ms"}
    assert isinstance(body["answer"], str)
    assert body["latency_ms"] >= 0


def test_ask_rejects_wrong_type() -> None:
    response = client.post("/ask", json={"question": 123})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "question"]


def test_ask_rejects_missing_field() -> None:
    response = client.post("/ask", json={})

    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["loc"] == ["body", "question"]
    assert detail["type"] == "missing"


def test_ask_rejects_short_question() -> None:
    response = client.post("/ask", json={"question": "ab"})

    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["type"] == "string_too_short"
    assert "at least 3 characters" in detail["msg"]


def test_ask_rejects_blank_question() -> None:
    response = client.post("/ask", json={"question": "      "})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "string_too_short"


def test_ask_rejects_long_question() -> None:
    response = client.post("/ask", json={"question": "a" * 3000})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "string_too_long"


def test_ask_accepts_both_limits() -> None:
    for question in ("abc", "a" * 2000):
        response = client.post("/ask", json={"question": question})
        assert response.status_code == 200


def test_ask_rejects_invalid_json() -> None:
    response = client.post(
        "/ask", content="{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_logs_nothing() -> None:
    # A probe hits this constantly, so it must not fill the log.
    with capture_logs() as logs:
        client.get("/health")

    assert logs == []


def test_unhandled_error_returns_500_without_traceback() -> None:
    broken = FastAPI()
    register_error_handlers(broken)

    @broken.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    response = TestClient(broken, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    assert "secret" not in response.text
    assert "Traceback" not in response.text


def test_ask_and_health_return_a_request_id() -> None:
    ask = client.post("/ask", json={"question": "What is the Equality Act 2010?"})
    health = client.get("/health")

    for response in (ask, health):
        assert uuid.UUID(response.headers["X-Request-ID"]).version == 4


def test_each_request_gets_a_different_request_id() -> None:
    first = client.post("/ask", json={"question": "What is the Equality Act 2010?"})
    second = client.post("/ask", json={"question": "What is the Equality Act 2010?"})

    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


def test_ask_log_line_has_the_request_id() -> None:
    # capture_logs replaces all processors, so add back the one that adds request_id.
    with capture_logs(processors=[merge_contextvars]) as logs:
        response = client.post(
            "/ask", json={"question": "What is the Equality Act 2010?"}
        )

    assert [entry["request_id"] for entry in logs] == [response.headers["X-Request-ID"]]


def test_unhandled_error_keeps_the_request_id() -> None:
    async def broken(question: str) -> str:
        raise RuntimeError("a bug")

    app.dependency_overrides[get_answerer] = lambda: broken

    with capture_logs(processors=[merge_contextvars]) as logs:
        response = TestClient(app, raise_server_exceptions=False).post(
            "/ask", json={"question": "What is the Equality Act 2010?"}
        )

    assert response.status_code == 500
    request_id = response.headers["X-Request-ID"]
    assert [entry["event"] for entry in logs] == ["ask", "unhandled_error"]
    assert all(entry["request_id"] == request_id for entry in logs)
