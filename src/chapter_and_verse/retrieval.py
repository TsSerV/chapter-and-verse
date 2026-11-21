"""Find the sections of the Act that are closest in meaning to a question."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chapter_and_verse.db import Chunk, Section, get_session
from chapter_and_verse.embeddings import Embedder

# Takes a question, returns the sections to answer it from, closest first.
Retriever = Callable[[str], Awaitable[list[Section]]]


async def nearest_sections(
    session: AsyncSession, embedding: list[float], limit: int = 5
) -> list[Section]:
    # Search by chunk, answer from the whole section. A section counts once, by its
    # closest chunk. Needs Postgres with pgvector: <=> is its cosine distance.
    distance = func.min(Chunk.embedding.op("<=>")(embedding)).label("distance")
    closest = (
        select(Chunk.section_id, distance)
        .group_by(Chunk.section_id)
        .order_by(distance)
        .limit(limit)
        .subquery()
    )
    rows = await session.scalars(
        select(Section)
        .join(closest, Section.id == closest.c.section_id)
        .order_by(closest.c.distance)
    )
    return list(rows)


def get_embedder(request: Request) -> Embedder:
    # Loaded once in the app lifespan, see main.py.
    embedder: Embedder = request.app.state.embedder
    return embedder


def get_retriever(
    session: Annotated[AsyncSession, Depends(get_session)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
) -> Retriever:
    async def retrieve(question: str) -> list[Section]:
        # The model runs on the CPU for a few milliseconds, so off the event loop.
        embedding = await asyncio.to_thread(embedder.query, question)
        return await nearest_sections(session, embedding)

    return retrieve
