from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chapter_and_verse.db import EMBEDDING_SIZE, Chunk, Section
from chapter_and_verse.ingest import chunk_lines, store
from chapter_and_verse.legislation import Provision

ACT = "ukpga/1996/18"


def provision(number: str, text: str) -> Provision:
    return Provision(
        act=ACT,
        number=number,
        title=f"Title of {number}.",
        text=text,
        uri=f"http://www.legislation.gov.uk/{ACT}/section/{number}",
        valid_from=date(2026, 10, 30),
    )


class FakeEmbedder:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def passages(self, texts: list[str]) -> list[list[float]]:
        self.seen.extend(texts)
        return [[float(len(text))] * EMBEDDING_SIZE for text in texts]

    def query(self, text: str) -> list[float]:
        return [0.0] * EMBEDDING_SIZE


def test_packs_whole_lines_up_to_the_limit() -> None:
    lines = ["one two three", "four five", "six seven eight nine", "ten"]

    assert chunk_lines(lines, max_words=5) == [
        "one two three\nfour five",
        "six seven eight nine\nten",
    ]


def test_a_line_longer_than_the_limit_is_a_chunk_of_its_own() -> None:
    lines = ["short", "one two three four five six", "short again"]

    assert chunk_lines(lines, max_words=3) == [
        "short",
        "one two three four five six",
        "short again",
    ]


def test_no_lines_give_no_chunks() -> None:
    assert chunk_lines([]) == []


@pytest.mark.anyio
async def test_stores_sections_with_a_vector_for_each_chunk(
    test_db: async_sessionmaker[AsyncSession],
) -> None:
    embedder = FakeEmbedder()
    long_text = "\n".join(["word " * 150] * 3).replace(" \n", "\n").strip()

    async with test_db() as session:
        count = await store(
            session,
            ACT,
            [provision("94", "(1) Short."), provision("98", long_text)],
            embedder,
        )

    # Section 98 has three lines of 150 words: one chunk each, under the 200 word limit.
    assert count == 4
    # The title is embedded with each chunk.
    assert embedder.seen[0] == "Title of 94.\n(1) Short."
    async with test_db() as session:
        chunks = (await session.scalars(select(Chunk).order_by(Chunk.id))).all()
        assert [chunk.position for chunk in chunks] == [0, 0, 1, 2]
        assert len(chunks[0].embedding) == EMBEDDING_SIZE


@pytest.mark.anyio
async def test_loading_an_act_again_replaces_it(
    test_db: async_sessionmaker[AsyncSession],
) -> None:
    embedder = FakeEmbedder()

    async with test_db() as session:
        await store(
            session, ACT, [provision("94", "Old."), provision("95", "Old.")], embedder
        )
    async with test_db() as session:
        await store(session, ACT, [provision("94", "New.")], embedder)

    async with test_db() as session:
        sections = (await session.scalars(select(Section))).all()
        assert [(s.number, s.text) for s in sections] == [("94", "New.")]
        assert await session.scalar(select(func.count()).select_from(Chunk)) == 1
