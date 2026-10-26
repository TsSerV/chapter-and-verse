import asyncio

import httpx
import pytest
from structlog.contextvars import merge_contextvars
from structlog.testing import capture_logs

from chapter_and_verse.llm import get_answerer
from chapter_and_verse.main import app

pytestmark = pytest.mark.anyio

QUESTION = "What is the Equality Act 2010?"
REQUESTS = 5
DELAY_SECONDS = 0.2


async def slow_fake_answer(question: str) -> str:
    # Waits without blocking the event loop, like the real call to Claude.
    await asyncio.sleep(DELAY_SECONDS)
    return f"Fake answer to: {question}"


async def ask_all_at_once() -> list[httpx.Response]:
    # In process, no network. The lifespan does not run, so the answerer must be a fake.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await asyncio.gather(
            *(client.post("/ask", json={"question": QUESTION}) for _ in range(REQUESTS))
        )


async def test_concurrent_requests_overlap() -> None:
    inside = 0
    all_inside = asyncio.Event()

    async def wait_for_the_others(question: str) -> str:
        nonlocal inside
        inside += 1
        if inside == REQUESTS:
            all_inside.set()
        # Returns only when all five are inside at once. One at a time would time out.
        await asyncio.wait_for(all_inside.wait(), timeout=5)
        return f"Fake answer to: {question}"

    app.dependency_overrides[get_answerer] = lambda: wait_for_the_others
    responses = await ask_all_at_once()

    assert [r.status_code for r in responses] == [200] * REQUESTS


async def test_concurrent_requests_keep_their_own_request_id() -> None:
    app.dependency_overrides[get_answerer] = lambda: slow_fake_answer

    with capture_logs(processors=[merge_contextvars]) as logs:
        responses = await ask_all_at_once()

    header_ids = sorted(r.headers["X-Request-ID"] for r in responses)
    logged_ids = sorted(entry["request_id"] for entry in logs)
    assert len(set(header_ids)) == REQUESTS
    # While all five overlap, no log line may pick up another request's ID.
    assert logged_ids == header_ids
