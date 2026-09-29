from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chapter_and_verse.db import Answer

pytestmark = pytest.mark.anyio

REQUEST_ID = "5f0c2d1e-8a47-4b8e-9d3a-2e61c7f4b0a9"
QUESTION = "When did the Data Protection Act 2018 come into force?"


async def test_answer_is_stored_and_read_back(
    test_db: async_sessionmaker[AsyncSession],
) -> None:
    async with test_db() as session:
        row = Answer(
            request_id=REQUEST_ID,
            question=QUESTION,
            answer="On 25 May 2018.",
            model="test-model",
            latency_ms=1432,
        )
        session.add(row)
        await session.commit()

    # A new session, so the row is read from the database, not from memory.
    async with test_db() as session:
        stored = await session.get(Answer, row.id)

    assert stored is not None
    assert stored.request_id == REQUEST_ID
    assert stored.question == QUESTION
    assert stored.answer == "On 25 May 2018."
    assert stored.model == "test-model"
    assert stored.latency_ms == 1432
    # The test never set it, so the database filled it in.
    assert isinstance(stored.created_at, datetime)
