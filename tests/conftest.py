from collections.abc import AsyncIterator, Iterator
from datetime import date
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from chapter_and_verse.config import Settings, get_settings
from chapter_and_verse.db import Base, Section, get_session
from chapter_and_verse.llm import get_answerer
from chapter_and_verse.main import app
from chapter_and_verse.retrieval import get_retriever


async def fake_answer(prompt: str) -> str:
    return f"Fake answer to: {prompt}"


def fake_section(number: str, title: str, text: str) -> Section:
    return Section(
        act="ukpga/1996/18",
        number=number,
        title=title,
        text=text,
        uri=f"http://www.legislation.gov.uk/ukpga/1996/18/section/{number}",
        valid_from=date(2026, 10, 30),
    )


async def fake_retrieve(question: str) -> list[Section]:
    return [
        fake_section("94", "The right.", "(1) An employee has the right..."),
        fake_section("95", "Circumstances of dismissal.", "(1) For the purposes..."),
    ]


@pytest.fixture(autouse=True)
def no_real_llm() -> Iterator[None]:
    # No test reaches Claude through the app unless it sets its own override.
    app.dependency_overrides[get_answerer] = lambda: fake_answer
    # The real search needs Postgres and the embedding model. See test_retrieval.py.
    app.dependency_overrides[get_retriever] = lambda: fake_retrieve
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def test_settings() -> Settings:
    # Fixed values, so tests pass in CI, which has no .env.
    settings = Settings(claude_api_token=SecretStr("test-token"), claude_model="test-model")
    app.dependency_overrides[get_settings] = lambda: settings
    # no_real_llm clears the override after the test.
    return settings


@pytest.fixture(autouse=True)
def test_db(tmp_path: Path) -> Iterator[async_sessionmaker[AsyncSession]]:
    # The lifespan does not run in tests, so each test gets its own SQLite file instead.
    path = tmp_path / "test.db"
    # Tables built with the plain sync driver, so no event loop is needed here.
    sync_engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    # No connection pool: TestClient runs the app in its own event loop, and an async
    # connection opened in one loop cannot be used in another.
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def get_test_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    # no_real_llm clears the override after the test.
    yield sessionmaker


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
