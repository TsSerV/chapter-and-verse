"""add sources to answers

Revision ID: 215a7835e916
Revises: 252f1baf14b8
Create Date: 2026-11-21 15:37:05.894278

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "215a7835e916"
down_revision: str | Sequence[str] | None = "252f1baf14b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Answers stored before this had no sections to answer from, so an empty list.
    op.add_column(
        "answers",
        sa.Column("sources", sa.JSON(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("answers", "sources")
