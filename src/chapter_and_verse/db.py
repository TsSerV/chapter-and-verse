from collections.abc import AsyncIterator
from datetime import date, datetime

from fastapi import Request
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    MetaData,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# The size of a vector from the embedding model, see embeddings.py.
EMBEDDING_SIZE = 384


class Base(DeclarativeBase):
    # Named constraints, so a later migration can find and drop them on any database.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


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


class Section(Base):
    """One section of an Act, as legislation.gov.uk publishes it."""

    __tablename__ = "sections"
    __table_args__ = (UniqueConstraint("act", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    act: Mapped[str]
    number: Mapped[str]
    title: Mapped[str]
    text: Mapped[str] = mapped_column(Text)
    uri: Mapped[str]
    # The date from which this version of the text is in force.
    valid_from: Mapped[date]
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="section")


class Chunk(Base):
    """A piece of a section, small enough for the embedding model to read whole."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"))
    position: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    # A pgvector column on Postgres. SQLite, in the unit tests, stores it as JSON.
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_SIZE).with_variant(JSON(), "sqlite")
    )
    section: Mapped[Section] = relationship(back_populates="chunks")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    # The sessionmaker is created once in the app lifespan, see main.py.
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session
