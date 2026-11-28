"""add status and claims to answers

Revision ID: 4888ff8fc451
Revises: 215a7835e916
Create Date: 2026-11-28 07:21:14.336168

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4888ff8fc451"
down_revision: str | Sequence[str] | None = "215a7835e916"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Answers stored before this were never checked, and they say so.
    op.add_column(
        "answers",
        sa.Column("status", sa.String(), server_default="unverified", nullable=False),
    )
    op.add_column(
        "answers",
        sa.Column("claims", sa.JSON(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("answers", "claims")
    op.drop_column("answers", "status")
