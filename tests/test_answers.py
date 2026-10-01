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
    assert record["model"] == test_settings.claude_model
    assert record["request_id"] == asked.headers["X-Request-ID"]
    assert record["latency_ms"] == asked.json()["latency_ms"]
    # Set by the database, not by the endpoint.
    assert record["created_at"]


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
