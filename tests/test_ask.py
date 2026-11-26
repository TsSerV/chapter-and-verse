import json

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from chapter_and_verse.errors import UpstreamUnavailable
from chapter_and_verse.llm import Answerer, get_answerer
from chapter_and_verse.main import app
from tests.conftest import FAKE_CLAIM, fake_answer

client = TestClient(app)


def test_ask_gives_the_answerer_the_sections_then_the_question() -> None:
    prompts: list[str] = []

    async def spy(prompt: str) -> str:
        prompts.append(prompt)
        return await fake_answer(prompt)

    app.dependency_overrides[get_answerer] = lambda: spy

    response = client.post("/ask", json={"question": "Can I be dismissed unfairly?"})

    assert response.status_code == 200
    assert prompts[0].startswith("Section 94. The right.\n(1) An employee has the right")
    assert prompts[0].endswith("Question: Can I be dismissed unfairly?")


def test_ask_returns_the_claims_and_an_answer_built_from_them() -> None:
    response = client.post("/ask", json={"question": "Can I be dismissed unfairly?"})

    body = response.json()
    assert body["status"] == "answered"
    assert body["claims"] == [{**FAKE_CLAIM, "verdict": "verified"}]
    assert body["answer"] == (
        "An employee has the right not to be unfairly dismissed. [s. 94]"
    )


def test_ask_says_it_cannot_answer_when_there_are_no_claims() -> None:
    async def no_claims(prompt: str) -> str:
        return '{"claims": []}'

    app.dependency_overrides[get_answerer] = lambda: no_claims

    response = client.post("/ask", json={"question": "What is the speed limit?"})

    assert response.status_code == 200
    assert response.json()["status"] == "refused"
    assert response.json()["claims"] == []
    assert response.json()["answer"].startswith("I cannot answer this")


def claims_reply(*claims: dict[str, str]) -> Answerer:
    async def answer(prompt: str) -> str:
        return json.dumps({"claims": list(claims)})

    return answer


@pytest.mark.parametrize(
    ("change", "verdict"),
    [
        # Words that section 94 does not have.
        ({"quote": "the right to be dismissed without any notice"}, "quote_not_found"),
        # A section the model was not given.
        ({"section": "108"}, "unknown_section"),
        ({"quote": "the right"}, "quote_too_short"),
    ],
)
def test_ask_refuses_when_a_claim_fails_its_check(
    change: dict[str, str], verdict: str
) -> None:
    # One good claim does not save the answer.
    app.dependency_overrides[get_answerer] = lambda: claims_reply(
        FAKE_CLAIM, {**FAKE_CLAIM, **change}
    )

    with capture_logs() as logs:
        response = client.post("/ask", json={"question": "Can I be dismissed unfairly?"})

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "refused"
    assert body["answer"].startswith("I cannot answer this")
    # The failed claim is not repeated to the caller. The log says which check failed.
    assert body["claims"] == []
    assert logs[0]["status"] == "refused"
    assert logs[0]["verdicts"] == ["verified", verdict]


def test_ask_returns_503_when_the_reply_is_not_claims() -> None:
    async def not_json(prompt: str) -> str:
        return "Section 94 gives the right."

    app.dependency_overrides[get_answerer] = lambda: not_json

    response = client.post("/ask", json={"question": "Can I be dismissed unfairly?"})

    assert response.status_code == 503


def test_ask_returns_the_sections_it_answered_from() -> None:
    response = client.post("/ask", json={"question": "Can I be dismissed unfairly?"})

    sources = response.json()["sources"]
    assert [source["number"] for source in sources] == ["94", "95"]
    assert sources[0] == {
        "act": "ukpga/1996/18",
        "number": "94",
        "title": "The right.",
        "uri": "http://www.legislation.gov.uk/ukpga/1996/18/section/94",
        "valid_from": "2026-10-30",
    }


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
    assert logs[0]["status"] == "answered"
    assert logs[0]["verdicts"] == ["verified"]
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
