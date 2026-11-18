"""Load one Act into the database: its sections, and a vector for each chunk of text.

Usage: python -m chapter_and_verse.ingest ukpga/1996/18
"""

import argparse
import asyncio

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from chapter_and_verse.config import DatabaseSettings
from chapter_and_verse.db import Chunk, Section
from chapter_and_verse.embeddings import Embedder, FastEmbedder
from chapter_and_verse.legislation import Provision, fetch_act, parse_sections

# About 300 tokens of legal text, under the model's limit of 512.
MAX_WORDS = 200


def chunk_lines(lines: list[str], max_words: int = MAX_WORDS) -> list[str]:
    # Whole lines only, as many as fit. A line longer than the limit is a chunk of its own.
    chunks: list[str] = []
    current: list[str] = []
    words = 0
    for line in lines:
        count = len(line.split())
        if current and words + count > max_words:
            chunks.append("\n".join(current))
            current, words = [], 0
        current.append(line)
        words += count
    if current:
        chunks.append("\n".join(current))
    return chunks


async def store(
    session: AsyncSession, act: str, provisions: list[Provision], embedder: Embedder
) -> int:
    # Replaces the Act in one transaction, so a reader never sees half of it.
    old = select(Section.id).where(Section.act == act)
    await session.execute(delete(Chunk).where(Chunk.section_id.in_(old)))
    await session.execute(delete(Section).where(Section.act == act))
    count = 0
    for provision in provisions:
        texts = chunk_lines(provision.text.split("\n"))
        # The title goes in front, so a chunk from the middle of a section keeps its subject.
        vectors = embedder.passages([f"{provision.title}\n{text}" for text in texts])
        section = Section(
            act=provision.act,
            number=provision.number,
            title=provision.title,
            text=provision.text,
            uri=provision.uri,
            valid_from=provision.valid_from,
        )
        section.chunks = [
            Chunk(position=position, text=text, embedding=vector)
            for position, (text, vector) in enumerate(zip(texts, vectors, strict=True))
        ]
        session.add(section)
        count += len(texts)
    await session.commit()
    return count


async def ingest(act: str) -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        provisions = parse_sections(await fetch_act(client, act), act)
    engine = create_async_engine(DatabaseSettings().database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            chunks = await store(session, act, provisions, FastEmbedder())
    finally:
        await engine.dispose()
    print(f"{act}: {len(provisions)} sections, {chunks} chunks")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("act", help="type/year/number, for example ukpga/1996/18")
    asyncio.run(ingest(parser.parse_args().act))


if __name__ == "__main__":
    main()
