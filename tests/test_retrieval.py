import os
from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from chapter_and_verse.db import EMBEDDING_SIZE, Base, Chunk, Section
from chapter_and_verse.retrieval import nearest_sections

# The search uses pgvector, so these tests need a real Postgres. CI gives them one.
# Locally: docker compose up -d db, then set TEST_DATABASE_URL as the README shows.
SERVER_URL = os.environ.get("TEST_DATABASE_URL")
DATABASE = "retrieval_test"
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(SERVER_URL is None, reason="TEST_DATABASE_URL is not set"),
]


def vector(first: float, second: float) -> list[float]:
    # Two numbers that matter, the rest zeros: easy to see which vectors are close.
    return [first, second] + [0.0] * (EMBEDDING_SIZE - 2)


def section(number: str, *embeddings: list[float]) -> Section:
    return Section(
        act="ukpga/1996/18",
        number=number,
        title=f"Title of {number}.",
        text="Text.",
        uri=f"http://www.legislation.gov.uk/ukpga/1996/18/section/{number}",
        valid_from=date(2026, 10, 30),
        chunks=[
            Chunk(position=position, text="Text.", embedding=embedding)
            for position, embedding in enumerate(embeddings)
        ],
    )


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    assert SERVER_URL is not None
    # A database of its own, so the one that holds the real Act is never touched.
    server = create_async_engine(
        SERVER_URL, poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    async with server.connect() as connection:
        await connection.execute(
            text(f"DROP DATABASE IF EXISTS {DATABASE} WITH (FORCE)")
        )
        await connection.execute(text(f"CREATE DATABASE {DATABASE}"))
    engine = create_async_engine(
        make_url(SERVER_URL).set(database=DATABASE), poolclass=NullPool
    )
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION vector"))
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine)() as session:
        yield session
    await engine.dispose()
    async with server.connect() as connection:
        await connection.execute(text(f"DROP DATABASE {DATABASE} WITH (FORCE)"))
    await server.dispose()


async def test_returns_the_closest_sections_first(session: AsyncSession) -> None:
    session.add_all(
        [
            section("1", vector(0.0, 1.0)),
            section("2", vector(1.0, 0.1)),
            section("3", vector(1.0, 0.5)),
        ]
    )
    await session.commit()

    found = await nearest_sections(session, vector(1.0, 0.0), limit=2)

    assert [s.number for s in found] == ["2", "3"]


async def test_a_section_counts_once_by_its_closest_chunk(
    session: AsyncSession,
) -> None:
    session.add_all(
        [
            section("1", vector(0.0, 1.0), vector(1.0, 0.0), vector(1.0, 0.2)),
            section("2", vector(1.0, 0.1)),
        ]
    )
    await session.commit()

    found = await nearest_sections(session, vector(1.0, 0.0), limit=5)

    assert [s.number for s in found] == ["1", "2"]


async def test_an_empty_table_gives_no_sections(session: AsyncSession) -> None:
    assert await nearest_sections(session, vector(1.0, 0.0)) == []
