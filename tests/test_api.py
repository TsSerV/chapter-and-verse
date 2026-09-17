from fastapi import FastAPI
from fastapi.testclient import TestClient

from chapter_and_verse.errors import register_error_handlers
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


def test_upstream_unavailable_returns_503_without_internals() -> None:
    response = client.post("/ask", json={"question": "fail: anything"})

    assert response.status_code == 503
    assert response.json() == {"detail": "The service is unavailable. Try again later."}


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
