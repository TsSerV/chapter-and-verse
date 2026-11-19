"""Find the sections of the Act that are closest in meaning to a question."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chapter_and_verse.db import Chunk, Section


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
