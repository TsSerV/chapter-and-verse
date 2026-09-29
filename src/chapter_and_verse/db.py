from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import Request
from sqlalchemy import DateTime, Text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Answer(Base):
    """One answered question, kept as the audit record."""

    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str]
    # Stored here, never logged. A table has access control, log lines get copied.
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    # Which model wrote the answer.
    model: Mapped[str]
    latency_ms: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    # The sessionmaker is created once in the app lifespan, see main.py.
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session
