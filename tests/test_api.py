from fastapi.testclient import TestClient

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
