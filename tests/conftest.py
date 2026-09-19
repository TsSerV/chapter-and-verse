from collections.abc import Iterator

import pytest

from chapter_and_verse.llm import get_answerer
from chapter_and_verse.main import app


async def fake_answer(question: str) -> str:
    return f"Fake answer to: {question}"


@pytest.fixture(autouse=True)
def no_real_llm() -> Iterator[None]:
    # No test reaches Claude through the app unless it sets its own override.
    app.dependency_overrides[get_answerer] = lambda: fake_answer
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
