import json
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chapter_and_verse.config import Settings
from chapter_and_verse.db import Answer
from chapter_and_verse.errors import UpstreamUnavailable
from chapter_and_verse.llm import get_answerer
from chapter_and_verse.main import app
from tests.conftest import FAKE_CLAIM

pytestmark = pytest.mark.anyio

QUESTION = "What is the Equality Act 2010?"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    # Async, so a test can also query the database through test_db.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_ask_stores_the_answer_and_reads_it_back(
    client: httpx.AsyncClient, test_settings: Settings
) -> None:
    asked = await client.post("/ask", json={"question": QUESTION})
    answer_id = asked.json()["answer_id"]

    response = await client.get(f"/answers/{answer_id}")

    assert response.status_code == 200
    record = response.json()
    assert record["id"] == answer_id
    assert record["question"] == QUESTION
    assert record["answer"] == asked.json()["answer"]
    assert record["status"] == "answered"
    assert record["claims"] == asked.json()["claims"]
    # The sections are kept with the answer, each with the date its text is in force from.
    assert record["sources"] == asked.json()["sources"]
    assert record["sources"][0]["valid_from"] == "2026-10-30"
    assert record["model"] == test_settings.claude_model
    assert record["request_id"] == asked.headers["X-Request-ID"]
    assert record["latency_ms"] == asked.json()["latency_ms"]
    # Set by the database, not by the endpoint.
    assert record["created_at"]


async def test_a_refused_answer_keeps_the_claims_that_failed(
    client: httpx.AsyncClient,
) -> None:
    bad = {**FAKE_CLAIM, "quote": "the right to be dismissed without any notice"}

    async def one_bad_claim(prompt: str) -> str:
        return json.dumps({"claims": [FAKE_CLAIM, bad]})

    app.dependency_overrides[get_answerer] = lambda: one_bad_claim
    asked = await client.post("/ask", json={"question": QUESTION})

    record = (await client.get(f"/answers/{asked.json()['answer_id']}")).json()

    # The reply shows no claims. The record keeps both, so the refusal can be explained.
    assert asked.json()["claims"] == []
    assert record["status"] == "refused"
    assert record["claims"] == [
        {**FAKE_CLAIM, "verdict": "verified"},
        {**bad, "verdict": "quote_not_found"},
    ]


async def test_get_answer_returns_404_when_missing(client: httpx.AsyncClient) -> None:
    response = await client.get("/answers/999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Answer not found."}


async def test_only_successful_asks_are_stored(
    client: httpx.AsyncClient, test_db: async_sessionmaker[AsyncSession]
) -> None:
    async def broken(question: str) -> str:
        raise UpstreamUnavailable("Claude is down")

    ok = await client.post("/ask", json={"question": QUESTION})
    app.dependency_overrides[get_answerer] = lambda: broken
    failed = await client.post("/ask", json={"question": QUESTION})

    assert [ok.status_code, failed.status_code] == [200, 503]
    async with test_db() as session:
        stored = await session.scalar(select(func.count()).select_from(Answer))
    assert stored == 1
