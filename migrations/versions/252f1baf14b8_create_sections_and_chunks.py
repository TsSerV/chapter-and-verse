"""create sections and chunks

Revision ID: 252f1baf14b8
Revises: 8e40005dc12e
Create Date: 2026-11-18 06:18:33.781440

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "252f1baf14b8"
down_revision: str | Sequence[str] | None = "8e40005dc12e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # The vector type comes from the pgvector extension. SQLite has none, and stores JSON.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "sections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("act", sa.String(), nullable=False),
        sa.Column("number", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("uri", sa.String(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sections")),
        sa.UniqueConstraint("act", "number", name=op.f("uq_sections_act")),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "embedding",
            Vector(384).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["section_id"], ["sections.id"], name=op.f("fk_chunks_section_id_sections")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("chunks")
    op.drop_table("sections")
